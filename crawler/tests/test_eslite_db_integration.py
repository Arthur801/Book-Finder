"""Eslite ingestion against the real PostgreSQL: the shared core, the real store, and the entry point.

Runs on the throwaway pgvector database of ``conftest.py`` (post-011 EF schema). The database tests never skip: the
``db_url`` fixture is required. The Eslite provider is disabled by the migration; the ``eslite_enabled`` fixture enables
it for one test and restores the disabled state afterwards.

No network: the fetcher is a fake that answers from the committed JSON fixtures and synthetic list responses built from
them. Sleep is a recording fake and the clock is controlled by the test.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from catalog_core import persistence
from catalog_core.category_ledger import RunStatus
from catalog_core.http_acquisition import AcquisitionError, AcquisitionFailure
from catalog_core.models import Identifier, IdentifierType, ProviderCode, WritePolicy
from catalog_core.session import DatabaseSession
from catalog_core.store import SessionCatalogStore
from eslite import cli
from eslite.parse_detail import parse_detail_json
from eslite.run import EsliteRunDependencies, SoftBudget, run_pages
from tests.fakes import FakeSleep, make_draft, ranking_rows
from tests.test_db_integration import bestsellers, query, run

FIXTURES = Path(__file__).parent / "fixtures" / "eslite"
NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
ESLITE = ProviderCode.ESLITE
BOOKS = ProviderCode.BOOKS_COM_TW
KINGSTONE = ProviderCode.KINGSTONE

LIST_101 = "https://www.eslite.com/category/3/101"
LIST_34 = "https://www.eslite.com/category/3/34"

G_DICTIONARY = "10012016112683201069007"  # no isbn13: the ean is used
G_16 = "1001114412021700"  # 16 digit guid
G_TRANSLATION = "1001136502682294792007"  # isbn13 9789888773701
G_SERIES = "1001124912682006780001"
G_NOVEL = "10012030392683263913003"  # list_34
G_NOT_FOUND = "10019999999999999999999"  # the detail API answers 404
REAL = [G_DICTIONARY, G_16, G_TRANSLATION, G_SERIES, G_NOVEL]
DETAIL_FIXTURES = {
    G_DICTIONARY: "detail_10012016112683201069007.json",
    G_16: "detail_1001114412021700.json",
    G_TRANSLATION: "detail_1001136502682294792007.json",
    G_SERIES: "detail_1001124912682006780001.json",
    G_NOVEL: "detail_10012030392683263913003.json",
}
ISBN_G_TRANSLATION = "9789888773701"

DSN_SECRET = "postgresql://eslite_user:hunter2@127.0.0.1:1/books"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def product(guid: str) -> str:
    return f"https://www.eslite.com/product/{guid}"


def list_body(guids: list[str], *, total: int = 188) -> str:
    card = json.loads(fixture_text("list_101_p1.json"))["products"][0]
    return json.dumps({"total": total, "page_no": 1, "page_size": 40, "products": [{**card, "guid": guid} for guid in guids]}, ensure_ascii=False)


def parsed(guid: str):
    """The draft the real parser makes of the fixture (the expectations come from the parser, not from a copy)."""
    return parse_detail_json(fixture_text(DETAIL_FIXTURES[guid]), guid)


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
        return [url for url in self.calls if url.startswith("https://www.eslite.com/product/")]

    def close(self) -> None:
        self.closed += 1


def not_found() -> AcquisitionError:
    return AcquisitionError(AcquisitionFailure.HTTP_STATUS, "GET detail failed: http_status 404", 1, 404)


def site(list_url: str, guids: list[str], *, total: int = 188) -> dict[str, object]:
    """Pages for one list page holding ``guids``: the list response and each product (404 for the missing one)."""
    pages: dict[str, object] = {list_url: list_body(guids, total=total)}
    for guid in guids:
        pages[product(guid)] = not_found() if guid == G_NOT_FOUND else fixture_text(DETAIL_FIXTURES[guid])
    return pages


def full_site() -> dict[str, object]:
    return {**site(LIST_101, [G_DICTIONARY, G_16, G_TRANSLATION, G_NOT_FOUND]), **site(LIST_34, [G_NOVEL, G_SERIES], total=1333)}


def run_pages_once(
    db_url: str,
    fetcher: FakeFetcher,
    pages: list[str],
    *,
    now: datetime = NOW,
    policy: WritePolicy = WritePolicy.NORMAL,
    sleep: FakeSleep | None = None,
):
    """One run through the real store and session, without the CLI."""
    session = DatabaseSession(lambda: persistence.connect(db_url))
    with session:
        deps = EsliteRunDependencies(
            fetcher=fetcher,
            store=SessionCatalogStore(session),
            budget=SoftBudget(7000, lambda: 0.0),
            clock=lambda: now,
            sleep=sleep if sleep is not None else FakeSleep(),
            write_policy=policy,
        )
        return run_pages(deps, pages)


def set_eslite_enabled(db_url: str, enabled: bool) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE source_providers SET enabled = %s WHERE code = %s", (enabled, ESLITE))


@pytest.fixture
def eslite_enabled(db_url):
    set_eslite_enabled(db_url, True)
    try:
        yield
    finally:
        set_eslite_enabled(db_url, False)


def eslite_sources(db_url: str) -> list[tuple]:
    return query(db_url, "SELECT external_id, source_url, book_id FROM book_sources WHERE source_code = 'ESLITE' ORDER BY external_id")


def all_sources(db_url: str) -> list[tuple]:
    return query(db_url, "SELECT source_code, external_id, source_url, book_id, last_seen_at FROM book_sources ORDER BY source_code, source_url")


def book_count(db_url: str) -> int:
    return query(db_url, "SELECT count(*) FROM books")[0][0]


def book_row(db_url: str, book_id: uuid.UUID) -> tuple:
    return query(db_url, "SELECT title, publisher, language, description FROM books WHERE id = %s", (book_id,))[0]


def seed_books_book(db_url: str, url: str, isbns: tuple[str, ...], title: str) -> uuid.UUID:
    """A BOOKS_COM_TW Book (with its Source) carrying the given ISBNs, written through persistence."""
    identifiers = tuple(Identifier(IdentifierType.ISBN, value) for value in isbns)
    with persistence.connect(db_url) as conn:
        return persistence.persist_new_source(conn, BOOKS, make_draft(url, title=title, identifiers=identifiers), NOW).book_id


def book_ids_of(db_url: str, external_ids: list[str]) -> list[uuid.UUID]:
    return [
        row[0]
        for row in query(db_url, "SELECT book_id FROM book_sources WHERE source_code = 'ESLITE' AND external_id = ANY(%s) ORDER BY external_id", (external_ids,))
    ]


def page_file(tmp_path: Path, *urls: str) -> str:
    path = tmp_path / "eslite-pages.txt"
    path.write_text("\n".join(urls) + "\n", encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Full flow, replay, and the write policies
# ---------------------------------------------------------------------------


def test_full_run_writes_every_real_book_with_its_eslite_source_and_fails_the_404_card(db_url, eslite_enabled):
    report = run_pages_once(db_url, FakeFetcher(full_site()), [LIST_101, LIST_34])

    assert report.status is RunStatus.PARTIAL_SUCCESS  # the 404 card failed; the pages completed
    assert report.exit_code == 0
    assert (report.items_seen, report.imported, report.failed, report.existing_source) == (6, 5, 1, 0)
    assert report.failed_items[0].reason == "http_status"
    assert report.failed_items[0].external_id == G_NOT_FOUND
    assert report.provider_code is ESLITE

    sources = eslite_sources(db_url)
    assert [row[0] for row in sources] == sorted(REAL)
    assert all(row[1] == product(row[0]) for row in sources)  # source_url is the www product URL
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE external_id = %s", (G_NOT_FOUND,)) == [(0,)]
    assert book_count(db_url) == 5


def test_the_written_rows_follow_the_parser(db_url, eslite_enabled):
    run_pages_once(db_url, FakeFetcher(site(LIST_101, REAL[:3])), [LIST_101])

    for guid in REAL[:3]:
        draft = parsed(guid)
        book_id = book_ids_of(db_url, [guid])[0]
        title, publisher, language, _ = book_row(db_url, book_id)
        assert (title, publisher, language) == (draft.title, draft.publisher, draft.language)
        identifiers = {row[0] for row in query(db_url, "SELECT identifier_value FROM book_identifiers WHERE book_id = %s AND identifier_type = 'ISBN'", (book_id,))}
        assert identifiers == {item.identifier_value for item in draft.identifiers}
        contributors = query(db_url, "SELECT name, role FROM book_contributors WHERE book_id = %s ORDER BY contributor_order", (book_id,))
        assert contributors == [(item.name, item.role.value) for item in draft.contributors]


def test_the_provider_code_is_eslite_for_every_source_written_by_the_run(db_url, eslite_enabled):
    run_pages_once(db_url, FakeFetcher(site(LIST_101, [G_DICTIONARY])), [LIST_101])

    assert query(db_url, "SELECT DISTINCT source_code FROM book_sources WHERE external_id = %s", (G_DICTIONARY,)) == [("ESLITE",)]


def test_replay_touches_every_existing_source_without_a_detail_request(db_url, eslite_enabled):
    run_pages_once(db_url, FakeFetcher(full_site()), [LIST_101, LIST_34], now=NOW)
    first = {row[0]: row[1] for row in query(db_url, "SELECT external_id, last_seen_at FROM book_sources WHERE source_code = 'ESLITE'")}
    fetcher = FakeFetcher(full_site())

    report = run_pages_once(db_url, fetcher, [LIST_101, LIST_34], now=LATER)

    assert report.existing_source == 5
    assert report.imported == 0
    assert fetcher.detail_calls() == [product(G_NOT_FOUND)]  # Existing cards cost no request; only the 404 card is fetched again
    assert len(eslite_sources(db_url)) == 5
    assert book_count(db_url) == 5
    second = {row[0]: row[1] for row in query(db_url, "SELECT external_id, last_seen_at FROM book_sources WHERE source_code = 'ESLITE'")}
    assert all(second[guid] == LATER and second[guid] > first[guid] for guid in REAL)


def test_a_clock_that_moved_back_does_not_move_last_seen_back(db_url, eslite_enabled):
    run_pages_once(db_url, FakeFetcher(site(LIST_101, [G_DICTIONARY])), [LIST_101], now=LATER)

    report = run_pages_once(db_url, FakeFetcher(site(LIST_101, [G_DICTIONARY])), [LIST_101], now=NOW)

    assert report.existing_source == 1
    assert query(db_url, "SELECT last_seen_at FROM book_sources WHERE source_code = 'ESLITE'") == [(LATER,)]


def test_normal_policy_attaches_a_one_match_isbn_to_that_book_and_fills_only_the_gaps(db_url, eslite_enabled):
    books_book = seed_books_book(db_url, "https://www.books.com.tw/products/0010000001", (ISBN_G_TRANSLATION,), title="Books.com.tw original")

    report = run_pages_once(db_url, FakeFetcher(site(LIST_101, [G_DICTIONARY, G_TRANSLATION])), [LIST_101], policy=WritePolicy.NORMAL)

    assert report.isbn_attached == 1
    assert report.policy_skipped_count == 0
    assert book_ids_of(db_url, [G_TRANSLATION]) == [books_book]  # the ESLITE Source attaches to the existing Book
    title, publisher, language, _ = book_row(db_url, books_book)
    assert title == "Books.com.tw original"  # a value already present is kept
    assert (publisher, language) == (parsed(G_TRANSLATION).publisher, parsed(G_TRANSLATION).language)  # NULL gaps are filled
    assert book_count(db_url) == 1 + 1  # the one card with no ISBN match became a new Book
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE book_id = %s", (books_book,)) == [(2,)]  # BOOKS + ESLITE


def test_new_books_only_skips_a_book_whose_isbn_matches_one_books_book(db_url, eslite_enabled):
    books_book = seed_books_book(db_url, "https://www.books.com.tw/products/0010000001", (ISBN_G_TRANSLATION,), title="Books.com.tw original")
    before = book_row(db_url, books_book)

    report = run_pages_once(db_url, FakeFetcher(site(LIST_101, [G_TRANSLATION])), [LIST_101], policy=WritePolicy.NEW_BOOKS_ONLY)

    assert report.policy_skipped_count == 1
    assert book_ids_of(db_url, [G_TRANSLATION]) == []  # no ESLITE Source for it
    assert book_row(db_url, books_book) == before
    assert book_count(db_url) == 1


# ---------------------------------------------------------------------------
# Other providers are untouched
# ---------------------------------------------------------------------------


def test_the_run_never_changes_the_other_providers_sources(db_url, eslite_enabled):
    seed_books_book(db_url, "https://www.books.com.tw/products/0010000003", ("9780000000011",), title="Books only")
    with persistence.connect(db_url) as conn:
        persistence.persist_new_source(conn, KINGSTONE, make_draft("https://www.kingstone.com.tw/basic/2018630959191/", title="Kingstone only"), NOW)
    before = [row for row in all_sources(db_url) if row[0] != "ESLITE"]

    run_pages_once(db_url, FakeFetcher(full_site()), [LIST_101, LIST_34], policy=WritePolicy.NORMAL)

    assert [row for row in all_sources(db_url) if row[0] != "ESLITE"] == before


# ---------------------------------------------------------------------------
# Atomicity: a card whose write keeps failing leaves no rows
# ---------------------------------------------------------------------------


def test_a_book_whose_identifier_write_keeps_failing_leaves_no_rows_and_fails_that_card(db_url, eslite_enabled, monkeypatch):
    real_identifiers = persistence._write_identifiers
    target = parsed(G_16).title

    def identifiers_fail_for_g16(conn, book_id, draft):
        if draft.external_id == G_16:
            raise psycopg.OperationalError("simulated failure while writing identifiers")
        return real_identifiers(conn, book_id, draft)

    monkeypatch.setattr(persistence, "_write_identifiers", identifiers_fail_for_g16)
    sleep = FakeSleep()

    report = run_pages_once(db_url, FakeFetcher(site(LIST_101, [G_DICTIONARY, G_16, G_TRANSLATION])), [LIST_101], sleep=sleep)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.imported == 2
    assert [(item.external_id, item.reason, item.attempts) for item in report.failed_items] == [(G_16, "database_error", 3)]
    assert sleep.calls == [1.0, 2.0]
    assert query(db_url, "SELECT count(*) FROM books WHERE title = %s", (target,)) == [(0,)]
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE external_id = %s", (G_16,)) == [(0,)]


# ---------------------------------------------------------------------------
# Bestseller protection
# ---------------------------------------------------------------------------


def test_an_eslite_run_never_changes_the_bestsellers(db_url, eslite_enabled):
    run(db_url, ranking_rows(100))
    before = bestsellers(db_url)
    assert len(before) == 100

    run_pages_once(db_url, FakeFetcher(full_site()), [LIST_101, LIST_34])

    assert bestsellers(db_url) == before


# ---------------------------------------------------------------------------
# Entry point (eslite.cli.main) against the real database
# ---------------------------------------------------------------------------


def test_the_provider_check_with_the_disabled_registry_row_exits_2_before_any_fetch(db_url, tmp_path, capsys):
    fetcher = FakeFetcher(full_site())
    created = []

    code = cli.main(
        {"DATABASE_URL": db_url, "ESLITE_PAGES_FILE": page_file(tmp_path, LIST_101), "ESLITE_ARTIFACTS_DIR": str(tmp_path / "artifacts")},
        fetcher_factory=lambda config, budget: created.append(config) or fetcher,
        monotonic=lambda: 0.0,
    )

    assert code == 2
    assert created == []
    assert fetcher.calls == []
    assert eslite_sources(db_url) == []
    assert "disabled or not registered" in capsys.readouterr().out


def test_the_cli_full_run_exits_0_writes_the_books_and_closes_the_fetcher(db_url, tmp_path, eslite_enabled, capsys):
    fetcher = FakeFetcher(site(LIST_101, [G_DICTIONARY, G_16, G_TRANSLATION]))

    code = cli.main(
        {
            "DATABASE_URL": db_url,
            "ESLITE_PAGES_FILE": page_file(tmp_path, LIST_101),
            "ESLITE_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
            "ESLITE_WRITE_POLICY": "normal",
        },
        fetcher_factory=lambda config, budget: fetcher,
        monotonic=lambda: 0.0,
    )

    assert code == 0
    assert fetcher.closed == 1
    assert [row[0] for row in eslite_sources(db_url)] == sorted([G_DICTIONARY, G_16, G_TRANSLATION])
    assert book_count(db_url) == 3
    out = capsys.readouterr().out
    assert "mode=eslite" in out
    assert DSN_SECRET not in out
    assert db_url not in out


def test_the_cli_writes_last_run_with_the_provider_counts_and_the_replay_touches_only(db_url, tmp_path, eslite_enabled, capsys):
    artifacts = tmp_path / "artifacts"
    environ = {
        "DATABASE_URL": db_url,
        "ESLITE_PAGES_FILE": page_file(tmp_path, LIST_101),
        "ESLITE_ARTIFACTS_DIR": str(artifacts),
        "ESLITE_WRITE_POLICY": "normal",
    }
    pages = site(LIST_101, [G_DICTIONARY, G_16, G_NOT_FOUND])

    assert cli.main(environ, fetcher_factory=lambda config, budget: FakeFetcher(pages), monotonic=lambda: 0.0) == 0

    data = json.loads((artifacts / "eslite" / "last-run.json").read_text(encoding="utf-8"))
    assert data["provider"] == "ESLITE"
    assert data["status"] == "PARTIAL_SUCCESS"
    assert (data["imported"], data["failed"]) == (2, 1)
    assert data["items_listed"] == data["items_seen"] == data["imported"] + data["failed"]
    assert data["details_fetched"] == 3
    assert data["http_attempts"] == 4
    assert data["write_policy"] == "normal"
    assert data["alert_reasons"] == []
    assert len(list((artifacts / "eslite" / "history").glob("*.json"))) == 1
    assert "ALERT" not in capsys.readouterr().out

    replay = FakeFetcher(pages)
    assert cli.main(environ, fetcher_factory=lambda config, budget: replay, monotonic=lambda: 0.0) == 0

    replayed = json.loads((artifacts / "eslite" / "last-run.json").read_text(encoding="utf-8"))
    assert replayed["existing_source"] == 2
    assert replayed["details_fetched"] == 1  # only the 404 card is fetched again
    assert replay.detail_calls() == [product(G_NOT_FOUND)]
    assert len(list((artifacts / "eslite" / "history").glob("*.json"))) == 2


def test_the_cli_is_a_second_entry_for_the_same_composition_as_run_pages(db_url, tmp_path, eslite_enabled):
    code = cli.main(
        {
            "DATABASE_URL": db_url,
            "ESLITE_PAGES_FILE": page_file(tmp_path, LIST_101),
            "ESLITE_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
            "ESLITE_WRITE_POLICY": "normal",
        },
        fetcher_factory=lambda config, budget: FakeFetcher(site(LIST_101, [G_DICTIONARY, G_16])),
        monotonic=lambda: 0.0,
    )
    replay = FakeFetcher(site(LIST_101, [G_DICTIONARY, G_16]))
    report = run_pages_once(db_url, replay, [LIST_101], now=LATER)

    assert code == 0
    assert report.existing_source == 2
    assert replay.detail_calls() == []
    assert book_count(db_url) == 2


def test_the_cli_run_with_every_page_skipped_exits_1_and_the_fetcher_is_closed(db_url, tmp_path, eslite_enabled):
    fetcher = FakeFetcher({LIST_101: AcquisitionError(AcquisitionFailure.HTTP_STATUS, "GET failed: http_status 503", 3, 503)})

    code = cli.main(
        {"DATABASE_URL": db_url, "ESLITE_PAGES_FILE": page_file(tmp_path, LIST_101), "ESLITE_ARTIFACTS_DIR": str(tmp_path / "artifacts")},
        fetcher_factory=lambda config, budget: fetcher,
        monotonic=lambda: 0.0,
    )

    assert code == 1
    assert fetcher.closed == 1
    assert eslite_sources(db_url) == []
