"""Run orchestration without a database: failures before any write never open a connection."""

from datetime import datetime, timezone

from books_crawler.cli import main
from books_crawler.fetcher import FetchError
from books_crawler.models import RankingRow, RunStatus
from books_crawler.parsers import RANKING_PAGE_URL, parse_detail_html, parse_ranking_html
from books_crawler.run import RunDependencies, format_report, run_once
from tests.fakes import (
    RANKING_HTML,
    FakeFetcher,
    fake_detail_parser,
    fake_ranking_parser,
    product_url,
    ranking_rows,
)

NOW = datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)


class RecordingConnect:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise AssertionError("database must not be touched when the ranking is invalid")


def _deps(fetcher, rows, connect):
    return RunDependencies(
        fetcher=fetcher,
        parse_ranking=fake_ranking_parser(rows),
        parse_detail=fake_detail_parser({}),
        connect=connect,
        clock=lambda: NOW,
    )


def test_incomplete_ranking_fails_before_database_and_detail_fetches():
    fetcher = FakeFetcher(pages={RANKING_PAGE_URL: RANKING_HTML})
    connect = RecordingConnect()

    report = run_once(_deps(fetcher, ranking_rows(99), connect), run_id="run-1")

    assert report.status is RunStatus.FAILED
    assert report.exit_code == 1
    assert connect.calls == 0
    assert fetcher.calls == [RANKING_PAGE_URL]
    assert "expected 100" in report.error


def test_duplicate_url_ranking_fails_before_database():
    rows = ranking_rows(100)
    rows[1] = RankingRow(rank=2, url=product_url(1))
    fetcher = FakeFetcher(pages={RANKING_PAGE_URL: RANKING_HTML})
    connect = RecordingConnect()

    report = run_once(_deps(fetcher, rows, connect))

    assert report.status is RunStatus.FAILED
    assert connect.calls == 0


def test_ranking_fetch_error_fails_run():
    fetcher = FakeFetcher(failures={RANKING_PAGE_URL: FetchError("HTTP 403")})
    connect = RecordingConnect()

    report = run_once(_deps(fetcher, [], connect))

    assert report.status is RunStatus.FAILED
    assert report.exit_code == 1
    assert "HTTP 403" in report.error
    assert connect.calls == 0


def test_real_parsers_reject_a_page_that_is_not_the_ranking_and_fail_the_run():
    fetcher = FakeFetcher(pages={RANKING_PAGE_URL: "<html><body>not a ranking</body></html>"})
    connect = RecordingConnect()
    deps = RunDependencies(
        fetcher=fetcher,
        parse_ranking=parse_ranking_html,
        parse_detail=parse_detail_html,
        connect=connect,
        clock=lambda: NOW,
    )

    report = run_once(deps)

    assert report.status is RunStatus.FAILED
    assert report.exit_code == 1
    assert "ParseError" in report.error
    assert connect.calls == 0


def test_format_report_has_required_fields():
    fetcher = FakeFetcher(pages={RANKING_PAGE_URL: RANKING_HTML})
    report = run_once(_deps(fetcher, ranking_rows(10), RecordingConnect()), run_id="run-42")

    line = format_report(report)

    for field in (
        "run_id=run-42",
        "started_at=2026-10-11T04:00:00+00:00",
        "finished_at=",
        "status=FAILED",
        "ranking_count=0",
        "existing_book_count=0",
        "new_book_count=0",
        "skipped_count=0",
        "exit_code=1",
    ):
        assert field in line


def test_cli_without_database_url_returns_config_error(capsys):
    assert main(environ={}) == 2
    assert "DATABASE_URL is not set" in capsys.readouterr().out
