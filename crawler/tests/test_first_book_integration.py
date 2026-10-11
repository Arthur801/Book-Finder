"""Real parsers + disposable PostgreSQL; no requests to books.com.tw."""

from datetime import datetime, timezone

from books_crawler import db
from books_crawler.models import RunStatus, SnapshotRow
from books_crawler.parsers import RANKING_PAGE_URL, parse_detail_html, parse_ranking_html
from books_crawler.run import RunDependencies, run_first_book
from tests.fakes import FakeFetcher, FakeSleep, RANKING_FIXTURE, fixture_html, make_draft, product_url


def test_first_book_real_fixture_is_persisted_idempotently_without_changing_snapshot(db_url):
    now = datetime.now(timezone.utc)
    with db.connect(db_url) as conn:
        previous = [db.persist_new_source(conn, make_draft(product_url(9000000000 + rank)), now)
                    for rank in range(1, 101)]
        db.replace_bestsellers(conn, [SnapshotRow(rank, ref.book_id, ref.source_id)
                                     for rank, ref in enumerate(previous, 1)], now)
        baseline = conn.execute("SELECT * FROM bestsellers ORDER BY rank").fetchall()

    ranking = fixture_html(RANKING_FIXTURE)
    first = parse_ranking_html(ranking)[0].url
    detail = fixture_html("detail_" + first.rsplit("/", 1)[1] + ".html")
    fetcher = FakeFetcher({RANKING_PAGE_URL: ranking, first: detail})
    deps = RunDependencies(fetcher, parse_ranking_html, parse_detail_html,
                           lambda: db.connect(db_url), sleep=FakeSleep())
    report = run_first_book(deps)
    assert report.status is RunStatus.SUCCESS
    assert report.new_book_count == 1
    assert fetcher.calls == [RANKING_PAGE_URL, first]
    with db.connect(db_url) as conn:
        ref = db.find_source(conn, first)
        assert ref is not None
        expected = parse_detail_html(detail, first)
        assert conn.execute("SELECT title, description, table_of_contents FROM books WHERE id=%s",
                            (ref.book_id,)).fetchone() == (expected.title, expected.description, expected.table_of_contents)
        assert conn.execute("SELECT count(*) FROM book_identifiers WHERE book_id=%s", (ref.book_id,)).fetchone()[0] == len(expected.identifiers)
        assert conn.execute("SELECT count(*) FROM book_contributors WHERE book_id=%s", (ref.book_id,)).fetchone()[0] == len(expected.contributors)
        assert conn.execute("SELECT count(*) FROM book_subjects WHERE book_id=%s", (ref.book_id,)).fetchone()[0] == len(set(expected.subjects))
        assert conn.execute("SELECT * FROM bestsellers ORDER BY rank").fetchall() == baseline
    second = run_first_book(deps)
    assert second.status is RunStatus.SUCCESS
    assert second.existing_book_count == 1
    assert fetcher.calls == [RANKING_PAGE_URL, first, RANKING_PAGE_URL]
    with db.connect(db_url) as conn:
        assert db.find_source(conn, first) == ref
        assert conn.execute("SELECT count(*) FROM books").fetchone()[0] == 101
        assert conn.execute("SELECT * FROM bestsellers ORDER BY rank").fetchall() == baseline
