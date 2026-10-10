"""Integration tests: one crawler run against a throwaway PostgreSQL with the EF Core schema.

Fetcher and parsers are fakes; books.com.tw is never contacted.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import psycopg
import pytest

from books_crawler import db
from books_crawler.fetcher import FetchError
from books_crawler.models import Contributor, RankingRow, SnapshotRow
from books_crawler.normalize import map_language, normalize_isbn
from books_crawler.run import STATUS_FAILED, STATUS_SUCCESS, RunDependencies, run_once
from tests.fakes import (
    RANKING_HTML,
    FakeFetcher,
    fake_detail_parser,
    fake_ranking_parser,
    make_draft,
    product_url,
    ranking_rows,
)

RANKING_URL = "https://www.books.com.tw/web/sys_saletopb/books/?attribute=7"
NOW = datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)


def query(url: str, sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def bestsellers(url: str) -> list[tuple]:
    return query(url, "SELECT rank, book_id, source_id, captured_at FROM bestsellers ORDER BY rank")


def count(url: str, table: str) -> int:
    return query(url, f"SELECT count(*) FROM {table}")[0][0]


def run(db_url, rows, drafts=None, failures=None):
    """Run one crawl with the given ranking rows; detail drafts default to title-only books."""
    pages = {RANKING_URL: RANKING_HTML, **{row.url: "<detail/>" for row in rows}}
    if drafts is None:
        drafts = {row.url: make_draft(row.url) for row in rows}
    fetcher = FakeFetcher(pages=pages, failures=failures)
    deps = RunDependencies(
        fetcher=fetcher,
        parse_ranking=fake_ranking_parser(rows),
        parse_detail=fake_detail_parser(drafts),
        connect=lambda: db.connect(db_url),
        clock=lambda: NOW,
        ranking_url=RANKING_URL,
    )
    return run_once(deps), fetcher


def test_full_ranking_success_writes_100_bestsellers(db_url):
    rows = ranking_rows(100)

    report, fetcher = run(db_url, rows)

    assert report.status == STATUS_SUCCESS
    assert report.exit_code == 0
    assert (report.ranking_count, report.new_book_count, report.existing_book_count) == (100, 100, 0)
    assert fetcher.detail_calls() == [row.url for row in rows]

    snapshot = bestsellers(db_url)
    assert [row[0] for row in snapshot] == list(range(1, 101))
    assert {row[3] for row in snapshot} == {NOW}  # one captured_at for the whole list

    joined = query(
        db_url,
        """
        SELECT b.rank, s.source_type, s.source_url, s.book_id, b.book_id, s.id, b.source_id
        FROM bestsellers b JOIN book_sources s ON s.id = b.source_id
        ORDER BY b.rank
        """,
    )
    for (rank, source_type, source_url, source_book_id, bestseller_book_id, source_id, bestseller_source_id), row in zip(
        joined, rows, strict=True
    ):
        assert source_type == "BOOKS_COM_TW"
        assert source_url == row.url
        assert source_book_id == bestseller_book_id
        assert source_id == bestseller_source_id


def test_existing_urls_are_reused_without_detail_fetch_or_metadata_change(db_url):
    run(db_url, ranking_rows(100))
    before = query(db_url, "SELECT id, title, publisher, created_at, updated_at FROM books ORDER BY id")
    old_ids_by_url = dict(
        query(db_url, "SELECT source_url, book_id FROM book_sources WHERE source_type = 'BOOKS_COM_TW'")
    )

    # Second run: products 51..100 are already known, 101..150 are new. The drafts for the known
    # products carry different titles, so any accidental overwrite would be visible.
    rows = ranking_rows(100, offset=50)
    drafts = {
        row.url: make_draft(row.url, title="CHANGED TITLE" if row.url in old_ids_by_url else None)
        for row in rows
    }

    report, fetcher = run(db_url, rows, drafts)

    assert report.status == STATUS_SUCCESS
    assert (report.existing_book_count, report.new_book_count) == (50, 50)
    assert fetcher.detail_calls() == [product_url(n) for n in range(101, 151)]

    after = query(db_url, "SELECT id, title, publisher, created_at, updated_at FROM books ORDER BY id")
    assert set(before) <= set(after)
    assert count(db_url, "books") == 150
    assert query(db_url, "SELECT count(*) FROM books WHERE title = 'CHANGED TITLE'") == [(0,)]

    for rank, book_id, _source_id, _captured in bestsellers(db_url):
        url = rows[rank - 1].url
        if url in old_ids_by_url:
            assert book_id == old_ids_by_url[url]


def test_ranking_with_99_rows_fails_and_keeps_previous_bestsellers(db_url):
    run(db_url, ranking_rows(100))
    previous = bestsellers(db_url)
    books_before = count(db_url, "books")

    report, fetcher = run(db_url, ranking_rows(99, offset=1000))

    assert report.status == STATUS_FAILED
    assert report.exit_code == 1
    assert fetcher.detail_calls() == []
    assert bestsellers(db_url) == previous
    assert count(db_url, "books") == books_before


def test_duplicate_product_url_fails_and_keeps_previous_bestsellers(db_url):
    run(db_url, ranking_rows(100))
    previous = bestsellers(db_url)
    rows = ranking_rows(100, offset=1000)
    rows[1] = RankingRow(rank=2, url=rows[0].url)

    report, fetcher = run(db_url, rows)

    assert report.status == STATUS_FAILED
    assert fetcher.detail_calls() == []
    assert bestsellers(db_url) == previous


def test_new_book_detail_failure_fails_run_and_keeps_previous_bestsellers(db_url):
    run(db_url, ranking_rows(100))
    previous = bestsellers(db_url)
    rows = ranking_rows(100, offset=100)  # all new; rank 50 cannot be fetched
    failing_url = rows[49].url

    report, _fetcher = run(db_url, rows, failures={failing_url: FetchError("HTTP 500")})

    assert report.status == STATUS_FAILED
    assert report.exit_code == 1
    assert "HTTP 500" in report.error
    assert bestsellers(db_url) == previous
    # Books persisted before the failure keep their own transactions; the failing one does not exist.
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (failing_url,)) == [(0,)]


def test_isbn_already_owned_by_another_book_fails_the_run(db_url):
    isbn = normalize_isbn("978-0-306-40615-7")
    earlier_rows = ranking_rows(100)
    earlier_drafts = {row.url: make_draft(row.url) for row in earlier_rows}
    earlier_drafts[earlier_rows[0].url] = make_draft(earlier_rows[0].url, identifiers=(isbn,))
    setup, _ = run(db_url, earlier_rows, earlier_drafts)
    assert setup.status == STATUS_SUCCESS
    previous = bestsellers(db_url)

    # A new product (not yet known by URL) carrying the same ISBN must not become a second Book.
    rows = ranking_rows(100, offset=100)
    drafts = {row.url: make_draft(row.url) for row in rows}
    drafts[rows[0].url] = make_draft(rows[0].url, identifiers=(isbn,))

    report, _ = run(db_url, rows, drafts)

    assert report.status == STATUS_FAILED
    assert "already belongs to another Book" in report.error
    assert bestsellers(db_url) == previous
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (rows[0].url,)) == [(0,)]


def test_new_book_columns_match_data_model_with_nulls_for_missing_fields(db_url):
    rows = ranking_rows(100)
    full_url, minimal_url, language_url = rows[0].url, rows[1].url, rows[2].url
    isbn13 = normalize_isbn("978-0-306-40615-7")
    isbn10 = normalize_isbn("0-306-40615-2")
    drafts = {row.url: make_draft(row.url) for row in rows}
    drafts[full_url] = make_draft(
        full_url,
        title="完整書名",
        publisher="某某出版社",
        published_date=date(2026, 10, 11),
        published_date_precision="DAY",
        language=map_language("繁體中文"),
        description="內容簡介",
        table_of_contents="第一章 開始",
        page_count=320,
        thumbnail_url="https://img.example.test/cover.jpg",
        identifiers=(isbn13, isbn10),
        contributors=(
            Contributor(order=1, name="作者甲", role="AUTHOR"),
            Contributor(order=2, name="譯者乙", role="TRANSLATOR"),
        ),
        subjects=("文學", "小說"),
    )
    drafts[language_url] = make_draft(language_url, language=map_language("簡體中文"))

    report, _ = run(db_url, rows, drafts)
    assert report.status == STATUS_SUCCESS

    book_id = query(db_url, "SELECT book_id FROM book_sources WHERE source_url = %s", (full_url,))[0][0]
    book = query(
        db_url,
        """
        SELECT title, subtitle, publisher, published_date, published_date_precision, language,
               description, table_of_contents, page_count, thumbnail_url, created_at, updated_at
        FROM books WHERE id = %s
        """,
        (book_id,),
    )[0]
    assert book == (
        "完整書名", None, "某某出版社", date(2026, 10, 11), "DAY", "zh-TW",
        "內容簡介", "第一章 開始", 320, "https://img.example.test/cover.jpg", NOW, NOW,
    )
    assert query(
        db_url, "SELECT identifier_type, identifier_value FROM book_identifiers WHERE book_id = %s ORDER BY 1, 2", (book_id,)
    ) == [("ISBN_10", "0306406152"), ("ISBN_13", "9780306406157")]
    assert query(
        db_url,
        "SELECT contributor_order, name, role FROM book_contributors WHERE book_id = %s ORDER BY contributor_order",
        (book_id,),
    ) == [(1, "作者甲", "AUTHOR"), (2, "譯者乙", "TRANSLATOR")]
    assert query(
        db_url, "SELECT subject, source_type FROM book_subjects WHERE book_id = %s ORDER BY subject", (book_id,)
    ) == [("小說", "BOOKS_COM_TW"), ("文學", "BOOKS_COM_TW")]
    assert query(
        db_url,
        "SELECT source_type, external_id, first_seen_at, last_seen_at FROM book_sources WHERE source_url = %s",
        (full_url,),
    ) == [("BOOKS_COM_TW", None, NOW, NOW)]

    # Minimal book (title only): every optional column and related row is absent, nothing guessed.
    minimal_id = query(db_url, "SELECT book_id FROM book_sources WHERE source_url = %s", (minimal_url,))[0][0]
    assert query(
        db_url,
        """
        SELECT subtitle, publisher, published_date, published_date_precision, language,
               description, table_of_contents, page_count, thumbnail_url
        FROM books WHERE id = %s
        """,
        (minimal_id,),
    ) == [(None,) * 9]
    for table in ("book_identifiers", "book_contributors", "book_subjects"):
        assert query(db_url, f"SELECT count(*) FROM {table} WHERE book_id = %s", (minimal_id,)) == [(0,)]

    language_id = query(db_url, "SELECT book_id FROM book_sources WHERE source_url = %s", (language_url,))[0][0]
    assert query(db_url, "SELECT language FROM books WHERE id = %s", (language_id,)) == [("zh-CN",)]


def test_failed_snapshot_replacement_keeps_previous_list(db_url):
    run(db_url, ranking_rows(100))
    previous = bestsellers(db_url)
    sources = query(db_url, "SELECT rank, source_id FROM bestsellers ORDER BY rank")
    books = dict(query(db_url, "SELECT rank, book_id FROM bestsellers"))
    snapshot = [
        SnapshotRow(rank=rank, book_id=books[rank], source_id=source_id)
        for rank, source_id in sources
    ]
    # Rank 50 references a Book that does not exist: the INSERT fails after 49 rows were written.
    snapshot[49] = SnapshotRow(rank=50, book_id=uuid.uuid4(), source_id=sources[49][1])

    with psycopg.connect(db_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            db.replace_bestsellers(conn, snapshot, captured_at=datetime(2030, 1, 1, tzinfo=timezone.utc))

    assert bestsellers(db_url) == previous
