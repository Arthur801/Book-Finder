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

Every row outcome goes, in rank order, to a ``RunLedger`` (``ledger.py``), which owns the counters,
the consecutive-error streak and abort, the snapshot rows and the final status. This module only
does the I/O: fetching, parsing, writing and publishing.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg

from books_crawler import db
from books_crawler.fetcher import FetchError, Fetcher
from books_crawler.ledger import RunLedger, RunReport
from books_crawler.models import (
    BookDraft,
    Failure,
    IsbnMatch,
    RankingRow,
    Resolution,
    ResolvedRow,
    SkipReason,
    SkippedRow,
    SourceRef,
)
from books_crawler.parsers import RANKING_PAGE_URL, DetailParser, RankingParser, RestrictedBookError
from books_crawler.ranking import validate_ranking, validate_snapshot
from books_crawler.redact import redact

log = logging.getLogger("books_crawler.run")

MAX_ATTEMPTS = 3  # crawler.md §6: total attempts, first try included
BACKOFF_BASE_SECONDS = 1.0  # sleep before attempt n (n = 2, 3) is 1s, then 2s


class DuplicateBookInRankingError(RuntimeError):
    """A later ranking row resolves to a Book that an earlier rank already uses (not retried)."""


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


@dataclass
class RunDependencies:
    fetcher: Fetcher
    parse_ranking: RankingParser
    parse_detail: DetailParser
    connect: Callable[[], psycopg.Connection]
    clock: Callable[[], datetime] = utc_now
    # Injected so that retry backoff never really waits in tests.
    sleep: Callable[[float], None] = time.sleep


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
        "restricted_book_count": report.restricted_book_count,
        "error_count": report.error_count,
        "consecutive_error_count": report.consecutive_error_count,
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
    except RestrictedBookError:
        raise
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
    ranked: Mapping[UUID, int],
) -> ResolvedRow | SkippedRow:
    """Resolve one ranking row to a Book, or skip it (crawler.md §5, §6).

    ``ranked`` maps each Book already used by an earlier rank to that rank (``RunLedger.ranked``).
    A row that would reuse one of those Books is skipped here, before anything is written.
    """
    existing = db.find_source(conn, row.url)
    if existing is not None:
        if existing.book_id in ranked:
            # The detail page is never fetched for a known URL, so no attempt was made.
            message = _duplicate_message(existing.book_id, ranked)
            return _skipped(row, _failure(SkipReason.DUPLICATE_BOOK_IN_RANKING, message, attempts=0))
        return ResolvedRow(rank=row.rank, source_ref=existing, resolution=Resolution.EXISTING_SOURCE)

    draft: BookDraft | None = None
    last_failure: Failure | None = None
    for attempt in _attempts(deps):
        try:
            if draft is None:
                draft = _fetch_and_parse(row, deps, attempt)
            ref, match = _write_new_source(conn, draft, deps, ranked, attempt)
        except RestrictedBookError as exc:
            log.info("rank %d restricted product skipped without retry: %s", row.rank, row.url)
            return _skipped(row, _failure(SkipReason.RESTRICTED_BOOK, str(exc), attempts=attempt))
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
            return ResolvedRow(rank=row.rank, source_ref=ref, resolution=Resolution.NEW_BOOK)
        log.info(
            "attached BOOKS_COM_TW source to existing Book: rank=%d url=%s matched=%s:%s book_id=%s",
            row.rank,
            row.url,
            match.identifier.identifier_type,
            match.identifier.identifier_value,
            match.book_id,
        )
        return ResolvedRow(rank=row.rank, source_ref=ref, resolution=Resolution.ISBN_ATTACHED)

    assert last_failure is not None  # the loop runs at least once and only continues on failure
    return _skipped(row, last_failure)


def run_first_book(deps: RunDependencies, run_id: str | None = None) -> RunReport:
    """Import only rank 1 into the catalog; never replace the bestseller snapshot.

    The ranking page is still validated in full. Resolution, normalization, ISBN matching,
    transactions and retry rules are shared with the daily crawler.
    """
    started_at = deps.clock()
    # Limit 0: a general error on the only row fails the import; a restricted page is a partial success.
    ledger = RunLedger(max_consecutive_errors=0)
    ranking_count = 0
    error: str | None = None
    try:
        rows = validate_ranking(deps.parse_ranking(_fetch_ranking_page(deps)))
        ranking_count = len(rows)
        row = rows[0]
        with deps.connect() as conn:
            outcome = _resolve_row(conn, row, deps, ledger.ranked)
        ledger.record(outcome)
        if isinstance(outcome, ResolvedRow):
            ref = outcome.source_ref
            log.info("rank=1 url=%s book_id=%s source_id=%s", row.url, ref.book_id, ref.source_id)
    except Exception as exc:
        error = redact(f"{type(exc).__name__}: {exc}")
    report = ledger.report(
        run_id=run_id or str(uuid.uuid4()),
        started_at=started_at,
        finished_at=deps.clock(),
        ranking_count=ranking_count,
        error=error,
    )
    if report.error:
        log.error("first-book import failed: %s", report.error)
    log.info("mode=first-book %s", format_report(report))
    return report


def run_once(deps: RunDependencies, run_id: str | None = None) -> RunReport:
    """Execute one crawl. Never raises: failures are reported through ``RunReport``."""
    started_at = deps.clock()
    ledger = RunLedger()
    ranking_count = 0
    error: str | None = None
    try:
        html = _fetch_ranking_page(deps)
        rows = validate_ranking(deps.parse_ranking(html))
        ranking_count = len(rows)

        with deps.connect() as conn:
            for row in rows:
                ledger.record(_resolve_row(conn, row, deps, ledger.ranked))
                if ledger.aborted:
                    break
            if not ledger.aborted:
                snapshot = ledger.snapshot
                source_books = db.booksdotcom_source_books(conn, [item.source_id for item in snapshot])
                replacement = validate_snapshot(snapshot, source_books, restricted_ranks=ledger.restricted_ranks)
                db.replace_bestsellers(conn, replacement, captured_at=deps.clock())
    except Exception as exc:  # any failure fails the run; the previous bestsellers are untouched
        error = redact(f"{type(exc).__name__}: {exc}")

    report = ledger.report(
        run_id=run_id or str(uuid.uuid4()),
        started_at=started_at,
        finished_at=deps.clock(),
        ranking_count=ranking_count,
        error=error,
    )
    if report.error:  # one ERROR line per failed run, abort included
        log.error("run failed: %s", report.error)
    log.info("%s", format_report(report))
    return report
