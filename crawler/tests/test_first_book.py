"""Single-book import: only rank 1 is resolved; the bestseller snapshot is never replaced."""

from contextlib import nullcontext
from uuid import uuid4

import psycopg
import pytest

from books_crawler import cli, db
from books_crawler.fetcher import FetchError
from books_crawler.models import RunStatus, SourceRef
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
    deps, first = dependencies(lambda: nullcontext(object()))
    monkeypatch.setattr(db, "find_source", lambda *args: SourceRef(uuid4(), uuid4()))
    monkeypatch.setattr(db, "persist_new_source", lambda *args, **kwargs: pytest.fail("must reuse existing book"))
    report = run_first_book(deps)
    assert report.status is RunStatus.SUCCESS
    assert report.existing_book_count == 1
    assert deps.fetcher.calls == [RANKING_PAGE_URL]


def test_first_book_challenge_exhausts_retries_and_fails(monkeypatch):
    first = ranking_rows()[0].url
    deps, _ = dependencies(lambda: nullcontext(object()), failures={first: FetchError("Cloudflare challenge")})
    monkeypatch.setattr(db, "find_source", lambda *args: None)
    monkeypatch.setattr(db, "persist_new_source", lambda *args, **kwargs: pytest.fail("must not write"))
    report = run_first_book(deps)
    assert report.status is RunStatus.FAILED
    assert report.exit_code == 1
    assert report.skipped[0].failure.attempts == 3
    assert report.error.startswith("FirstBookImportError: rank 1 import failed (fetch_error)")
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
    assert report.error.startswith("FirstBookImportError: rank 1 import failed (database_error)")
    assert "FetchError" not in report.error
    assert deps.fetcher.calls == [RANKING_PAGE_URL, first]


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
    monkeypatch.setattr(cli, "CurlCffiFetcher", lambda **kwargs: fetcher)
    monkeypatch.setattr(cli, "run_once", lambda *args: pytest.fail("must use single-book runner"))
    monkeypatch.setattr(cli, "run_first_book", lambda deps: type("Report", (), {"exit_code": 1})())
    assert cli.main({"DATABASE_URL": "postgresql://unused"}, first_book=True) == 1
    assert closed == [True]


def test_restricted_first_book_skips_once_without_error(monkeypatch):
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
