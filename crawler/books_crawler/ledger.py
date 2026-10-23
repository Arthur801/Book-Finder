"""Run accounting: every rule that turns row outcomes into a run result (crawler.md §6, §11).

The run resolves ranking rows and hands each outcome, in rank order, to one ``RunLedger``. The
ledger owns everything decided from those outcomes, so the rules live in one place:

- which Books the snapshot already uses (``ranked``), and the snapshot rows themselves;
- the counters of the run line (existing / attached / new Books, skipped rows);
- the consecutive-error streak: each terminal general error adds one, while an imported row,
  a reused source or a restricted page resets it. Cumulative errors have no limit;
- the abort decision: a streak above ``max_consecutive_errors`` stops the run at that rank;
- the final status and exit code (``report``).

The daily run uses the default limit of 20. The single-book import uses 0, so its only row
fails the run on a general error and is a partial success when restricted.

Pages mode (crawler.md §16) has its own ``PagesLedger``: it accounts for category pages and their rows,
with no rank order, no snapshot, no duplicate-Book rule and no consecutive-error limit. A skipped
page is recorded; the run fails only when every configured page was skipped. Both ledgers share
the status rule (``_status``) and the book counts (``_book_counts``), so status and exit code are
decided in one place.

No I/O apart from logging skipped rows: tests drive it directly, without a database or a
fetcher. The caller logs the one ERROR line of a failed run, abort included.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from books_crawler.models import (
    Resolution,
    ResolvedRow,
    RunStatus,
    SkippedPage,
    SkippedRow,
    SnapshotRow,
)

MAX_CONSECUTIVE_ERRORS = 20  # crawler.md §6, CRAWL-05

EXIT_SUCCESS = 0
EXIT_FAILED = 1

log = logging.getLogger("books_crawler.ledger")


@dataclass
class RunReport:
    """The outcome of one run, as logged on one line (crawler.md §12). Built by ``RunLedger.report`` or ``PagesLedger.report``."""

    run_id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    ranking_count: int = 0
    # Rows resolved to an existing Book: known source URL, or new source attached by ISBN.
    existing_book_count: int = 0
    # Rows that created a new Book.
    new_book_count: int = 0
    # Subset of existing_book_count: new sources attached to an existing Book by ISBN.
    attached_source_count: int = 0
    skipped: list[SkippedRow] = field(default_factory=list)
    # Current streak of terminal non-restricted row failures.
    consecutive_error_count: int = 0
    # Rank where the consecutive-error limit was exceeded; the run stopped there.
    aborted_at_rank: int | None = None
    error: str | None = None
    # Pages mode only (crawler.md §16); None / empty for the daily and first-book runs.
    pages_total: int | None = None  # category pages processed, fetched or skipped
    rows_seen: int | None = None  # rows of the processed pages, each given one outcome
    skipped_pages: list[SkippedPage] = field(default_factory=list)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def restricted_book_count(self) -> int:
        return sum(item.is_restricted for item in self.skipped)

    @property
    def error_count(self) -> int:
        return self.skipped_count - self.restricted_book_count

    @property
    def exit_code(self) -> int:
        return EXIT_FAILED if self.status is RunStatus.FAILED else EXIT_SUCCESS


def _new_counts() -> dict[Resolution, int]:
    return {resolution: 0 for resolution in Resolution}


def _log_skipped_row(outcome: SkippedRow, where: str) -> None:
    """One line for a skipped row (WARNING, INFO when restricted). ``where`` names the row: its rank, or page and rank."""
    log_skip = log.info if outcome.is_restricted else log.warning
    log_skip(
        "%s skipped after %d attempt(s) (%s): %s",
        where,
        outcome.failure.attempts,
        outcome.failure.error_type,
        outcome.failure.error_message,
    )


def _status(error: str | None, *, partial: bool) -> RunStatus:
    """The run status shared by every mode: FAILED on any error, else PARTIAL_SUCCESS when something was skipped."""
    if error is not None:
        return RunStatus.FAILED
    return RunStatus.PARTIAL_SUCCESS if partial else RunStatus.SUCCESS


def _book_counts(counts: Mapping[Resolution, int]) -> tuple[int, int, int]:
    """(existing, new, attached) Book counts for the run line; attached is a subset of existing."""
    attached = counts[Resolution.ISBN_ATTACHED]
    return counts[Resolution.EXISTING_SOURCE] + attached, counts[Resolution.NEW_BOOK], attached


class PagesLedger:
    """Accounts for one pages-mode run (crawler.md §16, pages mode).

    Pages mode only supplements the Catalog: it has no snapshot, no rank order, no duplicate-Book
    rule and no consecutive-error limit. A row failure never stops the run; a category page that
    could not be fetched or parsed is recorded as a skipped page. Status and exit code follow the
    same rules as ``RunLedger`` (``_status``), with one extra rule: when every configured page was
    skipped, the run fails.
    """

    def __init__(self) -> None:
        self._pages_total = 0
        self._skipped_pages: list[SkippedPage] = []
        self._rows_seen = 0
        self._skipped: list[SkippedRow] = []
        self._counts = _new_counts()

    def record_page_ok(self) -> None:
        """A category page was fetched and parsed; its rows are recorded next."""
        self._pages_total += 1

    def record_page_skipped(self, page: SkippedPage) -> None:
        """A category page was skipped after its attempts (crawler.md §16)."""
        self._pages_total += 1
        self._skipped_pages.append(page)
        log.warning(
            "category page skipped after %d attempt(s) (%s): %s: %s",
            page.failure.attempts,
            page.failure.error_type,
            page.url,
            page.failure.error_message,
        )

    def record(self, outcome: ResolvedRow | SkippedRow) -> None:
        """Account for one row of a processed page. Rank and Book identity are not checked across pages."""
        self._rows_seen += 1
        if isinstance(outcome, SkippedRow):
            self._skipped.append(outcome)
            _log_skipped_row(outcome, f"page rank {outcome.rank} ({outcome.url})")
        else:
            self._counts[outcome.resolution] += 1

    def report(
        self,
        *,
        run_id: str,
        started_at: datetime,
        finished_at: datetime,
        error: str | None = None,
    ) -> RunReport:
        """The run result. ``error`` is a failure that stops the run (database, browser, unexpected)."""
        if error is None and self._pages_total and len(self._skipped_pages) == self._pages_total:
            error = f"all {self._pages_total} category page(s) failed"
        existing, new, attached = _book_counts(self._counts)
        return RunReport(
            run_id=run_id,
            status=_status(error, partial=bool(self._skipped or self._skipped_pages)),
            started_at=started_at,
            finished_at=finished_at,
            existing_book_count=existing,
            new_book_count=new,
            attached_source_count=attached,
            skipped=list(self._skipped),
            error=error,
            pages_total=self._pages_total,
            rows_seen=self._rows_seen,
            skipped_pages=list(self._skipped_pages),
        )


class RunLedger:
    """Accounts for one run. Record outcomes in rank order; stop as soon as ``aborted`` is true.

    Error messages inside the outcomes are logged and reported as they are, so the caller must
    pass them already redacted (``run._failure`` does).
    """

    def __init__(self, *, max_consecutive_errors: int = MAX_CONSECUTIVE_ERRORS) -> None:
        self._max_consecutive_errors = max_consecutive_errors
        self._ranked: dict[UUID, int] = {}
        self._snapshot: list[SnapshotRow] = []
        self._skipped: list[SkippedRow] = []
        self._counts = _new_counts()
        self._streak = 0
        self._last_rank = 0
        self._aborted_at_rank: int | None = None
        self._abort_reason: str | None = None

    @property
    def ranked(self) -> Mapping[UUID, int]:
        """Each Book already in the snapshot, mapped to its rank (read-only)."""
        return MappingProxyType(self._ranked)

    @property
    def aborted(self) -> bool:
        return self._aborted_at_rank is not None

    @property
    def snapshot(self) -> tuple[SnapshotRow, ...]:
        """The rows that may replace the bestsellers, at their original ranks (gaps kept)."""
        return tuple(self._snapshot)

    def record(self, outcome: ResolvedRow | SkippedRow) -> None:
        """Account for the next row. Raises ``ValueError`` when called out of order or after an abort."""
        if self.aborted:
            raise ValueError(f"the run already aborted at rank {self._aborted_at_rank}")
        if outcome.rank <= self._last_rank:
            raise ValueError(f"rank {outcome.rank} recorded after rank {self._last_rank}: outcomes must arrive in rank order")
        self._last_rank = outcome.rank
        if isinstance(outcome, SkippedRow):
            self._record_skip(outcome)
        else:
            self._record_resolved(outcome)

    def report(
        self,
        *,
        run_id: str,
        started_at: datetime,
        finished_at: datetime,
        ranking_count: int,
        error: str | None = None,
    ) -> RunReport:
        """The run result. ``error`` is a failure outside the rows (ranking page, transaction, browser)."""
        if error is None and self._abort_reason is not None:
            error = self._abort_reason
        existing, new, attached = _book_counts(self._counts)
        return RunReport(
            run_id=run_id,
            status=_status(error, partial=bool(self._skipped)),
            started_at=started_at,
            finished_at=finished_at,
            ranking_count=ranking_count,
            existing_book_count=existing,
            new_book_count=new,
            attached_source_count=attached,
            skipped=list(self._skipped),
            consecutive_error_count=self._streak,
            aborted_at_rank=self._aborted_at_rank,
            error=error,
        )

    def _record_resolved(self, outcome: ResolvedRow) -> None:
        book_id = outcome.source_ref.book_id
        if book_id in self._ranked:
            # The run must skip a later rank that resolves to a ranked Book before writing anything.
            raise ValueError(f"rank {outcome.rank}: Book {book_id} is already used by rank {self._ranked[book_id]}")
        self._ranked[book_id] = outcome.rank
        self._snapshot.append(SnapshotRow(rank=outcome.rank, book_id=book_id, source_id=outcome.source_ref.source_id))
        self._counts[outcome.resolution] += 1
        self._streak = 0

    def _record_skip(self, outcome: SkippedRow) -> None:
        self._skipped.append(outcome)
        _log_skipped_row(outcome, f"rank {outcome.rank}")
        failure = outcome.failure
        if outcome.is_restricted:
            self._streak = 0
            return
        self._streak += 1
        if self._streak > self._max_consecutive_errors:
            # Stop early: a layout change would otherwise cost retries on every remaining row.
            self._aborted_at_rank = outcome.rank
            self._abort_reason = (
                f"run aborted at rank {outcome.rank} after {self._streak} consecutive error(s) "
                f"(limit {self._max_consecutive_errors}): {failure.error_type}: {failure.error_message}"
            )
