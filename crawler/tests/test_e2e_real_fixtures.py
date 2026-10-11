"""End-to-end run with the real ranking page and real detail pages (fake fetcher, throwaway DB).

Seeding (documented): the saved fixtures cover 4 of the 100 ranked products. The other 96 are
pre-seeded as existing BOOKS_COM_TW sources (minimal Books) so that the run does not need their
detail pages. The test asserts that the only detail requests are the 4 fixture products.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import psycopg
import pytest

from books_crawler import db
from books_crawler.models import RunStatus
from books_crawler.parsers import RANKING_PAGE_URL, parse_detail_html, parse_ranking_html
from books_crawler.run import RunDependencies, run_once
from tests.fakes import (
    RANKING_FIXTURE,
    RESTRICTED_GATE_FIXTURE,
    FakeFetcher,
    FakeSleep,
    detail_fixture_name,
    detail_without_product_container,
    detail_without_title,
    fixture_html,
    make_draft,
    product_url,
    ranking_with_duplicate_url,
    ranking_with_source_at_rank,
    ranking_without_last_item,
)

NOW = datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)
REAL_PRODUCTS = {
    "0011062863": 12,
    "0010852315": 8,
    "0011062550": 1,
    "0011057581": 17,
}
# (product id, rank in the ranking fixture) of the restricted book whose member gate is a fixture.
RESTRICTED_PRODUCT = (11063006, 2)
DERIVED_NEW_SOURCE_URL = product_url(9999999999)
DERIVED_RANK = 50


def query(url: str, sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def bestsellers(url: str) -> list[tuple]:
    return query(url, "SELECT rank, book_id, source_id, captured_at FROM bestsellers ORDER BY rank")


def count(url: str, table: str) -> int:
    return query(url, f"SELECT count(*) FROM {table}")[0][0]


def seed_existing_sources(url: str, source_urls: list[str]) -> None:
    with db.connect(url) as conn:
        for source_url in source_urls:
            db.persist_new_source(conn, make_draft(source_url), NOW)


def run_with(db_url: str, ranking_html: str, detail_pages: dict[str, str], sleep: FakeSleep | None = None):
    pages = {RANKING_PAGE_URL: ranking_html, **detail_pages}
    fetcher = FakeFetcher(pages=pages)
    deps = RunDependencies(
        fetcher=fetcher,
        parse_ranking=parse_ranking_html,
        parse_detail=parse_detail_html,
        connect=lambda: db.connect(db_url),
        clock=lambda: NOW,
        sleep=sleep if sleep is not None else FakeSleep(),
    )
    return run_once(deps), fetcher


def real_detail_pages() -> dict[str, str]:
    return {product_url(int(pid)): fixture_html(detail_fixture_name(pid)) for pid in REAL_PRODUCTS}


@pytest.fixture
def seeded_db(db_url):
    """The 96 products that have no saved detail page are existing sources in the database."""
    ranking_urls = [row.url for row in parse_ranking_html(fixture_html(RANKING_FIXTURE))]
    real_urls = {product_url(int(pid)) for pid in REAL_PRODUCTS}
    seed_existing_sources(db_url, [url for url in ranking_urls if url not in real_urls])
    assert count(db_url, "books") == 96
    return db_url


@pytest.fixture
def successful_baseline(seeded_db):
    """Run once with the real ranking and the 4 real detail pages: the bestseller list to protect."""
    report, fetcher = run_with(seeded_db, fixture_html(RANKING_FIXTURE), real_detail_pages())
    assert report.status is RunStatus.SUCCESS, report.error
    return seeded_db


def test_real_fixtures_run_writes_100_bestsellers_and_the_four_real_books(seeded_db):
    report, fetcher = run_with(seeded_db, fixture_html(RANKING_FIXTURE), real_detail_pages())

    assert report.status is RunStatus.SUCCESS
    assert report.exit_code == 0
    assert (report.ranking_count, report.existing_book_count, report.new_book_count) == (100, 96, 4)
    assert sorted(fetcher.detail_calls()) == sorted(product_url(int(pid)) for pid in REAL_PRODUCTS)

    snapshot = bestsellers(seeded_db)
    assert [row[0] for row in snapshot] == list(range(1, 101))
    assert {row[3] for row in snapshot} == {NOW}

    for product_id, rank in REAL_PRODUCTS.items():
        source_url = product_url(int(product_id))
        book_id = query(seeded_db, "SELECT book_id FROM book_sources WHERE source_url = %s", (source_url,))[0][0]
        assert snapshot[rank - 1][1] == book_id, f"rank {rank} should point at {product_id}"


def test_real_restricted_member_gate_is_skipped_once_and_leaves_a_gap(db_url):
    """Rank 2 (0011063006) returns the real member gate: skipped without retry, not an error."""
    restricted_url = product_url(RESTRICTED_PRODUCT[0])
    ranking_urls = [row.url for row in parse_ranking_html(fixture_html(RANKING_FIXTURE))]
    with_detail_pages = {product_url(int(pid)) for pid in REAL_PRODUCTS} | {restricted_url}
    seed_existing_sources(db_url, [url for url in ranking_urls if url not in with_detail_pages])
    pages = {**real_detail_pages(), restricted_url: fixture_html(RESTRICTED_GATE_FIXTURE)}

    report, fetcher = run_with(db_url, fixture_html(RANKING_FIXTURE), pages)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.exit_code == 0
    assert (report.restricted_book_count, report.error_count, report.consecutive_error_count) == (1, 0, 0)
    skipped = report.skipped[0]
    assert (skipped.rank, skipped.url, skipped.failure.error_type, skipped.failure.attempts) == (
        RESTRICTED_PRODUCT[1],
        restricted_url,
        "restricted_book",
        1,
    )
    assert fetcher.detail_calls().count(restricted_url) == 1
    assert [row[0] for row in bestsellers(db_url)] == [rank for rank in range(1, 101) if rank != RESTRICTED_PRODUCT[1]]
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (restricted_url,)) == [(0,)]


def test_real_books_are_written_with_the_expected_columns(successful_baseline):
    def book_for(product_id: str):
        return query(
            successful_baseline,
            """
            SELECT b.id, b.title, b.subtitle, b.publisher, b.published_date, b.published_date_precision,
                   b.language, b.description, b.table_of_contents, b.page_count, b.thumbnail_url,
                   b.created_at, b.updated_at
            FROM books b JOIN book_sources s ON s.book_id = b.id WHERE s.source_url = %s
            """,
            (product_url(int(product_id)),),
        )[0]

    rows = {pid: book_for(pid) for pid in REAL_PRODUCTS}

    # 0011062863: TOC and page count present, single author
    book = rows["0011062863"]
    assert book[1:6] == ("政。望：前線五十年，從國安決策到世界現場的國家思考", None, "聯經出版公司", date(2026, 9, 17), "DAY")
    assert book[6] == "zh-TW"
    assert book[9] == 320
    assert book[8] is not None and book[8].startswith("序 五十年軍政生涯的省思")
    assert book[11] == NOW and book[12] == NOW

    # 0011062550: no TOC section, so table_of_contents stays NULL
    book = rows["0011062550"]
    assert book[8] is None
    assert book[9] == 148

    # every real book: subtitle is always NULL, source-derived fields are present
    for pid, book in rows.items():
        assert book[2] is None, pid
        assert book[7] is not None and book[7] != "", pid
        assert book[10] is not None and book[10].startswith("https://"), pid

    # identifiers, contributors (with roles, in order) and subjects
    translated = rows["0011062550"][0]
    assert query(successful_baseline, "SELECT identifier_type, identifier_value FROM book_identifiers WHERE book_id = %s", (translated,)) == [
        ("ISBN_13", "9786260284909")
    ]
    assert query(
        successful_baseline,
        "SELECT contributor_order, name, role FROM book_contributors WHERE book_id = %s ORDER BY contributor_order",
        (translated,),
    ) == [(1, "あおのなち", "AUTHOR"), (2, "蔡夢芳", "TRANSLATOR")]
    assert query(
        successful_baseline,
        "SELECT subject, source_type FROM book_subjects WHERE book_id = %s ORDER BY subject",
        (translated,),
    ) == [("GL", "BOOKS_COM_TW"), ("漫畫/圖文書", "BOOKS_COM_TW")]

    author_only = rows["0010852315"][0]
    assert query(
        successful_baseline,
        "SELECT contributor_order, name, role FROM book_contributors WHERE book_id = %s ORDER BY contributor_order",
        (author_only,),
    ) == [(1, "楊双子", "AUTHOR")]

    source = query(
        successful_baseline,
        "SELECT source_type, external_id, first_seen_at, last_seen_at FROM book_sources WHERE source_url = %s",
        (product_url(11062550),),
    )
    assert source == [("BOOKS_COM_TW", None, NOW, NOW)]


def test_derived_ranking_with_99_rows_fails_and_keeps_bestsellers(successful_baseline):
    previous = bestsellers(successful_baseline)
    books_before = count(successful_baseline, "books")

    report, fetcher = run_with(successful_baseline, ranking_without_last_item(fixture_html(RANKING_FIXTURE)), real_detail_pages())

    assert report.status is RunStatus.FAILED
    assert report.exit_code == 1
    assert "expected 100" in report.error
    assert fetcher.detail_calls() == []
    assert bestsellers(successful_baseline) == previous
    assert count(successful_baseline, "books") == books_before


def test_derived_duplicate_product_url_fails_and_keeps_bestsellers(successful_baseline):
    previous = bestsellers(successful_baseline)

    report, fetcher = run_with(successful_baseline, ranking_with_duplicate_url(fixture_html(RANKING_FIXTURE)), real_detail_pages())

    assert report.status is RunStatus.FAILED
    assert "duplicate product URL" in report.error
    assert fetcher.detail_calls() == []
    assert bestsellers(successful_baseline) == previous


def _assert_derived_source_skipped(db_url, report, fetcher, previous, error_fragment):
    """The derived new source is retried 3 times, skipped at its rank, and writes nothing."""
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.exit_code == 0
    assert [item.rank for item in report.skipped] == [DERIVED_RANK]
    skipped = report.skipped[0]
    assert (skipped.url, skipped.failure.error_type, skipped.failure.attempts) == (DERIVED_NEW_SOURCE_URL, "parse_error", 3)
    assert error_fragment in skipped.failure.error_message
    assert fetcher.detail_calls() == [DERIVED_NEW_SOURCE_URL] * 3
    snapshot = bestsellers(db_url)
    assert [row[0] for row in snapshot] == [rank for rank in range(1, 101) if rank != DERIVED_RANK]
    assert [row[1:3] for row in snapshot if row[0] < DERIVED_RANK] == [
        row[1:3] for row in previous if row[0] < DERIVED_RANK
    ]
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (DERIVED_NEW_SOURCE_URL,)) == [(0,)]


def test_derived_new_source_without_title_is_retried_then_skipped_without_an_empty_book(successful_baseline):
    previous = bestsellers(successful_baseline)
    books_before = count(successful_baseline, "books")
    ranking = ranking_with_source_at_rank(fixture_html(RANKING_FIXTURE), DERIVED_RANK, DERIVED_NEW_SOURCE_URL)
    broken_detail = detail_without_title(fixture_html(detail_fixture_name("0011062863")))
    sleep = FakeSleep()

    report, fetcher = run_with(successful_baseline, ranking, {DERIVED_NEW_SOURCE_URL: broken_detail}, sleep=sleep)

    _assert_derived_source_skipped(successful_baseline, report, fetcher, previous, "title")
    assert sleep.calls == [1.0, 2.0]
    assert count(successful_baseline, "books") == books_before  # no empty Book was written


def test_derived_new_source_without_product_container_is_retried_then_skipped(successful_baseline):
    """The layout changed: the product container is gone. Nothing may be read from the rest of the page."""
    previous = bestsellers(successful_baseline)
    ranking = ranking_with_source_at_rank(fixture_html(RANKING_FIXTURE), DERIVED_RANK, DERIVED_NEW_SOURCE_URL)
    broken_detail = detail_without_product_container(fixture_html(detail_fixture_name("0011062863")))

    report, fetcher = run_with(successful_baseline, ranking, {DERIVED_NEW_SOURCE_URL: broken_detail})

    _assert_derived_source_skipped(successful_baseline, report, fetcher, previous, "main_column")
