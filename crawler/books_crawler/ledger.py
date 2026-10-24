"""Run accounting: every rule that turns item outcomes into a run result (crawler.md §10.2, §14, §15.7).

Every discovery item gets a ``CatalogResolution`` from the resolver (``run.py``). The ledger turns
that into the counters, and for the ranking job also into a ``RankingDecision``:

- the Catalog counters (crawler.md §10.2), which apply to every job and every decision;
- for the daily ranking (and first_book): ``decide_ranking`` (§14.2) gives ADMITTED, DUPLICATE_BOOK,
  RESTRICTED_SKIP or ERROR_SKIP. Only that decision moves the skip counters and the consecutive-error
  streak (§14.3). A Book that an earlier rank already uses becomes DUPLICATE_BOOK here, after the
  Catalog side has been committed;
- which Books the snapshot already uses (``ranked``) and the snapshot rows themselves;
- the abort decision: a streak above ``max_consecutive_errors`` stops the run at that rank;
- the final status and exit code (``report``).

The daily run uses the default limit of 20. The single-book import uses 0 (crawler.md §16), so its
only row fails the run on a general error and is a partial success when restricted.

Pages mode (crawler.md §15) has its own ``PagesLedger``: it uses only the ``CatalogResolution``, with no
rank order, no snapshot, no duplicate-Book rule and no consecutive-error limit. A skipped page is
recorded; the run fails only when every configured page was skipped. Both ledgers share the status
rule (``_status``) and the Catalog counters (``CatalogCounts``), so status and exit code are decided
in one place.

No I/O apart from logging skipped rows: tests drive it directly, without a database or a fetcher. The
caller logs the one ERROR line of a failed run, abort included.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from books_crawler.models import (
    PROVIDER_CODE,
    CatalogResolution,
    Failure,
    JobName,
    RankingDecision,
    ResolvedRow,
    RunStatus,
    SkippedPage,
    SkippedRow,
    SkipReason,
    SnapshotRow,
)

MAX_CONSECUTIVE_ERRORS = 20  # crawler.md §14.3, CRAWL-05

EXIT_SUCCESS = 0
EXIT_FAILED = 1

log = logging.getLogger("books_crawler.ledger")


@dataclass(frozen=True)
class CatalogCounts:
    """The Catalog-axis counters of crawler.md §10.2, derived from the ``CatalogResolution`` of every item."""

    existing_book: int = 0  # EXISTING + ISBN_ATTACHED (an attached source belongs to an existing Book)
    new_book: int = 0  # IMPORTED + AMBIGUOUS_CREATED
    attached_source: int = 0  # ISBN_ATTACHED
    existing_source: int = 0  # EXISTING
    new_source: int = 0  # IMPORTED + ISBN_ATTACHED + AMBIGUOUS_CREATED
    ambiguous_isbn: int = 0  # AMBIGUOUS_CREATED

    @classmethod
    def of(cls, counts: Mapping[CatalogResolution, int]) -> CatalogCounts:
        existing = counts[CatalogResolution.EXISTING]
        imported = counts[CatalogResolution.IMPORTED]
        attached = counts[CatalogResolution.ISBN_ATTACHED]
        ambiguous = counts[CatalogResolution.AMBIGUOUS_CREATED]
        return cls(
            existing_book=existing + attached,
            new_book=imported + ambiguous,
            attached_source=attached,
            existing_source=existing,
            new_source=imported + attached + ambiguous,
            ambiguous_isbn=ambiguous,
        )


def decide_ranking(resolution: CatalogResolution, *, already_ranked: bool) -> RankingDecision:
    """The ranking decision of one item (crawler.md §14.2). ``already_ranked``: its Book is used by an earlier rank."""
    if resolution is CatalogResolution.RESTRICTED:
        return RankingDecision.RESTRICTED_SKIP
    if resolution is CatalogResolution.FAILED:
        return RankingDecision.ERROR_SKIP
    return RankingDecision.DUPLICATE_BOOK if already_ranked else RankingDecision.ADMITTED


@dataclass
class RunReport:
    """The outcome of one run, as logged on one line (crawler.md §19.2, §15.8). Built by ``RunLedger.report`` or ``PagesLedger.report``."""

    run_id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    job_name: JobName
    provider_code: str = PROVIDER_CODE
    ranking_count: int = 0
    # Items sent to resolution (crawler.md §19.2). Pages mode reports the same number as rows_seen.
    items_seen: int = 0
    # Catalog axis: resolved to an existing Book (known source, or new source attached by ISBN).
    existing_book_count: int = 0
    # Catalog axis: created a new Book.
    new_book_count: int = 0
    # Subset of existing_book_count: new sources attached to an existing Book by ISBN.
    attached_source_count: int = 0
    existing_source_count: int = 0
    new_source_count: int = 0
    ambiguous_isbn_count: int = 0
    skipped: list[SkippedRow] = field(default_factory=list)
    # Current streak of terminal non-restricted row failures.
    consecutive_error_count: int = 0
    # Rank where the consecutive-error limit was exceeded; the run stopped there.
    aborted_at_rank: int | None = None
    error: str | None = None
    # Pages mode only (crawler.md §15); None / empty for the daily and first-book runs.
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
    def offer_updated_count(self) -> int:
        """Always 0: offers are not ingested yet (crawler.md §8)."""
        return 0

    @property
    def exit_code(self) -> int:
        return EXIT_FAILED if self.status is RunStatus.FAILED else EXIT_SUCCESS


def _new_counts() -> dict[CatalogResolution, int]:
    return {resolution: 0 for resolution in CatalogResolution}


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


class PagesLedger:
    """Accounts for one pages-mode run (crawler.md §15).

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
        """A category page was skipped after its attempts (crawler.md §15.4)."""
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
        self._counts[outcome.resolution] += 1
        if isinstance(outcome, SkippedRow):
            self._skipped.append(outcome)
            _log_skipped_row(outcome, f"page rank {outcome.rank} ({outcome.url})")

    def report(
        self,
        *,
        run_id: str,
        job_name: JobName,
        started_at: datetime,
        finished_at: datetime,
        error: str | None = None,
    ) -> RunReport:
        """The run result. ``error`` is a failure that stops the run (database, browser, unexpected)."""
        if error is None and self._pages_total and len(self._skipped_pages) == self._pages_total:
            error = f"all {self._pages_total} category page(s) failed"
        catalog = CatalogCounts.of(self._counts)
        return RunReport(
            run_id=run_id,
            status=_status(error, partial=bool(self._skipped or self._skipped_pages)),
            started_at=started_at,
            finished_at=finished_at,
            job_name=job_name,
            items_seen=self._rows_seen,
            existing_book_count=catalog.existing_book,
            new_book_count=catalog.new_book,
            attached_source_count=catalog.attached_source,
            existing_source_count=catalog.existing_source,
            new_source_count=catalog.new_source,
            ambiguous_isbn_count=catalog.ambiguous_isbn,
            skipped=list(self._skipped),
            error=error,
            pages_total=self._pages_total,
            rows_seen=self._rows_seen,
            skipped_pages=list(self._skipped_pages),
        )


class RunLedger:
    """Accounts for one ranking run. Record outcomes in rank order; stop as soon as ``aborted`` is true.

    Error messages inside the outcomes are logged and reported as they are, so the caller must
    pass them already redacted (``run._failure`` does).
    """

    def __init__(self, *, max_consecutive_errors: int = MAX_CONSECUTIVE_ERRORS) -> None:
        self._max_consecutive_errors = max_consecutive_errors
        self._ranked: dict[UUID, int] = {}
        self._snapshot: list[SnapshotRow] = []
        self._skipped: list[SkippedRow] = []
        self._counts = _new_counts()
        self._items_seen = 0
        self._streak = 0
        self._last_rank = 0
        self._aborted_at_rank: int | None = None
        self._abort_reason: str | None = None

    @property
    def ranked(self) -> Mapping[UUID, int]:
        """Each Book already used by an admitted rank, mapped to that rank (read-only)."""
        return MappingProxyType(self._ranked)

    @property
    def aborted(self) -> bool:
        return self._aborted_at_rank is not None

    @property
    def snapshot(self) -> tuple[SnapshotRow, ...]:
        """The admitted rows, at their original ranks (gaps kept): what may replace the bestsellers."""
        return tuple(self._snapshot)

    def record(self, outcome: ResolvedRow | SkippedRow) -> None:
        """Account for the next item. Raises ``ValueError`` when called out of order or after an abort."""
        if self.aborted:
            raise ValueError(f"the run already aborted at rank {self._aborted_at_rank}")
        if outcome.rank <= self._last_rank:
            raise ValueError(f"rank {outcome.rank} recorded after rank {self._last_rank}: outcomes must arrive in rank order")
        self._last_rank = outcome.rank
        self._items_seen += 1
        self._counts[outcome.resolution] += 1

        if isinstance(outcome, SkippedRow):
            self._apply(decide_ranking(outcome.resolution, already_ranked=False), outcome)
            return
        book_id = outcome.source_ref.book_id
        decision = decide_ranking(outcome.resolution, already_ranked=book_id in self._ranked)
        if decision is RankingDecision.DUPLICATE_BOOK:
            message = f"resolves to Book {book_id}, which rank {self._ranked[book_id]} already uses; bestsellers.book_id must be unique"
            failure = Failure(error_type=SkipReason.DUPLICATE_BOOK_IN_RANKING, error_message=message, attempts=outcome.attempts)
            self._apply(decision, SkippedRow(rank=outcome.rank, url=outcome.url, failure=failure))
            return
        self._ranked[book_id] = outcome.rank
        self._snapshot.append(SnapshotRow(rank=outcome.rank, book_id=book_id, source_id=outcome.source_ref.source_id))
        self._streak = 0

    def report(
        self,
        *,
        run_id: str,
        job_name: JobName,
        started_at: datetime,
        finished_at: datetime,
        ranking_count: int,
        error: str | None = None,
    ) -> RunReport:
        """The run result. ``error`` is a failure outside the rows (ranking page, transaction, browser)."""
        if error is None and self._abort_reason is not None:
            error = self._abort_reason
        catalog = CatalogCounts.of(self._counts)
        return RunReport(
            run_id=run_id,
            status=_status(error, partial=bool(self._skipped)),
            started_at=started_at,
            finished_at=finished_at,
            job_name=job_name,
            ranking_count=ranking_count,
            items_seen=self._items_seen,
            existing_book_count=catalog.existing_book,
            new_book_count=catalog.new_book,
            attached_source_count=catalog.attached_source,
            existing_source_count=catalog.existing_source,
            new_source_count=catalog.new_source,
            ambiguous_isbn_count=catalog.ambiguous_isbn,
            skipped=list(self._skipped),
            consecutive_error_count=self._streak,
            aborted_at_rank=self._aborted_at_rank,
            error=error,
        )

    def _apply(self, decision: RankingDecision, skip: SkippedRow) -> None:
        """Account for a row that is left out of the snapshot: RESTRICTED_SKIP, ERROR_SKIP or DUPLICATE_BOOK."""
        self._skipped.append(skip)
        _log_skipped_row(skip, f"rank {skip.rank}")
        if decision is RankingDecision.RESTRICTED_SKIP:
            self._streak = 0
            return
        # ERROR_SKIP and DUPLICATE_BOOK are general errors: they count toward the streak (crawler.md §14.3).
        self._streak += 1
        if self._streak > self._max_consecutive_errors:
            # Stop early: a layout change would otherwise cost retries on every remaining row.
            failure = skip.failure
            self._aborted_at_rank = skip.rank
            self._abort_reason = (
                f"run aborted at rank {skip.rank} after {self._streak} consecutive error(s) "
                f"(limit {self._max_consecutive_errors}): {failure.error_type}: {failure.error_message}"
            )
