"""SSH command grammar, plan/status/deploy gates, the SSH-side launch and follow, and the unit body of deploy.

Why: this module is the only thing an SSH key can reach. The grammar accepts exactly three commands with fixed fields,
the plan key may run only plan and status, and every deploy gate fails with a documented code before anything on the
host changes. A deploy runs as a transient unit (N7): the SSH side only checks, launches and follows, while the unit
body refuses a reused run id, writes the started record, takes the lock and runs the state machine in machine.py.
"""

import io
import json
import os
import re
import shlex
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO

from bookfinder_host import adapters, locks, machine, runs
from bookfinder_host import config as cfg
from bookfinder_host import history as hi
from bookfinder_host import manifest as mf
from bookfinder_host import runtime as rt
from bookfinder_host import state as st
from bookfinder_host.exit_codes import BAD_INPUT, DIRTY, DRIFT, INDETERMINATE, OK, RESULT_BY_EXIT
from bookfinder_host.ports import Clock, CommandResult, Effects, Runner, SubprocessRunner, SystemClock

# Test-only hook: when set, the fakes file replaces docker, systemd, aws, psql and the clock. It is refused for root,
# and the SSH forced command never sets it, so production cannot reach it by accident.
TEST_HOOK_ENV = "BOOKFINDER_HOST_TEST_FAKES"
# A local integration run points the host at a temporary host.conf; root never honours it, so the forced command cannot be redirected.
CONFIG_ENV = "BOOKFINDER_HOST_CONF"
DEFAULT_CONFIG = Path(cfg.DEFAULT_CONFIG_PATH)
DEFAULT_ENTRY = Path(__file__).resolve().parent.parent / "deploy-entry"
# Passed by systemd-run to the entry script; only accepted when INVOCATION_ID shows systemd started the process.
UNIT_BODY_FLAG = "--unit-body"
# The SSH side polls every 2 s. A run that is not active and has no started record reads "not-started"; the SSH side
# accepts that only after 30 s, because the unit may still be starting or may have exited before writing started.
FOLLOW_INTERVAL_S = 2.0
NOT_STARTED_GRACE_S = 30.0
# --detach waits this long for the run to be acknowledged (started, terminal, or not-started); then it returns "launched".
DETACH_ACK_TIMEOUT_S = 60.0
# The db-maintenance lock is held through a migration, which may include a long snapshot and a slow efbundle.
MAINTENANCE_TIMEOUT_S = 45 * 60.0

TAG_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
RUN_ID_RE = re.compile(r"[0-9]{1,20}-[0-9]{1,4}")
REVISION_RE = re.compile(r"[0-9]{1,9}")
CHAINS = ("in-sync", "forward", "schema-ahead")
# --run-id is chosen by CD (${{ github.run_id }}-${{ github.run_attempt }}) so CD can poll status even if SSH drops.
DEPLOY_VALUE_FLAGS = ("--run-id", "--expect-revision", "--expect-runtime", "--expect-schema", "--chain")


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
    # Only the SSH side reads this; it is never rendered into the unit's tokens, so the unit's argv is the same either way.
    detach: bool = False


Command = PlanCommand | StatusCommand | DeployCommand


@dataclass(frozen=True)
class Deps:
    settings: cfg.Settings
    runner: Runner
    clock: Clock
    db_query: Callable[[str], str]
    host_api_range: tuple[int, int]
    effects: Effects
    entry_argv: tuple[str, ...] = (sys.executable, str(DEFAULT_ENTRY))
    maintenance_timeout_s: float = MAINTENANCE_TIMEOUT_S


def _require(pattern: re.Pattern[str], value: str, what: str) -> str:
    if pattern.fullmatch(value) is None:
        raise UsageError(f"{what} is malformed")
    return value


def parse_command(text: str) -> Command:
    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        raise UsageError(f"cannot parse command: {exc}") from exc
    return parse_tokens(tokens)


def parse_tokens(tokens: list[str]) -> Command:
    if not tokens:
        raise UsageError("empty command")
    if UNIT_BODY_FLAG in tokens:
        raise UsageError(f"{UNIT_BODY_FLAG} is reserved for systemd")
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
    detach = False
    rest = args[3:]
    index = 0
    while index < len(rest):
        token = rest[index]
        if token in ("--cutover", "--detach"):
            if (token == "--cutover" and cutover) or (token == "--detach" and detach):
                raise UsageError(f"duplicate {token}")
            if token == "--cutover":
                cutover = True
            else:
                detach = True
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
        detach=detach,
    )


def render_deploy_tokens(command: DeployCommand) -> list[str]:
    """The canonical deploy tokens handed to the unit; they round-trip through parse_tokens."""
    tokens = [
        "deploy",
        command.tag,
        command.web_digest,
        command.crawler_digest,
        "--run-id",
        command.run_id,
        "--expect-revision",
        str(command.expect_revision),
        "--expect-runtime",
        command.expect_runtime,
        "--expect-schema",
        command.expect_schema,
        "--chain",
        command.chain,
    ]
    if command.cutover:
        tokens.append("--cutover")
    return tokens


def config_path_from(environ: Mapping[str, str]) -> Path:
    if CONFIG_ENV not in environ:
        return DEFAULT_CONFIG
    if os.geteuid() == 0:
        raise cfg.ConfigError(f"{CONFIG_ENV} is refused for root")
    return Path(environ[CONFIG_ENV])


def load_production_deps(config_path: Path = DEFAULT_CONFIG) -> Deps:
    settings = cfg.load_settings(config_path)
    # Above the aws waiter's own limit, so a slow snapshot is not cut short by this process.
    runner = SubprocessRunner(timeout_s=3600.0)
    return Deps(
        settings=settings,
        runner=runner,
        clock=SystemClock(),
        db_query=cfg.make_psql_query(runner, settings),
        host_api_range=cfg.read_host_api_range(),
        effects=adapters.build_effects(runner, settings),
    )


def load_fake_deps(path: str) -> Deps:
    from bookfinder_host import testing

    document, host, clock = testing.fakes_from_file(path)
    settings = cfg.Settings(**document["settings"])
    deps = Deps(
        settings=settings,
        runner=host,
        clock=clock,
        db_query=cfg.make_psql_query(host, settings),
        host_api_range=(1, 1),
        effects=testing.FakeEffects(host, release_tree=host.release_dir).as_effects(),
    )
    host.on_systemd_run = make_inline_launcher(deps)
    return deps


def make_inline_launcher(deps: Deps) -> Callable[[Sequence[str]], CommandResult]:
    """Test-only: runs the unit body in this process when systemd-run is asked to start it.

    Why: the SSH side and the unit are separate processes in production; tests need the unit's history writes to
    happen, so the fake systemd-run calls the same entry point the real unit would. systemd-run itself succeeds.
    """

    def launch(argv: Sequence[str]) -> CommandResult:
        index = list(argv).index(UNIT_BODY_FLAG)
        sink_out, sink_err = io.StringIO(), io.StringIO()
        main([UNIT_BODY_FLAG, *argv[index + 1 :]], {"INVOCATION_ID": "inline"}, sink_out, sink_err, deps=deps)
        return CommandResult(0, "", "")

    return launch


def main(argv: list[str], environ: Mapping[str, str], out: TextIO, err: TextIO, deps: Deps | None = None) -> int:
    unit_body = bool(argv) and argv[0] == UNIT_BODY_FLAG
    if unit_body:
        # The unit gets its command in argv, never from SSH_ORIGINAL_COMMAND, and only when systemd started it.
        if "SSH_ORIGINAL_COMMAND" in environ or "INVOCATION_ID" not in environ:
            err.write(f"rejected: {UNIT_BODY_FLAG} is accepted only from a systemd unit\n")
            return BAD_INPUT
        try:
            command = parse_tokens(argv[1:])
        except UsageError as exc:
            err.write(f"rejected: {exc}\n")
            return BAD_INPUT
        if not isinstance(command, DeployCommand):
            err.write(f"rejected: {UNIT_BODY_FLAG} takes only deploy\n")
            return BAD_INPUT
        plan_only = False
    else:
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
                deps = load_production_deps(config_path_from(environ))
    except cfg.ConfigError as exc:
        err.write(f"configuration error: {exc}\n")
        return BAD_INPUT
    try:
        return dispatch(command, deps, out, err, unit_body=unit_body)
    except Exception as exc:  # noqa: BLE001 - deliberate: an unexpected error must not exit 1 (rolled-back)
        err.write(f"internal error: {type(exc).__name__}: {exc}\n")
        return BAD_INPUT


def dispatch(command: Command, deps: Deps, out: TextIO, err: TextIO, unit_body: bool = False) -> int:
    if isinstance(command, PlanCommand):
        return run_plan(command, deps, out, err)
    if isinstance(command, StatusCommand):
        return run_status(command, deps, out)
    if unit_body:
        return run_deploy_unit(command, deps, out, err)
    return run_deploy_ssh(command, deps, out, err)


# Helpers shared by plan and deploy


def _read_state(deps: Deps, err: TextIO) -> st.State | None:
    try:
        return st.load_state(deps.settings.state_file)
    except st.StateMissing:
        err.write("state is missing: bootstrap required (N6); CD never creates state itself\n")
    except st.StateCorrupt as exc:
        err.write(f"state is unreadable: {exc}\n")
    return None


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


def _schema_ahead_crawler_problem(command: DeployCommand, current_digest: str) -> str | None:
    """Contract: a schema-ahead deploy never changes the crawler, so its crawler_digest must be the current one (M3c)."""
    if command.chain == "schema-ahead" and command.crawler_digest != current_digest:
        return f"schema-ahead keeps the current crawler ({current_digest}); crawler_digest must be that digest"
    return None


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
    blocked = runs.indeterminate_reasons(deps.settings, deps.runner)
    if blocked:
        out.write(json.dumps({"revision": state.revision, "indeterminate": blocked}, sort_keys=True) + "\n")
        return INDETERMINATE
    compose_version, problem = machine.compose_raw_env_check(deps.effects.compose, Path(deps.settings.run_dir))
    if problem is not None:
        out.write(json.dumps({"revision": state.revision, "compose_version": compose_version, "refused": problem}, sort_keys=True) + "\n")
        err.write(f"{problem}\n")
        return BAD_INPUT
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
        "crawler": {"paused": st.pause_to_json(state.crawler.paused), "digest": state.crawler.digest},
        "compose_version": compose_version,
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
    text = runs.status_text(deps.settings, deps.runner, command.run_id)
    out.write(json.dumps({"run_id": command.run_id, "status": text}, sort_keys=True) + "\n")
    return OK


def _check_deploy_gates(command: DeployCommand, state: st.State, deps: Deps) -> mf.ReleaseMetadata:
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
    problem = _schema_ahead_crawler_problem(command, state.crawler.digest)
    if problem is not None:
        raise GateFailure(BAD_INPUT, problem)
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
    return target


# deploy
#
# The SSH side (run_deploy_ssh) only checks, launches and follows; it changes nothing on the host itself. The unit
# (run_deploy_unit) refuses a reused run id, writes started before any lock or state read, then takes the deploy lock,
# runs the gates and hands over to the state machine. Every known outcome after started writes one completed record.


def run_deploy_ssh(command: DeployCommand, deps: Deps, out: TextIO, err: TextIO) -> int:
    run_id = command.run_id
    try:
        history = hi.read(deps.settings.history_file)
    except hi.HistoryCorrupt:
        history = None
    # A run id is never reused: a retried SSH call must not start a second deployment for the same CD run.
    if history is not None and any(entry.get("run_id") == run_id for entry in history.entries):
        err.write(f"run id already used: {run_id}\n")
        return DRIFT
    # The SSH side can only refuse what the state already shows; the unit gate repeats the check (completed rejected).
    try:
        current = st.load_state(deps.settings.state_file)
    except (st.StateMissing, st.StateCorrupt):
        current = None
    if current is not None:
        problem = _schema_ahead_crawler_problem(command, current.crawler.digest)
        if problem is not None:
            err.write(f"rejected: {problem}\n")
            return BAD_INPUT
    blocked = runs.indeterminate_reasons(deps.settings, deps.runner)
    if blocked:
        err.write(f"indeterminate runs block deploy: {', '.join(blocked)}\n")
        return INDETERMINATE
    unit = runs.unit_name(run_id)
    try:
        load_state = runs.unit_load_state(deps.runner, unit)
    except rt.ObservationError as exc:
        err.write(f"cannot inspect unit {unit}: {exc}\n")
        return DRIFT
    if load_state != "not-found":
        err.write(f"unit {unit} already exists; the same run is not started twice\n")
        return DRIFT
    # Argv only: the unit receives the validated tokens and reads its secrets from SSM itself, never from this call.
    launch_argv = [
        "systemd-run",
        f"--unit={unit}",
        "--property=Type=exec",
        "--collect",
        "--quiet",
        "--",
        *deps.entry_argv,
        UNIT_BODY_FLAG,
        *render_deploy_tokens(command),
    ]
    launched = deps.runner.run(launch_argv)
    if launched.returncode != 0:
        err.write(f"systemd-run failed: {launched.stderr.strip()[:300]}\n")
        return DRIFT
    if command.detach:
        return _acknowledge(command, deps, out, err, launched_at=deps.clock.monotonic())
    return _follow(command, deps, out, err, launched_at=deps.clock.monotonic())


def _acknowledge(command: DeployCommand, deps: Deps, out: TextIO, err: TextIO, launched_at: float) -> int:
    """--detach: waits only until the unit has taken ownership of the run, then returns (CD polls status from here on).

    A terminal status is reported as usual. A started record means the unit owns the run, so the answer is "launched".
    No started record and no unit after the grace period is not-started. If neither happens within DETACH_ACK_TIMEOUT_S,
    the unit is still alive, so the answer is "launched" as well: the outcome is still decided by history, not by this call.
    """
    run_id = command.run_id
    while True:
        status = runs.status_text(deps.settings, deps.runner, run_id)
        if status.startswith("completed:"):
            code = runs.completed_exit_code(deps.settings, run_id)
            return _report_final(out, run_id, status, INDETERMINATE if code is None else code)
        if status == "indeterminate":
            return _report_final(out, run_id, status, INDETERMINATE)
        if runs.started_recorded(deps.settings, run_id):
            return _report_final(out, run_id, "launched", OK)
        elapsed = deps.clock.monotonic() - launched_at
        if status == "not-started" and elapsed >= NOT_STARTED_GRACE_S:
            return _report_final(out, run_id, status, DRIFT)
        if elapsed >= DETACH_ACK_TIMEOUT_S:
            err.write(f"not acknowledged within {int(DETACH_ACK_TIMEOUT_S)} s; poll status {run_id}\n")
            return _report_final(out, run_id, "launched", OK)
        deps.clock.sleep(FOLLOW_INTERVAL_S)


def _follow(command: DeployCommand, deps: Deps, out: TextIO, err: TextIO, launched_at: float) -> int:
    """Polls status until it is terminal. Losing this process loses nothing: the unit and history carry on (N7)."""
    unit = runs.unit_name(command.run_id)
    shown = 0
    while True:
        shown = _show_journal(deps, unit, shown, err)
        status = runs.status_text(deps.settings, deps.runner, command.run_id)
        if status.startswith("completed:"):
            code = runs.completed_exit_code(deps.settings, command.run_id)
            return _report_final(out, command.run_id, status, INDETERMINATE if code is None else code)
        if status == "indeterminate":
            return _report_final(out, command.run_id, status, INDETERMINATE)
        if status == "not-started" and deps.clock.monotonic() - launched_at >= NOT_STARTED_GRACE_S:
            return _report_final(out, command.run_id, status, DRIFT)
        if deps.clock.monotonic() - launched_at >= deps.settings.follow_timeout_s:
            # Bounded wait: the unit keeps running, and CD carries on by polling status for this run id.
            err.write(f"follow timeout; poll status {command.run_id}\n")
            return _report_final(out, command.run_id, "running", DRIFT)
        deps.clock.sleep(FOLLOW_INTERVAL_S)


def _show_journal(deps: Deps, unit: str, shown: int, err: TextIO) -> int:
    """Informational only: the journal is not a source of truth, so any failure here is ignored."""
    result = deps.runner.run(["journalctl", "-u", unit, "-o", "cat", "--no-pager"])
    if result.returncode != 0:
        return shown
    lines = result.stdout.splitlines()
    err.writelines(line + "\n" for line in lines[shown:])
    return len(lines)


def _report_final(out: TextIO, run_id: str, status: str, code: int) -> int:
    out.write(json.dumps({"run_id": run_id, "status": status, "exit_code": code}, sort_keys=True) + "\n")
    return code


def run_deploy_unit(command: DeployCommand, deps: Deps, out: TextIO, err: TextIO) -> int:
    """The unit body (N7). Once started is appended, every known outcome writes exactly one completed record.

    Order: refuse a run id that has any record (writes nothing); append started and fsync it before any lock or state
    read; then take the deploy lock, read the state, check the other runs, run the gates and the state machine. Only an
    unexpected exception leaves a started record without a completed one, and that run is then indeterminate.
    """
    run_id = command.run_id
    try:
        records = hi.read(deps.settings.history_file)
    except hi.HistoryCorrupt as exc:
        err.write(f"history is unreadable; nothing was written: {exc}\n")
        return INDETERMINATE
    # A duplicate execution must not write: the outcome of this run id is whatever the first execution recorded.
    if any(entry.get("run_id") == run_id for entry in records.entries):
        err.write(f"run id already used: {run_id}\n")
        return DRIFT
    if records.tail_corrupt:
        # Appending after an incomplete final line would make that line a damaged middle line, so nothing is written.
        err.write("history final line is incomplete; nothing was written\n")
        return INDETERMINATE
    hi.append(
        deps.settings.history_file,
        hi.started_record(
            run_id=run_id,
            unit=runs.unit_name(run_id),
            at=deps.clock.now(),
            target={"tag": command.tag, "web_digest": command.web_digest, "crawler_digest": command.crawler_digest},
            expected_revision=command.expect_revision,
        ),
    )
    entered = False
    try:
        with locks.exclusive(deps.settings.deploy_lock_file, deps.settings.lock_timeout_s, deps.clock):
            entered = True
            return _deploy_locked(command, deps, out, err)
    except locks.LockTimeout as exc:
        if entered:
            raise  # not a lock-acquisition failure: the run may have changed something, so it stays indeterminate
        return machine.finish_run(deps, out, err, run_id, None, DRIFT, "drift", f"busy: {exc}")


def _deploy_locked(command: DeployCommand, deps: Deps, out: TextIO, err: TextIO) -> int:
    """Runs under the deploy lock, after started was written. Every return here is a known outcome with completed."""
    run_id = command.run_id
    try:
        state = st.load_state(deps.settings.state_file)
    except st.StateMissing:
        return machine.finish_run(deps, out, err, run_id, None, DRIFT, "drift", "state is missing: bootstrap required (N6); CD never creates state itself")
    except st.StateCorrupt as exc:
        return machine.finish_run(deps, out, err, run_id, None, BAD_INPUT, RESULT_BY_EXIT[BAD_INPUT], f"state is unreadable: {exc}")
    blocked = runs.indeterminate_reasons(deps.settings, deps.runner, exclude_run_id=run_id)
    if blocked:
        return machine.finish_run(
            deps,
            out,
            err,
            run_id,
            state,
            INDETERMINATE,
            RESULT_BY_EXIT[INDETERMINATE],
            f"indeterminate runs block deploy: {', '.join(blocked)}",
        )
    try:
        target = _check_deploy_gates(command, state, deps)
    except GateFailure as failure:
        return machine.finish_run(deps, out, err, run_id, state, failure.code, RESULT_BY_EXIT[failure.code], failure.reason)
    # An unexpected exception is not caught here on purpose: the run then stays indeterminate instead of claiming a result.
    return machine.run_state_machine(command, state, deps, run_id, target, out, err)
