"""Connection loss during a run, against the real PostgreSQL (crawler.md §13.1, §6.1, data-model §7.3).

Each test ends the crawler's backend with pg_terminate_backend from a second, admin connection, in a hook that runs
right before the operation under test. The fetcher and parsers are fakes; books.com.tw is never contacted.
"""

import logging

import psycopg

from books_crawler import db
from books_crawler.models import RunStatus
from books_crawler.parsers import RANKING_PAGE_URL
from books_crawler.run import RunDependencies, run_first_book
from tests.fakes import FakeFetcher, FakeSleep, fake_detail_parser, fake_ranking_parser, product_url, ranking_rows
from tests.test_db_integration import LATER, NOW, _seed_with_identifiers, bestsellers, query, run, skipped_ranks


def kill_backend(db_url: str, conn) -> None:
    """Terminate the backend behind ``conn`` from another connection, as an operator or a network drop would."""
    with psycopg.connect(db_url, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (conn.info.backend_pid,))


def _source_id(db_url: str, url: str):
    return query(db_url, "SELECT id FROM book_sources WHERE source_url = %s", (url,))[0][0]


def test_touch_after_a_terminated_backend_reconnects_and_advances_last_seen(db_url, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="books_crawler")
    _seed_with_identifiers(db_url, {})
    target = _source_id(db_url, product_url(5))
    real_touch = db.touch_source
    killed = []

    def touch_after_a_drop(conn, source_id, now):
        if source_id == target and not killed:
            killed.append(conn)
            kill_backend(db_url, conn)
        return real_touch(conn, source_id, now)

    monkeypatch.setattr(db, "touch_source", touch_after_a_drop)

    report, _ = run(db_url, ranking_rows(100), now=LATER, sleep=FakeSleep())

    assert report.status is RunStatus.SUCCESS
    assert report.existing_source_count == 100
    assert query(db_url, "SELECT last_seen_at FROM book_sources WHERE id = %s", (target,)) == [(LATER,)]
    assert "rank 5 attempt 1/3 failed" in caplog.text  # the touch took a second attempt on a new connection


def test_a_source_insert_after_a_terminated_backend_is_written_exactly_once(db_url, monkeypatch):
    real_persist = db.persist_new_source
    killed = []

    def persist_after_a_drop(conn, draft, now, attach_to_book_id=None):
        if draft.source_url == product_url(3) and not killed:
            killed.append(conn)
            kill_backend(db_url, conn)
        return real_persist(conn, draft, now, attach_to_book_id=attach_to_book_id)

    monkeypatch.setattr(db, "persist_new_source", persist_after_a_drop)

    report, _ = run(db_url, ranking_rows(100))

    assert report.status is RunStatus.SUCCESS
    assert report.new_book_count == 100
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (product_url(3),)) == [(1,)]


def test_a_commit_whose_acknowledgement_is_lost_is_not_inserted_again_on_retry(db_url, monkeypatch):
    real_persist = db.persist_new_source
    dropped = []

    def commit_then_drop(conn, draft, now, attach_to_book_id=None):
        result = real_persist(conn, draft, now, attach_to_book_id=attach_to_book_id)  # the commit succeeds
        if draft.source_url == product_url(3) and not dropped:
            dropped.append(conn)
            kill_backend(db_url, conn)  # the connection breaks before the client sees the success
            raise psycopg.OperationalError("connection lost before the commit was acknowledged")
        return result

    monkeypatch.setattr(db, "persist_new_source", commit_then_drop)

    report, _ = run(db_url, ranking_rows(100), sleep=FakeSleep())

    assert report.status is RunStatus.SUCCESS
    assert report.skipped == []
    assert query(db_url, "SELECT count(*) FROM book_sources WHERE source_url = %s", (product_url(3),)) == [(1,)]
    assert report.existing_source_count == 1  # the committed outcome is reported as EXISTING (crawler.md §13.1)


def test_three_broken_connections_fail_the_row_with_database_error_and_the_daily_policy_applies(db_url, monkeypatch):
    _seed_with_identifiers(db_url, {})
    target_url = product_url(5)
    target = _source_id(db_url, target_url)
    real_touch = db.touch_source
    kills = []

    def touch_always_drops(conn, source_id, now):
        if source_id == target:
            kills.append(conn)
            kill_backend(db_url, conn)
        return real_touch(conn, source_id, now)

    monkeypatch.setattr(db, "touch_source", touch_always_drops)
    sleep = FakeSleep()

    report, _ = run(db_url, ranking_rows(100), now=LATER, sleep=sleep)

    assert len(kills) == 3
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert skipped_ranks(report) == [5]
    failure = report.skipped[0].failure
    assert (failure.error_type, failure.attempts) == ("database_error", 3)
    assert report.existing_source_count == 99
    assert sleep.calls == [1.0, 2.0]
    assert query(db_url, "SELECT last_seen_at FROM book_sources WHERE id = %s", (target,)) == [(NOW,)]
    assert 5 not in [row[0] for row in bestsellers(db_url)]


def test_a_backend_lost_while_reading_an_existing_source_still_fails_the_run(db_url, monkeypatch):
    # crawler.md §6.1: a failed lookup of the existing Source is outside the retry rule and fails the run.
    _seed_with_identifiers(db_url, {})
    real_resolve = db.resolve_source_identity
    killed = []

    def resolve_after_a_drop(conn, source_url, external_id=None):
        if source_url == product_url(7) and not killed:
            killed.append(conn)
            kill_backend(db_url, conn)
        return real_resolve(conn, source_url, external_id)

    monkeypatch.setattr(db, "resolve_source_identity", resolve_after_a_drop)

    report, _ = run(db_url, ranking_rows(100))

    assert report.status is RunStatus.FAILED
    assert report.exit_code == 1
    assert report.error is not None
    assert "database" in report.error.lower() or "terminat" in report.error.lower() or "closed" in report.error.lower()


def test_first_book_with_three_broken_connections_fails_the_run_with_exit_1(db_url, monkeypatch):
    _seed_with_identifiers(db_url, {})
    target = _source_id(db_url, product_url(1))
    real_touch = db.touch_source
    kills = []

    def touch_always_drops(conn, source_id, now):
        if source_id == target:
            kills.append(conn)
            kill_backend(db_url, conn)
        return real_touch(conn, source_id, now)

    monkeypatch.setattr(db, "touch_source", touch_always_drops)
    deps = RunDependencies(
        fetcher=FakeFetcher({RANKING_PAGE_URL: "<ranking/>"}),
        parse_ranking=fake_ranking_parser(ranking_rows(100)),
        parse_detail=fake_detail_parser({}),
        connect=lambda: db.connect(db_url),
        sleep=FakeSleep(),
    )

    report = run_first_book(deps)

    assert len(kills) == 3
    assert report.status is RunStatus.FAILED
    assert report.exit_code == 1
    assert (report.skipped[0].failure.error_type, report.skipped[0].failure.attempts) == ("database_error", 3)
    assert report.existing_source_count == 0
