"""One Kingstone run, page by page (CB-07 Phase 4, plan §5 and §7): list page, cards, detail, catalog write.

The run takes a list of canonical category list page URLs (``kingstone.page_list``). For each page, in list order:

1. The page is fetched and parsed. A fetch or parse failure skips the page (``record_page_skipped``) and the run goes on.
2. Each card is resolved through ``catalog_core.service.resolve_item``. Existing Sources are touched and never fetched
   again; new ones fetch their detail page, match ISBNs and persist. The outcome goes to ``KingstoneLedger``.
3. When every card has an outcome the page is completed.

Budget (plan §7). Before every request the run checks ``deps.budget``: the soft budget is spent in steps, and when it
runs out no further request is sent. The check is made before each list page and before each card. The fetcher's own
check (``budget_remaining``) is the second guard: a request whose wait would exceed the rest of the budget comes back
as ``AcquisitionFailure.BUDGET_EXHAUSTED`` and the run stops cleanly the same way. The caller must hand the same
``SoftBudget`` to the real fetcher, as ``budget_remaining=budget.remaining``, so that both guards read one clock.
A card whose transaction is running is never cut: the budget is only checked between cards. Pages and books that were not
reached are left for the next run, which replays the list from the top: Existing cards are touched and cost no request,
so replay makes progress without a progress file.

Retries. A detail page is fetched once per card. ``AcquisitionError`` from the acquisition layer already retried inside
the HTTP layer (up to 3 requests, ``kingstone.acquisition``), so the service never fetches again: the card is failed with
the acquisition kind as its reason. A ``max_item_attempts`` budget (default 3) applies only to database failures, and the
parsed draft is kept between them. The backoff before attempt n is ``BACKOFF_BASE_SECONDS * 2**(n-2)``.

Failure scope. A card failure (soft 404, parse error, fetch error, exhausted database retries) fails that card only. A
page failure skips that page. Anything else escaping (a store exception from identity lookup, a ``ValueError`` from a URL
outside the grammar, an unexpected error) is fatal: the run stops and the report carries ``error``. The fatal message and
every message that reaches the ledger or the log pass through ``catalog_core.redact.redact``.

Identity warnings (URL drift on the touch path) are logged at WARNING and counted in the report.

Not here: composing the real fetcher and the database store (Phase 5/6), the CLI and the exit code wiring. ``run_pages``
never raises; the caller reads ``report.exit_code``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from catalog_core.models import BookDraft, ProviderCode
from catalog_core.redact import redact
from catalog_core.service import CatalogItem, CatalogStore, DraftFailure, ItemFailed, ItemResolved, resolve_item
from kingstone.acquisition import AcquisitionError, AcquisitionFailure
from kingstone.ledger import KingstoneLedger, KingstoneReport, RunStatus, SkippedPage, format_report
from kingstone.models import KingstoneParseError, ListedItem, ProductNotFound
from kingstone.parse_detail import parse_detail_html
from kingstone.parse_list import parse_list_html

log = logging.getLogger("kingstone.run")

MAX_ITEM_ATTEMPTS = 3  # database attempts per card, the first try included
BACKOFF_BASE_SECONDS = 1.0  # sleep before attempt n (n = 2, 3) is 1s, then 2s


class SoftBudget:
    """The run's time budget. Starts counting when it is created; ``monotonic`` is injected so tests need no real time."""

    def __init__(self, seconds: float, monotonic: Callable[[], float]) -> None:
        self._seconds = seconds
        self._monotonic = monotonic
        self._started = monotonic()

    def remaining(self) -> float:
        return self._seconds - (self._monotonic() - self._started)

    def exhausted(self) -> bool:
        return self.remaining() <= 0


class KingstoneFetcherPort(Protocol):
    """The page source. ``kingstone.acquisition.KingstoneFetcher`` is the production one."""

    def fetch_list_page(self, url: str) -> str: ...

    def fetch_detail_page(self, url: str) -> str: ...


@dataclass
class KingstoneRunDependencies:
    """Everything a run needs from outside.

    The caller must pass the same ``budget`` to the real fetcher (``budget_remaining=budget.remaining``); the run checks it
    between cards and the fetcher checks it before each request. Composing these from the real fetcher and the database
    store is not done here (Phase 5/6).
    """

    fetcher: KingstoneFetcherPort
    store: CatalogStore
    budget: SoftBudget
    clock: Callable[[], datetime]  # UTC; observed_at and the report times
    sleep: Callable[[float], None]  # database retry backoff; injected so tests never wait
    max_item_attempts: int = MAX_ITEM_ATTEMPTS


def backoff_seconds(attempt: int) -> float:
    """Seconds to wait before ``attempt`` (2 or 3): 1s, then 2s."""
    return BACKOFF_BASE_SECONDS * 2 ** (attempt - 2)


def _attempts(deps: KingstoneRunDependencies) -> Iterator[int]:
    """Attempt numbers 1..``max_item_attempts``, sleeping the backoff before each retry."""
    for attempt in range(1, deps.max_item_attempts + 1):
        if attempt > 1:
            deps.sleep(backoff_seconds(attempt))
        yield attempt


def _fatal_message(exc: BaseException) -> str:
    return redact(f"{type(exc).__name__}: {exc}")


def run_pages(deps: KingstoneRunDependencies, page_urls: Sequence[str], run_id: str | None = None) -> KingstoneReport:
    """Run the listed category pages once, in order. Never raises: fatal errors are reported through ``report.error``.

    A URL listed twice is run once (the page list file already drops duplicates; this keeps the ledger's rule).
    """
    started_at = deps.clock()
    urls = tuple(dict.fromkeys(page_urls))
    ledger = KingstoneLedger(urls)
    error: str | None = None
    try:
        for url in urls:
            if deps.budget.exhausted():
                ledger.stop_for_budget()
                break
            if not _run_page(deps, ledger, url):
                break
    except Exception as exc:  # noqa: BLE001 - a fatal error is recorded in the report, not raised
        error = _fatal_message(exc)

    report = ledger.report(
        run_id=run_id or str(uuid.uuid4()),
        started_at=started_at,
        finished_at=deps.clock(),
        error=error,
    )
    if report.status is RunStatus.FAILED:
        log.error("kingstone run failed: %s", report.error or report.zero_progress_reason)
    log.info("mode=kingstone %s", format_report(report))
    return report


def _run_page(deps: KingstoneRunDependencies, ledger: KingstoneLedger, url: str) -> bool:
    """Process one listed page. Returns False when the run must stop (budget); True to go on with the next page."""
    try:
        html = deps.fetcher.fetch_list_page(url)
    except AcquisitionError as exc:
        if exc.kind is AcquisitionFailure.BUDGET_EXHAUSTED:
            ledger.stop_for_budget()  # this page was not reached
            return False
        ledger.record_page_skipped(SkippedPage(url=url, reason=exc.kind.value.lower(), message=redact(str(exc)), attempts=exc.attempts))
        return True

    try:
        page = parse_list_html(html, url)
    except KingstoneParseError as exc:
        ledger.record_page_skipped(SkippedPage(url=url, reason="parse_error", message=redact(str(exc)), attempts=1))
        return True

    ledger.page_started(url)
    for item in page.items:
        if deps.budget.exhausted():
            ledger.stop_for_budget()  # the open page is interrupted
            return False
        result, budget_hit = _resolve_card(deps, item)
        ledger.record_item(url, result, source_url=item.source_url, external_id=item.external_id)
        if budget_hit:
            ledger.stop_for_budget()
            return False
    ledger.page_completed(url)
    return True


def _resolve_card(deps: KingstoneRunDependencies, item: ListedItem) -> tuple[ItemResolved | ItemFailed, bool]:
    """One card through the shared resolver. Returns the outcome and whether the detail fetch hit the budget."""
    budget_hit = False

    def on_attempt_failed(attempt: int, reason: str, message: str) -> None:
        log.warning("card %s attempt %d/%d failed (%s): %s", item.source_url, attempt, deps.max_item_attempts, reason, redact(message))

    def fetch_draft(attempt: int) -> BookDraft | DraftFailure:
        nonlocal budget_hit
        try:
            html = deps.fetcher.fetch_detail_page(item.source_url)
        except AcquisitionError as exc:
            if exc.kind is AcquisitionFailure.BUDGET_EXHAUSTED:
                budget_hit = True
                return DraftFailure("budget_exhausted", redact(str(exc)), retryable=False)
            # The acquisition layer already retried this request; the service does not fetch it again.
            return DraftFailure(exc.kind.value.lower(), redact(str(exc)), retryable=False)
        try:
            draft = parse_detail_html(html, item.source_url)
        except ProductNotFound:
            return DraftFailure("product_not_found", "the detail page is a soft 404: no product", retryable=False)
        except KingstoneParseError as exc:
            return DraftFailure("parse_error", redact(str(exc)), retryable=False)
        if draft.external_id != item.external_id:
            # The parser already checked sku against the URL, and the card's URL is built from its km_code: a mismatch is a bug.
            return DraftFailure("parse_error", f"detail km_code {draft.external_id!r} is not the card's {item.external_id!r}", retryable=False)
        return draft

    result = resolve_item(
        deps.store,
        CatalogItem(ProviderCode.KINGSTONE, item.source_url, item.external_id),
        fetch_draft,
        clock=deps.clock,
        attempts=lambda: _attempts(deps),
        on_attempt_failed=on_attempt_failed,
    )
    if isinstance(result, ItemFailed):
        result = replace(result, message=redact(result.message))
    if result.identity_warning is not None:
        log.warning("card %s: %s", item.source_url, redact(result.identity_warning))
    return result, budget_hit
