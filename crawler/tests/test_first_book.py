"""Single-book import: only rank 1 is resolved; the bestseller snapshot is never replaced."""

import logging
from contextlib import nullcontext
from uuid import uuid4

import psycopg
import pytest

from books_crawler import cli, db
from books_crawler.fetcher import FetchError
from books_crawler.models import BookDraft, RunStatus, SourceRef
from books_crawler.parsers import RANKING_PAGE_URL, RestrictedBookError
from books_crawler.run import RunDependencies, run_first_book
from tests.fakes import FakeFetcher, FakeSleep, fake_detail_parser, fake_ranking_parser, make_draft, ranking_rows


def dependencies(connect, *, count=100, failures=None):
    rows = ranking_rows(count)
    first = rows[0].url
    fetcher = FakeFetcher({RANKING_PAGE_URL: "<ranking/>", first: "<detail/>"}, failures=failures)
    deps = RunDependencies(
        fetcher=fetcher,
        parse_ranking=fake_ranking_parser(list(reversed(rows))),
        parse_detail=fake_detail_parser({first: make_draft(first)}),
        connect=connect,
        sleep=FakeSleep(),
    )
    return deps, first


def test_import_only_first_book_and_retry_database_without_refetch(monkeypatch):
    deps, first = dependencies(lambda: nullcontext(object()))
    lookups, writes = [], []
    monkeypatch.setattr(db, "find_source", lambda conn, url: lookups.append(url))
    monkeypatch.setattr(db, "find_book_by_isbn", lambda *args: None)
    ref = SourceRef(uuid4(), uuid4())

    def persist(conn, draft, now, **kwargs):
        writes.append(draft)
        if len(writes) == 1:
            raise psycopg.OperationalError("temporary write failure")
        return ref

    monkeypatch.setattr(db, "persist_new_source", persist)
    monkeypatch.setattr(db, "replace_bestsellers", lambda *args, **kwargs: pytest.fail("must preserve snapshot"))
    report = run_first_book(deps)
    assert report.status is RunStatus.SUCCESS
    assert report.new_book_count == 1
    assert lookups == [first]
    assert deps.fetcher.calls == [RANKING_PAGE_URL, first]
    assert writes[0] is writes[1]
    assert deps.sleep.calls == [1.0]


def test_known_first_book_does_not_fetch_detail_or_write(monkeypatch):
    deps, _first = dependencies(lambda: nullcontext(object()))
    monkeypatch.setattr(db, "find_source", lambda *args: SourceRef(uuid4(), uuid4()))
    monkeypatch.setattr(db, "persist_new_source", lambda *args, **kwargs: pytest.fail("must reuse existing book"))
    report = run_first_book(deps)
    assert report.status is RunStatus.SUCCESS
    assert report.existing_book_count == 1
    assert deps.fetcher.calls == [RANKING_PAGE_URL]


def test_first_book_challenge_exhausts_retries_and_fails(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="books_crawler")
    first = ranking_rows()[0].url
    deps, _ = dependencies(lambda: nullcontext(object()), failures={first: FetchError("Cloudflare challenge")})
    monkeypatch.setattr(db, "find_source", lambda *args: None)
    monkeypatch.setattr(db, "persist_new_source", lambda *args, **kwargs: pytest.fail("must not write"))
    report = run_first_book(deps)
    assert report.status is RunStatus.FAILED
    assert report.exit_code == 1
    assert (report.aborted_at_rank, report.consecutive_error_count) == (1, 1)
    assert report.skipped[0].failure.attempts == 3
    assert report.error == "run aborted at rank 1 after 1 consecutive error(s) (limit 0): fetch_error: Cloudflare challenge"
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == [f"first-book import failed: {report.error}"]
    assert deps.fetcher.calls == [RANKING_PAGE_URL, first, first, first]
    assert deps.sleep.calls == [1.0, 2.0]


def test_first_book_database_failure_is_not_reported_as_a_fetch_error(monkeypatch):
    deps, first = dependencies(lambda: nullcontext(object()))
    monkeypatch.setattr(db, "find_source", lambda *args: None)
    monkeypatch.setattr(db, "find_book_by_isbn", lambda *args: None)

    def persist(*args, **kwargs):
        raise psycopg.OperationalError("write failure")

    monkeypatch.setattr(db, "persist_new_source", persist)
    report = run_first_book(deps)
    assert report.status is RunStatus.FAILED
    assert report.exit_code == 1
    assert report.skipped[0].failure.error_type == "database_error"
    assert report.error.startswith("run aborted at rank 1 after 1 consecutive error(s) (limit 0): database_error: ")
    assert "FetchError" not in report.error
    assert deps.fetcher.calls == [RANKING_PAGE_URL, first]


def test_draft_validation_error_from_the_detail_parser_is_retried_as_parse_error(monkeypatch):
    deps, first = dependencies(lambda: nullcontext(object()))
    monkeypatch.setattr(db, "find_source", lambda *args: None)
    monkeypatch.setattr(db, "persist_new_source", lambda *args, **kwargs: pytest.fail("must not write"))

    def invalid_draft(html, url):
        return BookDraft(source_url=url, title="   ")  # BookDraft.__post_init__ raises ValueError

    deps.parse_detail = invalid_draft
    report = run_first_book(deps)
    assert report.status is RunStatus.FAILED
    failure = report.skipped[0].failure
    assert (failure.error_type, failure.attempts) == ("parse_error", 3)
    assert "title is required" in failure.error_message
    assert deps.fetcher.calls == [RANKING_PAGE_URL, first, first, first]  # the page is fetched again each time
    assert deps.sleep.calls == [1.0, 2.0]


def test_incomplete_ranking_does_not_open_database():
    deps, _ = dependencies(lambda: pytest.fail("must validate ranking first"), count=99)
    report = run_first_book(deps)
    assert report.status is RunStatus.FAILED
    assert "expected 100" in report.error
    assert deps.fetcher.calls == [RANKING_PAGE_URL]


def test_first_book_cli_selects_runner_and_closes_fetcher(monkeypatch):
    closed = []
    fetcher = FakeFetcher()
    fetcher.close = lambda: closed.append(True)
    monkeypatch.setattr(cli, "create_fetcher", lambda kind, **options: fetcher)
    monkeypatch.setattr(cli, "run_once", lambda *args: pytest.fail("must use single-book runner"))
    monkeypatch.setattr(cli, "run_first_book", lambda deps: type("Report", (), {"exit_code": 1})())
    assert cli.main({"DATABASE_URL": "postgresql://unused"}, mode=cli.CrawlerMode.FIRST_BOOK) == 1
    assert closed == [True]


def test_restricted_first_book_skips_once_without_error(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="books_crawler")
    deps, first = dependencies(lambda: nullcontext(object()))
    monkeypatch.setattr(db, "find_source", lambda *args: None)

    def restricted(html, url):
        raise RestrictedBookError("restricted product requires member login")

    deps.parse_detail = restricted
    report = run_first_book(deps)
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.exit_code == 0
    assert report.restricted_book_count == 1
    assert report.error_count == 0
    assert deps.fetcher.calls == [RANKING_PAGE_URL, first]
    assert deps.sleep.calls == []
    assert f"rank 1 restricted product skipped without retry: {first}" in [r.getMessage() for r in caplog.records]


def test_first_book_summary_line_names_the_job_and_the_catalog_counters(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="books_crawler")
    deps, _ = dependencies(lambda: nullcontext(object()))
    monkeypatch.setattr(db, "find_source", lambda *args: None)
    monkeypatch.setattr(db, "find_book_by_isbn", lambda *args: None)
    monkeypatch.setattr(db, "persist_new_source", lambda *args, **kwargs: SourceRef(uuid4(), uuid4()))

    report = run_first_book(deps, run_id="run-fb")

    summary = [r.getMessage() for r in caplog.records if r.getMessage().startswith("mode=first-book ")]
    assert len(summary) == 1
    assert summary[0].startswith("mode=first-book run_id=run-fb provider_code=BOOKS_COM_TW job_name=first-book ")
    assert " ranking_count=100 items_seen=1 existing_book_count=0 new_book_count=1 attached_source_count=0 " in summary[0]
    assert " existing_source_count=0 new_source_count=1 ambiguous_isbn_count=0 offer_updated_count=0 " in summary[0]
    assert " consecutive_error_count=0 aborted_at_rank=none exit_code=0 " in summary[0]
    assert report.exit_code == 0


def test_first_book_existing_source_is_counted_as_existing_not_as_new(monkeypatch):
    deps, _ = dependencies(lambda: nullcontext(object()))
    monkeypatch.setattr(db, "find_source", lambda conn, url: SourceRef(uuid4(), uuid4()))
    monkeypatch.setattr(db, "persist_new_source", lambda *args, **kwargs: pytest.fail("a known source is not written"))
    monkeypatch.setattr(db, "replace_bestsellers", lambda *args, **kwargs: pytest.fail("must preserve snapshot"))

    report = run_first_book(deps)

    assert report.status is RunStatus.SUCCESS
    assert (report.existing_book_count, report.existing_source_count, report.new_source_count) == (1, 1, 0)
    assert deps.fetcher.calls == [RANKING_PAGE_URL]
