"""One crawler run: ranking → resolve/persist books → replace bestsellers (crawler.md §3, §11).

Issue #6 scope: success path only. Any failure fails the whole run; retry and skip
(PARTIAL_SUCCESS, crawler.md §6) are issue #7. The per-book step is ``_resolve_row`` so #7 can
wrap it with retry/skip without changing the flow.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

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
    existing_book_count: int = 0
    new_book_count: int = 0
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
        "skipped_count": report.skipped_count,
        "exit_code": report.exit_code,
    }
    line = " ".join(f"{key}={value}" for key, value in fields.items())
    if report.error:
        line += f" error={report.error!r}"
    return line


def _resolve_row(
    conn: psycopg.Connection,
    row: RankingRow,
    deps: RunDependencies,
    report: RunReport,
) -> db.SourceRef:
    """Resolve one ranking row to a Book. Existing URLs are reused without fetching detail."""
    existing = db.find_source(conn, row.url)
    if existing is not None:
        report.existing_book_count += 1
        return existing

    html = deps.fetcher.get(row.url)
    draft = deps.parse_detail(html, row.url)
    ref = db.insert_new_book(conn, draft, deps.clock())
    report.new_book_count += 1
    return ref


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
            for row in rows:
                ref = _resolve_row(conn, row, deps, report)
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
