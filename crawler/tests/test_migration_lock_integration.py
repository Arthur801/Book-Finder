"""The Catalog migration lock and the schema preflight against the real PostgreSQL (plan v12 §8).

A migration holds the exclusive side of ``CATALOG_MIGRATION_LOCK_KEY`` (the deploy side lives outside the crawler). The
crawler takes the shared side on every connection it writes through. These tests hold the exclusive side from a second
connection and check that the crawler writes nothing; they end the crawler's backend and check that the new connection
takes the lock again. Schema changes are made inside a transaction and rolled back, or committed and restored in
``finally``. Runs on the throwaway database of ``conftest.py``; nothing skips.
"""

from __future__ import annotations

import json

import psycopg
import pytest

from books_crawler.models import RunStatus as BooksRunStatus
from books_crawler.run import RunDependencies
from books_crawler.run import run_pages as books_run_pages
from catalog_core import persistence
from catalog_core.migration_lock import CATALOG_MIGRATION_LOCK_KEY, MigrationLockBusy
from catalog_core.models import ProviderCode, WritePolicy
from catalog_core.session import DatabaseSession
from catalog_core.store import SessionCatalogStore
from kingstone import cli
from kingstone.ledger import RunStatus as KingstoneRunStatus
from kingstone.run import KingstoneRunDependencies, SoftBudget, run_pages
from tests.fakes import FakeFetcher as BooksFakeFetcher
from tests.fakes import FakeSleep, fake_detail_parser, make_draft, ranking_rows
from tests.test_db_integration import query
from tests.test_db_integration import run as books_run_once
from tests.test_kingstone_db_integration import (
    KM_1,
    KM_2,
    KM_3,
    LIST_A,
    NOW,
    FakeFetcher,
    book_count,
    kingstone_sources,
    set_kingstone_enabled,
    site,
)

KEY = CATALOG_MIGRATION_LOCK_KEY
KINGSTONE = ProviderCode.KINGSTONE


@pytest.fixture
def kingstone_enabled(db_url):
    """The KINGSTONE registry row is enabled for one test and restored to disabled afterwards."""
    set_kingstone_enabled(db_url, True)
    try:
        yield
    finally:
        set_kingstone_enabled(db_url, False)


def _page_file(tmp_path, *urls: str) -> str:
    path = tmp_path / "kingstone-pages.txt"
    path.write_text("\n".join(urls) + "\n", encoding="utf-8")
    return str(path)


class Migration:
    """A second connection that plays the migration: it holds the exclusive side of the Catalog lock."""

    def __init__(self, db_url: str) -> None:
        self._conn = psycopg.connect(db_url, autocommit=True)

    def hold(self) -> None:
        self._conn.execute("SELECT pg_advisory_lock(%s::bigint)", (KEY,))

    def try_hold(self) -> bool:
        return bool(self._conn.execute("SELECT pg_try_advisory_lock(%s::bigint)", (KEY,)).fetchone()[0])

    def release(self) -> None:
        self._conn.execute("SELECT pg_advisory_unlock(%s::bigint)", (KEY,))

    def close(self) -> None:
        self._conn.close()


@pytest.fixture
def migration(db_url):
    holder = Migration(db_url)
    try:
        yield holder
    finally:
        holder.close()


def kill_backend(db_url: str, conn) -> None:
    with psycopg.connect(db_url, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (conn.info.backend_pid,))


def shared_holders(db_url: str) -> list[int]:
    """Backend pids that hold the shared side of the Catalog lock right now."""
    rows = query(
        db_url,
        "SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND classid = 0 AND objid = %s AND objsubid = 1 AND granted AND mode = 'ShareLock'",
        (KEY,),
    )
    return sorted(row[0] for row in rows)


def catalog_counts(db_url: str) -> tuple[int, int, int]:
    return (
        query(db_url, "SELECT count(*) FROM books")[0][0],
        query(db_url, "SELECT count(*) FROM book_sources")[0][0],
        query(db_url, "SELECT count(*) FROM book_identifiers")[0][0],
    )


def kingstone_run(db_url, fetcher, *, on_session=None):
    """One Kingstone run through the real session and store (no CLI). Returns ``(report, session)``."""
    session = DatabaseSession(lambda: persistence.connect(db_url))
    with session:
        if on_session is not None:
            on_session(session)
        deps = KingstoneRunDependencies(
            fetcher=fetcher,
            store=SessionCatalogStore(session),
            budget=SoftBudget(3300, lambda: 0.0),
            clock=lambda: NOW,
            sleep=FakeSleep(),
            write_policy=WritePolicy.NORMAL,
        )
        return run_pages(deps, [LIST_A]), session


class HookedFetcher(FakeFetcher):
    """``hook(n)`` runs before the n-th detail fetch of the run (1-based); the pages come from ``site``."""

    def __init__(self, pages, hook) -> None:
        super().__init__(pages)
        self._hook = hook
        self._details = 0

    def fetch_detail_page(self, url: str) -> str:
        self._details += 1
        self._hook(self._details)
        return super().fetch_detail_page(url)


def books_pages_run(db_url, rows, page_url: str):
    """One Books category-pages run (``run_pages``) with fakes for the fetcher and parsers, and the real session."""
    pages = {page_url: "<category/>", **{row.url: "<detail/>" for row in rows}}
    deps = RunDependencies(
        fetcher=BooksFakeFetcher(pages=pages),
        parse_ranking=lambda html: rows,  # every category page holds these rows; the fake parser checks the bestseller page only
        parse_detail=fake_detail_parser({row.url: make_draft(row.url) for row in rows}),
        connect=lambda: persistence.connect(db_url),
        clock=lambda: NOW,
        sleep=FakeSleep(),
    )
    return books_run_pages(deps, [page_url])


# --- the crawler holds the shared side; a migration cannot start ------------------------------


def test_a_crawler_session_holds_the_shared_lock_so_a_migration_cannot_take_it(db_url, migration):
    with DatabaseSession(lambda: persistence.connect(db_url)) as session:
        pid = session.conn.info.backend_pid

        assert migration.try_hold() is False  # the exclusive attempt fails while the crawler is connected
        assert shared_holders(db_url) == [pid]


def test_the_lock_is_released_when_the_crawler_connection_closes(db_url, migration):
    with DatabaseSession(lambda: persistence.connect(db_url)) as session:
        _ = session.conn

    assert migration.try_hold() is True  # closing the connection released the shared side
    migration.release()


# --- an exclusive holder stops the crawler before any write -----------------------------------


def test_a_busy_first_connection_raises_migration_lock_busy_and_writes_nothing(db_url, migration):
    migration.hold()
    before = catalog_counts(db_url)

    with pytest.raises(MigrationLockBusy, match="migration lock busy"), DatabaseSession(lambda: persistence.connect(db_url)) as session:
        _ = session.conn

    assert catalog_counts(db_url) == before
    migration.release()


def test_a_kingstone_run_is_failed_with_zero_mutation_when_a_migration_holds_the_lock(db_url, migration):
    migration.hold()
    before = catalog_counts(db_url)

    report, _ = kingstone_run(db_url, FakeFetcher(site(LIST_A, [KM_1, KM_2])))

    assert report.status is KingstoneRunStatus.FAILED
    assert "migration lock busy" in report.error
    assert catalog_counts(db_url) == before
    migration.release()


def test_a_books_pages_run_is_failed_with_zero_mutation_when_a_migration_holds_the_lock(db_url, migration):
    migration.hold()
    before = catalog_counts(db_url)

    report = books_pages_run(db_url, ranking_rows(3), "https://www.books.com.tw/web/sys_bbotm/books/?page=1")

    assert report.status is BooksRunStatus.FAILED
    assert "migration lock busy" in report.error
    assert catalog_counts(db_url) == before
    migration.release()


def test_a_books_daily_run_is_failed_with_zero_mutation_when_a_migration_holds_the_lock(db_url, migration):
    migration.hold()
    before = catalog_counts(db_url)

    report, _ = books_run_once(db_url, ranking_rows(100))

    assert report.status is BooksRunStatus.FAILED
    assert "migration lock busy" in report.error
    assert catalog_counts(db_url) == before
    migration.release()


# --- reconnect takes the lock again -----------------------------------------------------------


def test_a_reconnect_takes_the_shared_lock_again_before_the_next_write(db_url):
    with DatabaseSession(lambda: persistence.connect(db_url)) as session:
        first = session.conn
        old_pid = first.info.backend_pid
        kill_backend(db_url, first)
        with pytest.raises(psycopg.OperationalError):
            first.execute("SELECT 1")  # the dead connection is marked broken on use

        second = session.conn

        assert second.info.backend_pid != old_pid
        assert shared_holders(db_url) == [second.info.backend_pid]
        SessionCatalogStore(session).persist_new_source(KINGSTONE, make_draft("https://www.kingstone.com.tw/book/x/basic/KM9"), NOW, None)
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_code = 'KINGSTONE'") == [(1,)]


def test_a_run_whose_connection_drops_reconnects_with_the_lock_and_finishes(db_url, kingstone_enabled):
    sessions: dict[str, DatabaseSession] = {}
    seen: dict[str, object] = {}

    def hook(number: int) -> None:
        session = sessions["session"]
        if number == 1:
            seen["first_pid"] = session.conn.info.backend_pid
        if number == 2:
            kill_backend(db_url, session.conn)  # the connection drops between two cards
        if number == 3:
            seen["reconnected_pid"] = session.conn.info.backend_pid
            seen["holders"] = shared_holders(db_url)

    report, _ = kingstone_run(
        db_url,
        HookedFetcher(site(LIST_A, [KM_1, KM_2, KM_3]), hook),
        on_session=lambda session: sessions.update(session=session),
    )

    assert report.status is KingstoneRunStatus.SUCCESS
    assert seen["reconnected_pid"] != seen["first_pid"]
    assert seen["holders"] == [seen["reconnected_pid"]]  # the new backend took the shared lock
    assert [row[0] for row in kingstone_sources(db_url)] == sorted([KM_1, KM_2, KM_3])


def test_a_reconnect_while_a_migration_holds_the_lock_writes_nothing_more(db_url, migration, kingstone_enabled):
    sessions: dict[str, DatabaseSession] = {}

    def hook(number: int) -> None:
        if number == 2:
            kill_backend(db_url, sessions["session"].conn)
            migration.hold()  # the migration starts once the crawler's connection is gone

    report, _ = kingstone_run(
        db_url,
        HookedFetcher(site(LIST_A, [KM_1, KM_2, KM_3]), hook),
        on_session=lambda session: sessions.update(session=session),
    )

    assert report.status is KingstoneRunStatus.FAILED
    assert "migration lock busy" in report.error
    assert [row[0] for row in kingstone_sources(db_url)] == [KM_1]  # only the card written before the drop
    migration.release()


# --- schema preflight --------------------------------------------------------------------------


def test_the_schema_preflight_passes_on_the_post_011_database(db_url):
    with psycopg.connect(db_url, autocommit=True) as conn:
        assert persistence.missing_schema_prerequisites(conn) == []


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("ALTER TABLE book_sources RENAME COLUMN last_seen_at TO last_seen_at_old", "book_sources.last_seen_at"),
        ("ALTER TABLE book_sources RENAME COLUMN external_id TO external_id_old", "book_sources.external_id"),
        ("ALTER TABLE book_sources RENAME COLUMN source_code TO source_code_old", "book_sources.source_code"),
        ("ALTER TABLE book_sources ADD COLUMN source_type text", "book_sources.source_type"),
        ("DELETE FROM source_providers WHERE code = 'KINGSTONE'", "source_providers row KINGSTONE"),
        ("ALTER TABLE book_subjects RENAME COLUMN source_code TO source_code_old", "book_subjects.source_code"),
        ("ALTER TABLE book_subjects ADD COLUMN source_type text", "book_subjects.source_type"),
        ("ALTER TABLE book_subjects RENAME TO book_subjects_old", "table book_subjects"),
        ("ALTER TABLE book_contributors RENAME TO book_contributors_old", "table book_contributors"),
        (
            (
                "ALTER TABLE book_identifiers DROP CONSTRAINT ck_book_identifiers_identifier_type, "
                "ADD CONSTRAINT ck_book_identifiers_identifier_type CHECK (identifier_type IN ('ISBN', 'ISBN_10', 'OTHER'))"
            ),
            "legacy ISBN_10/ISBN_13",
        ),
    ],
)
def test_the_schema_preflight_reports_each_missing_prerequisite(db_url, statement, expected):
    conn = psycopg.connect(db_url)  # autocommit off: the change lives in one transaction until it is rolled back
    try:
        conn.execute(statement)
        missing = persistence.missing_schema_prerequisites(conn)
    finally:
        conn.rollback()
        conn.close()

    assert any(expected in item for item in missing), missing
    with psycopg.connect(db_url, autocommit=True) as check:
        assert persistence.missing_schema_prerequisites(check) == []  # the rollback restored the schema


@pytest.mark.parametrize(
    ("break_schema", "restore_schema", "expected"),
    [
        (
            "ALTER TABLE book_sources RENAME COLUMN last_seen_at TO last_seen_at_old",
            "ALTER TABLE book_sources RENAME COLUMN last_seen_at_old TO last_seen_at",
            "book_sources.last_seen_at",
        ),
        (
            "ALTER TABLE book_subjects RENAME COLUMN source_code TO source_code_old",
            "ALTER TABLE book_subjects RENAME COLUMN source_code_old TO source_code",
            "book_subjects.source_code",
        ),
        ("ALTER TABLE book_subjects ADD COLUMN source_type text", "ALTER TABLE book_subjects DROP COLUMN source_type", "book_subjects.source_type"),
        ("ALTER TABLE book_subjects RENAME TO book_subjects_old", "ALTER TABLE book_subjects_old RENAME TO book_subjects", "table book_subjects"),
        (
            "ALTER TABLE book_contributors RENAME TO book_contributors_old",
            "ALTER TABLE book_contributors_old RENAME TO book_contributors",
            "table book_contributors",
        ),
    ],
)
def test_the_cli_exits_2_on_a_missing_prerequisite_and_builds_no_fetcher(db_url, tmp_path, kingstone_enabled, capsys, break_schema, restore_schema, expected):
    built = []
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(break_schema)
    try:
        code = cli.main(
            {"DATABASE_URL": db_url, "KINGSTONE_PAGES_FILE": _page_file(tmp_path, LIST_A), "KINGSTONE_ARTIFACTS_DIR": str(tmp_path / "artifacts")},
            fetcher_factory=lambda config, budget: built.append(config) or FakeFetcher(site(LIST_A, [KM_1])),
            monotonic=lambda: 0.0,
        )
    finally:
        with psycopg.connect(db_url, autocommit=True) as conn:
            conn.execute(restore_schema)

    assert code == 2
    assert built == []  # no fetcher, so no HTTP
    assert f"SCHEMA_PREREQUISITE_MISSING: {expected}" in capsys.readouterr().out
    assert book_count(db_url) == 0
    assert query(db_url, "SELECT count(*) FROM book_sources") == [(0,)]
    record = json.loads((tmp_path / "artifacts" / "kingstone" / "last-run.json").read_text(encoding="utf-8"))
    assert record["reason"] == "SCHEMA_PREREQUISITE_MISSING"
    assert record["alert_reasons"] == ["failed", "schema_prerequisite_missing"]


def test_the_cli_exits_1_with_maintenance_busy_when_the_first_connection_is_busy(db_url, tmp_path, migration, kingstone_enabled, capsys):
    migration.hold()
    built = []

    code = cli.main(
        {"DATABASE_URL": db_url, "KINGSTONE_PAGES_FILE": _page_file(tmp_path, LIST_A), "KINGSTONE_ARTIFACTS_DIR": str(tmp_path / "artifacts")},
        fetcher_factory=lambda config, budget: built.append(config) or FakeFetcher(site(LIST_A, [KM_1])),
        monotonic=lambda: 0.0,
    )

    assert code == 1
    assert built == []
    assert "maintenance busy" in capsys.readouterr().out
    assert book_count(db_url) == 0
    record = json.loads((tmp_path / "artifacts" / "kingstone" / "last-run.json").read_text(encoding="utf-8"))
    assert record["reason"] == "MAINTENANCE_BUSY"
    assert record["alert_reasons"] == ["failed", "maintenance_busy"]
    migration.release()
