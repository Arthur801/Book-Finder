"""Kingstone run artifacts (kingstone.artifacts), offline: temporary folders, fixed times, no network, no database.

The reports are built with the real ledger, so the records have the fields the ledger really produces.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from catalog_core.models import CatalogResolution, ProviderCode, SourceRef, WritePolicy
from catalog_core.service import ItemFailed, ItemResolved
from kingstone import artifacts
from kingstone.artifacts import HISTORY_RETAIN, KingstoneArtifacts, atomic_write_json, read_history, record_from_report, record_pre_run
from kingstone.ledger import KingstoneLedger, SkippedPage

START = datetime(2026, 10, 25, 1, 0, tzinfo=UTC)
P1 = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1"
P2 = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=2"
DETAIL = "https://www.kingstone.com.tw/basic/2018630959191/"


def finished(minutes: int) -> datetime:
    return START + timedelta(minutes=minutes)


def existing_card(ledger: KingstoneLedger, page: str, external_id: str) -> None:
    source = SourceRef(source_id=uuid.uuid4(), book_id=uuid.uuid4())
    ledger.record_item(page, ItemResolved(source, CatalogResolution.EXISTING, attempts=1), source_url=DETAIL, external_id=external_id)


def report_with(pages_not_reached: int, *, run_id: str | None = None, finished_minutes: int = 1):
    """A report with ``pages_not_reached`` listed pages never reached. The first page completes with one card."""
    urls = [P1] + [f"https://www.kingstone.com.tw/book/jdc/?dis=list&page={n}" for n in range(2, pages_not_reached + 2)]
    ledger = KingstoneLedger(urls, WritePolicy.NEW_BOOKS_ONLY)
    ledger.page_started(P1, items_listed=1)
    existing_card(ledger, P1, "2018630959191")
    ledger.page_completed(P1)
    if pages_not_reached:
        ledger.stop_for_budget()
    return ledger.report(
        run_id=run_id or f"run-{uuid.uuid4()}",
        started_at=START,
        finished_at=finished(finished_minutes),
        http_attempts=4,
        http_failures=1,
    )


def record_for(pages_not_reached: int, *, run_id: str, minutes: int) -> dict:
    return record_from_report(report_with(pages_not_reached, run_id=run_id, finished_minutes=minutes))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# last-run.json: atomic write and fields
# ---------------------------------------------------------------------------


def test_last_run_holds_the_terminal_fields_and_the_alert_reasons(tmp_path):
    store = KingstoneArtifacts(tmp_path)
    ledger = KingstoneLedger([P1, P2], WritePolicy.NEW_BOOKS_ONLY)
    ledger.record_page_skipped(SkippedPage(url=P2, reason="fetch_error", message="HTTP 503", attempts=3))
    ledger.page_started(P1, items_listed=2)
    ledger.record_detail_fetch()
    existing_card(ledger, P1, "2018630959191")
    existing_card(ledger, P1, "2018564008187")
    ledger.page_completed(P1)
    report = ledger.report(run_id="run-a", started_at=START, finished_at=finished(2), http_attempts=5, http_failures=2)

    reasons = store.publish(record_from_report(report))

    data = read_json(store.last_run_path)
    assert reasons == []
    assert data["run_id"] == "run-a"
    assert data["provider"] == ProviderCode.KINGSTONE.value
    assert data["status"] == "PARTIAL_SUCCESS"
    assert data["exit_code"] == 0
    assert data["write_policy"] == "new-books-only"
    assert data["started_at"] == START.isoformat()
    assert data["finished_at"] == finished(2).isoformat()
    assert data["pages_listed"] == 2
    assert data["pages_completed"] == 1
    assert data["pages_skipped"] == [{"url": P2, "reason": "fetch_error", "message": "HTTP 503", "attempts": 3}]
    assert data["pages_interrupted"] == 0
    assert data["pages_not_reached"] == 0
    assert data["items_listed"] == 2
    assert data["details_fetched"] == 1
    assert data["existing_source"] == 2
    assert data["http_attempts"] == 5
    assert data["http_failures"] == 2
    assert data["alert_reasons"] == []
    for key in ("imported", "isbn_attached", "ambiguous_created", "policy_skipped", "recovered_commit_count", "failed"):
        assert data[key] == 0


def test_the_record_carries_resolution_counts_and_failed_items(tmp_path):
    ledger = KingstoneLedger([P1], WritePolicy.NORMAL)
    ledger.page_started(P1, items_listed=3)
    ledger.record_detail_fetch()
    ledger.record_item(
        P1,
        ItemResolved(SourceRef(source_id=uuid.uuid4(), book_id=uuid.uuid4()), CatalogResolution.IMPORTED, attempts=1),
        source_url=DETAIL,
        external_id="2018630959191",
    )
    ledger.record_item(P1, ItemFailed("parse_error", "bad layout", attempts=2), source_url=DETAIL, external_id="2018630959191")
    ledger.page_completed(P1)
    report = ledger.report(run_id="run-b", started_at=START, finished_at=finished(3))

    data = record_from_report(report)

    assert data["imported"] == 1
    assert data["failed"] == 1
    assert data["items_seen"] == 2
    assert data["items_listed"] == 3
    assert data["failed_items"] == [
        {"list_url": P1, "source_url": DETAIL, "external_id": "2018630959191", "reason": "parse_error", "message": "bad layout", "attempts": 2}
    ]


def test_the_pre_run_record_has_zero_counts_and_an_unknown_page_count():
    data = record_pre_run(
        run_id="run-c",
        status="FAILED",
        exit_code=2,
        reason="SCHEMA_PREREQUISITE_MISSING",
        write_policy="new-books-only",
        started_at=START,
        finished_at=finished(0),
    )

    assert data["status"] == "FAILED"
    assert data["exit_code"] == 2
    assert data["reason"] == "SCHEMA_PREREQUISITE_MISSING"
    assert data["pages_not_reached"] is None
    assert data["items_listed"] == 0
    assert data["http_attempts"] == 0
    assert data["pages_skipped"] == []


def test_every_message_is_redacted_before_it_is_written(tmp_path):
    secret = "postgresql://kingstone_user:hunter2@db.internal:5432/books"
    ledger = KingstoneLedger([P1], WritePolicy.NORMAL)
    ledger.record_page_skipped(SkippedPage(url=P1, reason="fetch_error", message=f"boom {secret} password=hunter3", attempts=3))
    report = ledger.report(run_id="run-d", started_at=START, finished_at=finished(0), error=f"fatal {secret}")
    store = KingstoneArtifacts(tmp_path)

    store.publish(record_from_report(report))

    text = store.last_run_path.read_text(encoding="utf-8")
    assert "hunter2" not in text and "hunter3" not in text
    assert "kingstone_user" not in text
    assert "postgresql://<redacted>" in text


def test_a_failed_atomic_replace_keeps_the_previous_file_and_leaves_no_temp_file(tmp_path, monkeypatch):
    target = tmp_path / "last-run.json"
    atomic_write_json(target, {"run_id": "old"})

    def broken_replace(src, dst):
        raise OSError("disk gone")

    monkeypatch.setattr(artifacts.os, "replace", broken_replace)
    with pytest.raises(OSError):
        atomic_write_json(target, {"run_id": "new"})

    assert read_json(target) == {"run_id": "old"}
    assert [p.name for p in tmp_path.iterdir()] == ["last-run.json"]


def test_the_write_is_flushed_and_synced_before_the_replace(tmp_path, monkeypatch):
    synced = []
    real_fsync = os.fsync

    def recording_fsync(fd):
        synced.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(artifacts.os, "fsync", recording_fsync)
    atomic_write_json(tmp_path / "x.json", {"a": 1})

    assert synced  # at least the file itself


def test_a_write_failure_is_logged_and_the_alert_reasons_are_still_returned(tmp_path, caplog):
    store = KingstoneArtifacts(tmp_path)
    store.directory.parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "kingstone").write_text("not a folder", encoding="utf-8")  # every write under it fails
    record = record_from_report(report_with(0, run_id="run-e"))

    with caplog.at_level(logging.ERROR, logger="kingstone.artifacts"):
        reasons = store.publish(record)

    assert reasons == []
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and "could not write" in errors[0].getMessage()


# ---------------------------------------------------------------------------
# history: bounded, readable entries only
# ---------------------------------------------------------------------------


def test_the_history_keeps_only_the_newest_twenty_entries(tmp_path):
    store = KingstoneArtifacts(tmp_path)
    for n in range(HISTORY_RETAIN + 5):
        store.publish(record_for(0, run_id=f"run-{n:02d}", minutes=n))

    files = sorted(p.name for p in store.history_dir.glob("*.json"))

    assert len(files) == HISTORY_RETAIN
    assert "run-00.json" not in files  # the oldest is deleted
    assert f"run-{HISTORY_RETAIN + 4:02d}.json" in files
    summary = read_json(store.history_dir / f"run-{HISTORY_RETAIN + 4:02d}.json")
    assert set(summary) >= {"run_id", "finished_at", "status", "pages_not_reached"}


def test_unreadable_history_entries_are_skipped_with_a_warning(tmp_path, caplog):
    store = KingstoneArtifacts(tmp_path)
    store.history_dir.mkdir(parents=True)
    (store.history_dir / "broken.json").write_text("{not json", encoding="utf-8")
    (store.history_dir / "list.json").write_text("[1, 2]", encoding="utf-8")
    (store.history_dir / "naive.json").write_text(
        json.dumps({"run_id": "naive", "finished_at": "2026-10-25T01:00:00", "status": "SUCCESS", "pages_not_reached": 0}),
        encoding="utf-8",
    )
    (store.history_dir / "good.json").write_text(
        json.dumps({"run_id": "good", "finished_at": finished(1).isoformat(), "status": "SUCCESS", "pages_not_reached": 0}),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="kingstone.artifacts"):
        entries = read_history(store.history_dir)

    assert [entry["run_id"] for entry in entries] == ["good"]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 3
    assert any("broken.json" in message for message in warnings)


def test_a_missing_history_folder_is_an_empty_history(tmp_path):
    assert read_history(tmp_path / "nowhere") == []


def test_history_is_ordered_by_finished_at_not_by_file_name(tmp_path):
    store = KingstoneArtifacts(tmp_path)
    store.publish(record_for(0, run_id="zzz-first", minutes=1))
    store.publish(record_for(0, run_id="aaa-second", minutes=5))

    assert [entry["run_id"] for entry in read_history(store.history_dir)] == ["aaa-second", "zzz-first"]


# ---------------------------------------------------------------------------
# streak: pages_not_reached on three runs in a row
# ---------------------------------------------------------------------------


def run_sequence(store: KingstoneArtifacts, counts: list[int]) -> list[list[str]]:
    results = []
    for n, count in enumerate(counts):
        results.append(store.publish(record_for(count, run_id=f"run-{n:02d}", minutes=n + 1)))
    return results


def test_the_first_and_second_runs_above_zero_do_not_alert(tmp_path):
    results = run_sequence(KingstoneArtifacts(tmp_path), [2, 2])

    assert results == [[], []]


def test_the_third_run_above_zero_alerts_once_and_later_runs_keep_alerting(tmp_path):
    results = run_sequence(KingstoneArtifacts(tmp_path), [2, 2, 2, 2])

    assert results == [[], [], ["pages_not_reached_streak"], ["pages_not_reached_streak"]]


def test_a_run_with_zero_pages_not_reached_resets_the_streak(tmp_path):
    results = run_sequence(KingstoneArtifacts(tmp_path), [2, 2, 0, 2, 2, 2])

    assert results == [[], [], [], [], [], ["pages_not_reached_streak"]]


def test_the_current_run_is_counted_once_because_the_history_is_read_before_it_is_written(tmp_path):
    store = KingstoneArtifacts(tmp_path)
    run_sequence(store, [2, 2])

    reasons = store.publish(record_for(2, run_id="run-02", minutes=3))

    assert reasons == ["pages_not_reached_streak"]
    assert len(list(store.history_dir.glob("*.json"))) == 3


def test_a_broken_history_entry_is_not_counted_in_the_streak(tmp_path, caplog):
    store = KingstoneArtifacts(tmp_path)
    run_sequence(store, [2, 2])
    (store.history_dir / "run-01.json").write_text("garbage", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="kingstone.artifacts"):
        reasons = store.publish(record_for(2, run_id="run-02", minutes=3))

    assert reasons == []  # only run-00 is readable: the streak is not established
    assert any("run-01.json" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_an_unreadable_entry_stops_the_streak_check_so_older_entries_cannot_bridge_a_reset(tmp_path, caplog):
    store = KingstoneArtifacts(tmp_path)
    run_sequence(store, [2, 0, 2])  # run-01 reset the streak
    (store.history_dir / "run-01.json").write_text("garbage", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="kingstone.artifacts"):
        reasons = store.publish(record_for(2, run_id="run-03", minutes=4))

    # Skipping run-01 would leave run-03, run-02 and run-00 all above 0: a false streak. It is not evaluated.
    assert reasons == []
    assert any("streak not evaluated" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_a_pre_run_result_with_no_page_count_does_not_count_and_does_not_reset(tmp_path):
    store = KingstoneArtifacts(tmp_path)
    run_sequence(store, [2, 2])
    store.publish(
        record_pre_run(run_id="busy", status="FAILED", exit_code=1, reason="MAINTENANCE_BUSY", write_policy="normal", started_at=START, finished_at=finished(9))
    )

    reasons = store.publish(record_for(2, run_id="run-03", minutes=10))

    assert "maintenance_busy" not in reasons
    assert "pages_not_reached_streak" not in reasons  # the busy entry is in the window and has no count
