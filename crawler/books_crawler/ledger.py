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

from books_crawler.models import Resolution, ResolvedRow, RunStatus, SkippedRow, SnapshotRow

MAX_CONSECUTIVE_ERRORS = 20  # crawler.md §6, CRAWL-05

EXIT_SUCCESS = 0
EXIT_FAILED = 1

log = logging.getLogger("books_crawler.ledger")


@dataclass
class RunReport:
    """The outcome of one run, as logged on one line (crawler.md §12). Built by ``RunLedger.report``."""

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
        self._counts = {resolution: 0 for resolution in Resolution}
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

    @property
    def restricted_ranks(self) -> tuple[int, ...]:
        """Ranks skipped as restricted member pages; they must not appear in the snapshot."""
        return tuple(item.rank for item in self._skipped if item.is_restricted)

    def record(self, outcome: ResolvedRow | SkippedRow) -> None:
        """Account for the next row. Raises ``ValueError`` when called out of order or after an abort."""
        if self.aborted:
            raise ValueError(f"the run already aborted at rank {self._aborted_at_rank}")
        if outcome.rank <= self._last_rank:
            raise ValueError(
                f"rank {outcome.rank} recorded after rank {self._last_rank}: outcomes must arrive in rank order"
            )
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
        if error is not None:
            status = RunStatus.FAILED
        elif self._skipped:
            status = RunStatus.PARTIAL_SUCCESS
        else:
            status = RunStatus.SUCCESS
        attached = self._counts[Resolution.ISBN_ATTACHED]
        return RunReport(
            run_id=run_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            ranking_count=ranking_count,
            existing_book_count=self._counts[Resolution.EXISTING_SOURCE] + attached,
            new_book_count=self._counts[Resolution.NEW_BOOK],
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
        failure = outcome.failure
        log_skip = log.info if outcome.is_restricted else log.warning
        log_skip(
            "rank %d skipped after %d attempt(s) (%s): %s",
            outcome.rank,
            failure.attempts,
            failure.error_type,
            failure.error_message,
        )
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
