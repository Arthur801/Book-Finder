"""Append-only run history (history.jsonl): the durable source of truth for how a deploy ended (N7).

Why: systemd forgets transient units and their journals (--collect), so the unit state cannot prove an outcome. Each run
writes a "started" record before it takes any lock or changes anything, and a "completed" record when it ends. The
status rules below read the completed record first; the unit state only tells whether a run without one is still
running, and never changes an answer once the records say what happened.
"""

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from typing import Any

from bookfinder_host.safefile import UnsafeFileError, read_regular_file

# A single write of fewer than PIPE_BUF bytes to an O_APPEND file is atomic on Linux, so concurrent appends never interleave.
PIPE_BUF = 4096
MAX_HISTORY_BYTES = 64 << 20
ACTIVE_STATES = frozenset({"active", "activating"})
UNIT_STATES = frozenset({"active", "activating", "inactive", "failed", "missing"})
# Operator operations (M3c) are recorded as operator-started / operator-completed pairs keyed by op_id (see operator_cli).
OPERATOR_STARTED = "operator-started"
OPERATOR_COMPLETED = "operator-completed"
OP_PREFIX = "op-"
OP_ID_RE = re.compile(r"op-[0-9]{14}-[0-9a-f]{4}")


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


def operator_started_record(*, op_id: str, action: str, at: str, operator: str, reason: str, intended: dict[str, Any], before: Any) -> dict[str, Any]:
    """Written and fsynced before an operator command changes anything (M3c)."""
    return {
        "phase": OPERATOR_STARTED,
        "op_id": op_id,
        "action": action,
        "at": at,
        "operator": operator,
        "reason": reason,
        "intended": intended,
        "before": before,
    }


def operator_completed_record(*, op_id: str, action: str, at: str, result: str, before: Any, after: Any, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "phase": OPERATOR_COMPLETED,
        "op_id": op_id,
        "action": action,
        "at": at,
        "result": result,
        "before": before,
        "after": after,
    }
    record.update(extra or {})
    return record


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
    crawler_substeps: dict[str, str] | str | None = None,
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
    """Implements N7 ①-④, in this order and independent of whether systemd still remembers the unit.

    ① a completed record gives "completed:<result>";
    ② otherwise an active or activating unit gives "running";
    ③ otherwise a started record, or an incomplete final line, gives "indeterminate";
    ④ otherwise "not-started": started is written before anything changes, so no started record means nothing changed.
    The unit state after ① only decides between "running" and the records, so systemd garbage collection (--collect)
    of a failed unit never changes the answer.
    """
    if unit_state not in UNIT_STATES:
        raise ValueError(f"unknown unit state: {unit_state}")
    completed = _completed_for(records, run_id)
    if completed is not None:
        return f"completed:{completed['result']}"
    if unit_state in ACTIVE_STATES:
        return "running"
    if records.tail_corrupt or _started_for(records, run_id):
        return "indeterminate"
    return "not-started"


def open_operations(records: Records) -> list[str]:
    """Operator op ids with an operator-started record and no operator-completed record (M3c).

    Such an operation may have changed the host or state before it stopped, so it is indeterminate, like a run.
    """
    completed = {entry.get("op_id") for entry in records.entries if entry.get("phase") == OPERATOR_COMPLETED}
    opened: list[str] = []
    for entry in records.entries:
        op_id = entry.get("op_id")
        if entry.get("phase") == OPERATOR_STARTED and op_id not in completed and op_id not in opened:
            opened.append(op_id)
    return opened


def unresolved_indeterminate(records: Records, unit_states: dict[str, str]) -> list[str]:
    """Ids that block plan and deploy as indeterminate.

    Run ids: a started record, no completed record, and no active unit (a run without an entry in unit_states counts as
    "missing", so it is listed). Operator op ids (prefix "op-") come after them: an operator-started record with no
    operator-completed record blocks everything until resolve-run names it.
    """
    unresolved = []
    for entry in records.entries:
        run_id = entry.get("run_id")
        if entry.get("phase") != "started" or run_id in unresolved:
            continue
        if _completed_for(records, run_id) is not None:
            continue
        if unit_states.get(run_id, "missing") not in ACTIVE_STATES:
            unresolved.append(run_id)
    return unresolved + open_operations(records)


def _fsync_dir(directory: str) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def preserve_tail(path: str | os.PathLike[str], run_id: str, stamp: str) -> dict[str, Any] | None:
    """Keeps the exact bytes of an incomplete final line in a sidecar file; history itself is not changed here.

    Why: history is the durable record, so the bytes that a repair removes must stay recoverable. The sidecar is created
    exclusively with mode 0600, written and fsynced (file and directory) before the caller rewrites history. Returns
    None when there is no fragment, otherwise the sidecar path, byte count, sha256 and the cut offset in history.
    """
    name = os.fspath(path)
    data = read_regular_file(name, MAX_HISTORY_BYTES)
    cut = data.rfind(b"\n") + 1
    fragment = data[cut:]
    if not fragment:
        return None
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
    return {"path": sidecar, "bytes": len(fragment), "sha256": hashlib.sha256(fragment).hexdigest(), "cut": cut}


def rewrite_with_record(path: str | os.PathLike[str], cut: int, record: dict[str, Any]) -> None:
    """Atomically replaces history with its first cut bytes followed by one record (the tail repair plus its started record).

    Why: the damaged fragment must go before the operator's started record can be written, and a plain append would
    turn it into a damaged middle line. One rename removes the fragment and adds the record together, so no crash point
    leaves the fragment gone without the record, or the record in front of the fragment.
    """
    name = os.fspath(path)
    data = read_regular_file(name, MAX_HISTORY_BYTES)
    if cut > len(data) or (cut and data[cut - 1 : cut] != b"\n"):
        raise HistoryCorrupt("history changed since it was read; the tail repair was not applied")
    line = serialize(record).encode("ascii")
    directory = os.path.dirname(os.path.abspath(name))
    fd, temporary = tempfile.mkstemp(prefix=".history.", suffix=".tmp", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data[:cut] + line)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, name)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    _fsync_dir(directory)
