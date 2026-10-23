"""Append-only run history (history.jsonl): the durable source of truth for how a deploy ended (N7).

Why: systemd forgets transient units and their journals, so the unit state cannot prove an outcome. Each run writes a
"started" record before it changes anything and a "completed" record when it ends; the status rules below read only
these records, with the unit state used only where the records are silent.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

from bookfinder_host.safefile import UnsafeFileError, read_regular_file

# A single write of fewer than PIPE_BUF bytes to an O_APPEND file is atomic on Linux, so concurrent appends never interleave.
PIPE_BUF = 4096
MAX_HISTORY_BYTES = 64 << 20
ACTIVE_STATES = frozenset({"active", "activating"})
UNIT_STATES = frozenset({"active", "activating", "inactive", "failed", "missing"})


class HistoryCorrupt(Exception):
    """A line other than the last one is damaged, or the file is not a regular file."""


@dataclass(frozen=True)
class Records:
    entries: list[dict[str, Any]]
    # True when the final line is incomplete or unparsable: a crash may have lost a record, so the status is unknown.
    tail_corrupt: bool


def serialize(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def started_record(*, run_id: str, unit: str, at: str, target: dict[str, str], expected_revision: int) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "unit": unit,
        "phase": "started",
        "at": at,
        "target": target,
        "expected_revision": expected_revision,
    }


def completed_record(
    *,
    run_id: str,
    result: str,
    exit_code: int,
    at: str,
    state_summary: dict[str, Any],
    resolved_by_operator: bool = False,
    operator: str | None = None,
    reason: str | None = None,
    snapshot_id: str | None = None,
    crawler_substeps: dict[str, str] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "run_id": run_id,
        "phase": "completed",
        "result": result,
        "exit_code": exit_code,
        "at": at,
        "state_summary": state_summary,
    }
    if snapshot_id is not None:
        record["snapshot_id"] = snapshot_id
    if crawler_substeps is not None:
        # Lets resume-crawler (M3c) see which crawler sub-steps already took effect.
        record["crawler_substeps"] = crawler_substeps
    if resolved_by_operator:
        record.update({"resolved_by_operator": True, "operator": operator, "reason": reason})
    return record


def append(path: str | os.PathLike[str], record: dict[str, Any]) -> None:
    line = serialize(record).encode("ascii")
    # Refusing long lines keeps every append a single atomic write; a split line would corrupt the tail.
    if len(line) >= PIPE_BUF:
        raise ValueError(f"history record is {len(line)} bytes; must be under {PIPE_BUF}")
    fd = os.open(
        os.fspath(path),
        os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        written = os.write(fd, line)
        if written != len(line):
            raise OSError(f"short history write: {written} of {len(line)} bytes")
        os.fsync(fd)
    finally:
        os.close(fd)


def _parse_line(line: str) -> dict[str, Any] | None:
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    return entry if isinstance(entry, dict) else None


def read(path: str | os.PathLike[str]) -> Records:
    try:
        data = read_regular_file(os.fspath(path), MAX_HISTORY_BYTES)
    except FileNotFoundError:
        return Records([], tail_corrupt=False)
    except UnsafeFileError as exc:
        raise HistoryCorrupt(str(exc)) from exc
    text = data.decode("utf-8", errors="replace")
    lines = text.split("\n")
    # split leaves an empty last element when the file ends with a newline; anything else is an unterminated tail.
    unterminated = lines.pop()
    entries: list[dict[str, Any]] = []
    tail_corrupt = unterminated != ""
    for index, line in enumerate(lines):
        entry = _parse_line(line)
        if entry is None:
            # Only the final line may be damaged: a crash during append can truncate it, nothing else can.
            if index == len(lines) - 1:
                tail_corrupt = True
                break
            raise HistoryCorrupt(f"history line {index + 1} is damaged")
        entries.append(entry)
    return Records(entries, tail_corrupt=tail_corrupt)


def _completed_for(records: Records, run_id: str) -> dict[str, Any] | None:
    for entry in records.entries:
        if entry.get("run_id") == run_id and entry.get("phase") == "completed":
            return entry
    return None


def _started_for(records: Records, run_id: str) -> bool:
    return any(entry.get("run_id") == run_id and entry.get("phase") == "started" for entry in records.entries)


def status(records: Records, run_id: str, unit_state: str) -> str:
    """Implements N7 ①-④. The completed record is authoritative; the unit state only fills gaps."""
    if unit_state not in UNIT_STATES:
        raise ValueError(f"unknown unit state: {unit_state}")
    completed = _completed_for(records, run_id)
    if completed is not None:
        return f"completed:{completed['result']}"
    if records.tail_corrupt:
        return "indeterminate"
    if unit_state in ACTIVE_STATES:
        return "running"
    if _started_for(records, run_id) or unit_state != "missing":
        return "indeterminate"
    return "not-started"


def unresolved_indeterminate(records: Records, unit_states: dict[str, str]) -> list[str]:
    """Run ids with a started record, no completed record, and a unit that is no longer active."""
    unresolved = []
    for entry in records.entries:
        run_id = entry.get("run_id")
        if entry.get("phase") != "started" or run_id in unresolved:
            continue
        if _completed_for(records, run_id) is not None:
            continue
        if unit_states.get(run_id, "missing") not in ACTIVE_STATES:
            unresolved.append(run_id)
    return unresolved


def _fsync_dir(directory: str) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def preserve_and_truncate_tail(path: str | os.PathLike[str], run_id: str, stamp: str) -> dict[str, Any]:
    """Keeps the exact bytes of an incomplete final line in a sidecar file, then removes them from history.

    Why: history is the durable record, so dropped bytes must stay recoverable. The sidecar is created exclusively with
    mode 0600, written and fsynced (file and directory) before history is truncated; if any step before the truncation
    fails, history is unchanged. Returns the sidecar path, byte count and sha256 for the operator record.
    """
    name = os.fspath(path)
    data = read_regular_file(name, MAX_HISTORY_BYTES)
    cut = data.rfind(b"\n") + 1
    fragment = data[cut:]
    if not fragment:
        return {"path": None, "bytes": 0, "sha256": None}
    directory = os.path.dirname(os.path.abspath(name))
    sidecar = f"{name}.tail-{stamp}-{run_id}"
    fd = os.open(sidecar, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        try:
            view = memoryview(fragment)
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            fd = -1
            os.unlink(sidecar)
            raise
    finally:
        if fd >= 0:
            os.close(fd)
    _fsync_dir(directory)
    os.truncate(name, cut)
    _fsync_dir(directory)
    return {"path": sidecar, "bytes": len(fragment), "sha256": hashlib.sha256(fragment).hexdigest()}
