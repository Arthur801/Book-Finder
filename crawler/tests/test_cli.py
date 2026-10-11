"""CLI wiring: configuration, exit codes and fetcher lifetime (no browser, no database, no network)."""

import pytest

from books_crawler import cli
from books_crawler.fetcher import DEFAULT_NAVIGATION_TIMEOUT_MS, FetcherKind

DATABASE = {"DATABASE_URL": "postgresql://unused"}


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


def stub_factory_and_run(monkeypatch, *, exit_code: int = 0, error: Exception | None = None) -> dict:
    """Replace the fetcher factory and the daily run; record what the CLI passed to them."""
    seen: dict = {}

    def create_fetcher(kind, *, navigation_timeout_ms):
        seen["kind"] = kind
        seen["navigation_timeout_ms"] = navigation_timeout_ms
        seen["fetcher"] = FakeClosingFetcher()
        return seen["fetcher"]

    def run_once(deps):
        assert deps.fetcher is seen["fetcher"]
        if error is not None:
            raise error
        return FakeRunResult(exit_code)

    monkeypatch.setattr(cli, "create_fetcher", create_fetcher)
    monkeypatch.setattr(cli, "run_once", run_once)
    return seen


def test_curl_is_the_default_fetcher(monkeypatch):
    seen = stub_factory_and_run(monkeypatch)

    assert cli.main(DATABASE) == 0
    assert seen["kind"] is FetcherKind.CURL


def test_fetcher_kind_ignores_case_and_surrounding_spaces(monkeypatch):
    seen = stub_factory_and_run(monkeypatch)

    assert cli.main({**DATABASE, "CRAWLER_FETCHER": " BROWSER "}) == 0
    assert seen["kind"] is FetcherKind.BROWSER


@pytest.mark.parametrize("raw", ["selenium", "http"])
def test_unknown_fetcher_is_a_configuration_error(monkeypatch, raw):
    seen = stub_factory_and_run(monkeypatch)

    assert cli.main({**DATABASE, "CRAWLER_FETCHER": raw}) == cli.EXIT_CONFIG_ERROR
    assert seen == {}


def test_missing_database_url_is_a_configuration_error(monkeypatch):
    seen = stub_factory_and_run(monkeypatch)

    assert cli.main({}) == cli.EXIT_CONFIG_ERROR
    assert seen == {}


def test_navigation_timeout_is_passed_to_the_factory(monkeypatch):
    seen = stub_factory_and_run(monkeypatch)

    assert cli.main({**DATABASE, "CRAWLER_FETCHER": "browser", "CRAWLER_NAV_TIMEOUT_MS": " 45000 "}) == 0
    assert seen["navigation_timeout_ms"] == 45000


def test_navigation_timeout_defaults_when_unset(monkeypatch):
    seen = stub_factory_and_run(monkeypatch)

    assert cli.main({**DATABASE, "CRAWLER_FETCHER": "browser", "CRAWLER_NAV_TIMEOUT_MS": ""}) == 0
    assert seen["navigation_timeout_ms"] == DEFAULT_NAVIGATION_TIMEOUT_MS


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "1.5", "4e4", "300001"])
def test_invalid_navigation_timeout_is_a_configuration_error(monkeypatch, raw):
    seen = stub_factory_and_run(monkeypatch)

    assert cli.main({**DATABASE, "CRAWLER_FETCHER": "browser", "CRAWLER_NAV_TIMEOUT_MS": raw}) == cli.EXIT_CONFIG_ERROR
    assert seen == {}


def test_fetcher_is_closed_when_the_run_fails_normally(monkeypatch):
    seen = stub_factory_and_run(monkeypatch, exit_code=1)

    assert cli.main(DATABASE) == 1
    assert seen["fetcher"].closed == 1


def test_fetcher_is_closed_when_the_run_raises(monkeypatch):
    seen = stub_factory_and_run(monkeypatch, error=RuntimeError("unexpected"))

    with pytest.raises(RuntimeError, match="unexpected"):
        cli.main(DATABASE)
    assert seen["fetcher"].closed == 1
