"""One crawler run: ranking → resolve sources to Books → replace bestsellers (crawler.md §3, §11).

Resolution of a ranking row (crawler.md §5):
1. Known BOOKS_COM_TW Book Source URL → reuse its Book, no detail request.
2. Unknown URL → fetch and parse the detail page, then:
   a. an ISBN-13 (then ISBN-10) of the detail page matches an existing Book → attach a new
      BOOKS_COM_TW Book Source to that Book; the Book's metadata is not changed;
   b. otherwise → create a new Book.

Retry and skip (crawler.md §6): one attempt for a new source is detail fetch + parse + ISBN lookup
+ Book transaction. A failed attempt is retried (up to ``MAX_ATTEMPTS`` in total). A row that still
fails is skipped: no rows are written for it and the snapshot keeps the other ranks' numbers.

A Book may appear at most once in a ranking (``bestsellers.book_id`` is unique). When a later rank
resolves to a Book already used by an earlier rank, the later rank is skipped (not retried, since
the outcome is deterministic); the earlier rank keeps the Book (crawler.md §5).

The ranking page itself is retried on fetch failure only, and never skipped (crawler.md §4).
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg

from books_crawler import db
from books_crawler.fetcher import FetchError, Fetcher
from books_crawler.models import IsbnMatch, RankingRow, RunStatus, SkippedRow, SnapshotRow, SourceRef
from books_crawler.parsers import RANKING_PAGE_URL, DetailParser, RankingParser
from books_crawler.ranking import MAX_SKIPPED_ROWS, validate_ranking, validate_snapshot

log = logging.getLogger("books_crawler.run")

EXIT_SUCCESS = 0
EXIT_FAILED = 1

MAX_ATTEMPTS = 3  # crawler.md §6: total attempts, first try included
BACKOFF_BASE_SECONDS = 1.0  # sleep before attempt n (n = 2, 3) is 1s, then 2s

# error_type values written to the skipped list (crawler.md §12)
ERROR_FETCH = "fetch_error"
ERROR_PARSE = "parse_error"
ERROR_DATABASE = "database_error"
ERROR_DUPLICATE = "duplicate_book_in_ranking"

_DSN_PATTERN = re.compile(r"postgres(?:ql)?://[^\s'\"]+")


class DuplicateBookInRankingError(RuntimeError):
    """A later ranking row resolves to a Book that an earlier rank already uses (not retried)."""


class SkipLimitExceededError(RuntimeError):
    """More than ``MAX_SKIPPED_ROWS`` rows were skipped: the run fails (crawler.md §6, CRAWL-05)."""


class _AttemptFailed(Exception):
    """One attempt at a new source failed in a retryable way."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def backoff_seconds(attempt: int) -> float:
    """Seconds to wait before ``attempt`` (2 or 3): 1s, then 2s (crawler.md §6)."""
    return BACKOFF_BASE_SECONDS * 2 ** (attempt - 2)


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
    error: str | None = None

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def exit_code(self) -> int:
        return EXIT_FAILED if self.status is RunStatus.FAILED else EXIT_SUCCESS


def _redact(text: str) -> str:
    """Never let a database URL (which carries credentials) reach the log."""
    return _DSN_PATTERN.sub("postgresql://<redacted>", text)


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
        "exit_code": report.exit_code,
    }
    line = " ".join(f"{key}={value}" for key, value in fields.items())
    skipped = [
        {
            "rank": item.rank,
            "url": item.url,
            "error_type": item.error_type,
            "error_message": item.error_message,
            "attempts": item.attempts,
        }
        for item in report.skipped
    ]
    line += f" skipped={json.dumps(skipped, ensure_ascii=False)}"
    if report.error:
        line += f" error={report.error!r}"
    return _redact(line)


def _skipped(row: RankingRow, error_type: str, message: str, attempts: int) -> SkippedRow:
    return SkippedRow(rank=row.rank, url=row.url, error_type=error_type, error_message=message, attempts=attempts)


def _duplicate_message(book_id: UUID, ranked: Mapping[UUID, int]) -> str:
    return f"resolves to Book {book_id}, which rank {ranked[book_id]} already uses; bestsellers.book_id must be unique"


def _fetch_ranking_page(deps: RunDependencies) -> str:
    """Fetch the ranking page with the same retry policy as details; failure fails the run."""
    last_error: FetchError | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            deps.sleep(backoff_seconds(attempt))
        try:
            return deps.fetcher.get(RANKING_PAGE_URL)
        except FetchError as exc:
            last_error = exc
            log.warning("ranking page attempt %d/%d failed: %s", attempt, MAX_ATTEMPTS, exc)
    raise FetchError(f"ranking page failed after {MAX_ATTEMPTS} attempts: {last_error}")


def _attempt_new_source(
    conn: psycopg.Connection,
    row: RankingRow,
    deps: RunDependencies,
    ranked: Mapping[UUID, int],
) -> tuple[SourceRef, IsbnMatch | None]:
    """One attempt for a new product: fetch, parse, ISBN lookup and its Book transaction."""
    try:
        html = deps.fetcher.get(row.url)
    except FetchError as exc:
        raise _AttemptFailed(ERROR_FETCH, str(exc)) from exc
    try:
        # ParseError (e.g. missing title or product container) and BookDraft validation are ValueErrors.
        draft = deps.parse_detail(html, row.url)
    except ValueError as exc:
        raise _AttemptFailed(ERROR_PARSE, str(exc)) from exc

    try:
        match = db.find_book_by_isbn(conn, draft.identifiers)
    except psycopg.Error as exc:
        raise _AttemptFailed(ERROR_DATABASE, str(exc)) from exc
    if match is not None and match.book_id in ranked:
        # Deterministic: not retried by the caller.
        raise DuplicateBookInRankingError(_duplicate_message(match.book_id, ranked))

    try:
        ref = db.persist_new_source(
            conn,
            draft,
            deps.clock(),
            attach_to_book_id=match.book_id if match is not None else None,
        )
    except psycopg.Error as exc:
        raise _AttemptFailed(ERROR_DATABASE, str(exc)) from exc
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
            return _skipped(row, ERROR_DUPLICATE, _duplicate_message(existing.book_id, ranked), attempts=1)
        report.existing_book_count += 1
        return existing

    last_failure: _AttemptFailed | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            deps.sleep(backoff_seconds(attempt))
        try:
            ref, match = _attempt_new_source(conn, row, deps, ranked)
        except DuplicateBookInRankingError as exc:
            return _skipped(row, ERROR_DUPLICATE, str(exc), attempts=attempt)
        except _AttemptFailed as exc:
            last_failure = exc
            log.warning(
                "rank %d attempt %d/%d failed (%s): %s", row.rank, attempt, MAX_ATTEMPTS, exc.error_type, exc.message
            )
            continue

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
    return _skipped(row, last_failure.error_type, last_failure.message, attempts=MAX_ATTEMPTS)


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
                        outcome.attempts,
                        outcome.error_type,
                        outcome.error_message,
                    )
                    if report.skipped_count > MAX_SKIPPED_ROWS:
                        # Stop early: a layout change would otherwise cost retries on every remaining row.
                        raise SkipLimitExceededError(
                            f"{report.skipped_count} ranking rows skipped, more than the limit of {MAX_SKIPPED_ROWS}"
                        )
                    continue
                ranked[outcome.book_id] = row.rank
                snapshot.append(SnapshotRow(rank=row.rank, book_id=outcome.book_id, source_id=outcome.source_id))

            status = status_for_skipped_count(report.skipped_count)
            if status is RunStatus.FAILED:  # unreachable: the limit is enforced in the loop above
                raise SkipLimitExceededError(f"{report.skipped_count} ranking rows skipped")
            source_books = db.booksdotcom_source_books(conn, [item.source_id for item in snapshot])
            replacement = validate_snapshot(snapshot, source_books)
            db.replace_bestsellers(conn, replacement, captured_at=deps.clock())

        report.status = status
    except Exception as exc:  # any failure fails the run; the previous bestsellers are untouched
        report.error = _redact(f"{type(exc).__name__}: {exc}")
        log.error("run failed: %s", report.error)

    report.finished_at = deps.clock()
    log.info("%s", format_report(report))
    return report
