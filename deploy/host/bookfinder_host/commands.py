"""SSH command grammar, plan/status/deploy gates, and the exit-code mapping.

Why: this module is the only thing an SSH key can reach. The grammar accepts exactly three commands with fixed fields,
the plan key may run only plan and status, and every deploy gate fails with a documented code before anything on the
host changes. The state machine itself (M3b) is a stub here.
"""

import json
import os
import re
import shlex
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO

from bookfinder_host import config as cfg
from bookfinder_host import history as hi
from bookfinder_host import locks
from bookfinder_host import manifest as mf
from bookfinder_host import runtime as rt
from bookfinder_host import state as st
from bookfinder_host.exit_codes import BAD_INPUT, DIRTY, DRIFT, INDETERMINATE, OK, RESULT_BY_EXIT
from bookfinder_host.ports import Clock, Runner, SubprocessRunner, SystemClock

# Test-only hook: when set, the fakes file replaces docker, systemd, aws, psql and the clock. It is refused for root,
# and the SSH forced command never sets it, so production cannot reach it by accident.
TEST_HOOK_ENV = "BOOKFINDER_HOST_TEST_FAKES"
DEFAULT_CONFIG = Path(cfg.DEFAULT_CONFIG_PATH)
UNIT_PREFIX = "book-finder-deploy-"

TAG_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
RUN_ID_RE = re.compile(r"[0-9]{1,20}-[0-9]{1,4}")
REVISION_RE = re.compile(r"[0-9]{1,9}")
CHAINS = ("in-sync", "forward", "schema-ahead")
# --run-id is chosen by CD (${{ github.run_id }}-${{ github.run_attempt }}) so CD can poll status even if SSH drops.
DEPLOY_VALUE_FLAGS = ("--run-id", "--expect-revision", "--expect-runtime", "--expect-schema", "--chain")
NOT_IMPLEMENTED_RESULT = "not-implemented"


class UsageError(Exception):
    """The SSH command does not match the grammar."""


class GateFailure(Exception):
    def __init__(self, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class PlanCommand:
    tag: str
    web_digest: str


@dataclass(frozen=True)
class StatusCommand:
    run_id: str


@dataclass(frozen=True)
class DeployCommand:
    tag: str
    web_digest: str
    crawler_digest: str
    run_id: str
    expect_revision: int
    expect_runtime: str
    expect_schema: str
    chain: str
    cutover: bool


Command = PlanCommand | StatusCommand | DeployCommand


@dataclass(frozen=True)
class Deps:
    settings: cfg.Settings
    runner: Runner
    clock: Clock
    db_query: Callable[[str], str]
    host_api_range: tuple[int, int]


def _require(pattern: re.Pattern[str], value: str, what: str) -> str:
    if pattern.fullmatch(value) is None:
        raise UsageError(f"{what} is malformed")
    return value


def parse_command(text: str) -> Command:
    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        raise UsageError(f"cannot parse command: {exc}") from exc
    if not tokens:
        raise UsageError("empty command")
    verb, args = tokens[0], tokens[1:]
    if verb == "plan":
        if len(args) != 2:
            raise UsageError("plan takes <tag> <web_digest>")
        return PlanCommand(_require(TAG_RE, args[0], "tag"), _require(DIGEST_RE, args[1], "web digest"))
    if verb == "status":
        if len(args) != 1:
            raise UsageError("status takes <run_id>")
        return StatusCommand(_require(RUN_ID_RE, args[0], "run id"))
    if verb == "deploy":
        return _parse_deploy(args)
    raise UsageError(f"unknown command: {verb}")


def _parse_deploy(args: list[str]) -> DeployCommand:
    if len(args) < 3:
        raise UsageError("deploy takes <tag> <web_digest> <crawler_digest> and flags")
    tag = _require(TAG_RE, args[0], "tag")
    web_digest = _require(DIGEST_RE, args[1], "web digest")
    crawler_digest = _require(DIGEST_RE, args[2], "crawler digest")
    values: dict[str, str] = {}
    cutover = False
    rest = args[3:]
    index = 0
    while index < len(rest):
        token = rest[index]
        if token == "--cutover":
            if cutover:
                raise UsageError("duplicate --cutover")
            cutover = True
            index += 1
            continue
        if token not in DEPLOY_VALUE_FLAGS:
            raise UsageError(f"unknown argument: {token}")
        if token in values:
            raise UsageError(f"duplicate {token}")
        if index + 1 >= len(rest):
            raise UsageError(f"{token} needs a value")
        values[token] = rest[index + 1]
        index += 2
    missing = [flag for flag in DEPLOY_VALUE_FLAGS if flag not in values]
    if missing:
        raise UsageError(f"missing {', '.join(missing)}")
    runtime = values["--expect-runtime"]
    if runtime != "systemd":
        _require(DIGEST_RE, runtime, "expected runtime")
    if values["--chain"] not in CHAINS:
        raise UsageError("chain must be in-sync, forward or schema-ahead")
    return DeployCommand(
        tag=tag,
        web_digest=web_digest,
        crawler_digest=crawler_digest,
        run_id=_require(RUN_ID_RE, values["--run-id"], "run id"),
        expect_revision=int(_require(REVISION_RE, values["--expect-revision"], "expected revision")),
        expect_runtime=runtime,
        expect_schema=_require(DIGEST_RE, values["--expect-schema"], "expected schema digest"),
        chain=values["--chain"],
        cutover=cutover,
    )


def load_production_deps() -> Deps:
    settings = cfg.load_settings(DEFAULT_CONFIG)
    runner = SubprocessRunner()
    return Deps(
        settings=settings,
        runner=runner,
        clock=SystemClock(),
        db_query=cfg.make_psql_query(runner, settings),
        host_api_range=cfg.read_host_api_range(),
    )


def load_fake_deps(path: str) -> Deps:
    from bookfinder_host import testing

    document, host, clock = testing.fakes_from_file(path)
    settings = cfg.Settings(**document["settings"])
    return Deps(
        settings=settings,
        runner=host,
        clock=clock,
        db_query=cfg.make_psql_query(host, settings),
        host_api_range=(1, 1),
    )


def main(argv: list[str], environ: Mapping[str, str], out: TextIO, err: TextIO, deps: Deps | None = None) -> int:
    if argv not in ([], ["--plan-only"]):
        err.write("usage: deploy-entry [--plan-only]\n")
        return BAD_INPUT
    plan_only = bool(argv)
    try:
        command = parse_command(environ.get("SSH_ORIGINAL_COMMAND", ""))
    except UsageError as exc:
        err.write(f"rejected: {exc}\n")
        return BAD_INPUT
    if plan_only and isinstance(command, DeployCommand):
        err.write("rejected: deploy is not allowed through the plan key\n")
        return BAD_INPUT
    try:
        if deps is None:
            if TEST_HOOK_ENV in environ:
                # os.geteuid is checked here, not at import, so a root process can never load the fakes.
                if os.geteuid() == 0:
                    err.write("rejected: test hooks are refused for root\n")
                    return BAD_INPUT
                deps = load_fake_deps(environ[TEST_HOOK_ENV])
            else:
                deps = load_production_deps()
    except cfg.ConfigError as exc:
        err.write(f"configuration error: {exc}\n")
        return BAD_INPUT
    try:
        return dispatch(command, deps, out, err)
    except Exception as exc:  # noqa: BLE001 - deliberate: an unexpected error must not exit 1 (rolled-back)
        err.write(f"internal error: {type(exc).__name__}: {exc}\n")
        return BAD_INPUT


def dispatch(command: Command, deps: Deps, out: TextIO, err: TextIO) -> int:
    if isinstance(command, PlanCommand):
        return run_plan(command, deps, out, err)
    if isinstance(command, StatusCommand):
        return run_status(command, deps, out)
    return run_deploy(command, deps, out, err)


# Helpers shared by plan and deploy


def _unit_name(run_id: str) -> str:
    return f"{UNIT_PREFIX}{run_id}"


def unit_state(runner: Runner, unit: str) -> str:
    result = runner.run(["systemctl", "show", "--property=LoadState", "--property=ActiveState", unit])
    if result.returncode != 0:
        raise rt.ObservationError(f"systemctl show failed for {unit}")
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
        raise rt.ObservationError(f"unexpected ActiveState for {unit}: {active!r}")
    return mapping[active]


def _read_state(deps: Deps, err: TextIO) -> st.State | None:
    try:
        return st.load_state(deps.settings.state_file)
    except st.StateMissing:
        err.write("state is missing: bootstrap required (N6); CD never creates state itself\n")
    except st.StateCorrupt as exc:
        err.write(f"state is unreadable: {exc}\n")
    return None


def _open_run_ids(records: hi.Records) -> list[str]:
    completed = {entry.get("run_id") for entry in records.entries if entry.get("phase") == "completed"}
    open_runs: list[str] = []
    for entry in records.entries:
        run_id = entry.get("run_id")
        if entry.get("phase") == "started" and run_id not in completed and run_id not in open_runs:
            open_runs.append(run_id)
    return open_runs


def _indeterminate_reasons(deps: Deps) -> list[str]:
    """Every reason that history blocks plan and deploy (exit 8, N7)."""
    try:
        records = hi.read(deps.settings.history_file)
    except hi.HistoryCorrupt as exc:
        return [f"history: {exc}"]
    reasons = ["history: final line is incomplete"] if records.tail_corrupt else []
    open_runs = _open_run_ids(records)
    if any(RUN_ID_RE.fullmatch(run_id or "") is None for run_id in open_runs):
        return reasons + ["history: malformed run id"]
    try:
        states = {run_id: unit_state(deps.runner, _unit_name(run_id)) for run_id in open_runs}
    except rt.ObservationError as exc:
        return reasons + [f"units: {exc}"]
    return reasons + hi.unresolved_indeterminate(records, states)


def _observe_runtime(state: st.State, deps: Deps) -> tuple[rt.ObservedRuntime | None, list[str]]:
    try:
        if isinstance(state.runtime, st.SystemdRuntime):
            observed = rt.observe_systemd(deps.runner, state.runtime.unit)
        else:
            observed = rt.observe_docker(deps.runner, deps.settings.compose_project)
        drift = rt.check_runtime_matches(state.runtime, observed, deps.runner, deps.settings.web_image_repository)
        return observed, drift
    except rt.ObservationError as exc:
        return None, [f"runtime: observation failed: {exc}"]


def _observe_schema(state: st.State, deps: Deps) -> list[str]:
    try:
        return rt.check_schema_matches(state.schema, rt.observe_schema(deps.db_query))
    except (rt.ObservationError, cfg.ConfigError) as exc:
        return [f"schema: observation failed: {exc}"]


def _fetch_target(deps: Deps, web_digest: str) -> mf.ReleaseMetadata:
    image_ref = f"{deps.settings.web_image_repository}@{web_digest}"
    with tempfile.TemporaryDirectory(prefix="bookfinder-release-") as scratch:
        return mf.extract_release_metadata(deps.runner, image_ref, Path(scratch))


def _api_in_range(release_api: int, deps: Deps) -> bool:
    low, high = deps.host_api_range
    return low <= release_api <= high


# plan


def run_plan(command: PlanCommand, deps: Deps, out: TextIO, err: TextIO) -> int:
    try:
        with locks.shared(deps.settings.deploy_lock_file, deps.settings.lock_timeout_s, deps.clock):
            return _plan_locked(command, deps, out, err)
    except locks.LockTimeout as exc:
        err.write(f"busy: {exc}\n")
        return DRIFT


def _plan_locked(command: PlanCommand, deps: Deps, out: TextIO, err: TextIO) -> int:
    state = _read_state(deps, err)
    if state is None:
        return DRIFT
    blocked = _indeterminate_reasons(deps)
    if blocked:
        out.write(json.dumps({"revision": state.revision, "indeterminate": blocked}, sort_keys=True) + "\n")
        return INDETERMINATE
    try:
        target = _fetch_target(deps, command.web_digest)
    except mf.ManifestError as exc:
        err.write(f"release metadata rejected: {exc}\n")
        return BAD_INPUT
    applied = st.applied_migrations(state)
    classification = mf.classify(applied, list(target.migrations))
    pending_ids = []
    if classification in ("in-sync", "forward"):
        pending_ids = [m.id for m in mf.pending(applied, list(target.migrations))]
    observed, runtime_drift = _observe_runtime(state, deps)
    drift = runtime_drift + _observe_schema(state, deps)
    report: dict[str, Any] = {
        "revision": state.revision,
        "runtime": {
            "state": st.runtime_to_json(state.runtime),
            "observed": None if observed is None else asdict(observed),
        },
        "drift": drift,
        "schema": {
            "digest": state.schema.digest,
            "applied_last": applied[-1].id if applied else None,
            "dirty": state.schema.dirty,
            "dirty_since": state.schema.dirty_since,
            "dirty_release": state.schema.dirty_release,
            "rebuild": {"tag": state.schema.rebuild.tag, "web_digest": state.schema.rebuild.web_digest},
        },
        "crawler": {"paused": st.pause_to_json(state.crawler.paused)},
        "target": {"tag": command.tag, "web_digest": command.web_digest, "release_api": target.release_api},
        "classification": classification,
        "pending": pending_ids,
    }
    out.write(json.dumps(report, sort_keys=True) + "\n")
    if classification == "divergent" or not _api_in_range(target.release_api, deps):
        return BAD_INPUT
    if state.schema.dirty:
        return DIRTY
    if drift:
        return DRIFT
    return OK


# status


def run_status(command: StatusCommand, deps: Deps, out: TextIO) -> int:
    unit = _unit_name(command.run_id)
    try:
        records = hi.read(deps.settings.history_file)
    except hi.HistoryCorrupt:
        # An unreadable history cannot prove an outcome, so the answer is indeterminate.
        out.write(json.dumps({"run_id": command.run_id, "status": "indeterminate"}, sort_keys=True) + "\n")
        return OK
    try:
        state = unit_state(deps.runner, unit)
    except rt.ObservationError:
        # Unknown unit state is treated as not running, which yields indeterminate instead of a false "running".
        state = "inactive"
    status_text = hi.status(records, command.run_id, state)
    out.write(json.dumps({"run_id": command.run_id, "status": status_text}, sort_keys=True) + "\n")
    return OK


# deploy


def _check_deploy_gates(command: DeployCommand, state: st.State, deps: Deps) -> None:
    """Every check that must pass before the state machine may change anything (plan section 5, step 0)."""
    if state.revision != command.expect_revision:
        raise GateFailure(DRIFT, f"revision is {state.revision}, expected {command.expect_revision}")
    if st.runtime_fingerprint(state.runtime) != command.expect_runtime:
        raise GateFailure(DRIFT, "runtime expectation does not match state")
    if state.schema.digest != command.expect_schema:
        raise GateFailure(DRIFT, "schema expectation does not match state")
    if state.schema.dirty:
        raise GateFailure(DIRTY, "schema is dirty; resolve it with reconcile-schema first")
    try:
        target = _fetch_target(deps, command.web_digest)
    except mf.ManifestError as exc:
        raise GateFailure(BAD_INPUT, f"release metadata rejected: {exc}") from exc
    if not _api_in_range(target.release_api, deps):
        raise GateFailure(BAD_INPUT, f"release_api {target.release_api} is outside the host range")
    classification = mf.classify(st.applied_migrations(state), list(target.migrations))
    if classification == "divergent":
        raise GateFailure(BAD_INPUT, "chain is divergent")
    if classification != command.chain:
        raise GateFailure(DRIFT, f"chain is {classification}, expected {command.chain}")
    is_systemd = isinstance(state.runtime, st.SystemdRuntime)
    if command.cutover:
        if not is_systemd:
            raise GateFailure(DRIFT, "cutover requires a systemd runtime in state")
        if classification != "in-sync":
            raise GateFailure(BAD_INPUT, "cutover is only accepted for an in-sync chain")
    elif is_systemd:
        # S5: after cutover, a systemd runtime is drift; the first cutover must say so explicitly.
        raise GateFailure(DRIFT, "systemd runtime is still active; cutover must be requested explicitly (S5)")
    _, runtime_drift = _observe_runtime(state, deps)
    drift = runtime_drift + _observe_schema(state, deps)
    if drift:
        raise GateFailure(DRIFT, "; ".join(drift))


def run_state_machine(command: DeployCommand, state: st.State, deps: Deps, run_id: str) -> int:
    """Placeholder for the state machine of plan section 5; implemented in M3b."""
    raise NotImplementedError("the deploy state machine is implemented in M3b")


def run_deploy(command: DeployCommand, deps: Deps, out: TextIO, err: TextIO) -> int:
    try:
        with locks.exclusive(deps.settings.deploy_lock_file, deps.settings.lock_timeout_s, deps.clock):
            return _deploy_locked(command, deps, out, err)
    except locks.LockTimeout as exc:
        err.write(f"busy: {exc}\n")
        return DRIFT


def _deploy_locked(command: DeployCommand, deps: Deps, out: TextIO, err: TextIO) -> int:
    state = _read_state(deps, err)
    if state is None:
        return DRIFT
    # A run id is never reused: a retried SSH call must not start a second deployment for the same CD run.
    try:
        history = hi.read(deps.settings.history_file)
    except hi.HistoryCorrupt:
        history = None
    if history is not None and any(entry.get("run_id") == command.run_id for entry in history.entries):
        err.write(f"run id already used: {command.run_id}\n")
        return DRIFT
    blocked = _indeterminate_reasons(deps)
    if blocked:
        err.write(f"indeterminate runs block deploy: {', '.join(blocked)}\n")
        return INDETERMINATE
    run_id = command.run_id
    hi.append(
        deps.settings.history_file,
        hi.started_record(
            run_id=run_id,
            unit=_unit_name(run_id),
            at=deps.clock.now(),
            target={"tag": command.tag, "web_digest": command.web_digest, "crawler_digest": command.crawler_digest},
            expected_revision=command.expect_revision,
        ),
    )
    try:
        _check_deploy_gates(command, state, deps)
        return run_state_machine(command, state, deps, run_id)
    except GateFailure as failure:
        return _finish(deps, out, err, run_id, state, failure.code, RESULT_BY_EXIT[failure.code], failure.reason)
    except NotImplementedError as exc:
        return _finish(deps, out, err, run_id, state, BAD_INPUT, NOT_IMPLEMENTED_RESULT, str(exc))


def _finish(
    deps: Deps,
    out: TextIO,
    err: TextIO,
    run_id: str,
    state: st.State,
    code: int,
    result: str,
    reason: str,
) -> int:
    hi.append(
        deps.settings.history_file,
        hi.completed_record(
            run_id=run_id,
            result=result,
            exit_code=code,
            at=deps.clock.now(),
            state_summary=st.state_summary(state),
        ),
    )
    out.write(json.dumps({"run_id": run_id, "result": result, "exit_code": code}, sort_keys=True) + "\n")
    err.write(f"{reason}\n")
    return code
