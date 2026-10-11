"""Run orchestration without a database: failures before any write never open a connection."""

from datetime import datetime, timezone

import pytest

from books_crawler.cli import main
from books_crawler.fetcher import BrowserUnavailableError, FetchError
from books_crawler.models import Failure, RankingRow, RunStatus, SkipReason, SkippedRow
from books_crawler.parsers import RANKING_PAGE_URL, parse_detail_html, parse_ranking_html
from books_crawler.redact import redact
from books_crawler.run import RunDependencies, RunReport, backoff_seconds, format_report, run_once
from tests.fakes import (
    RANKING_HTML,
    FakeFetcher,
    FakeSleep,
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


def _deps(fetcher, rows, connect, sleep=None):
    return RunDependencies(
        fetcher=fetcher,
        parse_ranking=fake_ranking_parser(rows),
        parse_detail=fake_detail_parser({}),
        connect=connect,
        clock=lambda: NOW,
        sleep=sleep if sleep is not None else FakeSleep(),
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


def test_ranking_fetch_error_is_retried_three_times_then_fails_run():
    fetcher = FakeFetcher(failures={RANKING_PAGE_URL: FetchError("HTTP 403")})
    connect = RecordingConnect()
    sleep = FakeSleep()

    report = run_once(_deps(fetcher, [], connect, sleep))

    assert report.status is RunStatus.FAILED
    assert report.exit_code == 1
    assert "HTTP 403" in report.error
    assert fetcher.calls == [RANKING_PAGE_URL] * 3
    assert sleep.calls == [1.0, 2.0]
    assert connect.calls == 0


def test_ranking_fetch_that_recovers_is_validated_as_usual():
    fetcher = FakeFetcher(pages={RANKING_PAGE_URL: RANKING_HTML}, transient_failures={RANKING_PAGE_URL: 2})
    connect = RecordingConnect()
    sleep = FakeSleep()

    report = run_once(_deps(fetcher, ranking_rows(99), connect, sleep))

    assert fetcher.calls == [RANKING_PAGE_URL] * 3  # two transient failures, then the page
    assert sleep.calls == [1.0, 2.0]
    assert report.status is RunStatus.FAILED  # the 99-row ranking is still rejected, never skipped
    assert "expected 100" in report.error


def test_browser_unavailable_on_the_ranking_page_fails_the_run_without_retry():
    fetcher = FakeFetcher(failures={RANKING_PAGE_URL: BrowserUnavailableError("no chromium")})
    connect = RecordingConnect()
    sleep = FakeSleep()

    report = run_once(_deps(fetcher, ranking_rows(100), connect, sleep))

    assert report.status is RunStatus.FAILED
    assert "BrowserUnavailableError" in report.error
    assert fetcher.calls == [RANKING_PAGE_URL]  # environment problem: not retried
    assert sleep.calls == []
    assert connect.calls == 0


def test_real_parsers_reject_a_page_that_is_not_the_ranking_and_fail_the_run():
    fetcher = FakeFetcher(pages={RANKING_PAGE_URL: "<html><body>not a ranking</body></html>"})
    connect = RecordingConnect()
    sleep = FakeSleep()
    deps = RunDependencies(
        fetcher=fetcher,
        parse_ranking=parse_ranking_html,
        parse_detail=parse_detail_html,
        connect=connect,
        clock=lambda: NOW,
        sleep=sleep,
    )

    report = run_once(deps)

    assert report.status is RunStatus.FAILED
    assert report.exit_code == 1
    assert "ParseError" in report.error
    assert fetcher.calls == [RANKING_PAGE_URL]  # a parse failure is deterministic: not retried
    assert sleep.calls == []
    assert connect.calls == 0


@pytest.mark.parametrize("attempt, seconds", [(2, 1.0), (3, 2.0)])
def test_backoff_schedule(attempt, seconds):
    assert backoff_seconds(attempt) == seconds


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
        "attached_source_count=0",
        "skipped_count=0",
        "exit_code=1",
        "aborted_at_rank=none",
        "consecutive_error_count=0",
        "skipped=[]",
    ):
        assert field in line


def test_format_report_lists_skipped_rows_and_redacts_database_urls():
    report = RunReport(
        run_id="run-7",
        status=RunStatus.PARTIAL_SUCCESS,
        started_at=NOW,
        finished_at=NOW,
        ranking_count=100,
        skipped=[
            SkippedRow(
                rank=7,
                url=product_url(7),
                failure=Failure(
                    error_type=SkipReason.DATABASE_ERROR,
                    error_message="connect failed: postgresql://crawler:s3cret@db.internal/books",
                    attempts=3,
                ),
            )
        ],
        aborted_at_rank=None,
    )

    line = format_report(report)

    assert '"rank": 7' in line
    assert f'"url": "{product_url(7)}"' in line
    assert '"error_type": "database_error"' in line
    assert '"attempts": 3' in line
    assert "s3cret" not in line
    assert "db.internal" not in line
    assert "postgresql://<redacted>" in line


@pytest.mark.parametrize(
    "raw, leaked",
    [
        ("could not connect to postgresql://user:pw@host/db", "user:pw"),
        ("postgresql+psycopg://user:pw@host:5432/db?sslmode=require", "user:pw"),
        ("connection failed: host=db password=hunter2 dbname=x", "hunter2"),
        ("auth failed for password='hunter2';", "hunter2"),
    ],
)
def test_redact_removes_connection_strings_and_password_assignments(raw, leaked):
    cleaned = redact(raw)

    assert leaked not in cleaned
    assert "<redacted>" in cleaned


def test_skip_reason_values_are_the_stored_vocabulary():
    assert [reason.value for reason in SkipReason] == [
        "fetch_error",
        "parse_error",
        "database_error",
        "duplicate_book_in_ranking",
        "restricted_book",
    ]


def test_cli_without_database_url_returns_config_error(capsys):
    assert main(environ={}) == 2
    assert "DATABASE_URL is not set" in capsys.readouterr().out
