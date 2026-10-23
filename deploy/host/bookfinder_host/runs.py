"""Run-level queries shared by the SSH side (launch, follow, status) and the unit: unit state and the N7 rules.

Why: launch, follow and status must agree on what "running", "indeterminate" and "not-started" mean, so the rules
live once here and read only the history and the unit state.
"""

import re

from bookfinder_host import history as hi
from bookfinder_host.config import Settings
from bookfinder_host.ports import Runner
from bookfinder_host.runtime import ObservationError

UNIT_PREFIX = "book-finder-deploy-"
# Kept in step with commands.RUN_ID_RE; history values are re-checked here because they are read back from disk.
_RUN_ID_RE = re.compile(r"[0-9]{1,20}-[0-9]{1,4}")


def unit_name(run_id: str) -> str:
    return f"{UNIT_PREFIX}{run_id}"


def unit_state(runner: Runner, unit: str) -> str:
    result = runner.run(["systemctl", "show", "--property=LoadState", "--property=ActiveState", unit])
    if result.returncode != 0:
        raise ObservationError(f"systemctl show failed for {unit}")
    properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if properties.get("LoadState") == "not-found":
        return "missing"
    mapping = {
        "active": "active",
        "reloading": "active",
        "deactivating": "active",  # still running until it finishes, so not safe to call dead
        "activating": "activating",
        "inactive": "inactive",
        "failed": "failed",
    }
    active = properties.get("ActiveState", "")
    if active not in mapping:
        raise ObservationError(f"unexpected ActiveState for {unit}: {active!r}")
    return mapping[active]


def unit_load_state(runner: Runner, unit: str) -> str:
    """LoadState only: "not-found" means no unit of that name exists, including one that already finished."""
    result = runner.run(["systemctl", "show", "-p", "LoadState", "--value", unit])
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise ObservationError(f"systemctl show LoadState failed for {unit}")
    return value


def open_run_ids(records: hi.Records) -> list[str]:
    completed = {entry.get("run_id") for entry in records.entries if entry.get("phase") == "completed"}
    open_runs: list[str] = []
    for entry in records.entries:
        run_id = entry.get("run_id")
        if entry.get("phase") == "started" and run_id not in completed and run_id not in open_runs:
            open_runs.append(run_id)
    return open_runs


def indeterminate_reasons(settings: Settings, runner: Runner) -> list[str]:
    """Every reason that history blocks plan and deploy (exit 8, N7)."""
    try:
        records = hi.read(settings.history_file)
    except hi.HistoryCorrupt as exc:
        return [f"history: {exc}"]
    reasons = ["history: final line is incomplete"] if records.tail_corrupt else []
    open_runs = open_run_ids(records)
    if any(not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None for run_id in open_runs):
        return reasons + ["history: malformed run id"]
    try:
        states = {run_id: unit_state(runner, unit_name(run_id)) for run_id in open_runs}
    except ObservationError as exc:
        return reasons + [f"units: {exc}"]
    return reasons + hi.unresolved_indeterminate(records, states)


def status_text(settings: Settings, runner: Runner, run_id: str) -> str:
    """N7 ①-④. An unreadable history or an unknown unit state is never reported as running."""
    try:
        records = hi.read(settings.history_file)
    except hi.HistoryCorrupt:
        return "indeterminate"
    try:
        state = unit_state(runner, unit_name(run_id))
    except ObservationError:
        state = "inactive"
    return hi.status(records, run_id, state)


def completed_exit_code(settings: Settings, run_id: str) -> int | None:
    records = hi.read(settings.history_file)
    for entry in records.entries:
        if entry.get("run_id") == run_id and entry.get("phase") == "completed":
            return int(entry["exit_code"])
    return None
