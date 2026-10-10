"""One crawler run: ranking → resolve sources to Books → replace bestsellers (crawler.md §3, §11).

Resolution of a ranking row (crawler.md §5):
1. Known BOOKS_COM_TW Book Source URL → reuse its Book, no detail request.
2. Unknown URL → fetch and parse the detail page, then:
   a. an ISBN-13 (then ISBN-10) of the detail page matches an existing Book → attach a new
      BOOKS_COM_TW Book Source to that Book; the Book's metadata is not changed;
   b. otherwise → create a new Book.

Retry and skip (crawler.md §6). A new source gets at most ``MAX_ATTEMPTS`` attempts in total:

- a fetch or parse failure is retried from the detail request (the page is fetched again);
- a failure of the database write (ISBN lookup or the Book transaction) is retried with the
  already-parsed draft; the detail page is not fetched again.

A row that still fails is skipped: no rows are written for it, and the snapshot keeps the other
ranks' numbers. The ranking page is retried on fetch failure only and is never skipped (crawler.md §4).

A Book may appear at most once in a ranking (``bestsellers.book_id`` is unique). When a later rank
resolves to a Book already used by an earlier rank, the later rank is skipped (not retried, since
the outcome is deterministic); the earlier rank keeps the Book (crawler.md §5).

A browser that cannot be started raises ``BrowserUnavailableError``. That is not a ``FetchError``,
so it is neither retried nor skipped per row: it fails the whole run.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg

from books_crawler import db
from books_crawler.fetcher import FetchError, Fetcher
from books_crawler.models import (
    BookDraft,
    Failure,
    IsbnMatch,
    RankingRow,
    RunStatus,
    SkipReason,
    SkippedRow,
    SnapshotRow,
    SourceRef,
)
from books_crawler.parsers import RANKING_PAGE_URL, DetailParser, RankingParser
from books_crawler.ranking import MAX_SKIPPED_ROWS, validate_ranking, validate_snapshot
from books_crawler.redact import redact

log = logging.getLogger("books_crawler.run")

EXIT_SUCCESS = 0
EXIT_FAILED = 1

MAX_ATTEMPTS = 3  # crawler.md §6: total attempts, first try included
BACKOFF_BASE_SECONDS = 1.0  # sleep before attempt n (n = 2, 3) is 1s, then 2s


class DuplicateBookInRankingError(RuntimeError):
    """A later ranking row resolves to a Book that an earlier rank already uses (not retried)."""


class SkipLimitExceededError(RuntimeError):
    """More than ``MAX_SKIPPED_ROWS`` rows were skipped: the run fails (crawler.md §6, CRAWL-05)."""


class _AttemptFailed(Exception):
    """A retryable failure of one attempt; carries the ``Failure`` describing it."""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.error_message)
        self.failure = failure


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def backoff_seconds(attempt: int) -> float:
    """Seconds to wait before ``attempt`` (2 or 3): 1s, then 2s (crawler.md §6)."""
    return BACKOFF_BASE_SECONDS * 2 ** (attempt - 2)


def _attempts(deps: RunDependencies) -> Iterator[int]:
    """The shared retry loop: yields attempt numbers 1..MAX_ATTEMPTS, sleeping the backoff before each retry.

    The caller decides what is retryable: it ``continue``s on a retryable failure and returns on success.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            deps.sleep(backoff_seconds(attempt))
        yield attempt


def status_for_skipped_count(skipped_count: int) -> RunStatus:
    """crawler.md §11: 0 skipped → SUCCESS, 1..10 → PARTIAL_SUCCESS, more → FAILED."""
    if skipped_count == 0:
        return RunStatus.SUCCESS
    if skipped_count <= MAX_SKIPPED_ROWS:
        return RunStatus.PARTIAL_SUCCESS
    return RunStatus.FAILED


@dataclass
class RunDependencies:
    fetcher: Fetcher
    parse_ranking: RankingParser
    parse_detail: DetailParser
    connect: Callable[[], psycopg.Connection]
    clock: Callable[[], datetime] = utc_now
    # Injected so that retry backoff never really waits in tests.
    sleep: Callable[[float], None] = time.sleep


@dataclass
class RunReport:
    run_id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    ranking_count: int = 0
    # Rows resolved to an existing Book: known source URL, or new product attached by ISBN.
    existing_book_count: int = 0
    # Rows that created a new Book.
    new_book_count: int = 0
    # Subset of existing_book_count: new products attached to an existing Book by ISBN.
    attached_source_count: int = 0
    skipped: list[SkippedRow] = field(default_factory=list)
    # Rank of the row whose skip pushed the count over the limit; the run stopped there.
    aborted_at_rank: int | None = None
    error: str | None = None

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def exit_code(self) -> int:
        return EXIT_FAILED if self.status is RunStatus.FAILED else EXIT_SUCCESS


def format_report(report: RunReport) -> str:
    """One line per run for stdout (crawler.md §12). ``skipped`` is a JSON list of the skipped rows."""
    fields: dict[str, Any] = {
        "run_id": report.run_id,
        "started_at": report.started_at.isoformat(),
        "finished_at": report.finished_at.isoformat(),
        "status": report.status,
        "ranking_count": report.ranking_count,
        "existing_book_count": report.existing_book_count,
        "new_book_count": report.new_book_count,
        "attached_source_count": report.attached_source_count,
        "skipped_count": report.skipped_count,
        "aborted_at_rank": "none" if report.aborted_at_rank is None else report.aborted_at_rank,
        "exit_code": report.exit_code,
    }
    line = " ".join(f"{key}={value}" for key, value in fields.items())
    skipped = [
        {
            "rank": item.rank,
            "url": item.url,
            "error_type": item.failure.error_type,
            "error_message": item.failure.error_message,
            "attempts": item.failure.attempts,
        }
        for item in report.skipped
    ]
    line += f" skipped={json.dumps(skipped, ensure_ascii=False)}"
    if report.error:
        line += f" error={report.error!r}"
    return redact(line)


def _failure(reason: SkipReason, message: str, attempts: int) -> Failure:
    """Every stored error message is redacted here, so no later log line can leak a secret."""
    return Failure(error_type=reason, error_message=redact(message), attempts=attempts)


def _skipped(row: RankingRow, failure: Failure) -> SkippedRow:
    return SkippedRow(rank=row.rank, url=row.url, failure=failure)


def _duplicate_message(book_id: UUID, ranked: Mapping[UUID, int]) -> str:
    return f"resolves to Book {book_id}, which rank {ranked[book_id]} already uses; bestsellers.book_id must be unique"


def _fetch_ranking_page(deps: RunDependencies) -> str:
    """Fetch the ranking page with the shared retry loop; failure after all attempts fails the run."""
    last_error: FetchError | None = None
    for attempt in _attempts(deps):
        try:
            return deps.fetcher.get(RANKING_PAGE_URL)
        except FetchError as exc:
            last_error = exc
            log.warning("ranking page attempt %d/%d failed: %s", attempt, MAX_ATTEMPTS, redact(str(exc)))
    raise FetchError(f"ranking page failed after {MAX_ATTEMPTS} attempts: {last_error}") from last_error


def _fetch_and_parse(row: RankingRow, deps: RunDependencies, attempt: int) -> BookDraft:
    """Detail request and parse. Both failures are retryable; the caller fetches again on retry."""
    try:
        html = deps.fetcher.get(row.url)
    except FetchError as exc:
        raise _AttemptFailed(_failure(SkipReason.FETCH_ERROR, str(exc), attempt)) from exc
    try:
        # ParseError (e.g. missing title or product container) and BookDraft validation are ValueErrors.
        return deps.parse_detail(html, row.url)
    except ValueError as exc:
        raise _AttemptFailed(_failure(SkipReason.PARSE_ERROR, str(exc), attempt)) from exc


def _write_new_source(
    conn: psycopg.Connection,
    draft: BookDraft,
    deps: RunDependencies,
    ranked: Mapping[UUID, int],
    attempt: int,
) -> tuple[SourceRef, IsbnMatch | None]:
    """ISBN lookup and the Book transaction for one parsed draft. Database errors are retryable."""
    try:
        match = db.find_book_by_isbn(conn, draft.identifiers)
    except psycopg.Error as exc:
        raise _AttemptFailed(_failure(SkipReason.DATABASE_ERROR, str(exc), attempt)) from exc
    if match is not None and match.book_id in ranked:
        # Deterministic: the caller skips the row without retrying.
        raise DuplicateBookInRankingError(_duplicate_message(match.book_id, ranked))

    try:
        ref = db.persist_new_source(
            conn,
            draft,
            deps.clock(),
            attach_to_book_id=match.book_id if match is not None else None,
        )
    except psycopg.Error as exc:
        raise _AttemptFailed(_failure(SkipReason.DATABASE_ERROR, str(exc), attempt)) from exc
    return ref, match


def _resolve_row(
    conn: psycopg.Connection,
    row: RankingRow,
    deps: RunDependencies,
    report: RunReport,
    ranked: Mapping[UUID, int],
) -> SourceRef | SkippedRow:
    """Resolve one ranking row to a Book, or skip it (crawler.md §5, §6).

    ``ranked`` maps each Book already used by an earlier rank to that rank.
    """
    existing = db.find_source(conn, row.url)
    if existing is not None:
        if existing.book_id in ranked:
            # The detail page is never fetched for a known URL, so no attempt was made.
            message = _duplicate_message(existing.book_id, ranked)
            return _skipped(row, _failure(SkipReason.DUPLICATE_BOOK_IN_RANKING, message, attempts=0))
        report.existing_book_count += 1
        return existing

    draft: BookDraft | None = None
    last_failure: Failure | None = None
    for attempt in _attempts(deps):
        try:
            if draft is None:
                draft = _fetch_and_parse(row, deps, attempt)
            ref, match = _write_new_source(conn, draft, deps, ranked, attempt)
        except _AttemptFailed as exc:
            last_failure = exc.failure
            log.warning(
                "rank %d attempt %d/%d failed (%s): %s",
                row.rank,
                attempt,
                MAX_ATTEMPTS,
                exc.failure.error_type,
                exc.failure.error_message,
            )
            continue
        except DuplicateBookInRankingError as exc:
            return _skipped(row, _failure(SkipReason.DUPLICATE_BOOK_IN_RANKING, str(exc), attempts=attempt))

        if match is None:
            report.new_book_count += 1
            return ref
        report.existing_book_count += 1
        report.attached_source_count += 1
        log.info(
            "attached BOOKS_COM_TW source to existing Book: rank=%d url=%s matched=%s:%s book_id=%s",
            row.rank,
            row.url,
            match.identifier.identifier_type,
            match.identifier.identifier_value,
            match.book_id,
        )
        return ref

    assert last_failure is not None  # the loop runs at least once and only continues on failure
    return _skipped(row, last_failure)


def run_once(deps: RunDependencies, run_id: str | None = None) -> RunReport:
    """Execute one crawl. Never raises: failures are reported through ``RunReport``."""
    report = RunReport(
        run_id=run_id or str(uuid.uuid4()),
        status=RunStatus.FAILED,
        started_at=deps.clock(),
        finished_at=deps.clock(),
    )
    try:
        html = _fetch_ranking_page(deps)
        rows = validate_ranking(deps.parse_ranking(html))
        report.ranking_count = len(rows)

        with deps.connect() as conn:
            snapshot: list[SnapshotRow] = []
            ranked: dict[UUID, int] = {}
            for row in rows:
                outcome = _resolve_row(conn, row, deps, report, ranked)
                if isinstance(outcome, SkippedRow):
                    report.skipped.append(outcome)
                    log.warning(
                        "rank %d skipped after %d attempt(s) (%s): %s",
                        outcome.rank,
                        outcome.failure.attempts,
                        outcome.failure.error_type,
                        outcome.failure.error_message,
                    )
                    if report.skipped_count > MAX_SKIPPED_ROWS:
                        # Stop early: a layout change would otherwise cost retries on every remaining row.
                        report.aborted_at_rank = row.rank
                        raise SkipLimitExceededError(
                            f"{report.skipped_count} ranking rows skipped, more than the limit of {MAX_SKIPPED_ROWS}"
                        )
                    continue
                ranked[outcome.book_id] = row.rank
                snapshot.append(SnapshotRow(rank=row.rank, book_id=outcome.book_id, source_id=outcome.source_id))

            status = status_for_skipped_count(report.skipped_count)
            source_books = db.booksdotcom_source_books(conn, [item.source_id for item in snapshot])
            replacement = validate_snapshot(snapshot, source_books)
            db.replace_bestsellers(conn, replacement, captured_at=deps.clock())

        report.status = status
    except Exception as exc:  # any failure fails the run; the previous bestsellers are untouched
        report.error = redact(f"{type(exc).__name__}: {exc}")
        log.error("run failed: %s", report.error)

    report.finished_at = deps.clock()
    log.info("%s", format_report(report))
    return report
