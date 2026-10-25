"""Run accounting for the Kingstone adapter (CB-07 Phase 4): the ledger, the run report and the one terminal status rule.

The caller (the run, Phase 4 M2) drives the ledger in page order: ``page_started``, one ``record_item`` per card,
``page_completed``. A page that cannot be fetched or parsed is ``record_page_skipped`` instead. ``stop_for_budget``
ends the run early; the page that was open then is interrupted, and every listed page that was neither started nor
skipped is not reached. ``report`` turns the counters into a ``KingstoneReport``.

Terminal status (``decide_status``, plan §7). Useful progress means at least one page completed, and every card of
that page was handled (an Existing touch, a new write, a failed book all count as handled):

- a fatal error: FAILED;
- no useful progress: FAILED, with ``zero_progress_reason`` saying why;
- useful progress, and something was skipped, failed, interrupted or not reached: PARTIAL_SUCCESS;
- otherwise SUCCESS. A completed page with no cards is a success, counted in ``zero_card_pages``.

No I/O apart from logging: skipped pages and failed books are logged as WARNING on ``kingstone.ledger``. Messages are
stored as given, so the caller must redact them before passing them in.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from catalog_core.models import CatalogResolution, ProviderCode
from catalog_core.service import ItemFailed, ItemResolved

EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_CONFIG_ERROR = 2

log = logging.getLogger("kingstone.ledger")


class RunStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SkippedPage:
    """A listed page that was not processed: its fetch, redirect or parse failed after its attempts."""

    url: str
    reason: str  # the run's vocabulary, e.g. fetch_error, redirect, parse_error; the ledger does not interpret it
    message: str
    attempts: int


@dataclass(frozen=True)
class FailedItem:
    """A card whose book could not be resolved; the page and the run continue."""

    list_url: str
    source_url: str
    external_id: str
    reason: str
    message: str
    attempts: int


def decide_status(
    *,
    error: str | None,
    pages_listed: int,
    pages_completed: int,
    pages_skipped: int,
    pages_interrupted: int,
    pages_not_reached: int,
    failed_items: int,
    budget_exhausted: bool,
) -> tuple[RunStatus, str | None]:
    """The terminal status and, for a zero-progress failure, the reason. The only place this rule is written."""
    if error is not None:
        return RunStatus.FAILED, None
    if pages_completed == 0:
        return RunStatus.FAILED, _zero_progress_reason(pages_listed, pages_skipped, budget_exhausted)
    if pages_skipped or pages_interrupted or pages_not_reached or failed_items:
        return RunStatus.PARTIAL_SUCCESS, None
    return RunStatus.SUCCESS, None


def _zero_progress_reason(pages_listed: int, pages_skipped: int, budget_exhausted: bool) -> str:
    if pages_listed == 0:
        return "the page list has no pages"
    if pages_skipped == pages_listed:
        return f"every listed page was skipped ({pages_skipped} of {pages_listed})"
    if budget_exhausted:
        return "the run budget ran out before any listed page was completed"
    return "no listed page was completed"


@dataclass(frozen=True)
class KingstoneReport:
    """The outcome of one Kingstone run. Built by ``KingstoneLedger.report``; rendered by ``format_report``."""

    run_id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    pages_listed: int
    pages_completed: int
    pages_skipped: tuple[SkippedPage, ...]
    pages_interrupted: int
    pages_not_reached: int
    zero_card_pages: int
    budget_exhausted: bool
    items_seen: int
    existing_source: int
    imported: int
    isbn_attached: int
    ambiguous_created: int
    failed: int
    recovered_commit_count: int
    identity_warning_count: int
    failed_items: tuple[FailedItem, ...]
    zero_progress_reason: str | None = None
    error: str | None = None
    provider_code: ProviderCode = ProviderCode.KINGSTONE

    @property
    def exit_code(self) -> int:
        return EXIT_FAILED if self.status is RunStatus.FAILED else EXIT_SUCCESS


class KingstoneLedger:
    """Accounts for one Kingstone run over the listed pages, in list order."""

    def __init__(self, page_urls: Sequence[str]) -> None:
        if len(set(page_urls)) != len(page_urls):
            raise ValueError("the page URLs must be unique")
        self._listed = tuple(page_urls)
        self._listed_set = frozenset(self._listed)
        self._started: set[str] = set()
        self._open: str | None = None
        self._open_items = 0
        self._completed = 0
        self._skipped: list[SkippedPage] = []
        self._skipped_urls: set[str] = set()
        self._zero_card_pages = 0
        self._budget_exhausted = False
        self._items_seen = 0
        self._counts: dict[CatalogResolution, int] = {resolution: 0 for resolution in CatalogResolution}
        self._recovered = 0
        self._identity_warnings = 0
        self._failed_items: list[FailedItem] = []

    def page_started(self, url: str) -> None:
        """The page was fetched and parsed; its cards are recorded next. One page is open at a time."""
        self._require_listed(url)
        if self._budget_exhausted:
            raise ValueError(f"the run budget is exhausted; {url} cannot start")
        if self._open is not None:
            raise ValueError(f"{self._open} is still open; finish it before starting {url}")
        if url in self._started or url in self._skipped_urls:
            raise ValueError(f"{url} was already processed")
        self._started.add(url)
        self._open = url
        self._open_items = 0

    def record_item(self, url: str, result: ItemResolved | ItemFailed, *, source_url: str, external_id: str) -> None:
        """One card of the open page reached its outcome."""
        if url != self._open:
            raise ValueError(f"items must be recorded for the open page, not {url}")
        self._items_seen += 1
        self._open_items += 1
        if isinstance(result, ItemResolved):
            self._counts[result.resolution] += 1
            if result.recovered_commit:
                self._recovered += 1
        elif isinstance(result, ItemFailed):
            self._counts[CatalogResolution.FAILED] += 1
            self._failed_items.append(
                FailedItem(
                    list_url=url,
                    source_url=source_url,
                    external_id=external_id,
                    reason=result.reason,
                    message=result.message,
                    attempts=result.attempts,
                )
            )
            log.warning(
                "%s item failed after %d attempt(s) (%s): %s: %s",
                url,
                result.attempts,
                result.reason,
                source_url,
                result.message,
            )
        else:
            raise TypeError(f"not an item outcome: {type(result).__name__}")
        if result.identity_warning is not None:
            self._identity_warnings += 1

    def page_completed(self, url: str) -> None:
        """Every card of the open page has its outcome."""
        if url != self._open:
            raise ValueError(f"{url} is not the open page")
        if self._open_items == 0:
            self._zero_card_pages += 1
        self._completed += 1
        self._open = None

    def record_page_skipped(self, page: SkippedPage) -> None:
        """A listed page that was not processed. Only between pages, before the budget runs out."""
        self._require_listed(page.url)
        if self._budget_exhausted:
            raise ValueError(f"the run budget is exhausted; {page.url} cannot be skipped")
        if self._open is not None:
            raise ValueError(f"{self._open} is still open; {page.url} cannot be skipped now")
        if page.url in self._started or page.url in self._skipped_urls:
            raise ValueError(f"{page.url} was already processed")
        self._skipped.append(page)
        self._skipped_urls.add(page.url)
        log.warning("page skipped after %d attempt(s) (%s): %s: %s", page.attempts, page.reason, page.url, page.message)

    def stop_for_budget(self) -> None:
        """No further page starts. The open page, if any, is interrupted and is never completed."""
        self._budget_exhausted = True

    def report(
        self,
        *,
        run_id: str,
        started_at: datetime,
        finished_at: datetime,
        error: str | None = None,
    ) -> KingstoneReport:
        """The run result. ``error`` is a failure that stops the run (database, unexpected)."""
        interrupted = 0 if self._open is None else 1
        not_reached = len(self._listed) - (self._completed + interrupted) - len(self._skipped)
        status, reason = decide_status(
            error=error,
            pages_listed=len(self._listed),
            pages_completed=self._completed,
            pages_skipped=len(self._skipped),
            pages_interrupted=interrupted,
            pages_not_reached=not_reached,
            failed_items=len(self._failed_items),
            budget_exhausted=self._budget_exhausted,
        )
        c = self._counts
        return KingstoneReport(
            run_id=run_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            pages_listed=len(self._listed),
            pages_completed=self._completed,
            pages_skipped=tuple(self._skipped),
            pages_interrupted=interrupted,
            pages_not_reached=not_reached,
            zero_card_pages=self._zero_card_pages,
            budget_exhausted=self._budget_exhausted,
            items_seen=self._items_seen,
            existing_source=c[CatalogResolution.EXISTING],
            imported=c[CatalogResolution.IMPORTED],
            isbn_attached=c[CatalogResolution.ISBN_ATTACHED],
            ambiguous_created=c[CatalogResolution.AMBIGUOUS_CREATED],
            failed=c[CatalogResolution.FAILED],
            recovered_commit_count=self._recovered,
            identity_warning_count=self._identity_warnings,
            failed_items=tuple(self._failed_items),
            zero_progress_reason=reason,
            error=error,
        )

    def _require_listed(self, url: str) -> None:
        if url not in self._listed_set:
            raise ValueError(f"not a listed page: {url}")


def format_report(report: KingstoneReport) -> str:
    """One line of ``key=value`` pairs, in the fixed order below.

    Counts are plain integers, ``budget_exhausted`` is ``true`` or ``false``. ``zero_progress_reason`` and ``error`` are
    JSON strings or ``null``; ``skipped_pages`` and ``failed_items`` are JSON lists (``ensure_ascii=False``). The
    messages inside them are not redacted here: the run redacts them before they reach the ledger.
    """
    fields: list[tuple[str, Any]] = [
        ("run_id", report.run_id),
        ("provider_code", report.provider_code),
        ("started_at", report.started_at.isoformat()),
        ("finished_at", report.finished_at.isoformat()),
        ("status", report.status),
        ("pages_listed", report.pages_listed),
        ("pages_completed", report.pages_completed),
        ("pages_skipped", len(report.pages_skipped)),
        ("pages_interrupted", report.pages_interrupted),
        ("pages_not_reached", report.pages_not_reached),
        ("zero_card_pages", report.zero_card_pages),
        ("budget_exhausted", "true" if report.budget_exhausted else "false"),
        ("items_seen", report.items_seen),
        ("existing_source", report.existing_source),
        ("imported", report.imported),
        ("isbn_attached", report.isbn_attached),
        ("ambiguous_created", report.ambiguous_created),
        ("failed", report.failed),
        ("recovered_commit_count", report.recovered_commit_count),
        ("identity_warning_count", report.identity_warning_count),
        ("zero_progress_reason", _json_text(report.zero_progress_reason)),
        ("error", _json_text(report.error)),
        ("exit_code", report.exit_code),
        (
            "skipped_pages",
            _json_list([{"url": item.url, "reason": item.reason, "message": item.message, "attempts": item.attempts} for item in report.pages_skipped]),
        ),
        (
            "failed_items",
            _json_list(
                [
                    {
                        "list_url": item.list_url,
                        "source_url": item.source_url,
                        "external_id": item.external_id,
                        "reason": item.reason,
                        "message": item.message,
                        "attempts": item.attempts,
                    }
                    for item in report.failed_items
                ]
            ),
        ),
    ]
    return " ".join(f"{key}={value}" for key, value in fields)


def _json_text(text: str | None) -> str:
    return "null" if text is None else json.dumps(text, ensure_ascii=False)


def _json_list(items: list[dict[str, Any]]) -> str:
    return json.dumps(items, ensure_ascii=False)
