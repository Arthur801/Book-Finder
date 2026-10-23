"""Tests for bookfinder_host.history: append-only run records and the status rules of N7.

Why: history.jsonl is the durable answer to "did this deploy finish". The status rules decide whether an operator must
intervene, so each branch is tested, including the ones where the systemd unit state disagrees with the record.
"""

import os
import stat

import pytest
from bookfinder_host import history as hi

RUN = "123456-7"
OTHER = "999-1"
UNIT = "book-finder-deploy-123456-7"
TARGET = {"tag": "v1.1.0", "web_digest": "sha256:" + "2" * 64, "crawler_digest": "sha256:" + "3" * 64}
SUMMARY = {"revision": 3, "runtime": "sha256:" + "1" * 64, "schema_digest": "sha256:" + "4" * 64, "dirty": False}


def started(run_id=RUN):
    return hi.started_record(run_id=run_id, unit=f"book-finder-deploy-{run_id}", at="t0", target=TARGET, expected_revision=3)


def completed(run_id=RUN, result="ok", exit_code=0):
    return hi.completed_record(run_id=run_id, result=result, exit_code=exit_code, at="t1", state_summary=SUMMARY)


def write_lines(path, *lines, trailing_newline=True):
    text = "\n".join(lines) + ("\n" if trailing_newline and lines else "")
    path.write_text(text, encoding="utf-8")
    return path


def test_append_writes_one_json_line_with_mode_0600(tmp_path):
    path = tmp_path / "history.jsonl"
    hi.append(path, started())
    hi.append(path, completed())
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert '"phase":"started"' in lines[0]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_append_refuses_a_record_at_or_above_pipe_buf(tmp_path):
    path = tmp_path / "history.jsonl"
    record = completed()
    record["state_summary"] = {"blob": "x" * 4096}
    with pytest.raises(ValueError):
        hi.append(path, record)
    assert not path.exists() or path.read_bytes() == b""


def test_read_missing_file_is_empty(tmp_path):
    records = hi.read(tmp_path / "history.jsonl")
    assert records.entries == [] and records.tail_corrupt is False


def test_read_returns_records_in_order(tmp_path):
    path = tmp_path / "history.jsonl"
    hi.append(path, started())
    hi.append(path, completed())
    records = hi.read(path)
    assert [r["phase"] for r in records.entries] == ["started", "completed"]
    assert records.tail_corrupt is False


def test_last_line_without_newline_is_tail_corrupt_and_excluded(tmp_path):
    path = tmp_path / "history.jsonl"
    full = hi.serialize(started())
    path.write_text(full + hi.serialize(completed())[:-1], encoding="utf-8")
    records = hi.read(path)
    assert records.tail_corrupt is True
    assert [r["phase"] for r in records.entries] == ["started"]


def test_last_line_with_invalid_json_is_tail_corrupt(tmp_path):
    path = write_lines(tmp_path / "history.jsonl", hi.serialize(started())[:-1], '{"phase": "comp')
    records = hi.read(path)
    assert records.tail_corrupt is True
    assert len(records.entries) == 1


def test_corrupt_middle_line_raises(tmp_path):
    path = write_lines(tmp_path / "history.jsonl", "{broken", hi.serialize(completed())[:-1])
    with pytest.raises(hi.HistoryCorrupt):
        hi.read(path)


def test_read_rejects_symlink(tmp_path):
    real = write_lines(tmp_path / "real.jsonl", hi.serialize(started())[:-1])
    link = tmp_path / "history.jsonl"
    link.symlink_to(real)
    with pytest.raises(hi.HistoryCorrupt):
        hi.read(link)


# status: rules ①-④ of N7


def test_completed_wins_even_when_unit_reports_active():
    records = hi.Records([started(), completed(result="failed-migration", exit_code=4)], tail_corrupt=False)
    assert hi.status(records, RUN, "active") == "completed:failed-migration"


def test_started_with_active_unit_is_running():
    records = hi.Records([started()], tail_corrupt=False)
    assert hi.status(records, RUN, "activating") == "running"


def test_started_with_dead_unit_is_indeterminate():
    records = hi.Records([started()], tail_corrupt=False)
    for unit_state in ("inactive", "failed", "missing"):
        assert hi.status(records, RUN, unit_state) == "indeterminate"


def test_tail_corrupt_without_completed_is_indeterminate_even_if_unit_active():
    records = hi.Records([started()], tail_corrupt=True)
    assert hi.status(records, RUN, "active") == "indeterminate"


def test_tail_corrupt_with_no_records_is_indeterminate_because_started_may_be_the_lost_line():
    assert hi.status(hi.Records([], tail_corrupt=True), RUN, "missing") == "indeterminate"


def test_no_records_and_no_unit_is_not_started():
    assert hi.status(hi.Records([], tail_corrupt=False), RUN, "missing") == "not-started"


def test_unit_present_without_started_record_is_indeterminate():
    assert hi.status(hi.Records([], tail_corrupt=False), RUN, "failed") == "indeterminate"


def test_status_rejects_unknown_unit_state():
    with pytest.raises(ValueError):
        hi.status(hi.Records([], tail_corrupt=False), RUN, "reloading")


def test_status_only_considers_the_given_run():
    records = hi.Records([started(OTHER), completed(OTHER)], tail_corrupt=False)
    assert hi.status(records, RUN, "missing") == "not-started"


# unresolved_indeterminate: gates plan and deploy with exit 8


def test_unresolved_lists_started_runs_without_completed_and_dead_units():
    records = hi.Records([started(RUN), started(OTHER), completed(OTHER)], tail_corrupt=False)
    assert hi.unresolved_indeterminate(records, {RUN: "inactive"}) == [RUN]


def test_unresolved_ignores_runs_whose_unit_is_still_active():
    records = hi.Records([started(RUN)], tail_corrupt=False)
    assert hi.unresolved_indeterminate(records, {RUN: "active"}) == []


def test_resolved_operator_record_clears_the_run():
    resolved = hi.completed_record(
        run_id=RUN,
        result="failed-down",
        exit_code=5,
        at="t9",
        state_summary=SUMMARY,
        resolved_by_operator=True,
        operator="alice",
        reason="checked journal and DB",
    )
    records = hi.Records([started(RUN), resolved], tail_corrupt=False)
    assert hi.unresolved_indeterminate(records, {}) == []
    assert hi.status(records, RUN, "missing") == "completed:failed-down"
    assert resolved["resolved_by_operator"] is True
