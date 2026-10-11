"""Category-list import (``run_pages``): adds books from a list of 7-day category pages to the Catalog.

The mode never writes ``bestsellers``. Tests never contact books.com.tw: the fetcher is a fake,
pages are prepared HTML strings and the parsers are fakes. The unit tests fake the database store
functions; the DB tests use the throwaway ``db_url`` PostgreSQL only.
"""

from __future__ import annotations

import logging
import runpy
from contextlib import nullcontext
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
import pytest

from books_crawler import cli, db
from books_crawler.cli import CrawlerMode
from books_crawler.fetcher import BrowserUnavailableError, FetcherKind, FetchError
from books_crawler.models import Identifier, IdentifierType, IsbnMatch, RankingRow, RunStatus, SkipReason, SourceRef
from books_crawler.page_list import PAGES_FILE_ENV
from books_crawler.parsers import RANKING_PAGE_URL, ParseError, RestrictedBookError
from books_crawler.run import RunDependencies, run_once, run_pages
from tests.fakes import (
    RANKING_HTML,
    FakeFetcher,
    FakeSleep,
    fake_detail_parser,
    fake_ranking_parser,
    make_draft,
    product_url,
    ranking_rows,
)

NOW = datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)
RETRY_SLEEPS = [1.0, 2.0]  # backoff before attempts 2 and 3 (crawler.md §6)
CATEGORY_1 = "https://www.books.com.tw/web/sys_saletopb/books/01/?attribute=7&loc=P_0002_002"
CATEGORY_2 = "https://www.books.com.tw/web/sys_saletopb/books/02/?attribute=7&loc=P_0002_003"
CATEGORY_3 = "https://www.books.com.tw/web/sys_saletopb/books/03/?attribute=7&loc=P_0002_004"
DATABASE = {"DATABASE_URL": "postgresql://unused"}


class FakeStore:
    """In-memory stand-in for the database functions ``run_pages`` calls on a Catalog write."""

    def __init__(self) -> None:
        self.sources: dict[str, SourceRef] = {}
        self.isbn_owners: dict[str, UUID] = {}  # identifier value -> owning Book
        self.persisted: list[tuple] = []  # (draft, attach_to_book_id)

    def find_source(self, conn, source_url):
        return self.sources.get(source_url)

    def find_book_by_isbn(self, conn, identifiers):
        for identifier in identifiers:
            if identifier.identifier_value in self.isbn_owners:
                return IsbnMatch(book_id=self.isbn_owners[identifier.identifier_value], identifier=identifier)
        return None

    def persist(self, conn, draft, now, attach_to_book_id=None):
        self.persisted.append((draft, attach_to_book_id))
        book_id = attach_to_book_id if attach_to_book_id is not None else uuid4()
        ref = SourceRef(source_id=uuid4(), book_id=book_id)
        self.sources[draft.source_url] = ref
        return ref

    def persisted_urls(self) -> list[str]:
        return [draft.source_url for draft, _ in self.persisted]


@pytest.fixture
def store(monkeypatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setattr(db, "find_source", fake.find_source)
    monkeypatch.setattr(db, "find_book_by_isbn", fake.find_book_by_isbn)
    monkeypatch.setattr(db, "persist_new_source", fake.persist)
    # The Catalog import must never touch the bestseller list; an attempt fails the test outright.
    monkeypatch.setattr(db, "replace_bestsellers", lambda *args, **kwargs: pytest.fail("run_pages must not write bestsellers"))
    return fake


def category_html(url: str) -> str:
    return f"<category {url}/>"


def site(rows_by_url: dict[str, list[RankingRow]], parse_errors: dict[str, Exception] | None = None):
    """Prepared category pages, and a ranking parser that returns each page's rows or raises its error."""
    rows_by_html = {category_html(url): rows for url, rows in rows_by_url.items()}
    errors_by_html = {category_html(url): error for url, error in (parse_errors or {}).items()}

    def parse(html: str) -> list[RankingRow]:
        if html in errors_by_html:
            raise errors_by_html[html]
        return list(rows_by_html[html])

    return {url: category_html(url) for url in rows_by_url}, parse


def products_of(rows_by_url: dict[str, list[RankingRow]]) -> list[str]:
    return [row.url for rows in rows_by_url.values() for row in rows]


def detail_parser(drafts: dict[str, BookDraft], errors: dict[str, Exception] | None = None):
    """Detail parser: raises the prepared error for a URL on every call, otherwise returns its draft."""
    errors = errors or {}

    def parse(html: str, url: str) -> BookDraft:
        if url in errors:
            raise errors[url]
        return drafts[url]

    return parse


def crawl(
    monkeypatch,
    rows_by_url,
    *,
    category_urls=None,
    failures=None,
    transient=None,
    parse_detail=None,
    parse_errors=None,
    connect=None,
    run_id=None,
):
    """Run ``run_pages`` over prepared category pages. Returns ``(report, deps)``; ``deps.fetcher`` records calls."""
    pages, parse_category = site(rows_by_url, parse_errors)
    products = products_of(rows_by_url)
    fetcher = FakeFetcher(
        pages={**pages, **{url: "<detail/>" for url in products}},
        failures=failures,
        transient_failures=transient,
    )
    deps = RunDependencies(
        fetcher=fetcher,
        parse_ranking=parse_category,
        parse_detail=parse_detail or fake_detail_parser({url: make_draft(url) for url in products}),
        connect=connect or (lambda: nullcontext(object())),
        clock=lambda: NOW,
        sleep=FakeSleep(),
    )
    page_urls = list(rows_by_url) if category_urls is None else category_urls
    return run_pages(deps, page_urls, run_id=run_id), deps


# ---------------------------------------------------------------------------
# Unit tests: fake fetcher, fake parsers, fake store (no database, no network)
# ---------------------------------------------------------------------------


def test_each_listed_page_is_fetched_in_order_and_every_new_product_is_written_once(store, monkeypatch):
    p = product_url
    rows = {
        CATEGORY_1: ranking_rows(3),
        CATEGORY_2: ranking_rows(2, offset=3),
        CATEGORY_3: ranking_rows(1, offset=5),
    }

    report, deps = crawl(monkeypatch, rows, run_id="run-pages-1")

    assert report.error is None
    assert report.exit_code == 0
    assert report.run_id == "run-pages-1"
    assert (report.started_at, report.finished_at) == (NOW, NOW)
    assert deps.fetcher.calls == [CATEGORY_1, p(1), p(2), p(3), CATEGORY_2, p(4), p(5), CATEGORY_3, p(6)]
    assert store.persisted_urls() == [p(n) for n in range(1, 7)]
    assert all(attach is None for _, attach in store.persisted)  # each product is a new Book


def test_run_id_is_generated_when_not_given(store, monkeypatch):
    report, _ = crawl(monkeypatch, {CATEGORY_1: ranking_rows(1)})

    assert UUID(report.run_id)  # a valid UUID string


def test_product_listed_on_two_pages_is_detail_fetched_and_written_once(store, monkeypatch):
    rows = {
        CATEGORY_1: [RankingRow(rank=1, url=product_url(1)), RankingRow(rank=2, url=product_url(2))],
        CATEGORY_2: [RankingRow(rank=1, url=product_url(2)), RankingRow(rank=2, url=product_url(3))],
    }

    report, deps = crawl(monkeypatch, rows)

    assert report.error is None
    assert deps.fetcher.detail_calls() == [product_url(1), product_url(2), product_url(3)]
    assert store.persisted_urls() == [product_url(1), product_url(2), product_url(3)]


def test_same_product_twice_on_one_page_is_written_once(store, monkeypatch):
    rows = {CATEGORY_1: [RankingRow(rank=1, url=product_url(1)), RankingRow(rank=2, url=product_url(1))]}

    report, deps = crawl(monkeypatch, rows)

    assert report.error is None
    assert deps.fetcher.detail_calls() == [product_url(1)]
    assert store.persisted_urls() == [product_url(1)]


def test_existing_book_source_is_reused_without_detail_request_or_persist(store, monkeypatch):
    known = SourceRef(source_id=uuid4(), book_id=uuid4())
    store.sources[product_url(1)] = known

    report, deps = crawl(monkeypatch, {CATEGORY_1: ranking_rows(2)})

    assert report.error is None
    assert deps.fetcher.detail_calls() == [product_url(2)]  # product 1 is never requested
    assert store.persisted_urls() == [product_url(2)]
    assert store.sources[product_url(1)] is known


def test_new_source_whose_isbn_is_already_catalogued_attaches_to_that_book(store, monkeypatch):
    owner = uuid4()
    store.isbn_owners["9789570000001"] = owner
    isbn = (Identifier(IdentifierType.ISBN_13, "9789570000001"),)
    drafts = {product_url(1): make_draft(product_url(1), title="Reprint listing", identifiers=isbn)}

    report, deps = crawl(
        monkeypatch,
        {CATEGORY_1: [RankingRow(rank=1, url=product_url(1))]},
        parse_detail=detail_parser(drafts),
    )

    assert report.error is None
    assert [attach for _, attach in store.persisted] == [owner]  # attached, not a new Book


def test_unparseable_category_page_is_skipped_without_retry_and_the_list_continues(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(2), CATEGORY_2: ranking_rows(1, offset=2), CATEGORY_3: ranking_rows(1, offset=3)}
    error = ParseError("ranking page is not the 7日暢銷榜 (simulated)")

    report, deps = crawl(monkeypatch, rows, parse_errors={CATEGORY_2: error})

    assert deps.fetcher.calls.count(CATEGORY_2) == 1  # a parse failure is deterministic: no retry
    assert deps.fetcher.calls.count(CATEGORY_3) == 1  # the list goes on
    assert store.persisted_urls() == [product_url(1), product_url(2), product_url(4)]
    assert report.error is None
    assert report.exit_code == 0
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert [(page.url, page.failure.error_type, page.failure.attempts) for page in report.skipped_pages] == [
        (CATEGORY_2, SkipReason.PARSE_ERROR, 1)
    ]


def test_category_page_fetch_is_retried_then_the_list_continues(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(1), CATEGORY_2: ranking_rows(1, offset=1)}

    report, deps = crawl(monkeypatch, rows, transient={CATEGORY_2: 2})

    assert report.error is None
    assert deps.fetcher.calls.count(CATEGORY_2) == 3
    assert deps.sleep.calls == RETRY_SLEEPS
    assert store.persisted_urls() == [product_url(1), product_url(2)]


def test_category_page_that_keeps_failing_is_skipped_after_three_attempts_and_the_list_continues(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(1), CATEGORY_2: ranking_rows(1, offset=1), CATEGORY_3: ranking_rows(1, offset=2)}

    report, deps = crawl(monkeypatch, rows, failures={CATEGORY_2: FetchError("HTTP 403")})

    assert deps.fetcher.calls.count(CATEGORY_2) == 3
    assert CATEGORY_3 in deps.fetcher.calls
    assert deps.sleep.calls == RETRY_SLEEPS
    assert store.persisted_urls() == [product_url(1), product_url(3)]
    assert report.error is None
    assert report.exit_code == 0
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert [(page.url, page.failure.error_type, page.failure.attempts) for page in report.skipped_pages] == [
        (CATEGORY_2, SkipReason.FETCH_ERROR, 3)
    ]
    assert report.skipped_pages[0].failure.error_message == "ranking page failed after 3 attempts: HTTP 403"


def test_category_page_rows_are_not_checked_against_the_bestseller_rules(store, monkeypatch):
    # Documented current behaviour: the list mode accepts any row count and does not run validate_ranking.
    report, deps = crawl(monkeypatch, {CATEGORY_1: ranking_rows(3)})

    assert report.error is None
    assert deps.fetcher.detail_calls() == [product_url(1), product_url(2), product_url(3)]


def test_new_book_detail_fetch_is_retried_and_written_once(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(3)}

    report, deps = crawl(monkeypatch, rows, failures=None, transient={product_url(2): 1})

    assert report.error is None
    assert deps.fetcher.calls.count(product_url(2)) == 2
    assert deps.sleep.calls == [1.0]
    assert store.persisted_urls() == [product_url(1), product_url(2), product_url(3)]


def test_detail_that_keeps_failing_is_skipped_after_three_attempts_and_the_page_continues(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(3)}

    report, deps = crawl(monkeypatch, rows, failures={product_url(2): FetchError("HTTP 500")})

    assert deps.fetcher.calls.count(product_url(2)) == 3
    assert deps.sleep.calls == RETRY_SLEEPS
    assert store.persisted_urls() == [product_url(1), product_url(3)]
    assert report.error is None
    assert report.exit_code == 0
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert [(row.url, row.failure.error_type, row.failure.attempts) for row in report.skipped] == [
        (product_url(2), SkipReason.FETCH_ERROR, 3)
    ]


def test_detail_parse_error_is_retried_three_times_then_skipped_as_parse_error(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(2)}
    drafts = {url: make_draft(url) for url in products_of(rows)}
    parse = detail_parser(drafts, {product_url(1): ParseError("title (h1) not found (simulated)")})

    report, deps = crawl(monkeypatch, rows, parse_detail=parse)

    assert deps.fetcher.calls.count(product_url(1)) == 3  # the page is fetched again on every attempt
    assert store.persisted_urls() == [product_url(2)]
    assert report.error is None
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert [(row.rank, row.failure.error_type, row.failure.attempts) for row in report.skipped] == [
        (1, SkipReason.PARSE_ERROR, 3)
    ]


def test_restricted_member_page_is_skipped_without_retry_and_is_not_an_error(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(3)}
    drafts = {url: make_draft(url) for url in products_of(rows)}
    parse = detail_parser(drafts, {product_url(2): RestrictedBookError("restricted product requires member login")})

    report, deps = crawl(monkeypatch, rows, parse_detail=parse)

    assert report.error is None
    assert report.exit_code == 0
    assert deps.fetcher.calls.count(product_url(2)) == 1
    assert deps.sleep.calls == []
    assert store.persisted_urls() == [product_url(1), product_url(3)]


def test_every_failed_row_is_recorded_and_none_of_them_stops_the_run(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(3)}

    report, deps = crawl(monkeypatch, rows, failures={product_url(1): FetchError("a"), product_url(3): FetchError("b")})

    assert deps.fetcher.calls.count(product_url(3)) == 3
    assert report.error is None
    assert [row.url for row in report.skipped] == [product_url(1), product_url(3)]
    assert store.persisted_urls() == [product_url(2)]


def test_browser_unavailable_on_a_detail_page_fails_the_run_without_retry(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(2), CATEGORY_2: ranking_rows(1, offset=2)}

    report, deps = crawl(monkeypatch, rows, failures={product_url(2): BrowserUnavailableError("no chromium")})

    assert report.exit_code == 1
    assert report.error.startswith("BrowserUnavailableError: ")
    assert deps.fetcher.calls == [CATEGORY_1, product_url(1), product_url(2)]  # neither retried nor skipped
    assert deps.sleep.calls == []
    assert store.persisted_urls() == [product_url(1)]


def test_database_failure_on_the_source_lookup_stops_the_run(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(1), CATEGORY_2: ranking_rows(1, offset=1)}

    def broken_lookup(conn, source_url):
        raise psycopg.OperationalError("database is down")

    monkeypatch.setattr(db, "find_source", broken_lookup)

    report, deps = crawl(monkeypatch, rows)

    assert report.exit_code == 1
    assert report.error.startswith("OperationalError: ")
    assert deps.fetcher.calls == [CATEGORY_1]


def test_database_write_is_retried_with_the_parsed_draft_without_refetching_the_detail(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(1)}
    attempts: list[BookDraft] = []
    real_persist = store.persist

    def flaky_persist(conn, draft, now, attach_to_book_id=None):
        attempts.append(draft)
        if len(attempts) < 3:
            raise psycopg.OperationalError("temporary write failure")
        return real_persist(conn, draft, now, attach_to_book_id=attach_to_book_id)

    monkeypatch.setattr(db, "persist_new_source", flaky_persist)

    report, deps = crawl(monkeypatch, rows)

    assert report.error is None
    assert deps.fetcher.calls.count(product_url(1)) == 1
    assert attempts[0] is attempts[1] is attempts[2]
    assert deps.sleep.calls == RETRY_SLEEPS


def test_empty_list_fetches_nothing_and_succeeds(store, monkeypatch):
    report, deps = crawl(monkeypatch, {})

    assert report.error is None
    assert report.exit_code == 0
    assert deps.fetcher.calls == []


def test_duplicate_page_url_in_the_list_is_fetched_twice_and_its_products_written_once(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(2)}

    report, deps = crawl(monkeypatch, rows, category_urls=[CATEGORY_1, CATEGORY_1])

    assert report.error is None
    assert deps.fetcher.calls.count(CATEGORY_1) == 2
    assert deps.fetcher.detail_calls() == [product_url(1), product_url(2)]
    assert store.persisted_urls() == [product_url(1), product_url(2)]


def test_database_error_text_with_a_connection_string_is_redacted_in_the_report(store, monkeypatch):
    def failing_persist(conn, draft, now, attach_to_book_id=None):
        raise psycopg.OperationalError("connect failed: postgresql://crawler:s3cret@db.internal/books")

    monkeypatch.setattr(db, "persist_new_source", failing_persist)

    report, _ = crawl(monkeypatch, {CATEGORY_1: ranking_rows(1)})

    message = report.skipped[0].failure.error_message  # a write failure is a retried, skipped row
    assert report.skipped[0].failure.error_type is SkipReason.DATABASE_ERROR
    assert "s3cret" not in message
    assert "db.internal" not in message
    assert "postgresql://<redacted>" in message


def test_run_logs_each_page_and_one_summary_line_with_the_run_id(store, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="books_crawler")

    crawl(monkeypatch, {CATEGORY_1: ranking_rows(1), CATEGORY_2: ranking_rows(1, offset=1)}, run_id="run-log-1")

    messages = [record.getMessage() for record in caplog.records]
    assert f"importing page: {CATEGORY_1}" in messages
    assert f"importing page: {CATEGORY_2}" in messages
    summary = [message for message in messages if message.startswith("mode=pages ")]
    assert summary == [
        "mode=pages run_id=run-log-1 started_at=2026-10-11T04:00:00+00:00 "
        "finished_at=2026-10-11T04:00:00+00:00 status=SUCCESS pages_total=2 pages_skipped=0 rows_seen=2 "
        "existing_book_count=0 new_book_count=2 attached_source_count=0 skipped_count=0 "
        "restricted_book_count=0 error_count=0 exit_code=0 skipped=[] skipped_pages=[]"
    ]


def test_failed_run_logs_exactly_one_error_line(store, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="books_crawler")

    crawl(monkeypatch, {CATEGORY_1: ranking_rows(1)}, failures={CATEGORY_1: FetchError("HTTP 403")})

    errors = [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]
    assert errors == ["pages import failed: all 1 category page(s) failed"]


def test_every_configured_page_failing_fails_the_run_with_exit_one(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(1), CATEGORY_2: ranking_rows(1, offset=1)}

    report, deps = crawl(monkeypatch, rows, failures={CATEGORY_1: FetchError("HTTP 403"), CATEGORY_2: FetchError("HTTP 500")})

    assert report.status is RunStatus.FAILED
    assert report.exit_code == 1
    assert report.error == "all 2 category page(s) failed"
    assert store.persisted_urls() == []
    assert len(report.skipped_pages) == 2


def test_more_than_twenty_consecutive_row_failures_do_not_stop_the_run(store, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(26)}
    failures = {product_url(n): FetchError("HTTP 500") for n in range(1, 26)}

    report, deps = crawl(monkeypatch, rows, failures=failures)

    assert report.error is None
    assert report.exit_code == 0
    assert report.skipped_count == 25
    assert deps.fetcher.detail_calls()[-1] == product_url(26)  # the last row of the list was still processed
    assert store.persisted_urls() == [product_url(26)]


def test_the_report_counts_pages_rows_and_book_outcomes(store, monkeypatch):
    known = SourceRef(source_id=uuid4(), book_id=uuid4())
    store.sources[product_url(1)] = known
    rows = {
        CATEGORY_1: [RankingRow(rank=1, url=product_url(1)), RankingRow(rank=2, url=product_url(2))],
        CATEGORY_2: [RankingRow(rank=1, url=product_url(3)), RankingRow(rank=2, url=product_url(4))],
    }
    parse = detail_parser(
        {url: make_draft(url) for url in products_of(rows)},
        {product_url(2): RestrictedBookError("restricted product requires member login")},
    )

    report, _ = crawl(monkeypatch, rows, parse_detail=parse, failures={product_url(4): FetchError("HTTP 500")}, category_urls=[CATEGORY_1, CATEGORY_2, CATEGORY_1])

    assert report.pages_total == 3
    assert report.rows_seen == 6
    assert report.existing_book_count == 2  # product 1 (known) and product 1 again on the third page
    assert report.new_book_count == 1  # product 3
    assert report.attached_source_count == 0
    assert report.restricted_book_count == 2  # product 2 is restricted on both pages it appears on
    assert report.error_count == 1  # product 4: three failed attempts
    assert report.skipped_pages == []
    assert report.status is RunStatus.PARTIAL_SUCCESS


# ---------------------------------------------------------------------------
# Database tests: what is actually written (throwaway PostgreSQL)
# ---------------------------------------------------------------------------


def query(url: str, sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def count(url: str, table: str) -> int:
    return query(url, f"SELECT count(*) FROM {table}")[0][0]


def seed_bestsellers(db_url: str) -> None:
    """Daily crawl of 100 products, so the bestseller list and its sources exist before the category import."""
    rows = ranking_rows(100)
    drafts = {row.url: make_draft(row.url, title=f"Seed {row.rank}") for row in rows}
    fetcher = FakeFetcher(pages={RANKING_PAGE_URL: RANKING_HTML, **{row.url: "<detail/>" for row in rows}})
    deps = RunDependencies(
        fetcher=fetcher,
        parse_ranking=fake_ranking_parser(rows),
        parse_detail=fake_detail_parser(drafts),
        connect=lambda: db.connect(db_url),
        clock=lambda: NOW,
        sleep=FakeSleep(),
    )
    report = run_once(deps)
    assert report.error is None, report.error


def test_category_import_adds_new_books_and_leaves_bestsellers_and_known_sources_untouched(db_url, monkeypatch):
    seed_bestsellers(db_url)
    before_bestsellers = query(db_url, "SELECT rank, book_id, source_id, captured_at FROM bestsellers ORDER BY rank")
    before_sources = dict(query(db_url, "SELECT source_url, last_seen_at FROM book_sources"))
    rows = {
        CATEGORY_1: [RankingRow(rank=1, url=product_url(1)), RankingRow(rank=2, url=product_url(101))],
        CATEGORY_2: [RankingRow(rank=1, url=product_url(1)), RankingRow(rank=2, url=product_url(102))],
    }

    report, deps = crawl(monkeypatch, rows, connect=lambda: db.connect(db_url))

    assert report.error is None
    assert deps.fetcher.detail_calls() == [product_url(101), product_url(102)]
    assert query(db_url, "SELECT rank, book_id, source_id, captured_at FROM bestsellers ORDER BY rank") == before_bestsellers
    after_sources = dict(query(db_url, "SELECT source_url, last_seen_at FROM book_sources"))
    assert {url: after_sources[url] for url in before_sources} == before_sources  # last_seen_at not advanced
    assert count(db_url, "books") == 102
    assert count(db_url, "book_sources") == 102
    assert query(db_url, "SELECT title FROM books WHERE id = (SELECT book_id FROM book_sources WHERE source_url = %s)", (product_url(1),)) == [("Seed 1",)]


def test_isbn_match_attaches_a_second_source_to_the_existing_book_and_keeps_its_metadata(db_url, monkeypatch):
    isbn = (Identifier(IdentifierType.ISBN_13, "9789570000001"),)
    first = {product_url(201): make_draft(product_url(201), title="Original title", identifiers=isbn)}
    crawl(monkeypatch, {CATEGORY_1: [RankingRow(rank=1, url=product_url(201))]}, parse_detail=fake_detail_parser(first), connect=lambda: db.connect(db_url))
    second = {product_url(202): make_draft(product_url(202), title="Reprint listing", identifiers=isbn)}

    report, deps = crawl(monkeypatch, {CATEGORY_2: [RankingRow(rank=1, url=product_url(202))]}, parse_detail=fake_detail_parser(second), connect=lambda: db.connect(db_url))

    assert report.error is None
    assert deps.fetcher.detail_calls() == [product_url(202)]
    assert count(db_url, "books") == 1
    assert query(db_url, "SELECT title FROM books") == [("Original title",)]
    book_ids = query(db_url, "SELECT DISTINCT book_id FROM book_sources")
    assert len(book_ids) == 1
    assert count(db_url, "book_sources") == 2


def test_books_are_kept_when_a_later_page_is_skipped_and_the_run_completes(db_url, monkeypatch):
    rows = {CATEGORY_1: ranking_rows(2), CATEGORY_2: ranking_rows(1, offset=2), CATEGORY_3: ranking_rows(1, offset=3)}

    report, _ = crawl(monkeypatch, rows, failures={CATEGORY_2: FetchError("HTTP 403")}, connect=lambda: db.connect(db_url))

    assert report.exit_code == 0
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert count(db_url, "books") == 3
    assert count(db_url, "book_sources") == 3
    assert count(db_url, "bestsellers") == 0


# ---------------------------------------------------------------------------
# CLI wiring: pages mode (runners and fetcher stubbed, no network, no database)
# ---------------------------------------------------------------------------

PAGE1 = "https://www.books.com.tw/web/sys_saletopb/books/01/?attribute=7&loc=P_0002_002"
PAGE2 = "https://www.books.com.tw/web/sys_saletopb/books/02/?attribute=7&loc=P_0002_003"


class FakeRunResult:
    def __init__(self, exit_code: int) -> None:
        self.exit_code = exit_code


class FakeClosingFetcher:
    def __init__(self) -> None:
        self.closed = 0

    def get(self, url: str) -> str:
        raise AssertionError("the stubbed run never fetches")

    def close(self) -> None:
        self.closed += 1


def stub_runs(monkeypatch, *, exit_code: int = 0, error: Exception | None = None) -> dict:
    """Stub the fetcher factory and the three runners. ``seen["runs"]`` records (mode, runner arguments)."""
    seen: dict = {"runs": [], "fetcher": None}

    def create_fetcher(kind, *, navigation_timeout_ms):
        seen["fetcher"] = FakeClosingFetcher()
        return seen["fetcher"]

    def runner(name):
        def run(deps, *args):
            assert deps.fetcher is seen["fetcher"]
            seen["runs"].append((name, args))
            if error is not None:
                raise error
            return FakeRunResult(exit_code)

        return run

    monkeypatch.setattr(cli, "create_fetcher", create_fetcher)
    monkeypatch.setattr(cli, "run_once", runner("daily"))
    monkeypatch.setattr(cli, "run_first_book", runner("first-book"))
    monkeypatch.setattr(cli, "run_pages", runner("pages"))
    return seen


def write_page_list(tmp_path, text: str):
    path = tmp_path / "pages.txt"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("exit_code", [0, 1])
def test_pages_mode_selects_the_category_runner_and_returns_its_exit_code(monkeypatch, exit_code):
    seen = stub_runs(monkeypatch, exit_code=exit_code)

    assert cli.main(DATABASE, mode=CrawlerMode.PAGES) == exit_code
    assert [name for name, _ in seen["runs"]] == ["pages"]
    assert seen["fetcher"].closed == 1


def test_pages_mode_closes_the_fetcher_when_the_run_raises(monkeypatch):
    seen = stub_runs(monkeypatch, error=RuntimeError("unexpected"))

    with pytest.raises(RuntimeError, match="unexpected"):
        cli.main(DATABASE, mode=CrawlerMode.PAGES)
    assert seen["fetcher"].closed == 1


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {**DATABASE, "CRAWLER_FETCHER": "selenium"},
        {**DATABASE, "CRAWLER_FETCHER": "browser", "CRAWLER_NAV_TIMEOUT_MS": "0"},
    ],
)
def test_pages_mode_configuration_error_exits_2_before_any_fetcher_or_run(monkeypatch, environ):
    seen = stub_runs(monkeypatch)

    assert cli.main(environ, mode=CrawlerMode.PAGES) == cli.EXIT_CONFIG_ERROR
    assert seen == {"runs": [], "fetcher": None}


def test_pages_mode_passes_the_browser_settings_to_the_fetcher_factory(monkeypatch):
    seen = stub_runs(monkeypatch)
    settings: dict = {}

    def create_fetcher(kind, *, navigation_timeout_ms):
        settings.update(kind=kind, navigation_timeout_ms=navigation_timeout_ms)
        seen["fetcher"] = FakeClosingFetcher()
        return seen["fetcher"]

    monkeypatch.setattr(cli, "create_fetcher", create_fetcher)

    assert cli.main({**DATABASE, "CRAWLER_FETCHER": "browser", "CRAWLER_NAV_TIMEOUT_MS": "45000"}, mode=CrawlerMode.PAGES) == 0
    assert settings == {"kind": FetcherKind.BROWSER, "navigation_timeout_ms": 45000}


@pytest.mark.parametrize("entry_module, runner_name", [
    ("books_crawler.__main__", "daily"),
    ("books_crawler.first_book", "first-book"),
    ("books_crawler.pages", "pages"),
])
def test_each_entry_point_runs_its_own_mode(monkeypatch, entry_module, runner_name):
    seen = stub_runs(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.delenv("CRAWLER_FETCHER", raising=False)
    monkeypatch.delenv("CRAWLER_NAV_TIMEOUT_MS", raising=False)
    monkeypatch.delenv(PAGES_FILE_ENV, raising=False)

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module(entry_module, run_name="__main__")

    assert exit_info.value.code == 0
    assert [name for name, _ in seen["runs"]] == [runner_name]


@pytest.mark.parametrize(
    "content",
    [None, "# nothing here\n\n", f"{PAGE1}\nhttps://example.com/not-books\n", "https://www.books.com.tw/web/sys_saletopb/books/?attribute=7\n"],
    ids=["missing-file", "only-comments", "non-books-url", "overall-daily-ranking-page"],
)
def test_an_invalid_page_list_exits_2_before_any_fetch_or_run(monkeypatch, tmp_path, content):
    path = tmp_path / "pages.txt"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    seen = stub_runs(monkeypatch)

    assert cli.main({**DATABASE, PAGES_FILE_ENV: str(path)}, mode=CrawlerMode.PAGES) == cli.EXIT_CONFIG_ERROR
    assert seen == {"runs": [], "fetcher": None}


def test_the_config_error_names_the_file_and_the_line(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="books_crawler")
    path = write_page_list(tmp_path, f"# comment\n{PAGE1}\nhttps://example.com/not-books\n")
    stub_runs(monkeypatch)

    assert cli.main({**DATABASE, PAGES_FILE_ENV: str(path)}, mode=CrawlerMode.PAGES) == cli.EXIT_CONFIG_ERROR
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert str(path) in errors[0] and "line 3" in errors[0]


def test_the_env_var_selects_the_page_list_that_pages_mode_reads(monkeypatch, tmp_path):
    path = write_page_list(tmp_path, f"{PAGE2}\n{PAGE1}\n")
    seen = stub_runs(monkeypatch)

    assert cli.main({**DATABASE, PAGES_FILE_ENV: str(path)}, mode=CrawlerMode.PAGES) == 0
    assert seen["runs"] == [("pages", ([PAGE2, PAGE1],))]


@pytest.mark.parametrize("mode, runner_name", [(CrawlerMode.DAILY, "daily"), (CrawlerMode.FIRST_BOOK, "first-book")])
def test_daily_and_first_book_ignore_the_page_list_env_var(monkeypatch, tmp_path, mode, runner_name):
    seen = stub_runs(monkeypatch)
    missing = tmp_path / "missing.txt"

    assert cli.main({**DATABASE, PAGES_FILE_ENV: str(missing)}, mode=mode) == 0
    assert [name for name, _ in seen["runs"]] == [runner_name]
