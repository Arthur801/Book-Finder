"""Kingstone ingestion against the real PostgreSQL (CR-K10): the shared core, the real store, and the entry point.

Runs on the throwaway pgvector database of ``conftest.py`` (post-011 EF schema). The database tests never skip: the
``db_url`` fixture is required, so a missing dotnet SDK or Docker fails the run instead of skipping it. The
Kingstone provider is disabled by the migration; the ``kingstone_enabled`` fixture enables it for one test and
restores the disabled state afterwards (``test_provider_enabled_reads_the_registry_row`` expects it disabled).

No network: the fetcher is a fake that answers from the committed fixtures and a synthetic list page built from
them. Sleep is a recording fake and the clock is controlled by the test.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from catalog_core import persistence
from catalog_core.models import Identifier, IdentifierType, ProviderCode, WritePolicy
from catalog_core.session import DatabaseSession
from catalog_core.store import SessionCatalogStore
from kingstone import cli
from kingstone.acquisition import AcquisitionError, AcquisitionFailure
from kingstone.ledger import RunStatus
from kingstone.parse_detail import parse_detail_html
from kingstone.run import KingstoneRunDependencies, SoftBudget, run_pages
from kingstone.urls import detail_url
from tests.fakes import FakeSleep, make_draft, product_url, ranking_rows
from tests.test_db_integration import bestsellers, query, run

FIXTURE_DIR = "tests/fixtures/kingstone"
NOW = datetime(2026, 10, 25, 3, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
BOOKS = ProviderCode.BOOKS_COM_TW
KINGSTONE = ProviderCode.KINGSTONE

LIST_A = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1"
LIST_B = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=2"

# The seven real detail fixtures, and the soft 404 (HTTP 200, no product).
KM_1 = "2018630959191"  # 一般書: ISBN 9786263589612, publisher 三采, zh-TW
KM_2 = "2018564008187"  # 套書: ISBN 9786267718537, publisher 大旗
KM_3 = "2018741206573"  # 翻譯書: AUTHOR + TRANSLATOR
KM_4 = "2018250016458"  # 簡體書: language zh-CN
KM_5 = "2018630844053"  # 多作者
KM_6 = "2028594173144"  # 非書商品: ISBN is a retail barcode
KM_7 = "2028870033469"  # 角色前綴 (OTHER)
SOFT_404 = "2099999999999"
REAL = [KM_1, KM_2, KM_3, KM_4, KM_5, KM_6, KM_7]
ISBN_KM_1 = "9786263589612"
ISBN_KM_2 = "9786267718537"

DSN_SECRET = "postgresql://kingstone_user:hunter2@127.0.0.1:1/books"


def detail_html(km_code: str) -> str:
    with open(f"{FIXTURE_DIR}/detail_{km_code}.html", encoding="utf-8") as handle:
        return handle.read()


def list_html(km_codes: list[str]) -> str:
    cards = "".join(
        f'<div class="mod_prod_card" data-prodno="{code}"><div class="coverbox"><a href="/basic/{code}/?lid=test">x</a></div></div>' for code in km_codes
    )
    return f'<html><body><section id="allProducts"><div id="displayCSS"><div class="productGrid">{cards}</div></div></section></body></html>'


def parsed(km_code: str):
    """The draft the real parser makes of the fixture (the expectations come from the parser, not from a copy)."""
    return parse_detail_html(detail_html(km_code), detail_url(km_code))


class FakeFetcher:
    """URL -> body. An exception value is raised. Records every request (list and detail)."""

    def __init__(self, pages: dict[str, object]) -> None:
        self.pages = pages
        self.calls: list[str] = []
        self.closed = 0
        self.http_failures = 0

    @property
    def http_attempts(self) -> int:
        return len(self.calls)

    def fetch_list_page(self, url: str) -> str:
        return self._get(url)

    def fetch_detail_page(self, url: str) -> str:
        return self._get(url)

    def _get(self, url: str) -> str:
        self.calls.append(url)
        value = self.pages[url]
        if isinstance(value, BaseException):
            raise value
        return value

    def detail_calls(self) -> list[str]:
        return [url for url in self.calls if "/basic/" in url]

    def close(self) -> None:
        self.closed += 1


def site(list_url: str, codes: list[str], *, soft_404: bool = False) -> dict[str, object]:
    """Pages for one list page holding ``codes`` (and optionally the soft 404 card)."""
    cards = [*codes, SOFT_404] if soft_404 else codes
    pages: dict[str, object] = {list_url: list_html(cards)}
    for code in cards:
        pages[detail_url(code)] = detail_html(code)
    return pages


def run_pages_once(
    db_url: str,
    fetcher: FakeFetcher,
    pages: list[str],
    *,
    now: datetime = NOW,
    policy: WritePolicy = WritePolicy.NEW_BOOKS_ONLY,
    sleep: FakeSleep | None = None,
):
    """One run through the real store and session, without the CLI."""
    session = DatabaseSession(lambda: persistence.connect(db_url))
    with session:
        deps = KingstoneRunDependencies(
            fetcher=fetcher,
            store=SessionCatalogStore(session),
            budget=SoftBudget(3300, lambda: 0.0),
            clock=lambda: now,
            sleep=sleep if sleep is not None else FakeSleep(),
            write_policy=policy,
        )
        return run_pages(deps, pages)


def set_kingstone_enabled(db_url: str, enabled: bool) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE source_providers SET enabled = %s WHERE code = %s", (enabled, KINGSTONE))


@pytest.fixture
def kingstone_enabled(db_url):
    set_kingstone_enabled(db_url, True)
    try:
        yield
    finally:
        set_kingstone_enabled(db_url, False)


def kingstone_sources(db_url: str) -> list[tuple]:
    return query(db_url, "SELECT external_id, source_url, book_id FROM book_sources WHERE source_code = 'KINGSTONE' ORDER BY external_id")


def book_count(db_url: str) -> int:
    return query(db_url, "SELECT count(*) FROM books")[0][0]


def book_row(db_url: str, book_id: uuid.UUID) -> tuple:
    return query(db_url, "SELECT title, publisher, language, description, updated_at FROM books WHERE id = %s", (book_id,))[0]


def seed_books_book(db_url: str, url: str, isbns: tuple[str, ...], title: str) -> uuid.UUID:
    """A BOOKS_COM_TW Book (with its Source) carrying the given ISBNs, written through persistence."""
    identifiers = tuple(Identifier(IdentifierType.ISBN, value) for value in isbns)
    with persistence.connect(db_url) as conn:
        return persistence.persist_new_source(conn, BOOKS, make_draft(url, title=title, identifiers=identifiers), NOW).book_id


def kill_backend(db_url: str, conn) -> None:
    with psycopg.connect(db_url, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (conn.info.backend_pid,))


def orphan_rows(db_url: str, keep: list[uuid.UUID]) -> dict[str, int]:
    """Rows of the five Book tables that belong to no Book in ``keep``. A rolled-back attempt leaves none."""
    result = {}
    for table in ("book_sources", "book_identifiers", "book_contributors", "book_subjects"):
        result[table] = query(db_url, f"SELECT count(*) FROM {table} WHERE book_id <> ALL(%s)", (keep,))[0][0]
    result["books"] = query(db_url, "SELECT count(*) FROM books WHERE id <> ALL(%s)", (keep,))[0][0]
    return result


def book_ids_of(db_url: str, external_ids: list[str]) -> list[uuid.UUID]:
    return [row[0] for row in query(db_url, "SELECT book_id FROM book_sources WHERE source_code = 'KINGSTONE' AND external_id = ANY(%s)", (external_ids,))]


# ---------------------------------------------------------------------------
# Full flow, replay, and the write policies
# ---------------------------------------------------------------------------


def test_full_run_writes_every_real_book_and_skips_the_soft_404(db_url):
    fetcher = FakeFetcher(site(LIST_A, REAL, soft_404=True))

    report = run_pages_once(db_url, fetcher, [LIST_A])

    assert report.status is RunStatus.PARTIAL_SUCCESS  # the soft 404 card failed; the page completed
    assert report.exit_code == 0
    assert (report.items_seen, report.imported, report.failed, report.existing_source) == (8, 7, 1, 0)
    assert report.failed_items[0].reason == "product_not_found"
    assert report.failed_items[0].external_id == SOFT_404

    sources = kingstone_sources(db_url)
    assert [row[0] for row in sources] == sorted(REAL)
    assert all(row[1] == detail_url(row[0]) for row in sources)  # source_url is the canonical detail URL
    assert book_count(db_url) == 7
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_code = 'KINGSTONE' AND external_id = %s", (SOFT_404,)) == [(0,)]


def test_the_written_rows_follow_the_parser(db_url):
    run_pages_once(db_url, FakeFetcher(site(LIST_A, REAL)), [LIST_A])

    for km in REAL:
        draft = parsed(km)
        book_id = book_ids_of(db_url, [km])[0]
        title, publisher, language, _, _ = book_row(db_url, book_id)
        assert (title, publisher, language) == (draft.title, draft.publisher, draft.language)
        identifiers = {row[0] for row in query(db_url, "SELECT identifier_value FROM book_identifiers WHERE book_id = %s AND identifier_type = 'ISBN'", (book_id,))}
        assert identifiers == {item.identifier_value for item in draft.identifiers}
        contributors = query(db_url, "SELECT name, role FROM book_contributors WHERE book_id = %s ORDER BY contributor_order", (book_id,))
        assert contributors == [(item.name, item.role.value) for item in draft.contributors]
        subjects = {row[0] for row in query(db_url, "SELECT subject FROM book_subjects WHERE book_id = %s AND source_code = 'KINGSTONE'", (book_id,))}
        assert subjects == set(draft.subjects)


def test_simplified_chinese_book_is_stored_as_zh_cn(db_url):
    run_pages_once(db_url, FakeFetcher(site(LIST_A, [KM_4])), [LIST_A])

    assert book_row(db_url, book_ids_of(db_url, [KM_4])[0])[2] == "zh-CN"


def test_replay_touches_every_existing_source_without_a_detail_request(db_url):
    run_pages_once(db_url, FakeFetcher(site(LIST_A, REAL)), [LIST_A], now=NOW)
    first = {row[0]: row[1] for row in query(db_url, "SELECT external_id, last_seen_at FROM book_sources WHERE source_code = 'KINGSTONE'")}
    fetcher = FakeFetcher(site(LIST_A, REAL))

    report = run_pages_once(db_url, fetcher, [LIST_A], now=LATER)

    assert report.existing_source == 7
    assert report.imported == 0
    assert fetcher.detail_calls() == []  # every card is EXISTING: no detail page is requested
    assert len(kingstone_sources(db_url)) == 7
    assert book_count(db_url) == 7
    second = {row[0]: row[1] for row in query(db_url, "SELECT external_id, last_seen_at FROM book_sources WHERE source_code = 'KINGSTONE'")}
    assert all(second[km] == LATER and second[km] > first[km] for km in REAL)


def test_a_clock_that_moved_back_does_not_move_last_seen_back(db_url):
    run_pages_once(db_url, FakeFetcher(site(LIST_A, [KM_1])), [LIST_A], now=LATER)

    report = run_pages_once(db_url, FakeFetcher(site(LIST_A, [KM_1])), [LIST_A], now=NOW)

    assert report.existing_source == 1
    assert query(db_url, "SELECT last_seen_at FROM book_sources WHERE source_code = 'KINGSTONE'") == [(LATER,)]


def test_new_books_only_skips_a_book_whose_isbn_matches_one_books_book(db_url):
    books_book = seed_books_book(db_url, product_url(1), (ISBN_KM_1,), title="Books.com.tw original")
    before = book_row(db_url, books_book)
    identifiers_before = query(db_url, "SELECT count(*) FROM book_identifiers WHERE book_id = %s", (books_book,))
    fetcher = FakeFetcher(site(LIST_A, REAL))

    report = run_pages_once(db_url, fetcher, [LIST_A], policy=WritePolicy.NEW_BOOKS_ONLY)

    assert report.policy_skipped_count == 1
    assert report.write_policy is WritePolicy.NEW_BOOKS_ONLY
    assert KM_1 not in [row[0] for row in kingstone_sources(db_url)]  # no KINGSTONE Source for it
    assert detail_url(KM_1) in fetcher.detail_calls()  # the policy decides after the detail page is read
    assert book_row(db_url, books_book) == before  # no field of the Books book was filled
    assert query(db_url, "SELECT count(*) FROM book_identifiers WHERE book_id = %s", (books_book,)) == identifiers_before
    assert book_count(db_url) == 1 + 6  # the six cards with no match were created as before


def test_normal_policy_attaches_a_one_match_isbn_to_that_book_and_fills_only_the_gaps(db_url):
    books_book = seed_books_book(db_url, product_url(1), (ISBN_KM_1,), title="Books.com.tw original")

    report = run_pages_once(db_url, FakeFetcher(site(LIST_A, REAL)), [LIST_A], policy=WritePolicy.NORMAL)

    assert report.isbn_attached == 1
    assert report.policy_skipped_count == 0
    title, publisher, language, _, _ = book_row(db_url, books_book)
    assert title == "Books.com.tw original"  # a value already present is kept
    assert (publisher, language) == (parsed(KM_1).publisher, parsed(KM_1).language)  # NULL gaps are filled
    assert book_ids_of(db_url, [KM_1]) == [books_book]
    assert query(db_url, "SELECT count(*) FROM book_identifiers WHERE book_id = %s AND identifier_value = %s", (books_book, ISBN_KM_1)) == [(1,)]
    assert book_count(db_url) == 1 + 6


def test_new_books_only_with_two_isbn_matches_creates_a_new_book_and_changes_neither_old_book(db_url):
    first = seed_books_book(db_url, product_url(1), (ISBN_KM_2,), title="Books A")
    second = seed_books_book(db_url, product_url(2), (ISBN_KM_2,), title="Books B")
    before = [book_row(db_url, first), book_row(db_url, second)]

    report = run_pages_once(db_url, FakeFetcher(site(LIST_A, [KM_2])), [LIST_A], policy=WritePolicy.NEW_BOOKS_ONLY)

    assert report.ambiguous_created == 1
    assert report.policy_skipped_count == 0
    new_book = book_ids_of(db_url, [KM_2])[0]
    assert new_book not in (first, second)
    assert [book_row(db_url, first), book_row(db_url, second)] == before
    assert book_count(db_url) == 3


# ---------------------------------------------------------------------------
# Atomicity and the uncertain commit
# ---------------------------------------------------------------------------


def test_a_book_whose_identifier_write_keeps_failing_leaves_no_rows_and_fails_that_card(db_url, monkeypatch):
    real_identifiers = persistence._write_identifiers
    target_title = parsed(KM_3).title

    def identifiers_fail_for_km_3(conn, book_id, draft):
        if draft.external_id == KM_3:
            raise psycopg.OperationalError("simulated failure while writing identifiers")
        return real_identifiers(conn, book_id, draft)

    monkeypatch.setattr(persistence, "_write_identifiers", identifiers_fail_for_km_3)
    sleep = FakeSleep()

    report = run_pages_once(db_url, FakeFetcher(site(LIST_B, [KM_1, KM_3, KM_2])), [LIST_B], sleep=sleep)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.imported == 2
    assert [(item.external_id, item.reason, item.attempts) for item in report.failed_items] == [(KM_3, "database_error", 3)]
    assert sleep.calls == [1.0, 2.0]
    keep = book_ids_of(db_url, [KM_1, KM_2])
    assert len(keep) == 2
    assert orphan_rows(db_url, keep) == {"book_sources": 0, "book_identifiers": 0, "book_contributors": 0, "book_subjects": 0, "books": 0}
    assert query(db_url, "SELECT count(*) FROM books WHERE title = %s", (target_title,)) == [(0,)]


def test_a_failure_just_before_the_commit_is_rolled_back_and_the_retry_writes_the_book_once(db_url, monkeypatch):
    real_subjects = persistence._write_subjects
    failed = []

    def subjects_then_fail_once(conn, provider, book_id, draft):
        real_subjects(conn, provider, book_id, draft)  # every other row of the book is written
        if draft.external_id == KM_3 and not failed:
            failed.append(True)
            raise psycopg.OperationalError("simulated failure before the commit")

    monkeypatch.setattr(persistence, "_write_subjects", subjects_then_fail_once)
    sleep = FakeSleep()

    report = run_pages_once(db_url, FakeFetcher(site(LIST_B, [KM_1, KM_3, KM_2])), [LIST_B], sleep=sleep)

    assert failed == [True]
    assert report.status is RunStatus.SUCCESS
    assert (report.imported, report.failed) == (3, 0)
    assert sleep.calls == [1.0]
    assert book_count(db_url) == 3  # the rolled-back first attempt left no fourth Book
    assert len(kingstone_sources(db_url)) == 3
    assert orphan_rows(db_url, book_ids_of(db_url, [KM_1, KM_2, KM_3])) == {
        "book_sources": 0,
        "book_identifiers": 0,
        "book_contributors": 0,
        "book_subjects": 0,
        "books": 0,
    }


def test_a_commit_whose_acknowledgement_is_lost_is_recovered_on_retry_and_not_written_twice(db_url, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="kingstone")
    real_persist = persistence.persist_new_source
    dropped = []

    def commit_then_drop(conn, provider, draft, now, attach_to_book_id=None):
        result = real_persist(conn, provider, draft, now, attach_to_book_id=attach_to_book_id)  # the commit succeeds
        if draft.external_id == KM_3 and not dropped:
            dropped.append(conn)
            kill_backend(db_url, conn)  # the connection breaks before the client sees the success
            raise psycopg.OperationalError("connection lost before the commit was acknowledged")
        return result

    monkeypatch.setattr(persistence, "persist_new_source", commit_then_drop)
    fetcher = FakeFetcher(site(LIST_B, [KM_1, KM_3, KM_2]))

    report = run_pages_once(db_url, fetcher, [LIST_B])

    assert len(dropped) == 1
    assert report.status is RunStatus.SUCCESS
    assert report.recovered_commit_count == 1
    assert report.existing_source == 1  # the committed outcome is reported as EXISTING
    assert (report.imported, report.failed) == (2, 0)
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_code = 'KINGSTONE' AND external_id = %s", (KM_3,)) == [(1,)]
    assert fetcher.detail_calls().count(detail_url(KM_3)) == 1  # the parsed draft was kept: no second detail fetch
    assert book_count(db_url) == 3


# ---------------------------------------------------------------------------
# Bestseller protection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pages, expected",
    [
        pytest.param(site(LIST_A, REAL), RunStatus.SUCCESS, id="success"),
        pytest.param(site(LIST_A, REAL[:2], soft_404=True), RunStatus.PARTIAL_SUCCESS, id="partial"),
        pytest.param({LIST_A: AcquisitionError(AcquisitionFailure.REDIRECT, "302", attempts=1, status=302)}, RunStatus.FAILED, id="failed"),
    ],
)
def test_a_kingstone_run_never_changes_the_bestsellers(db_url, pages, expected):
    run(db_url, ranking_rows(100))
    before = bestsellers(db_url)
    assert len(before) == 100

    report = run_pages_once(db_url, FakeFetcher(pages), [LIST_A])

    assert report.status is expected
    assert bestsellers(db_url) == before


# ---------------------------------------------------------------------------
# Entry point (kingstone.cli.main) against the real database
# ---------------------------------------------------------------------------


def _page_file(tmp_path, *urls: str) -> str:
    path = tmp_path / "kingstone-pages.txt"
    path.write_text("\n".join(urls) + "\n", encoding="utf-8")
    return str(path)


def test_the_provider_check_with_the_disabled_registry_row_exits_2_before_any_fetch(db_url, tmp_path, capsys):
    fetcher = FakeFetcher(site(LIST_A, REAL))
    created = []

    code = cli.main(
        {"DATABASE_URL": db_url, "KINGSTONE_PAGES_FILE": _page_file(tmp_path, LIST_A), "KINGSTONE_ARTIFACTS_DIR": str(tmp_path / "artifacts")},
        fetcher_factory=lambda config, budget: created.append(config) or fetcher,
        monotonic=lambda: 0.0,
    )

    assert code == 2
    assert created == []
    assert fetcher.calls == []
    assert kingstone_sources(db_url) == []
    assert "disabled or not registered" in capsys.readouterr().out


def test_the_cli_full_run_exits_0_writes_the_books_and_closes_the_fetcher(db_url, tmp_path, kingstone_enabled, capsys):
    fetcher = FakeFetcher(site(LIST_A, REAL, soft_404=True))

    code = cli.main(
        {
            "DATABASE_URL": db_url,
            "KINGSTONE_PAGES_FILE": _page_file(tmp_path, LIST_A),
            "KINGSTONE_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
            "KINGSTONE_WRITE_POLICY": "normal",
        },
        fetcher_factory=lambda config, budget: fetcher,
        monotonic=lambda: 0.0,
    )

    assert code == 0  # a PARTIAL_SUCCESS run (the soft 404) exits 0
    assert fetcher.closed == 1
    assert [row[0] for row in kingstone_sources(db_url)] == sorted(REAL)
    assert book_count(db_url) == 7
    out = capsys.readouterr().out
    assert "mode=kingstone" in out
    assert DSN_SECRET not in out
    assert db_url not in out


def test_the_cli_writes_last_run_with_the_counts_and_no_alert_for_a_normal_run_and_its_replay(db_url, tmp_path, kingstone_enabled, capsys):
    artifacts = tmp_path / "artifacts"
    environ = {
        "DATABASE_URL": db_url,
        "KINGSTONE_PAGES_FILE": _page_file(tmp_path, LIST_A),
        "KINGSTONE_ARTIFACTS_DIR": str(artifacts),
        "KINGSTONE_WRITE_POLICY": "normal",
    }
    fetcher = FakeFetcher(site(LIST_A, REAL, soft_404=True))

    code = cli.main(environ, fetcher_factory=lambda config, budget: fetcher, monotonic=lambda: 0.0)

    assert code == 0
    data = json.loads((artifacts / "kingstone" / "last-run.json").read_text(encoding="utf-8"))
    assert data["status"] == "PARTIAL_SUCCESS"  # the soft 404 is one failed card
    assert data["imported"] == len(REAL)
    assert data["failed"] == 1
    assert data["items_listed"] == data["items_seen"] == data["details_fetched"] == data["imported"] + data["failed"]
    assert data["http_attempts"] == len(fetcher.calls)
    assert data["http_failures"] == 0
    assert data["write_policy"] == "normal"
    assert data["alert_reasons"] == []
    assert len(list((artifacts / "kingstone" / "history").glob("*.json"))) == 1
    assert "ALERT" not in capsys.readouterr().out

    replay = FakeFetcher(site(LIST_A, REAL, soft_404=True))
    assert cli.main(environ, fetcher_factory=lambda config, budget: replay, monotonic=lambda: 0.0) == 0

    replayed = json.loads((artifacts / "kingstone" / "last-run.json").read_text(encoding="utf-8"))
    assert replayed["existing_source"] == len(REAL)
    assert replayed["details_fetched"] == 1  # only the soft 404 is fetched again: Existing cards are touched, not fetched
    assert replayed["alert_reasons"] == []
    assert len(list((artifacts / "kingstone" / "history").glob("*.json"))) == 2


def test_the_cli_run_with_every_page_skipped_exits_1_and_the_fetcher_is_closed(db_url, tmp_path, kingstone_enabled):
    fetcher = FakeFetcher({LIST_A: AcquisitionError(AcquisitionFailure.HTTP_STATUS, "503", attempts=3, status=503)})

    code = cli.main(
        {"DATABASE_URL": db_url, "KINGSTONE_PAGES_FILE": _page_file(tmp_path, LIST_A), "KINGSTONE_ARTIFACTS_DIR": str(tmp_path / "artifacts")},
        fetcher_factory=lambda config, budget: fetcher,
        monotonic=lambda: 0.0,
    )

    assert code == 1
    assert fetcher.closed == 1
    assert kingstone_sources(db_url) == []


def test_the_cli_is_a_second_entry_for_the_same_composition_as_run_pages(db_url, tmp_path, kingstone_enabled):
    # The CLI's first run and a direct run through the same store must agree on the same rows.
    code = cli.main(
        {
            "DATABASE_URL": db_url,
            "KINGSTONE_PAGES_FILE": _page_file(tmp_path, LIST_A),
            "KINGSTONE_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
            "KINGSTONE_WRITE_POLICY": "normal",
        },
        fetcher_factory=lambda config, budget: FakeFetcher(site(LIST_A, REAL)),
        monotonic=lambda: 0.0,
    )
    replay = FakeFetcher(site(LIST_A, REAL))
    report = run_pages_once(db_url, replay, [LIST_A], policy=WritePolicy.NORMAL, now=LATER)

    assert code == 0
    assert report.existing_source == 7
    assert replay.detail_calls() == []
    assert book_count(db_url) == 7


def test_the_provider_code_is_kingstone_for_every_source(db_url):
    run_pages_once(db_url, FakeFetcher(site(LIST_A, [KM_1])), [LIST_A])

    assert query(db_url, "SELECT DISTINCT source_code FROM book_sources") == [("KINGSTONE",)]
