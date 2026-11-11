"""Provider-neutral run artifacts (catalog_core.run_artifacts), offline, with a non-Kingstone setup.

The directory is ``eslite``, the provider ``ESLITE`` and the logger ``fake.artifacts``: nothing here reads a Kingstone name.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from catalog_core.category_ledger import CategoryLedger, CategoryReport
from catalog_core.models import ProviderCode, WritePolicy
from catalog_core.run_artifacts import (
    HISTORY_RETAIN,
    CategoryArtifacts,
    read_history,
    record_from_report,
    record_pre_run,
)

START = datetime(2026, 10, 25, 1, 0, tzinfo=UTC)
P1 = "https://example.test/list?page=1"
P2 = "https://example.test/list?page=2"


def eslite_report(pages_not_reached: int, *, run_id: str, minutes: int = 1) -> CategoryReport:
    """A report of an ESLITE run: the first page completes with no card, the rest are not reached when asked."""
    urls = [P1] + [f"https://example.test/list?page={n}" for n in range(2, pages_not_reached + 2)]
    ledger = CategoryLedger(
        urls,
        WritePolicy.NORMAL,
        provider_code=ProviderCode.ESLITE,
        logger=logging.getLogger("fake.ledger"),
        report_class=CategoryReport,
    )
    ledger.page_started(P1, items_listed=0)
    ledger.page_completed(P1)
    if pages_not_reached:
        ledger.stop_for_budget()
    return ledger.report(run_id=run_id, started_at=START, finished_at=START + timedelta(minutes=minutes), http_attempts=1, http_failures=0)


def eslite_record(pages_not_reached: int, *, run_id: str, minutes: int) -> dict:
    return record_from_report(eslite_report(pages_not_reached, run_id=run_id, minutes=minutes))


def store(root: Path, **kwargs) -> CategoryArtifacts:
    return CategoryArtifacts(root, directory_name="eslite", logger_name="fake.artifacts", **kwargs)


def test_files_land_under_the_provider_directory_and_no_other(tmp_path):
    record = eslite_record(0, run_id="run-a", minutes=1)
    store(tmp_path).publish(record)

    assert json.loads((tmp_path / "eslite" / "last-run.json").read_text(encoding="utf-8"))["run_id"] == "run-a"
    assert (tmp_path / "eslite" / "history" / "run-a.json").is_file()
    assert not (tmp_path / "kingstone").exists()


def test_the_record_carries_the_provider_of_the_report(tmp_path):
    final = store(tmp_path).publish(eslite_record(0, run_id="run-a", minutes=1))

    assert final["provider"] == "ESLITE"
    assert final["alert_reasons"] == ["zero_card_pages"]  # one completed page that listed no card


def test_a_pre_run_record_takes_the_given_provider():
    record = record_pre_run(
        provider="ESLITE",
        run_id="run-x",
        status="FAILED",
        exit_code=2,
        reason=None,
        write_policy="NORMAL",
        started_at=START,
        finished_at=START,
        error="no pages",
    )

    assert record["provider"] == "ESLITE"
    assert record["pages_not_reached"] is None
    assert record["error"] == "no pages"


def test_the_streak_alert_needs_three_runs_with_pages_not_reached(tmp_path):
    artifacts = store(tmp_path)
    artifacts.publish(eslite_record(1, run_id="run-1", minutes=1))
    artifacts.publish(eslite_record(1, run_id="run-2", minutes=2))

    final = artifacts.publish(eslite_record(1, run_id="run-3", minutes=3))

    assert "pages_not_reached_streak" in final["alert_reasons"]


def test_history_is_pruned_to_the_retain_count_and_read_newest_first(tmp_path):
    artifacts = store(tmp_path, history_retain=2)
    for minute in range(1, 4):
        artifacts.publish(eslite_record(0, run_id=f"run-{minute}", minutes=minute))

    names = sorted(path.name for path in (tmp_path / "eslite" / "history").glob("*.json"))
    assert names == ["run-2.json", "run-3.json"]
    assert [entry["run_id"] for entry in read_history(tmp_path / "eslite" / "history", logging.getLogger("fake.artifacts"))] == [
        "run-3",
        "run-2",
    ]
    assert HISTORY_RETAIN == 20


def test_a_failed_history_write_is_logged_on_the_given_logger_and_never_raises(tmp_path, caplog):
    (tmp_path / "eslite").mkdir()
    (tmp_path / "eslite" / "history").write_text("a file, not a folder", encoding="utf-8")
    artifacts = store(tmp_path)

    with caplog.at_level(logging.ERROR, logger="fake.artifacts"):
        final = artifacts.publish(eslite_record(0, run_id="run-a", minutes=1))

    assert final["run_id"] == "run-a"
    assert (tmp_path / "eslite" / "last-run.json").is_file()
    assert any(
        record.name == "fake.artifacts" and record.levelno == logging.ERROR and "could not write the eslite history under" in record.getMessage()
        for record in caplog.records
    )


def test_an_unreadable_history_entry_is_skipped_with_a_warning_on_the_given_logger(tmp_path, caplog):
    history = tmp_path / "eslite" / "history"
    history.mkdir(parents=True)
    (history / f"{uuid.uuid4()}.json").write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="fake.artifacts"):
        assert read_history(history, logging.getLogger("fake.artifacts")) == []

    assert any(record.name == "fake.artifacts" and "skipping unreadable history entry" in record.getMessage() for record in caplog.records)
