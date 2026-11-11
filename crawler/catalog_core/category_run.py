"""One category run, page by page (provider-neutral; CB-07 Phase 4 logic, moved here in CB-08 Phase 3 M2).

The run takes a list of canonical category list page URLs. For each page, in list order:

1. The page is fetched and parsed. A fetch or parse failure skips the page (``record_page_skipped``) and the run goes on.
2. Each card is resolved through ``catalog_core.service.resolve_item``. Existing Sources are touched and never fetched
   again; new ones fetch their detail page, match ISBNs and persist, under the run's write policy (``new-books-only``
   skips the write when one existing Book matches the ISBN, spec §5). The outcome goes to ``CategoryLedger``.
3. When every card has an outcome the page is completed.

Provider points. Everything provider-specific comes from a ``CategoryAdapter`` passed to ``run_category_pages``: the
provider code, the log mode and logger names, the list and detail parsers, the parse and not-found exception types, the
diagnostic file code of a list page, the skip reason of a list parse error, and the exception type of a provider exclusion.
An excluded card (Eslite: age-restricted) is skipped, not failed: no diagnostic, no catalog write, counted in
``items_excluded``. The run itself never imports a provider.

Budget (plan §7). Before every request the run checks ``deps.budget``: the soft budget is spent in steps, and when it
runs out no further request is sent. The check is made before each list page and before each card. The fetcher's own
check (``budget_remaining``) is the second guard: a request whose wait would exceed the rest of the budget comes back
as ``AcquisitionFailure.BUDGET_EXHAUSTED`` and the run stops cleanly the same way. The caller must hand the same
``SoftBudget`` to the real fetcher, as ``budget_remaining=budget.remaining``, so that both guards read one clock.
A card whose transaction is running is never cut: the budget is only checked between cards. Pages and books that were not
reached are left for the next run, which replays the list from the top: Existing cards are touched and cost no request,
so replay makes progress without a progress file.

Retries. A detail page is fetched once per card. ``AcquisitionError`` from the acquisition layer already retried inside
the HTTP layer, so the service never fetches again: the card is failed with the acquisition kind as its reason. A
``max_item_attempts`` budget (default 3) applies only to database failures, and the parsed draft is kept between them.
The backoff before attempt n is ``BACKOFF_BASE_SECONDS * 2**(n-2)``.

Failure scope. A card failure (soft 404, parse error, fetch error, exhausted database retries) fails that card only. A
provider exclusion (the adapter's ``excluded``, detail stage; list stage cards are dropped by ``parse_list`` through
``ListPage.excluded_count``) skips that card only and is counted in ``items_excluded``, never in ``failed``. A
page failure skips that page. Anything else escaping (a store exception from identity lookup, a ``ValueError`` from a URL
outside the grammar, an unexpected error) is fatal: the run stops and the report carries ``error``. The fatal message and
every message that reaches the ledger or the log pass through ``catalog_core.redact.redact``.

Identity warnings (URL drift on the touch path, or any warning an outcome carries) are logged at WARNING and counted in the report.

Write policy. ``deps.write_policy`` is passed to every ``resolve_item``. Under ``new-books-only`` a card whose ISBN matches exactly one Book is a policy skip: nothing is written, and the card counts as handled, not failed.

A parse error of a list or detail page (the adapter's ``parse_error``, not a soft 404 and not an acquisition failure) is also
handed to ``deps.diagnostics`` when one is given (plan v12 §8). A diagnostic sink never affects the run: its failures are
logged and dropped.

Counts (plan v12 §8). ``items_listed`` is the number of cards each parsed list page returned; ``details_fetched`` counts
every detail fetch the run asked for; ``http_attempts`` and ``http_failures`` are read from the fetcher when the report
is built, so the fetcher must provide them (``CategoryFetcherPort``).

Loggers. The run logs on the adapter's ``run_logger_name`` and the ledger on its ``ledger_logger_name``; both are looked up
by name when the run starts, so a test or the CLI sees the records under the provider's names.

Not here: composing the real fetcher and the database store, the CLI and the exit code wiring. ``run_category_pages``
never raises; the caller reads ``report.exit_code``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from catalog_core.category_ledger import PARSE_ERROR_REASON, CategoryLedger, CategoryReport, RunStatus, SkippedPage, format_report
from catalog_core.http_acquisition import AcquisitionError, AcquisitionFailure
from catalog_core.models import BookDraft, ListedItem, ListPage, ProviderCode, WritePolicy
from catalog_core.redact import redact
from catalog_core.service import (
    CatalogItem,
    CatalogStore,
    DraftFailure,
    ItemFailed,
    ItemPolicySkipped,
    ItemResolved,
    resolve_item,
)

MAX_ITEM_ATTEMPTS = 3  # database attempts per card, the first try included
BACKOFF_BASE_SECONDS = 1.0  # sleep before attempt n (n = 2, 3) is 1s, then 2s
EXCLUDED_REASON = "excluded"  # the DraftFailure reason of a card the provider rule excludes (no diagnostic, no write)


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


class CategoryFetcherPort(Protocol):
    """The page source. A provider's acquisition fetcher is the production one.

    ``http_attempts`` and ``http_failures`` are the requests sent so far and the sent requests that gave no usable body.
    """

    @property
    def http_attempts(self) -> int: ...

    @property
    def http_failures(self) -> int: ...

    def fetch_list_page(self, url: str) -> str: ...

    def fetch_detail_page(self, url: str) -> str: ...


class DiagnosticSink(Protocol):
    """Saves the HTML of a page that failed to parse. It must not raise; ``kingstone.diagnostics`` is the production one."""

    def save_html(self, *, kind: str, code: str, html: str) -> None: ...


@dataclass
class CategoryRunDependencies:
    """Everything a run needs from outside.

    The caller must pass the same ``budget`` to the real fetcher (``budget_remaining=budget.remaining``); the run checks it
    between cards and the fetcher checks it before each request. Composing these from the real fetcher and the database
    store is not done here.

    ``write_policy`` has no default: the caller decides it (the Kingstone config defaults to ``normal``).
    """

    fetcher: CategoryFetcherPort
    store: CatalogStore
    budget: SoftBudget
    clock: Callable[[], datetime]  # UTC; observed_at and the report times
    sleep: Callable[[float], None]  # database retry backoff; injected so tests never wait
    write_policy: WritePolicy
    max_item_attempts: int = MAX_ITEM_ATTEMPTS
    diagnostics: DiagnosticSink | None = None  # None: parse-error pages are not saved


def _default_list_skip_reason(exc: Exception) -> str:
    return PARSE_ERROR_REASON


@dataclass(frozen=True)
class CategoryAdapter:
    """What a provider supplies to the category run. Every field is required except the last two.

    - ``provider``: the code written to ``CatalogItem``, the ledger and the report.
    - ``mode``: the word in the log lines ``"<mode> run failed: ..."`` and ``"mode=<mode> ..."``.
    - ``run_logger_name`` / ``ledger_logger_name``: the loggers of the run and of the ledger (for example ``kingstone.run``).
    - ``parse_list(text, url)``: a list page body to ``ListPage``; it raises ``parse_error`` on a rejected page.
    - ``parse_detail(text, item)``: a detail page body to ``BookDraft`` for the card; it raises ``not_found`` for a soft 404
      and ``parse_error`` for a rejected body.
    - ``parse_error`` / ``not_found``: the exception types of the two cases above.
    - ``excluded``: the exception type ``parse_detail`` raises for a product the provider rule excludes (Eslite: age-restricted);
      such a card is skipped, not failed, with no diagnostic. ``None`` (default): the provider has no exclusion rule.
    - ``list_page_code(url)``: the code in the diagnostic file name of a list page that failed to parse.
    - ``list_skip_reason(exc)``: the skipped-page reason of a list parse error (default: ``parse_error``).
    - ``report_class``: the report class built by the ledger; it must accept the ``CategoryReport`` fields.

    A frozen dataclass rather than a Protocol: a provider is a bundle of functions and names, with no state of its own.
    """

    provider: ProviderCode
    mode: str
    run_logger_name: str
    ledger_logger_name: str
    parse_list: Callable[[str, str], ListPage]
    parse_detail: Callable[[str, ListedItem], BookDraft]
    parse_error: type[Exception]
    not_found: type[Exception]
    list_page_code: Callable[[str], str]
    list_skip_reason: Callable[[Exception], str] = _default_list_skip_reason
    report_class: type[CategoryReport] = CategoryReport
    excluded: type[Exception] | None = None


def backoff_seconds(attempt: int) -> float:
    """Seconds to wait before ``attempt`` (2 or 3): 1s, then 2s."""
    return BACKOFF_BASE_SECONDS * 2 ** (attempt - 2)


def _attempts(deps: CategoryRunDependencies) -> Iterator[int]:
    """Attempt numbers 1..``max_item_attempts``, sleeping the backoff before each retry."""
    for attempt in range(1, deps.max_item_attempts + 1):
        if attempt > 1:
            deps.sleep(backoff_seconds(attempt))
        yield attempt


def _diagnose(deps: CategoryRunDependencies, log: logging.Logger, *, kind: str, code: str, html: str) -> None:
    """Hands a page that failed to parse to the diagnostic sink. Never raises: the run does not depend on the file."""
    if deps.diagnostics is None:
        return
    try:
        deps.diagnostics.save_html(kind=kind, code=code, html=html)
    except Exception as exc:  # noqa: BLE001 - a diagnostic write must not change the run
        log.warning("could not save the %s diagnostic for %s: %s", kind, code, redact(f"{type(exc).__name__}: {exc}"))


def _fatal_message(exc: BaseException) -> str:
    return redact(f"{type(exc).__name__}: {exc}")


def run_category_pages(adapter: CategoryAdapter, deps: CategoryRunDependencies, page_urls: Sequence[str], run_id: str | None = None) -> CategoryReport:
    """Run the listed category pages once, in order. Never raises: fatal errors are reported through ``report.error``.

    A URL listed twice is run once (the page list file already drops duplicates; this keeps the ledger's rule).
    """
    run_log = logging.getLogger(adapter.run_logger_name)
    started_at = deps.clock()
    urls = tuple(dict.fromkeys(page_urls))
    ledger = CategoryLedger(
        urls,
        deps.write_policy,
        provider_code=adapter.provider,
        logger=logging.getLogger(adapter.ledger_logger_name),
        report_class=adapter.report_class,
    )
    error: str | None = None
    try:
        for url in urls:
            if deps.budget.exhausted():
                ledger.stop_for_budget()
                break
            if not _run_page(adapter, deps, ledger, run_log, url):
                break
    except Exception as exc:  # noqa: BLE001 - a fatal error is recorded in the report, not raised
        error = _fatal_message(exc)

    report = ledger.report(
        run_id=run_id or str(uuid.uuid4()),
        started_at=started_at,
        finished_at=deps.clock(),
        error=error,
        http_attempts=deps.fetcher.http_attempts,
        http_failures=deps.fetcher.http_failures,
    )
    if report.status is RunStatus.FAILED:
        run_log.error("%s run failed: %s", adapter.mode, report.error or report.zero_progress_reason)
    run_log.info("mode=%s %s", adapter.mode, format_report(report))
    return report


def _run_page(adapter: CategoryAdapter, deps: CategoryRunDependencies, ledger: CategoryLedger, run_log: logging.Logger, url: str) -> bool:
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
        page = adapter.parse_list(html, url)
    except adapter.parse_error as exc:
        _diagnose(deps, run_log, kind="list", code=adapter.list_page_code(url), html=html)
        ledger.record_page_skipped(SkippedPage(url=url, reason=adapter.list_skip_reason(exc), message=redact(str(exc)), attempts=1))
        return True

    ledger.page_started(url, items_listed=len(page.items), items_excluded=page.excluded_count)
    for item in page.items:
        if deps.budget.exhausted():
            ledger.stop_for_budget()  # the open page is interrupted
            return False
        result, budget_hit = _resolve_card(adapter, deps, ledger, run_log, item)
        if isinstance(result, ItemFailed) and result.reason == EXCLUDED_REASON:
            ledger.record_excluded(url, source_url=item.source_url, external_id=item.external_id)
        else:
            ledger.record_item(url, result, source_url=item.source_url, external_id=item.external_id)
        if budget_hit:
            ledger.stop_for_budget()
            return False
    ledger.page_completed(url)
    return True


def _resolve_card(
    adapter: CategoryAdapter,
    deps: CategoryRunDependencies,
    ledger: CategoryLedger,
    run_log: logging.Logger,
    item: ListedItem,
) -> tuple[ItemResolved | ItemFailed | ItemPolicySkipped, bool]:
    """One card through the shared resolver. Returns the outcome and whether the detail fetch hit the budget."""
    budget_hit = False
    excluded_types: tuple[type[Exception], ...] = () if adapter.excluded is None else (adapter.excluded,)

    def on_attempt_failed(attempt: int, reason: str, message: str) -> None:
        run_log.warning("card %s attempt %d/%d failed (%s): %s", item.source_url, attempt, deps.max_item_attempts, reason, redact(message))

    def fetch_draft(attempt: int) -> BookDraft | DraftFailure:
        nonlocal budget_hit
        ledger.record_detail_fetch()
        try:
            html = deps.fetcher.fetch_detail_page(item.source_url)
        except AcquisitionError as exc:
            if exc.kind is AcquisitionFailure.BUDGET_EXHAUSTED:
                budget_hit = True
                return DraftFailure("budget_exhausted", redact(str(exc)), retryable=False)
            # The acquisition layer already retried this request; the service does not fetch it again.
            return DraftFailure(exc.kind.value.lower(), redact(str(exc)), retryable=False)
        try:
            draft = adapter.parse_detail(html, item)
        except adapter.not_found:
            return DraftFailure("product_not_found", "the detail page is a soft 404: no product", retryable=False)
        except excluded_types:
            return DraftFailure(EXCLUDED_REASON, "the product is excluded by the provider rule", retryable=False)
        except adapter.parse_error as exc:
            _diagnose(deps, run_log, kind="detail", code=item.external_id, html=html)
            return DraftFailure(PARSE_ERROR_REASON, redact(str(exc)), retryable=False)
        if draft.external_id != item.external_id:
            # The parser already checked sku against the URL, and the card's URL is built from its km_code: a mismatch is a bug.
            return DraftFailure(PARSE_ERROR_REASON, f"detail km_code {draft.external_id!r} is not the card's {item.external_id!r}", retryable=False)
        return draft

    result = resolve_item(
        deps.store,
        CatalogItem(adapter.provider, item.source_url, item.external_id),
        fetch_draft,
        clock=deps.clock,
        attempts=lambda: _attempts(deps),
        on_attempt_failed=on_attempt_failed,
        write_policy=deps.write_policy,
    )
    if isinstance(result, ItemFailed):
        result = replace(result, message=redact(result.message))
    if result.identity_warning is not None:
        run_log.warning("card %s: %s", item.source_url, redact(result.identity_warning))
    return result, budget_hit
