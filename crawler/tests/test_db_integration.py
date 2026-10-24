"""Integration tests: one crawler run against a throwaway PostgreSQL with the EF Core schema.

Fetcher and parsers are fakes; books.com.tw is never contacted.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime

import psycopg
import pytest

from books_crawler import db
from books_crawler.browser import PlaywrightFetcher
from books_crawler.fetcher import BrowserUnavailableError, FetchError
from books_crawler.models import Contributor, ContributorRole, RankingRow, RunStatus, SnapshotRow
from books_crawler.normalize import map_language, normalize_isbn
from books_crawler.parsers import RANKING_PAGE_URL, ParseError, RestrictedBookError
from books_crawler.run import RunDependencies, run_once
from tests.browser_fakes import FakeBrowserContext, launching
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

NOW = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 12, 4, 0, tzinfo=UTC)
RETRY_SLEEPS = [1.0, 2.0]  # the backoff between the three attempts of one row (crawler.md §13.1)


def query(url: str, sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def bestsellers(url: str) -> list[tuple]:
    return query(url, "SELECT rank, book_id, source_id, captured_at FROM bestsellers ORDER BY rank")


def count(url: str, table: str) -> int:
    return query(url, f"SELECT count(*) FROM {table}")[0][0]


def run(
    db_url,
    rows,
    drafts=None,
    failures=None,
    transient=None,
    now=NOW,
    sleep=None,
    fetcher=None,
    transient_parse=None,
):
    """Run one crawl with the given ranking rows; detail drafts default to title-only books.

    ``transient``: URL -> number of leading fetches that fail. ``transient_parse``: URL -> number of
    leading parses that raise ParseError. Returns ``(report, fetcher)``. Backoff sleeps go to
    ``sleep`` (a FakeSleep, never a real wait). Pass ``fetcher`` to use a different fetcher.
    """
    pages = {RANKING_PAGE_URL: RANKING_HTML, **{row.url: "<detail/>" for row in rows}}
    if drafts is None:
        drafts = {row.url: make_draft(row.url) for row in rows}
    if fetcher is None:
        fetcher = FakeFetcher(pages=pages, failures=failures, transient_failures=transient)
    parse = fake_detail_parser(drafts)
    if transient_parse:
        remaining = dict(transient_parse)
        inner = parse

        def parse(html, url):
            if remaining.get(url, 0) > 0:
                remaining[url] -= 1
                raise ParseError(f"title (h1) not found in the product container of {url} (simulated)")
            return inner(html, url)

    deps = RunDependencies(
        fetcher=fetcher,
        parse_ranking=fake_ranking_parser(rows),
        parse_detail=parse,
        connect=lambda: db.connect(db_url),
        clock=lambda: now,
        sleep=sleep if sleep is not None else FakeSleep(),
    )
    return run_once(deps), fetcher


def skipped_ranks(report) -> list[int]:
    return [item.rank for item in report.skipped]


def _seed_with_identifiers(db_url, identifiers_by_rank: dict[int, tuple]):
    """Run 1: 100 products (urls 1..100); the given ranks carry the given identifiers."""
    rows = ranking_rows(100)
    drafts = {row.url: make_draft(row.url) for row in rows}
    for rank, identifiers in identifiers_by_rank.items():
        url = rows[rank - 1].url
        drafts[url] = make_draft(url, title=f"Original rank {rank}", publisher="Original publisher", identifiers=identifiers)
    report, _ = run(db_url, rows, drafts)
    assert report.status is RunStatus.SUCCESS, report.error
    return report


def test_full_ranking_success_writes_100_bestsellers(db_url):
    rows = ranking_rows(100)

    report, fetcher = run(db_url, rows)

    assert report.status is RunStatus.SUCCESS
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
    for (rank, source_type, source_url, source_book_id, bestseller_book_id, source_id, bestseller_source_id), row in zip(joined, rows, strict=True):
        assert source_type == "BOOKS_COM_TW"
        assert source_url == row.url
        assert source_book_id == bestseller_book_id
        assert source_id == bestseller_source_id


def test_existing_urls_are_reused_without_detail_fetch_or_metadata_change(db_url):
    run(db_url, ranking_rows(100))
    before = query(db_url, "SELECT id, title, publisher, created_at, updated_at FROM books ORDER BY id")
    old_ids_by_url = dict(query(db_url, "SELECT source_url, book_id FROM book_sources WHERE source_type = 'BOOKS_COM_TW'"))

    # Second run: products 51..100 are already known, 101..150 are new. The drafts for the known
    # products carry different titles, so any accidental overwrite would be visible.
    rows = ranking_rows(100, offset=50)
    drafts = {row.url: make_draft(row.url, title="CHANGED TITLE" if row.url in old_ids_by_url else None) for row in rows}

    report, fetcher = run(db_url, rows, drafts)

    assert report.status is RunStatus.SUCCESS
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

    assert report.status is RunStatus.FAILED
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

    assert report.status is RunStatus.FAILED
    assert fetcher.detail_calls() == []
    assert bestsellers(db_url) == previous


def test_three_persistently_failing_new_books_are_skipped_and_ranks_keep_their_numbers(db_url):
    run(db_url, ranking_rows(100))  # previous list: products 1..100
    rows = ranking_rows(100, offset=100)  # all new
    failing_ranks = {10, 50, 90}
    failures = {rows[rank - 1].url: FetchError("HTTP 500") for rank in failing_ranks}
    sleep = FakeSleep()

    report, fetcher = run(db_url, rows, failures=failures, sleep=sleep)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.exit_code == 0
    assert (report.ranking_count, report.new_book_count, report.skipped_count) == (100, 97, 3)
    assert skipped_ranks(report) == [10, 50, 90]
    for item in report.skipped:
        assert (item.failure.error_type, item.failure.attempts, item.url) == ("fetch_error", 3, rows[item.rank - 1].url)
        assert "HTTP 500" in item.failure.error_message
        assert fetcher.calls.count(item.url) == 3
    assert sleep.calls == RETRY_SLEEPS * 3

    snapshot = bestsellers(db_url)
    assert [row[0] for row in snapshot] == [rank for rank in range(1, 101) if rank not in failing_ranks]
    assert len(snapshot) == 97
    for rank, book_id, _source_id, captured_at in snapshot:
        assert captured_at == NOW
    for rank in failing_ranks:
        assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (rows[rank - 1].url,)) == [(0,)]


def test_detail_failing_twice_then_succeeding_writes_the_book_normally(db_url):
    rows = ranking_rows(100, offset=100)
    sleep = FakeSleep()

    report, fetcher = run(db_url, rows, transient={rows[0].url: 2}, sleep=sleep)

    assert report.status is RunStatus.SUCCESS
    assert report.skipped == []
    assert fetcher.calls.count(rows[0].url) == 3
    assert sleep.calls == RETRY_SLEEPS
    assert len(bestsellers(db_url)) == 100
    assert query(db_url, "SELECT title FROM books WHERE id = (SELECT book_id FROM bestsellers WHERE rank = 1)") == [("Book " + rows[0].url.rsplit("/", 1)[-1],)]


def test_book_transaction_failing_twice_then_succeeding_writes_the_book_normally(db_url, monkeypatch):
    rows = ranking_rows(100, offset=100)
    target = rows[0].url
    real_persist = db.persist_new_source
    attempts = {"count": 0}

    def flaky_persist(conn, draft, now, attach_to_book_id=None):
        if draft.source_url == target:
            attempts["count"] += 1
            if attempts["count"] <= 2:
                raise psycopg.OperationalError("simulated connection drop inside the Book transaction")
        return real_persist(conn, draft, now, attach_to_book_id=attach_to_book_id)

    monkeypatch.setattr(db, "persist_new_source", flaky_persist)
    sleep = FakeSleep()

    report, fetcher = run(db_url, rows, sleep=sleep)

    assert report.status is RunStatus.SUCCESS
    assert attempts["count"] == 3  # two failed writes, then the write that succeeds
    assert fetcher.calls.count(target) == 1  # only the write was retried: the detail page was fetched once
    assert sleep.calls == RETRY_SLEEPS
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (target,)) == [(1,)]
    assert count(db_url, "books") == 100


def test_detail_page_is_fetched_once_when_database_writes_fail_three_times(db_url):
    rows = ranking_rows(100, offset=100)
    failing = rows[2]
    # The over-long contributor name (varchar(255)) makes every write of this draft fail.
    failing_draft = make_draft(failing.url, contributors=(Contributor(order=1, name="甲" * 300, role=ContributorRole.AUTHOR),))
    drafts = {row.url: make_draft(row.url) for row in rows}
    drafts[failing.url] = failing_draft
    sleep = FakeSleep()

    report, fetcher = run(db_url, rows, drafts, sleep=sleep)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert skipped_ranks(report) == [3]
    skipped = report.skipped[0]
    assert (skipped.failure.error_type, skipped.failure.attempts) == ("database_error", 3)
    assert fetcher.calls.count(failing.url) == 1  # the same parsed draft was written three times
    assert sleep.calls == RETRY_SLEEPS


def test_detail_page_fetch_is_retried_when_the_parse_fails_at_first(db_url):
    rows = ranking_rows(100, offset=100)
    target = rows[0].url
    sleep = FakeSleep()

    report, fetcher = run(db_url, rows, sleep=sleep, transient_parse={target: 1})

    assert report.status is RunStatus.SUCCESS
    assert fetcher.calls.count(target) == 2  # a parse failure is retried from the detail request
    assert sleep.calls == [1.0]
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (target,)) == [(1,)]


def test_fetch_retry_that_reaches_a_restricted_page_is_skipped_as_restricted_after_two_attempts(db_url):
    rows = ranking_rows(100, offset=100)
    target = rows[0].url
    fetcher = FakeFetcher(
        pages={RANKING_PAGE_URL: RANKING_HTML, **{row.url: "<detail/>" for row in rows}},
        transient_failures={target: 1},
    )

    def parse(html, url):
        if url == target:
            raise RestrictedBookError("restricted product requires member login")
        return make_draft(url)

    sleep = FakeSleep()
    deps = RunDependencies(
        fetcher,
        fake_ranking_parser(rows),
        parse,
        lambda: db.connect(db_url),
        clock=lambda: NOW,
        sleep=sleep,
    )

    report = run_once(deps)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert skipped_ranks(report) == [1]
    failure = report.skipped[0].failure
    assert (failure.error_type, failure.attempts) == ("restricted_book", 2)
    assert fetcher.calls.count(target) == 2  # attempt 1 failed to fetch; attempt 2 reached the restricted page
    assert sleep.calls == [1.0]  # one backoff: before attempt 2, none after the restricted outcome
    assert (report.restricted_book_count, report.error_count) == (1, 0)
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (target,)) == [(0,)]


def test_write_retry_that_finds_an_isbn_used_by_an_earlier_rank_is_skipped_as_duplicate_after_two_attempts(db_url, monkeypatch):
    isbn = normalize_isbn("978-0-306-40615-7")
    _seed_with_identifiers(db_url, {1: (isbn,)})  # Book A carries the ISBN and is used by rank 1 below
    rows = [RankingRow(rank=1, url=product_url(1)), RankingRow(rank=2, url=product_url(201))] + [
        RankingRow(rank=rank, url=product_url(200 + rank)) for rank in range(3, 101)
    ]
    drafts = {row.url: make_draft(row.url) for row in rows}
    drafts[product_url(201)] = make_draft(product_url(201), identifiers=(isbn,))
    real_find = db.find_book_by_isbn
    failed = {"once": False}

    def flaky_find(conn, identifiers):
        # The first DB call of rank 2's write step fails; the retry's ISBN lookup then succeeds.
        if identifiers == (isbn,) and not failed["once"]:
            failed["once"] = True
            raise psycopg.OperationalError("simulated connection drop during the ISBN lookup")
        return real_find(conn, identifiers)

    monkeypatch.setattr(db, "find_book_by_isbn", flaky_find)
    sleep = FakeSleep()

    report, fetcher = run(db_url, rows, drafts, sleep=sleep)

    assert failed["once"]
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert skipped_ranks(report) == [2]
    failure = report.skipped[0].failure
    assert (failure.error_type, failure.attempts) == ("duplicate_book_in_ranking", 2)
    assert fetcher.calls.count(product_url(201)) == 1  # the write is retried with the parsed draft, not refetched
    assert sleep.calls == [1.0]
    # The Catalog side is committed before the ledger decides DUPLICATE_BOOK (crawler.md §14.2).
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (product_url(201),)) == [(1,)]


# ---------------------------------------------------------------------------
# ISBN attach policy (crawler.md §6.3, data-model §6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw_isbn", ["978-0-306-40615-7", "0-306-40615-2"], ids=["isbn13", "isbn10"])
def test_new_source_with_known_isbn_attaches_to_existing_book(db_url, caplog, raw_isbn):
    caplog.set_level(logging.INFO, logger="books_crawler")
    isbn = normalize_isbn(raw_isbn)
    _seed_with_identifiers(db_url, {1: (isbn,)})
    existing = query(
        db_url,
        """
        SELECT b.id, b.title, b.publisher, b.created_at, b.updated_at
        FROM books b JOIN book_sources s ON s.book_id = b.id WHERE s.source_url = %s
        """,
        (product_url(1),),
    )[0]
    existing_book_id = existing[0]
    books_before = count(db_url, "books")
    identifiers_before = query(db_url, "SELECT identifier_type, identifier_value FROM book_identifiers WHERE book_id = %s", (existing_book_id,))

    # Run 2: ranks 2..100 are known products; rank 1 is a product never seen before with the same ISBN.
    rows = [RankingRow(rank=1, url=product_url(101))] + [RankingRow(rank=rank, url=product_url(rank)) for rank in range(2, 101)]
    drafts = {row.url: make_draft(row.url) for row in rows}
    drafts[product_url(101)] = make_draft(product_url(101), title="Other edition title", publisher="Other publisher", identifiers=(isbn,))

    report, fetcher = run(db_url, rows, drafts)

    assert report.status is RunStatus.SUCCESS
    assert report.attached_source_count == 1
    assert product_url(101) in fetcher.detail_calls()  # the new product's detail page was fetched
    assert count(db_url, "books") == books_before  # no new Book was created
    assert query(db_url, "SELECT id, title, publisher, created_at, updated_at FROM books WHERE id = %s", (existing_book_id,)) == [existing]
    assert query(db_url, "SELECT identifier_type, identifier_value FROM book_identifiers WHERE book_id = %s", (existing_book_id,)) == identifiers_before
    assert query(
        db_url,
        "SELECT book_id, source_type, external_id, first_seen_at, last_seen_at FROM book_sources WHERE source_url = %s",
        (product_url(101),),
    ) == [(existing_book_id, "BOOKS_COM_TW", None, NOW, NOW)]

    new_source_id = query(db_url, "SELECT id FROM book_sources WHERE source_url = %s", (product_url(101),))[0][0]
    rank_one = bestsellers(db_url)[0]
    assert rank_one[0] == 1
    assert rank_one[1] == existing_book_id  # bestseller points at the existing Book...
    assert rank_one[2] == new_source_id  # ...through the new BOOKS_COM_TW source
    assert "attached BOOKS_COM_TW source to existing Book" in caplog.text


def test_isbn13_match_takes_priority_over_isbn10_match(db_url):
    isbn13 = normalize_isbn("978-0-306-40615-7")
    isbn10_of_other = normalize_isbn("080442957X")
    _seed_with_identifiers(db_url, {1: (isbn13,), 2: (isbn10_of_other,)})
    book_a = query(db_url, "SELECT book_id FROM book_sources WHERE source_url = %s", (product_url(1),))[0][0]

    rows = [RankingRow(rank=1, url=product_url(101))] + [RankingRow(rank=rank, url=product_url(rank)) for rank in range(2, 101)]
    drafts = {row.url: make_draft(row.url) for row in rows}
    # The new source carries the ISBN-10 of book B (rank 2) and the ISBN-13 of book A (rank 1).
    drafts[product_url(101)] = make_draft(product_url(101), identifiers=(isbn10_of_other, isbn13))

    report, _ = run(db_url, rows, drafts)

    assert report.status is RunStatus.SUCCESS
    assert bestsellers(db_url)[0][1] == book_a


def test_existing_url_then_new_source_with_same_isbn_skips_the_later_rank(db_url):
    isbn = normalize_isbn("978-0-306-40615-7")
    _seed_with_identifiers(db_url, {1: (isbn,)})
    book_a = query(db_url, "SELECT book_id FROM book_sources WHERE source_url = %s", (product_url(1),))[0][0]
    books_before = count(db_url, "books")
    sleep = FakeSleep()

    # Rank 1 is a known source (Book A). Rank 2 is a new source whose ISBN also belongs to Book A.
    rows = [RankingRow(rank=1, url=product_url(1)), RankingRow(rank=2, url=product_url(201))] + [
        RankingRow(rank=rank, url=product_url(200 + rank)) for rank in range(3, 101)
    ]
    drafts = {row.url: make_draft(row.url) for row in rows}
    drafts[product_url(201)] = make_draft(product_url(201), identifiers=(isbn,))

    report, fetcher = run(db_url, rows, drafts, sleep=sleep)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.exit_code == 0
    assert skipped_ranks(report) == [2]
    skipped = report.skipped[0]
    # Rank 2 is a new product: its ISBN is found only after the detail page was read, so one attempt.
    assert (skipped.failure.error_type, skipped.failure.attempts) == ("duplicate_book_in_ranking", 1)
    assert "rank 1" in skipped.failure.error_message
    assert fetcher.calls.count(product_url(201)) == 1  # the ISBN source is fetched once, never retried
    assert sleep.calls == []
    # Ranks 3..100 are new products (98 Books); the skipped rank 2 must not create or attach anything.
    assert count(db_url, "books") == books_before + 98
    # The Catalog side of rank 2 is committed (attached to Book A); the ledger only skips the rank.
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (product_url(201),)) == [(1,)]
    snapshot = bestsellers(db_url)
    assert [row[0] for row in snapshot] == [rank for rank in range(1, 101) if rank != 2]
    assert snapshot[0][1] == book_a  # the earlier rank keeps the Book


def test_new_source_then_existing_url_for_same_book_skips_the_later_rank(db_url):
    isbn = normalize_isbn("978-0-306-40615-7")
    _seed_with_identifiers(db_url, {1: (isbn,)})
    book_a = query(db_url, "SELECT book_id FROM book_sources WHERE source_url = %s", (product_url(1),))[0][0]

    # Rank 1 is a new source attached to Book A by ISBN. Rank 2 is the known source of Book A.
    rows = [RankingRow(rank=1, url=product_url(201)), RankingRow(rank=2, url=product_url(1))] + [
        RankingRow(rank=rank, url=product_url(rank)) for rank in range(3, 101)
    ]
    drafts = {row.url: make_draft(row.url) for row in rows}
    drafts[product_url(201)] = make_draft(product_url(201), identifiers=(isbn,))

    report, fetcher = run(db_url, rows, drafts)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert skipped_ranks(report) == [2]
    assert report.skipped[0].failure.error_type == "duplicate_book_in_ranking"
    assert product_url(1) not in fetcher.detail_calls()
    snapshot = bestsellers(db_url)
    attached_source = query(db_url, "SELECT id FROM book_sources WHERE source_url = %s", (product_url(201),))[0][0]
    assert snapshot[0][:3] == (1, book_a, attached_source)  # the earlier rank keeps Book A via the new source
    assert [row[0] for row in snapshot] == [rank for rank in range(1, 101) if rank != 2]


def test_two_new_sources_sharing_an_isbn_skip_the_later_rank(db_url):
    isbn = normalize_isbn("978-0-306-40615-7")
    _seed_with_identifiers(db_url, {})

    # Ranks 1 and 2 are both new. Rank 1 creates a Book with the ISBN; rank 2 would attach to it.
    rows = [RankingRow(rank=1, url=product_url(101)), RankingRow(rank=2, url=product_url(102))] + [
        RankingRow(rank=rank, url=product_url(rank)) for rank in range(3, 101)
    ]
    drafts = {row.url: make_draft(row.url) for row in rows}
    drafts[product_url(101)] = make_draft(product_url(101), identifiers=(isbn,))
    drafts[product_url(102)] = make_draft(product_url(102), identifiers=(isbn,))

    report, fetcher = run(db_url, rows, drafts)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert skipped_ranks(report) == [2]
    assert report.skipped[0].failure.error_type == "duplicate_book_in_ranking"
    # The duplicate is only detected after the detail page was read, so the one attempt is recorded.
    assert report.skipped[0].failure.attempts == 1
    assert fetcher.calls.count(product_url(102)) == 1
    # The Catalog side is committed (the source is attached to the Book of rank 1); only the rank is skipped.
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (product_url(102),)) == [(1,)]
    snapshot = bestsellers(db_url)
    assert [row[0] for row in snapshot] == [rank for rank in range(1, 101) if rank != 2]
    assert snapshot[0][1] == query(db_url, "SELECT book_id FROM book_sources WHERE source_url = %s", (product_url(101),))[0][0]


# ---------------------------------------------------------------------------
# Writes inside one source's transaction (crawler.md §9)
# ---------------------------------------------------------------------------


def test_failed_book_transaction_is_rolled_back_retried_and_skipped_while_others_are_unaffected(db_url):
    _seed_with_identifiers(db_url, {})
    rows = ranking_rows(100, offset=100)  # all new: rank 5 fails in every attempt
    failing_url = rows[4].url
    isbn = normalize_isbn("9786267859506")
    drafts = {row.url: make_draft(row.url) for row in rows}
    # The identifier is written first; the over-long contributor name (varchar(255)) then fails.
    drafts[failing_url] = make_draft(
        failing_url,
        title="Rolled back book",
        identifiers=(isbn,),
        contributors=(Contributor(order=1, name="甲" * 300, role=ContributorRole.AUTHOR),),
    )
    sleep = FakeSleep()

    report, fetcher = run(db_url, rows, drafts, sleep=sleep)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.exit_code == 0
    assert skipped_ranks(report) == [5]
    skipped = report.skipped[0]
    assert (skipped.failure.error_type, skipped.failure.attempts, skipped.url) == ("database_error", 3, failing_url)
    assert "too long" in skipped.failure.error_message
    assert fetcher.calls.count(failing_url) == 1  # the write is retried with the same draft, not the page
    assert sleep.calls == RETRY_SLEEPS  # the only failing row: one backoff sequence
    snapshot = bestsellers(db_url)
    assert [row[0] for row in snapshot] == [rank for rank in range(1, 101) if rank != 5]
    assert count(db_url, "books") == 100 + 99  # seeded 100, plus every other new Book; rank 5 wrote nothing
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (failing_url,)) == [(0,)]
    assert query(db_url, "SELECT count(*) FROM books WHERE title = 'Rolled back book'") == [(0,)]
    assert query(db_url, "SELECT count(*) FROM book_identifiers WHERE identifier_value = %s", (isbn.identifier_value,)) == [(0,)]


# ---------------------------------------------------------------------------
# Language codes through the DB path (data-model §2.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label, code",
    [("英文", "en"), ("日文", "ja"), ("韓文", "ko"), ("繁體中文", "zh-TW"), ("簡體中文", "zh-CN")],
)
def test_language_code_is_written_to_books(db_url, label, code):
    assert map_language(label) == code
    url = product_url(7777)
    with db.connect(db_url) as conn:
        ref = db.persist_new_source(conn, make_draft(url, language=map_language(label)), NOW)

    assert query(db_url, "SELECT language FROM books WHERE id = %s", (ref.book_id,)) == [(code,)]


# ---------------------------------------------------------------------------
# Atomic bestseller replacement
# ---------------------------------------------------------------------------


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
    assert report.status is RunStatus.SUCCESS

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
        "完整書名",
        None,
        "某某出版社",
        date(2026, 10, 11),
        "DAY",
        "zh-TW",
        "內容簡介",
        "第一章 開始",
        320,
        "https://img.example.test/cover.jpg",
        NOW,
        NOW,
    )
    assert query(db_url, "SELECT identifier_type, identifier_value FROM book_identifiers WHERE book_id = %s ORDER BY 1, 2", (book_id,)) == [
        ("ISBN_10", "0306406152"),
        ("ISBN_13", "9780306406157"),
    ]
    assert query(
        db_url,
        "SELECT contributor_order, name, role FROM book_contributors WHERE book_id = %s ORDER BY contributor_order",
        (book_id,),
    ) == [(1, "作者甲", "AUTHOR"), (2, "譯者乙", "TRANSLATOR")]
    assert query(db_url, "SELECT subject, source_type FROM book_subjects WHERE book_id = %s ORDER BY subject", (book_id,)) == [
        ("小說", "BOOKS_COM_TW"),
        ("文學", "BOOKS_COM_TW"),
    ]
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


def test_failed_snapshot_replacement_keeps_previous_list_and_last_seen(db_url):
    run(db_url, ranking_rows(100))
    previous = bestsellers(db_url)
    sources_before = query(db_url, "SELECT id, last_seen_at FROM book_sources ORDER BY id")
    sources = query(db_url, "SELECT rank, source_id FROM bestsellers ORDER BY rank")
    books = dict(query(db_url, "SELECT rank, book_id FROM bestsellers"))
    snapshot = [SnapshotRow(rank=rank, book_id=books[rank], source_id=source_id) for rank, source_id in sources]
    # Rank 50 repeats rank 49's Book and source: it passes the source check, but the schema's unique
    # bestsellers.book_id makes the INSERT fail after 49 rows were written.
    snapshot[49] = SnapshotRow(rank=50, book_id=books[49], source_id=sources[48][1])

    with psycopg.connect(db_url, autocommit=True) as conn, pytest.raises(psycopg.errors.UniqueViolation):
        db.replace_bestsellers(conn, snapshot, captured_at=LATER)

    assert bestsellers(db_url) == previous
    assert query(db_url, "SELECT id, last_seen_at FROM book_sources ORDER BY id") == sources_before


@pytest.mark.parametrize("case", ["another_books_source", "google_books_source", "missing_source"])
def test_replacement_rejects_a_source_that_is_not_the_books_own_books_com_tw_source(db_url, case):
    """crawler.md §14.4: checked inside the replacement transaction, before the current list is deleted."""
    run(db_url, ranking_rows(100))
    previous = bestsellers(db_url)
    snapshot = [SnapshotRow(rank=rank, book_id=book_id, source_id=source_id) for rank, book_id, source_id, _ in previous]
    target = snapshot[4]
    if case == "another_books_source":
        bad_source = snapshot[5].source_id
    else:
        bad_source = uuid.uuid4()
    if case == "google_books_source":
        query(
            db_url,
            """
            INSERT INTO book_sources (id, book_id, source_type, external_id, source_url, first_seen_at, last_seen_at)
            VALUES (%s, %s, 'GOOGLE_BOOKS', 'volume-1', 'https://books.google.com/books?id=volume-1', %s, %s)
            RETURNING id
            """,
            (bad_source, target.book_id, NOW, NOW),
        )
    sources_before = query(db_url, "SELECT id, last_seen_at FROM book_sources ORDER BY id")
    snapshot[4] = SnapshotRow(rank=5, book_id=target.book_id, source_id=bad_source)

    with (
        db.connect(db_url) as conn,
        pytest.raises(
            db.SnapshotValidationError,
            match=f"rank 5: source {bad_source} is not a BOOKS_COM_TW source of Book {target.book_id}",
        ),
    ):
        db.replace_bestsellers(conn, snapshot, captured_at=LATER)

    assert bestsellers(db_url) == previous
    assert query(db_url, "SELECT id, last_seen_at FROM book_sources ORDER BY id") == sources_before


def test_an_empty_snapshot_still_replaces_the_list(db_url):
    """crawler.md §14.4: no minimum row count, even when every rank was skipped."""
    run(db_url, ranking_rows(100), now=NOW)
    seen_before = query(db_url, "SELECT id, last_seen_at FROM book_sources ORDER BY id")

    with db.connect(db_url) as conn:
        db.replace_bestsellers(conn, [], captured_at=LATER)

    assert bestsellers(db_url) == []
    assert query(db_url, "SELECT id, last_seen_at FROM book_sources ORDER BY id") == seen_before


# ---------------------------------------------------------------------------
# last_seen_at on Book Sources (Q2): source metadata, set only by a successful run
# ---------------------------------------------------------------------------


def test_existing_source_last_seen_advances_on_success_and_book_is_untouched(db_url):
    run(db_url, ranking_rows(100), now=NOW)
    book_before = query(db_url, "SELECT id, title, updated_at FROM books ORDER BY id")

    # Run 2 (a day later): products 51..100 are known, 101..150 are new.
    report, fetcher = run(db_url, ranking_rows(100, offset=50), now=LATER)

    assert report.status is RunStatus.SUCCESS
    assert fetcher.detail_calls() == [product_url(n) for n in range(101, 151)]
    for number in range(51, 101):
        assert query(db_url, "SELECT first_seen_at, last_seen_at FROM book_sources WHERE source_url = %s", (product_url(number),)) == [(NOW, LATER)], number
    for number in range(101, 151):
        assert query(db_url, "SELECT first_seen_at, last_seen_at FROM book_sources WHERE source_url = %s", (product_url(number),)) == [(LATER, LATER)], number
    book_after = query(db_url, "SELECT id, title, updated_at FROM books ORDER BY id")
    assert set(book_before) <= set(book_after)  # Book rows are unchanged; only Book Source rows moved


def test_failed_run_leaves_last_seen_unchanged(db_url):
    run(db_url, ranking_rows(100), now=NOW)
    seen_before = query(db_url, "SELECT source_url, last_seen_at FROM book_sources ORDER BY source_url")

    report, _ = run(db_url, ranking_rows(99, offset=0), now=LATER)

    assert report.status is RunStatus.FAILED
    assert query(db_url, "SELECT source_url, last_seen_at FROM book_sources ORDER BY source_url") == seen_before


# ---------------------------------------------------------------------------
# Consecutive error threshold (crawler.md §13.1, §14.3; CRAWL-05) and run log (crawler.md §19.2)
# ---------------------------------------------------------------------------


# The streak and status rules themselves are covered in test_ledger.py; these cases check what only
# a real run against the database shows: what an abort leaves behind, and that scattered errors
# still replace the list.
@pytest.mark.parametrize(
    "failing_ranks, expected_status, abort_rank",
    [
        (set(range(1, 22)), RunStatus.FAILED, 21),  # early abort: later ranks are never requested
        (set(range(80, 101)), RunStatus.FAILED, 100),  # late abort: books committed before it stay
        (set(range(1, 101, 2)), RunStatus.PARTIAL_SUCCESS, None),  # 50 scattered errors still replace
    ],
)
def test_abort_keeps_previous_data_and_scattered_errors_still_replace(db_url, caplog, failing_ranks, expected_status, abort_rank):
    caplog.set_level(logging.INFO, logger="books_crawler")
    run(db_url, ranking_rows(), now=NOW)
    previous = bestsellers(db_url)
    seen_before = query(db_url, "SELECT source_url, last_seen_at FROM book_sources ORDER BY source_url")
    rows = ranking_rows(offset=100)
    failures = {row.url: FetchError("HTTP 500") for row in rows if row.rank in failing_ranks}

    report, fetcher = run(db_url, rows, failures=failures, now=LATER)

    assert report.status is expected_status
    assert report.exit_code == (1 if abort_rank else 0)
    assert report.aborted_at_rank == abort_rank
    processed = abort_rank or 100
    expected_errors = sorted(rank for rank in failing_ranks if rank <= processed)
    assert skipped_ranks(report) == expected_errors
    assert report.error_count == len(expected_errors)
    assert all(fetcher.calls.count(rows[rank - 1].url) == 3 for rank in expected_errors)
    assert not any(row.url in fetcher.calls for row in rows[processed:])
    if abort_rank:
        assert report.consecutive_error_count == 21
        assert bestsellers(db_url) == previous
        old_urls = [item[0] for item in seen_before]
        assert query(db_url, "SELECT source_url, last_seen_at FROM book_sources WHERE source_url = ANY(%s) ORDER BY source_url", (old_urls,)) == seen_before
        assert f"aborted_at_rank={abort_rank}" in caplog.text
        assert report.error.startswith(f"run aborted at rank {abort_rank} after 21 consecutive error(s) (limit 20): fetch_error: ")
        # One ERROR line per failed run, with the same prefix as every other failure (crawler.md §14.6).
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == [f"run failed: {report.error}"]
        # Successfully committed new books before a late abort remain in Catalog.
        assert count(db_url, "books") == 100 + processed - len(expected_errors)
    else:
        assert [item[0] for item in bestsellers(db_url)] == [rank for rank in range(1, 101) if rank not in failing_ranks]
        assert {item[3] for item in bestsellers(db_url)} == {LATER}


def test_each_restricted_page_is_requested_once_and_leaves_a_gap(db_url):
    rows = ranking_rows()
    restricted = {row.url for row in rows if row.rank in {3, 4, 5, 50, 100}}
    fetcher = FakeFetcher(pages={RANKING_PAGE_URL: RANKING_HTML, **{row.url: "<detail/>" for row in rows}})

    def parse(html, url):
        if url in restricted:
            raise RestrictedBookError("restricted product requires member login")
        return make_draft(url)

    sleep = FakeSleep()
    deps = RunDependencies(fetcher, fake_ranking_parser(rows), parse, lambda: db.connect(db_url), clock=lambda: NOW, sleep=sleep)
    report = run_once(deps)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert (report.restricted_book_count, report.error_count) == (5, 0)
    assert all(fetcher.calls.count(url) == 1 for url in restricted)
    assert all(item.failure.attempts == 1 for item in report.skipped)
    assert sleep.calls == []  # no retry backoff
    assert [row[0] for row in bestsellers(db_url)] == [rank for rank in range(1, 101) if rank not in {3, 4, 5, 50, 100}]
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = ANY(%s)", (list(restricted),)) == [(0,)]


def test_eventual_success_after_retries_resets_twenty_errors(db_url):
    rows = ranking_rows()
    failing_ranks = set(range(1, 21)) | set(range(22, 42))
    failures = {row.url: FetchError("HTTP 500") for row in rows if row.rank in failing_ranks}
    report, fetcher = run(db_url, rows, failures=failures, transient={rows[20].url: 2})
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.error_count == 40
    assert report.aborted_at_rank is None
    assert fetcher.calls.count(rows[20].url) == 3
    assert count(db_url, "bestsellers") == 60


def test_run_log_has_the_required_fields_and_no_database_url(db_url, caplog):
    caplog.set_level(logging.INFO, logger="books_crawler")
    rows = ranking_rows(offset=100)
    failures = {rows[4].url: FetchError("HTTP 500")}

    report, _ = run(db_url, rows, failures=failures)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    summary = [record.getMessage() for record in caplog.records if "run_id=" in record.getMessage()]
    assert len(summary) == 1
    line = summary[0]
    for expected in (
        f"run_id={report.run_id}",
        "started_at=",
        "finished_at=",
        "status=PARTIAL_SUCCESS",
        "provider_code=BOOKS_COM_TW",
        "job_name=daily-bestseller",
        "ranking_count=100",
        "items_seen=100",
        "existing_book_count=0",
        "new_book_count=99",
        "attached_source_count=0",
        "existing_source_count=0",
        "new_source_count=99",
        "skipped_count=1",
        "error_count=1",
        "consecutive_error_count=0",
        '"rank": 5',
        f'"url": "{rows[4].url}"',
        '"error_type": "fetch_error"',
        '"attempts": 3',
    ):
        assert expected in line, expected
    assert db_url not in caplog.text
    assert "crawler_test:crawler_test@" not in caplog.text


# ---------------------------------------------------------------------------
# Early abort, browser failures, and redaction (crawler.md §12.1, §14.3, §19.3; code review A1/A3/D3/D15)
# ---------------------------------------------------------------------------


def test_browser_crash_during_navigation_is_retried_and_the_row_is_written(db_url):
    rows = ranking_rows(100, offset=100)
    target = rows[0].url
    pages = {RANKING_PAGE_URL: RANKING_HTML, **{row.url: "<detail/>" for row in rows}}
    context = FakeBrowserContext(pages=pages, goto_failures={target: 2})  # two crashes, then the page loads
    fetcher = PlaywrightFetcher(delay_seconds=0, launch=launching(context))  # no real browser starts
    sleep = FakeSleep()
    try:
        report, _ = run(db_url, rows, sleep=sleep, fetcher=fetcher)
    finally:
        fetcher.close()

    assert report.status is RunStatus.SUCCESS
    assert context.goto_calls.count(target) == 3
    assert sleep.calls == RETRY_SLEEPS
    assert context.open_pages == 0  # every page was closed, including the ones that crashed
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (target,)) == [(1,)]


def test_browser_unavailable_on_a_detail_page_fails_the_run_without_retry_or_skip(db_url):
    run(db_url, ranking_rows(100))
    previous = bestsellers(db_url)
    rows = ranking_rows(100, offset=100)
    sleep = FakeSleep()

    report, fetcher = run(db_url, rows, failures={rows[0].url: BrowserUnavailableError("no chromium")}, sleep=sleep)

    assert report.status is RunStatus.FAILED
    assert "BrowserUnavailableError" in report.error
    assert fetcher.calls.count(rows[0].url) == 1  # an environment problem is not retried
    assert sleep.calls == []
    assert report.skipped == []  # and it is not a per-book skip
    assert bestsellers(db_url) == previous


def test_database_error_text_with_a_connection_string_never_reaches_the_log_or_report(db_url, caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="books_crawler")
    rows = ranking_rows(100, offset=100)
    target = rows[0].url
    secret_error = "could not connect to postgresql://app_user:pw-s3cret@db.internal:5432/books password=pw-s3cret"
    real_persist = db.persist_new_source

    def failing_persist(conn, draft, now, attach_to_book_id=None):
        if draft.source_url == target:
            raise psycopg.OperationalError(secret_error)
        return real_persist(conn, draft, now, attach_to_book_id=attach_to_book_id)

    monkeypatch.setattr(db, "persist_new_source", failing_persist)

    report, _ = run(db_url, rows)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.skipped[0].failure.error_type == "database_error"
    for text in (caplog.text, report.skipped[0].failure.error_message, report.error or ""):
        assert "pw-s3cret" not in text
        assert "app_user:pw" not in text
        assert "db.internal" not in text
    assert "postgresql://<redacted>" in caplog.text
    assert db_url not in caplog.text
