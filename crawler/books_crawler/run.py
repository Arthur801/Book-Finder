"""One crawler run: ranking → resolve/persist books → replace bestsellers (crawler.md §3, §11).

Issue #6 scope: success path only. Any failure fails the whole run; retry and skip
(PARTIAL_SUCCESS, crawler.md §6) are issue #7. The per-row step is ``_resolve_row`` so #7 can
wrap it with retry/skip without changing the flow.

Resolution of a ranking row (crawler.md §5):
1. Known BOOKS_COM_TW source URL → reuse its Book, no detail request.
2. Unknown URL → fetch and parse the detail page, then:
   a. an ISBN-13 (then ISBN-10) of the product matches an existing Book → attach a new
      BOOKS_COM_TW source to that Book; the Book's metadata is not changed;
   b. otherwise → create a new Book.
A Book may appear at most once in a ranking (``bestsellers.book_id`` is unique); a second rank
resolving to the same Book fails the run.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg

from books_crawler import db
from books_crawler.fetcher import Fetcher
from books_crawler.models import RankingRow, SnapshotRow
from books_crawler.parsers import RANKING_PAGE_URL, DetailParser, RankingParser
from books_crawler.ranking import validate_ranking, validate_snapshot

log = logging.getLogger("books_crawler.run")

STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
EXIT_CODES = {STATUS_SUCCESS: 0, STATUS_FAILED: 1}


class DuplicateBookInRankingError(RuntimeError):
    """Two ranking rows resolve to the same Book, which the bestseller table cannot hold."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RunDependencies:
    fetcher: Fetcher
    parse_ranking: RankingParser
    parse_detail: DetailParser
    connect: Callable[[], psycopg.Connection]
    clock: Callable[[], datetime] = utc_now
    ranking_url: str = RANKING_PAGE_URL


@dataclass
class RunReport:
    run_id: str
    status: str
    started_at: datetime
    finished_at: datetime
    ranking_count: int = 0
    # Rows resolved to an existing Book: known source URL, or new product attached by ISBN.
    existing_book_count: int = 0
    # Rows that created a new Book.
    new_book_count: int = 0
    # Subset of existing_book_count: new products attached to an existing Book by ISBN.
    attached_source_count: int = 0
    skipped_count: int = 0
    error: str | None = None

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.status]


def format_report(report: RunReport) -> str:
    """One key=value line per run for stdout (crawler.md §12, without #7's skipped list)."""
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
    if report.error:
        line += f" error={report.error!r}"
    return line


def _reject_if_ranked(book_id: UUID, row: RankingRow, ranked_book_ids: set[UUID]) -> None:
    if book_id in ranked_book_ids:
        raise DuplicateBookInRankingError(
            f"rank {row.rank} ({row.url}) resolves to Book {book_id}, which another rank in this ranking "
            "already uses; bestsellers.book_id must be unique"
        )


def _resolve_row(
    conn: psycopg.Connection,
    row: RankingRow,
    deps: RunDependencies,
    report: RunReport,
    ranked_book_ids: set[UUID],
) -> db.SourceRef:
    """Resolve one ranking row to a Book. Known URLs are reused without fetching the detail page."""
    existing = db.find_source(conn, row.url)
    if existing is not None:
        _reject_if_ranked(existing.book_id, row, ranked_book_ids)
        report.existing_book_count += 1
        return existing

    html = deps.fetcher.get(row.url)
    draft = deps.parse_detail(html, row.url)
    try:
        persisted = db.persist_new_product(conn, draft, deps.clock(), reserved_book_ids=ranked_book_ids)
    except db.BookAlreadyRankedError as exc:
        raise DuplicateBookInRankingError(
            f"rank {row.rank} ({row.url}) matches an ISBN of Book {exc.book_id}, which another rank "
            "in this ranking already uses; bestsellers.book_id must be unique"
        ) from exc

    if persisted.matched_identifier is not None:
        report.existing_book_count += 1
        report.attached_source_count += 1
        log.info(
            "attached BOOKS_COM_TW source to existing Book: rank=%d url=%s matched=%s:%s book_id=%s",
            row.rank,
            row.url,
            persisted.matched_identifier.identifier_type,
            persisted.matched_identifier.identifier_value,
            persisted.ref.book_id,
        )
    else:
        report.new_book_count += 1
    return persisted.ref


def run_once(deps: RunDependencies, run_id: str | None = None) -> RunReport:
    """Execute one crawl. Never raises: failures are reported through ``RunReport``."""
    report = RunReport(
        run_id=run_id or str(uuid.uuid4()),
        status=STATUS_FAILED,
        started_at=deps.clock(),
        finished_at=deps.clock(),
    )
    try:
        html = deps.fetcher.get(deps.ranking_url)
        rows = validate_ranking(deps.parse_ranking(html))
        report.ranking_count = len(rows)

        with deps.connect() as conn:
            snapshot: list[SnapshotRow] = []
            ranked_book_ids: set[UUID] = set()
            for row in rows:
                ref = _resolve_row(conn, row, deps, report, ranked_book_ids)
                ranked_book_ids.add(ref.book_id)
                snapshot.append(SnapshotRow(rank=row.rank, book_id=ref.book_id, source_id=ref.source_id))
            replacement = validate_snapshot(snapshot)
            db.replace_bestsellers(conn, replacement, captured_at=deps.clock())

        report.status = STATUS_SUCCESS
    except Exception as exc:  # any failure fails the run; the previous bestsellers are untouched
        report.error = f"{type(exc).__name__}: {exc}"
        log.error("run failed: %s", report.error)

    report.finished_at = deps.clock()
    log.info("%s", format_report(report))
    return report
