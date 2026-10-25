"""Kingstone entry point ``kingstone.cli.main`` (CR-K09), offline: fake fetcher, fake provider check, no database.

The provider check is faked. The database session and the schema check are stubbed (``stub_database``), so no
connection is opened: the DATABASE_URL used is unreachable on purpose, and a test that connects to it would hang or fail.
The runs use a page list whose pages are all skipped, so the store is never touched. The real lock, schema and CLI
paths against PostgreSQL are in ``test_kingstone_db_integration.py`` and ``test_migration_lock_integration.py``.
"""

from __future__ import annotations

import json
import logging

import psycopg
import pytest

from catalog_core.migration_lock import MigrationLockBusy
from catalog_core.models import ProviderCode
from kingstone import cli
from kingstone.acquisition import AcquisitionError, AcquisitionFailure, KingstoneFetcher
from kingstone.config import KingstoneConfigError
from kingstone.page_list import MAX_PAGES
from kingstone.run import SoftBudget

DSN_SECRET = "postgresql://kingstone_user:hunter2@127.0.0.1:1/books"
LIST_URL = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1"


class FakeFetcher:
    """Every page request fails with the given error. Records calls and close()."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error or AcquisitionError(AcquisitionFailure.REDIRECT, "302 to /book/", attempts=1, status=302)
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

    def fetch_detail_page(self, url: str) -> str:  # pragma: no cover - never reached: no page is parsed
        self.calls.append(url)
        raise AssertionError("no detail page may be requested")

    def close(self) -> None:
        self.closed += 1


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
    state = {"missing": []}
    monkeypatch.setattr(cli, "DatabaseSession", StubSession)
    monkeypatch.setattr(cli.persistence, "missing_schema_prerequisites", lambda conn: list(state["missing"]))
    return state


class Harness:
    """Runs ``cli.main`` with recording fakes and reports what happened."""

    def __init__(self, tmp_path, *, enabled=True, fetcher=None, environ=None):
        self.pages = tmp_path / "pages.txt"
        self.pages.write_text(LIST_URL + "\n", encoding="utf-8")
        self.fetcher = fetcher or FakeFetcher()
        self.factory_calls: list[tuple] = []
        self.provider_calls: list[tuple] = []
        self.enabled = enabled
        self.environ = {"DATABASE_URL": DSN_SECRET, "KINGSTONE_PAGES_FILE": str(self.pages), "KINGSTONE_ARTIFACTS_DIR": str(tmp_path / "artifacts")}
        if environ is not None:
            self.environ = environ

    def provider_enabled(self, url, code):
        self.provider_calls.append((url, code))
        return self.enabled

    def factory(self, config, budget):
        self.factory_calls.append((config, budget))
        return self.fetcher

    def run(self, **overrides):
        kwargs = {
            "provider_enabled": self.provider_enabled,
            "fetcher_factory": self.factory,
            "monotonic": lambda: 0.0,
        }
        kwargs.update(overrides)
        return cli.main(self.environ, **kwargs)


def test_a_disabled_provider_exits_2_and_builds_no_fetcher(tmp_path, capsys):
    harness = Harness(tmp_path, enabled=False)

    assert harness.run() == 2

    assert harness.provider_calls == [(DSN_SECRET, ProviderCode.KINGSTONE)]
    assert harness.factory_calls == []
    assert "disabled or not registered" in capsys.readouterr().out


def test_an_unregistered_provider_exits_2(tmp_path):
    harness = Harness(tmp_path)

    assert harness.run(provider_enabled=lambda url, code: None) == 2
    assert harness.factory_calls == []


@pytest.mark.parametrize("content", ["", "# only a comment\n\n", "https://evil.example/book/jdc/?dis=list&page=1\n"])
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


def test_an_oversized_page_list_exits_2_before_the_fetcher_or_provider(tmp_path):
    harness = Harness(tmp_path)
    harness.pages.write_text("\n".join(f"https://www.kingstone.com.tw/book/jdc/?dis=list&page={n}" for n in range(1, MAX_PAGES + 2)), encoding="utf-8")

    assert harness.run() == 2

    assert harness.provider_calls == []
    assert harness.factory_calls == []


@pytest.mark.parametrize("environ_value", [None, "", "   "])
def test_a_missing_database_url_exits_2_and_logs_no_value(tmp_path, capsys, environ_value):
    harness = Harness(tmp_path)
    harness.environ = {"KINGSTONE_PAGES_FILE": str(harness.pages)}
    if environ_value is not None:
        harness.environ["DATABASE_URL"] = environ_value

    assert harness.run() == 2

    assert harness.provider_calls == []
    assert harness.factory_calls == []
    assert "DATABASE_URL is not set" in capsys.readouterr().out


@pytest.mark.parametrize(
    "key, value",
    [
        ("KINGSTONE_SOFT_RUN_BUDGET_SECONDS", "abc"),
        ("KINGSTONE_SOFT_RUN_BUDGET_SECONDS", "9000"),  # not below CRAWLER_RUN_HARD_LIMIT_SECONDS (9000)
        ("KINGSTONE_WRITE_POLICY", "bogus"),
        ("KINGSTONE_HTTP_MAX_ATTEMPTS", "0"),
    ],
)
def test_an_invalid_kingstone_setting_exits_2_before_the_fetcher(tmp_path, key, value):
    harness = Harness(tmp_path)
    harness.environ[key] = value

    assert harness.run() == 2

    assert harness.factory_calls == []
    assert harness.provider_calls == []


def test_an_unsupported_runtime_unicode_exits_2(tmp_path, monkeypatch):
    harness = Harness(tmp_path)

    def too_old():
        raise RuntimeError("The runtime's Unicode data is older than 15.0")

    monkeypatch.setattr(cli, "ensure_runtime_unicode_supported", too_old)

    assert harness.run() == 2
    assert harness.factory_calls == []


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
    assert "SCHEMA_PREREQUISITE_MISSING: book_sources.last_seen_at" in capsys.readouterr().out


def test_a_busy_first_connection_exits_1_with_maintenance_busy_before_the_fetcher(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(StubSession, "busy", True)
    harness = Harness(tmp_path)

    assert harness.run() == 1

    assert harness.factory_calls == []
    assert harness.fetcher.calls == []
    assert "maintenance busy" in capsys.readouterr().out


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


def test_the_output_never_contains_the_database_url_or_its_password(tmp_path, capsys):
    harness = Harness(tmp_path)

    harness.run()

    out = capsys.readouterr().out
    assert "hunter2" not in out
    assert DSN_SECRET not in out
    assert "mode=kingstone" in out  # the run report line is on stdout at INFO


def test_logging_is_on_stdout_at_info_for_the_kingstone_loggers(tmp_path, capsys):
    harness = Harness(tmp_path)

    harness.run()

    out = capsys.readouterr().out
    assert "INFO kingstone.run" in out
    assert logging.getLogger("kingstone").level == logging.INFO
    assert logging.getLogger("catalog_core").level == logging.INFO


def test_the_default_fetcher_is_built_from_the_config_and_the_budget(tmp_path, monkeypatch):
    seen = {}

    class RecordingFetcher(FakeFetcher):
        def __init__(self, **kwargs):
            super().__init__()
            seen.update(kwargs)

    monkeypatch.setattr(cli, "KingstoneFetcher", RecordingFetcher)
    harness = Harness(
        tmp_path,
        environ={
            "DATABASE_URL": DSN_SECRET,
            "KINGSTONE_PAGES_FILE": str(tmp_path / "pages.txt"),
            "KINGSTONE_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
            "KINGSTONE_HTTP_TIMEOUT_SECONDS": "7",
            "KINGSTONE_HTTP_MAX_ATTEMPTS": "2",
            "KINGSTONE_MAX_RESPONSE_BYTES": "1234",
        },
    )
    (tmp_path / "pages.txt").write_text(LIST_URL + "\n", encoding="utf-8")

    cli.main(harness.environ, provider_enabled=harness.provider_enabled, monotonic=lambda: 0.0)

    assert seen["timeout"] == 7.0
    assert seen["max_attempts"] == 2
    assert seen["max_response_bytes"] == 1234
    assert callable(seen["budget_remaining"])


def test_the_default_fetcher_is_a_kingstone_fetcher(tmp_path):
    budget = SoftBudget(3300, lambda: 0.0)
    fetcher = cli._default_fetcher(cli.load_config({"KINGSTONE_PAGES_FILE": str(tmp_path / "pages.txt")}), budget)
    try:
        assert isinstance(fetcher, KingstoneFetcher)
    finally:
        fetcher.close()


def test_config_error_type_is_a_value_error():
    assert issubclass(KingstoneConfigError, ValueError)


# ---------------------------------------------------------------------------
# Terminal artifacts (plan v12 §8): last-run.json on every terminal result after the config, and the ALERT line
# ---------------------------------------------------------------------------

EMPTY_PAGE = '<html><body><section id="allProducts"><div id="displayCSS"><div class="emptyCategory">此分類沒有相關商品唷！</div></div></section></body></html>'


class ScriptedFetcher(FakeFetcher):
    """Serves one list page body for any request."""

    def __init__(self, body: str) -> None:
        super().__init__()
        self.body = body

    def fetch_list_page(self, url: str) -> str:
        self.calls.append(url)
        return self.body

    @property
    def http_failures(self) -> int:
        return 0


def last_run(tmp_path) -> dict:
    return json.loads((tmp_path / "artifacts" / "kingstone" / "last-run.json").read_text(encoding="utf-8"))


def test_a_failed_run_writes_last_run_and_logs_one_alert_line(tmp_path, capsys):
    harness = Harness(tmp_path)

    assert harness.run() == 1

    data = last_run(tmp_path)
    assert data["status"] == "FAILED"
    assert data["exit_code"] == 1
    assert data["alert_reasons"] == ["failed"]
    assert data["pages_listed"] == 1
    assert data["pages_skipped"][0]["reason"] == "redirect"
    out = capsys.readouterr().out
    assert f"ALERT reasons=failed last_run={tmp_path / 'artifacts' / 'kingstone' / 'last-run.json'}" in out
    assert (tmp_path / "artifacts" / "kingstone" / "history").is_dir()


def test_a_run_whose_only_page_is_empty_succeeds_and_alerts_zero_card_pages(tmp_path, capsys):
    harness = Harness(tmp_path, fetcher=ScriptedFetcher(EMPTY_PAGE))

    assert harness.run() == 0

    data = last_run(tmp_path)
    assert data["status"] == "SUCCESS"
    assert data["exit_code"] == 0
    assert data["pages_completed"] == 1
    assert data["zero_card_pages"] == 1
    assert data["alert_reasons"] == ["zero_card_pages"]
    assert data["http_attempts"] == 1
    assert data["http_failures"] == 0
    assert "ALERT reasons=zero_card_pages" in capsys.readouterr().out


def test_a_schema_prerequisite_missing_writes_the_pre_run_record_and_alerts(tmp_path, capsys, stub_database):
    stub_database["missing"] = ["book_sources.last_seen_at"]
    harness = Harness(tmp_path)

    assert harness.run() == 2

    data = last_run(tmp_path)
    assert data["status"] == "FAILED"
    assert data["exit_code"] == 2
    assert data["reason"] == "SCHEMA_PREREQUISITE_MISSING"
    assert data["pages_not_reached"] is None
    assert data["alert_reasons"] == ["failed", "schema_prerequisite_missing"]
    assert "ALERT reasons=failed,schema_prerequisite_missing" in capsys.readouterr().out


def test_a_busy_first_connection_writes_the_pre_run_record_and_alerts(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(StubSession, "busy", True)
    harness = Harness(tmp_path)

    assert harness.run() == 1

    data = last_run(tmp_path)
    assert data["exit_code"] == 1
    assert data["reason"] == "MAINTENANCE_BUSY"
    assert data["alert_reasons"] == ["failed", "maintenance_busy"]
    assert "ALERT reasons=failed,maintenance_busy" in capsys.readouterr().out


def test_a_disabled_provider_writes_the_pre_run_record_with_exit_2(tmp_path):
    harness = Harness(tmp_path, enabled=False)

    assert harness.run() == 2

    data = last_run(tmp_path)
    assert data["status"] == "FAILED"
    assert data["exit_code"] == 2
    assert data["alert_reasons"] == ["failed"]


def test_an_invalid_page_list_after_the_config_writes_a_record(tmp_path):
    harness = Harness(tmp_path)
    harness.pages.write_text("", encoding="utf-8")

    assert harness.run() == 2

    assert last_run(tmp_path)["exit_code"] == 2


def test_an_invalid_config_writes_nothing_because_the_artifacts_folder_is_unknown(tmp_path, capsys):
    harness = Harness(tmp_path)
    harness.environ["KINGSTONE_SOFT_RUN_BUDGET_SECONDS"] = "abc"

    assert harness.run() == 2

    assert not (tmp_path / "artifacts").exists()
    assert "KINGSTONE_SOFT_RUN_BUDGET_SECONDS" in capsys.readouterr().out


def test_a_missing_database_url_writes_nothing(tmp_path):
    harness = Harness(tmp_path)
    harness.environ.pop("DATABASE_URL")

    assert harness.run() == 2

    assert not (tmp_path / "artifacts").exists()


def test_an_artifact_write_failure_is_logged_and_never_changes_the_exit_code(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(StubSession, "busy", True)
    harness = Harness(tmp_path)
    (tmp_path / "artifacts").write_text("a file, not a folder", encoding="utf-8")  # the kingstone folder cannot be created

    assert harness.run() == 1

    out = capsys.readouterr().out
    assert "ERROR kingstone.artifacts could not write" in out
    assert "maintenance busy" in out


def test_an_all_skipped_run_with_a_failing_artifact_write_still_returns_its_own_code(tmp_path, monkeypatch):
    harness = Harness(tmp_path)
    (tmp_path / "artifacts").write_text("a file, not a folder", encoding="utf-8")

    assert harness.run() == 1
