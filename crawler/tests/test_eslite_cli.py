"""Eslite entry point ``eslite.cli.main``, offline: fake fetcher, fake provider check, stubbed database session and schema.

The database session and the schema check are stubbed (``stub_database``), so no connection is opened. The DATABASE_URL
used is unreachable on purpose. The real lock, schema and CLI paths against PostgreSQL are in
``test_eslite_db_integration.py``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import psycopg
import pytest

from catalog_core.http_acquisition import AcquisitionError, AcquisitionFailure
from catalog_core.migration_lock import MigrationLockBusy
from catalog_core.models import ProviderCode
from eslite import cli
from eslite.acquisition import EsliteFetcher
from eslite.config import EsliteConfigError
from eslite.page_list import MAX_PAGES
from eslite.run import SoftBudget

DSN_SECRET = "postgresql://eslite_user:hunter2@127.0.0.1:1/books"
LIST_URL = "https://www.eslite.com/category/3/101"
EMPTY_CATEGORY_URL = "https://www.eslite.com/category/3/9999999"
FIXTURES = Path(__file__).parent / "fixtures" / "eslite"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    """Every list request fails with the given error. Records calls and close()."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error or AcquisitionError(AcquisitionFailure.HTTP_STATUS, "GET failed: http_status 503", attempts=3, status=503)
        self.calls: list[str] = []
        self.closed = 0

    @property
    def http_attempts(self) -> int:
        return len(self.calls)

    @property
    def http_failures(self) -> int:
        return len(self.calls)

    def fetch_list_page(self, url: str) -> str:
        self.calls.append(url)
        raise self.error

    def fetch_detail_page(self, url: str) -> str:  # pragma: no cover - never reached: no card is parsed
        self.calls.append(url)
        raise AssertionError("no detail page may be requested")

    def close(self) -> None:
        self.closed += 1


class ScriptedFetcher(FakeFetcher):
    """Serves one list body for any list request, and no failure."""

    def __init__(self, body: str) -> None:
        super().__init__()
        self.body = body

    def fetch_list_page(self, url: str) -> str:
        self.calls.append(url)
        return self.body

    @property
    def http_failures(self) -> int:
        return 0


class StubSession:
    """Stands in for ``DatabaseSession``: no connection. ``busy`` makes the first access raise MigrationLockBusy."""

    busy = False

    def __init__(self, connect) -> None:
        self._connect = connect

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    @property
    def conn(self):
        if StubSession.busy:
            raise MigrationLockBusy("migration lock busy: stub")
        return object()


@pytest.fixture(autouse=True)
def stub_database(monkeypatch):
    """Replaces the session and the schema check. ``state["missing"]`` is what the schema check reports."""
    state = {"missing": [], "preflight_providers": []}

    def fake_preflight(conn, provider):
        state["preflight_providers"].append(provider)
        return list(state["missing"])

    monkeypatch.setattr(cli, "DatabaseSession", StubSession)
    monkeypatch.setattr(cli.persistence, "missing_schema_prerequisites", fake_preflight)
    return state


@pytest.fixture(autouse=True)
def _reset_busy():
    StubSession.busy = False
    yield
    StubSession.busy = False


class Harness:
    """Runs ``cli.main`` with recording fakes and reports what happened."""

    def __init__(self, tmp_path: Path, *, enabled=True, fetcher=None, environ=None) -> None:
        self.pages = tmp_path / "eslite-pages.txt"
        self.pages.write_text(LIST_URL + "\n", encoding="utf-8")
        self.fetcher = fetcher or FakeFetcher()
        self.factory_calls: list[tuple] = []
        self.provider_calls: list[tuple] = []
        self.enabled = enabled
        self.environ = {"DATABASE_URL": DSN_SECRET, "ESLITE_PAGES_FILE": str(self.pages), "ESLITE_ARTIFACTS_DIR": str(tmp_path / "artifacts")}
        if environ is not None:
            self.environ = environ

    def provider_enabled(self, url, code):
        self.provider_calls.append((url, code))
        return self.enabled

    def factory(self, config, budget):
        self.factory_calls.append((config, budget))
        return self.fetcher

    def run(self, **overrides) -> int:
        kwargs = {
            "provider_enabled": self.provider_enabled,
            "fetcher_factory": self.factory,
            "monotonic": lambda: 0.0,
        }
        kwargs.update(overrides)
        return cli.main(self.environ, **kwargs)


def last_run(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "artifacts" / "eslite" / "last-run.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Exit 2 before anything is fetched
# ---------------------------------------------------------------------------


def test_a_disabled_provider_exits_2_and_builds_no_fetcher(tmp_path, capsys):
    harness = Harness(tmp_path, enabled=False)

    assert harness.run() == 2

    assert harness.provider_calls == [(DSN_SECRET, ProviderCode.ESLITE)]
    assert harness.factory_calls == []
    assert harness.fetcher.calls == []
    assert "disabled or not registered" in capsys.readouterr().out


def test_an_unregistered_provider_exits_2(tmp_path):
    harness = Harness(tmp_path)

    assert harness.run(provider_enabled=lambda url, code: None) == 2
    assert harness.factory_calls == []


@pytest.mark.parametrize(
    "content",
    [
        "",
        "# only a comment\n\n",
        "https://www.eslite.com/category/3/101/\n",  # not canonical
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1\n",  # other site
        "https://athena.eslite.com/api/v1/categories/101/products?page_no=1\n",  # an API URL is not a list page
        "https://www.eslite.com/category/2/28\n",  # level 2
    ],
)
def test_an_empty_or_invalid_page_list_exits_2_before_the_fetcher_or_provider(tmp_path, content):
    harness = Harness(tmp_path)
    harness.pages.write_text(content, encoding="utf-8")

    assert harness.run() == 2

    assert harness.provider_calls == []
    assert harness.factory_calls == []
    assert harness.fetcher.calls == []


def test_a_missing_page_list_exits_2_before_the_fetcher_or_provider(tmp_path):
    harness = Harness(tmp_path)
    harness.pages.unlink()

    assert harness.run() == 2

    assert harness.provider_calls == []
    assert harness.factory_calls == []
    assert harness.fetcher.calls == []


def test_a_missing_page_list_is_recorded_as_a_pre_run_record(tmp_path):
    harness = Harness(tmp_path)
    harness.pages.unlink()

    assert harness.run() == 2

    data = last_run(tmp_path)
    assert data["provider"] == "ESLITE"
    assert data["status"] == "FAILED"
    assert data["exit_code"] == 2
    assert data["alert_reasons"] == ["failed"]


def test_an_oversized_page_list_exits_2_before_the_fetcher_or_provider(tmp_path):
    harness = Harness(tmp_path)
    harness.pages.write_text("\n".join(f"https://www.eslite.com/category/3/{n}" for n in range(1, MAX_PAGES + 2)), encoding="utf-8")

    assert harness.run() == 2

    assert harness.provider_calls == []
    assert harness.factory_calls == []


@pytest.mark.parametrize("environ_value", [None, "", "   "])
def test_a_missing_database_url_exits_2_and_logs_no_value(tmp_path, capsys, environ_value):
    harness = Harness(tmp_path)
    harness.environ = {"ESLITE_PAGES_FILE": str(harness.pages)}
    if environ_value is not None:
        harness.environ["DATABASE_URL"] = environ_value

    assert harness.run() == 2

    assert harness.provider_calls == []
    assert harness.factory_calls == []
    assert "DATABASE_URL is not set" in capsys.readouterr().out


@pytest.mark.parametrize(
    "key, value",
    [
        ("ESLITE_SOFT_RUN_BUDGET_SECONDS", "abc"),
        ("ESLITE_SOFT_RUN_BUDGET_SECONDS", "9000"),  # not below CRAWLER_RUN_HARD_LIMIT_SECONDS (default 9000)
        ("ESLITE_WRITE_POLICY", "bogus"),
        ("ESLITE_HTTP_MAX_ATTEMPTS", "0"),
    ],
)
def test_an_invalid_eslite_setting_exits_2_before_the_fetcher(tmp_path, key, value):
    harness = Harness(tmp_path)
    harness.environ[key] = value

    assert harness.run() == 2

    assert harness.factory_calls == []
    assert harness.provider_calls == []


def test_a_kingstone_setting_is_ignored_by_the_eslite_run(tmp_path):
    harness = Harness(tmp_path)
    harness.environ["KINGSTONE_WRITE_POLICY"] = "bogus"
    harness.environ["KINGSTONE_SOFT_RUN_BUDGET_SECONDS"] = "abc"

    assert harness.run() == 1  # the run starts (the fake fetcher fails every page): no configuration error
    assert len(harness.factory_calls) == 1


def test_an_unsupported_runtime_unicode_exits_2(tmp_path, monkeypatch):
    harness = Harness(tmp_path)

    def too_old():
        raise RuntimeError("The runtime's Unicode data is older than 15.0")

    monkeypatch.setattr(cli, "ensure_runtime_unicode_supported", too_old)

    assert harness.run() == 2
    assert harness.factory_calls == []


def test_the_config_error_type_is_a_value_error():
    assert issubclass(EsliteConfigError, ValueError)


# ---------------------------------------------------------------------------
# Exit 1 and exit 2 from the database
# ---------------------------------------------------------------------------


def test_a_provider_query_error_exits_1_and_the_message_is_redacted(tmp_path, capsys):
    harness = Harness(tmp_path)

    def broken(url, code):
        raise psycopg.OperationalError(f"could not connect using {DSN_SECRET}")

    assert harness.run(provider_enabled=broken) == 1

    out = capsys.readouterr().out
    assert "could not read source_providers" in out
    assert "hunter2" not in out
    assert harness.factory_calls == []


def test_a_missing_schema_prerequisite_exits_2_before_the_fetcher_and_is_logged(tmp_path, capsys, stub_database):
    stub_database["missing"] = ["book_sources.last_seen_at"]
    harness = Harness(tmp_path)

    assert harness.run() == 2

    assert harness.factory_calls == []
    assert harness.fetcher.calls == []
    assert stub_database["preflight_providers"] == [ProviderCode.ESLITE]
    assert "SCHEMA_PREREQUISITE_MISSING: book_sources.last_seen_at" in capsys.readouterr().out
    assert last_run(tmp_path)["reason"] == "SCHEMA_PREREQUISITE_MISSING"


def test_a_busy_first_connection_exits_1_with_maintenance_busy_before_the_fetcher(tmp_path, capsys):
    StubSession.busy = True
    harness = Harness(tmp_path)

    assert harness.run() == 1

    assert harness.factory_calls == []
    assert harness.fetcher.calls == []
    assert "maintenance busy" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def test_every_page_skipped_exits_1_and_the_fetcher_is_closed(tmp_path):
    harness = Harness(tmp_path)

    assert harness.run() == 1

    assert len(harness.factory_calls) == 1
    assert harness.fetcher.calls == [LIST_URL]
    assert harness.fetcher.closed == 1


def test_a_fatal_error_exits_1_redacted_and_the_fetcher_is_still_closed(tmp_path, capsys):
    harness = Harness(tmp_path, fetcher=FakeFetcher(error=RuntimeError(f"boom {DSN_SECRET}")))

    assert harness.run() == 1

    assert harness.fetcher.closed == 1
    out = capsys.readouterr().out
    assert "hunter2" not in out
    assert "postgresql://<redacted>" in out


def test_a_run_whose_only_page_is_empty_succeeds_and_alerts_zero_card_pages(tmp_path, capsys):
    harness = Harness(tmp_path, fetcher=ScriptedFetcher(fixture_text("list_101_p6.json")))
    harness.pages.write_text("https://www.eslite.com/category/3/101?page=6\n", encoding="utf-8")

    assert harness.run() == 0

    data = last_run(tmp_path)
    assert data["provider"] == "ESLITE"
    assert data["status"] == "SUCCESS"
    assert data["exit_code"] == 0
    assert data["pages_completed"] == 1
    assert data["zero_card_pages"] == 1
    assert data["alert_reasons"] == ["zero_card_pages"]
    assert data["http_attempts"] == 1
    assert data["http_failures"] == 0
    assert "ALERT reasons=zero_card_pages" in capsys.readouterr().out


def test_an_empty_category_page_fails_the_run_with_reason_empty_category_and_alerts(tmp_path, capsys):
    harness = Harness(tmp_path, fetcher=ScriptedFetcher(fixture_text("list_9999999_p1.json")))
    harness.pages.write_text(EMPTY_CATEGORY_URL + "\n", encoding="utf-8")

    assert harness.run() == 1

    data = last_run(tmp_path)
    assert data["status"] == "FAILED"
    assert data["pages_skipped"][0]["reason"] == "empty_category"
    assert data["alert_reasons"] == ["failed"]
    assert f"ALERT reasons=failed last_run={tmp_path / 'artifacts' / 'eslite' / 'last-run.json'}" in capsys.readouterr().out


def test_a_failed_run_writes_last_run_history_and_one_alert_line(tmp_path, capsys):
    harness = Harness(tmp_path)

    assert harness.run() == 1

    data = last_run(tmp_path)
    assert data["status"] == "FAILED"
    assert data["exit_code"] == 1
    assert data["alert_reasons"] == ["failed"]
    assert data["pages_listed"] == 1
    assert data["pages_skipped"][0]["reason"] == "http_status"
    assert data["pages_skipped"][0]["attempts"] == 3
    out = capsys.readouterr().out
    assert out.count("ALERT") == 1
    assert f"ALERT reasons=failed last_run={tmp_path / 'artifacts' / 'eslite' / 'last-run.json'}" in out
    assert len(list((tmp_path / "artifacts" / "eslite" / "history").glob("*.json"))) == 1


def test_the_stdout_terminal_line_is_the_last_run_record(tmp_path, capsys):
    harness = Harness(tmp_path, fetcher=ScriptedFetcher(fixture_text("list_101_p6.json")))
    harness.pages.write_text("https://www.eslite.com/category/3/101?page=6\n", encoding="utf-8")

    harness.run()

    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert len(lines) == 1
    assert json.loads(lines[0]) == last_run(tmp_path)


def test_the_run_report_line_is_on_stdout_and_no_database_url_is(tmp_path, capsys):
    harness = Harness(tmp_path)

    harness.run()

    out = capsys.readouterr().out
    assert "mode=eslite" in out
    assert "INFO eslite.run" in out
    assert "hunter2" not in out
    assert DSN_SECRET not in out


def test_logging_is_on_stdout_at_info_for_the_eslite_and_core_loggers(tmp_path):
    harness = Harness(tmp_path)

    harness.run()

    assert logging.getLogger("eslite").level == logging.INFO
    assert logging.getLogger("catalog_core").level == logging.INFO


def test_the_default_fetcher_is_built_from_the_config_and_the_budget(tmp_path, monkeypatch):
    seen = {}

    class RecordingFetcher(FakeFetcher):
        def __init__(self, **kwargs):
            super().__init__()
            seen.update(kwargs)

    monkeypatch.setattr(cli, "EsliteFetcher", RecordingFetcher)
    harness = Harness(
        tmp_path,
        environ={
            "DATABASE_URL": DSN_SECRET,
            "ESLITE_PAGES_FILE": str(tmp_path / "eslite-pages.txt"),
            "ESLITE_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
            "ESLITE_HTTP_TIMEOUT_SECONDS": "7",
            "ESLITE_HTTP_MAX_ATTEMPTS": "2",
            "ESLITE_MAX_RESPONSE_BYTES": "1234",
        },
    )
    (tmp_path / "eslite-pages.txt").write_text(LIST_URL + "\n", encoding="utf-8")

    cli.main(harness.environ, provider_enabled=harness.provider_enabled, monotonic=lambda: 0.0)

    assert seen["timeout"] == 7.0
    assert seen["max_attempts"] == 2
    assert seen["max_response_bytes"] == 1234
    assert callable(seen["budget_remaining"])


def test_the_default_fetcher_is_an_eslite_fetcher(tmp_path):
    budget = SoftBudget(7200, lambda: 0.0)
    fetcher = cli._default_fetcher(cli.load_config({"ESLITE_PAGES_FILE": str(tmp_path / "pages.txt")}), budget)
    try:
        assert isinstance(fetcher, EsliteFetcher)
    finally:
        fetcher.close()


def test_the_fetcher_is_built_only_after_the_schema_check(tmp_path, stub_database):
    seen_at_build = []
    harness = Harness(tmp_path)

    def factory(config, budget):
        seen_at_build.append(list(stub_database["preflight_providers"]))
        return harness.fetcher

    harness.run(fetcher_factory=factory)

    assert seen_at_build == [[ProviderCode.ESLITE]]


def test_a_fetcher_refusal_of_a_list_url_is_fatal_and_the_fetcher_is_closed(tmp_path):
    harness = Harness(tmp_path, fetcher=FakeFetcher(error=ValueError("not an accepted Eslite category list page URL")))

    assert harness.run() == 1

    assert harness.fetcher.closed == 1
