"""Tests for the SSH side of deploy (launch, follow, status) and the --unit-body guard.

Why: the SSH call only checks, launches and follows; the unit owns the outcome (N7). These tests pin the exact
systemd-run argv (no secrets), the refusals that happen before anything is launched, the follow rules (completed,
indeterminate, not-started after a grace period) and that losing the SSH side loses nothing.
"""

import fcntl
import io
import os
import sys
from dataclasses import replace
from pathlib import Path

from bookfinder_host import commands as cmd
from bookfinder_host import history as hi
from bookfinder_host import state as st
from bookfinder_host.exit_codes import BAD_INPUT, DRIFT, INDETERMINATE, OK
from bookfinder_host.ports import CommandResult
from bookfinder_host.testing import FakeClock, sample_state
from worlds import (
    CRAWLER,
    DEPLOY_RUN_ID,
    DIGEST_OK,
    H1,
    ID1,
    SYSTEMD_UNIT,
    TAG1,
    WEB1,
    applied,
    make_world,
)

UNIT = f"book-finder-deploy-{DEPLOY_RUN_ID}"


class KilledSshSide(FakeClock):
    """Simulates the SSH process being killed: the first sleep in the follow loop raises."""

    def sleep(self, seconds: float) -> None:
        raise KeyboardInterrupt


class RecordingLauncher:
    """Records the systemd-run argv and, optionally, marks the unit active without running its body."""

    def __init__(self, world, *, mark_active: bool = False, returncode: int = 0) -> None:
        self.world = world
        self.calls: list[list[str]] = []
        self.mark_active = mark_active
        self.returncode = returncode

    def __call__(self, argv):
        self.calls.append(list(argv))
        if self.mark_active:
            self.world.host.unit_states[UNIT] = "active"
        return CommandResult(self.returncode, "", "" if self.returncode == 0 else "no bus")


def deploy_text(world, *, run_id=DEPLOY_RUN_ID, chain="in-sync", revision=None, schema=None):
    state = world.state
    return (
        f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --run-id {run_id} --expect-revision {state.revision if revision is None else revision} "
        f"--expect-runtime {st.runtime_fingerprint(state.runtime)} --expect-schema {schema or state.schema.digest} --chain {chain}"
    )


def in_sync(tmp_path, **kwargs):
    return make_world(tmp_path, sample_state(applied=applied((ID1, H1))), target=applied((ID1, H1)), **kwargs)


def history_phases(world):
    return [entry.get("phase") for entry in world.history().entries]


def test_systemd_run_argv_is_exact_and_carries_no_secrets(tmp_path):
    world = in_sync(tmp_path)
    launcher = RecordingLauncher(world, mark_active=True)
    world.host.on_systemd_run = launcher
    world.deps = replace(world.deps, clock=KilledSshSide())
    try:
        world.run(deploy_text(world))
    except KeyboardInterrupt:
        pass
    assert len(launcher.calls) == 1
    argv = launcher.calls[0]
    assert argv[: argv.index("--") + 1] == ["systemd-run", f"--unit={UNIT}", "--property=Type=exec", "--collect", "--quiet", "--"]
    assert argv[argv.index("--") + 1 :] == [
        sys.executable,
        str(cmd.DEFAULT_ENTRY),
        cmd.UNIT_BODY_FLAG,
        "deploy",
        TAG1,
        DIGEST_OK,
        CRAWLER,
        "--run-id",
        DEPLOY_RUN_ID,
        "--expect-revision",
        "1",
        "--expect-runtime",
        WEB1,
        "--expect-schema",
        world.state.schema.digest,
        "--chain",
        "in-sync",
    ]
    assert all("secret" not in part for part in argv)
    assert "--pipe" not in argv and "--wait" not in argv


def test_cutover_argv_carries_the_cutover_flag_as_a_token(tmp_path):
    state = replace(sample_state(applied=applied((ID1, H1))), runtime=st.SystemdRuntime(unit=SYSTEMD_UNIT, version="pre-cd"))
    world = make_world(tmp_path, state, target=applied((ID1, H1)), unit_states={SYSTEMD_UNIT: "active"})
    launcher = RecordingLauncher(world, mark_active=True)
    world.host.on_systemd_run = launcher
    world.deps = replace(world.deps, clock=KilledSshSide())
    try:
        world.run(
            f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --run-id {DEPLOY_RUN_ID} --expect-revision 1 --expect-runtime systemd "
            f"--expect-schema {state.schema.digest} --chain in-sync --cutover"
        )
    except KeyboardInterrupt:
        pass
    assert launcher.calls[0][-1] == "--cutover"


def test_completed_run_is_followed_to_its_exit_code_and_printed_once(tmp_path):
    # The health check fails, so the unit completes as drift (exit 3) and the SSH side must report exactly that.
    world = in_sync(tmp_path)
    world.fx.http.script[cmd.machine.LOCAL_URL] = [503]
    assert world.run(deploy_text(world)) == DRIFT
    lines = world.out.getvalue().splitlines()
    assert len(lines) == 1
    assert world.stdout_json() == {"run_id": DEPLOY_RUN_ID, "status": "completed:drift", "exit_code": DRIFT}


def test_success_is_followed_to_exit_zero(tmp_path):
    world = in_sync(tmp_path)
    assert world.run(deploy_text(world)) == OK
    assert world.stdout_json() == {"run_id": DEPLOY_RUN_ID, "status": "completed:success", "exit_code": OK}


def test_duplicate_unit_is_refused_before_anything_is_written(tmp_path):
    world = in_sync(tmp_path)
    world.host.unit_states[UNIT] = "active"
    launcher = RecordingLauncher(world)
    world.host.on_systemd_run = launcher
    assert world.run(deploy_text(world)) == DRIFT
    assert "already exists" in world.err.getvalue()
    assert launcher.calls == []
    assert world.history().entries == []


def test_run_id_already_in_history_is_refused_without_a_launch(tmp_path):
    world = in_sync(tmp_path)
    assert world.run(deploy_text(world)) == OK
    launcher = RecordingLauncher(world)
    world.host.on_systemd_run = launcher
    before = Path(world.settings.history_file).read_text()
    assert world.run(deploy_text(world)) == DRIFT
    assert "run id already used" in world.err.getvalue()
    assert launcher.calls == []
    assert Path(world.settings.history_file).read_text() == before


def test_indeterminate_run_blocks_the_launch_with_exit_8(tmp_path):
    world = in_sync(tmp_path)
    world.run_unit(deploy_text(world, run_id="7000-1"))  # leaves a started record only if the run crashed
    from bookfinder_host import history as hi

    hi.append(world.settings.history_file, hi.started_record(run_id="7001-1", unit="book-finder-deploy-7001-1", at="t", target={}, expected_revision=1))
    launcher = RecordingLauncher(world)
    world.host.on_systemd_run = launcher
    assert world.run(deploy_text(world)) == INDETERMINATE
    assert launcher.calls == []


def test_follow_gives_up_after_the_timeout_and_the_unit_keeps_running(tmp_path):
    world = in_sync(tmp_path)
    world.host.on_systemd_run = RecordingLauncher(world, mark_active=True)
    world.deps = replace(world.deps, settings=replace(world.deps.settings, follow_timeout_s=10.0))
    assert world.run(deploy_text(world)) == DRIFT
    assert world.stdout_json() == {"run_id": DEPLOY_RUN_ID, "status": "running", "exit_code": DRIFT}
    assert world.err.getvalue().strip().endswith("follow timeout; poll status 5555-1")
    assert world.history().entries == []  # the SSH side wrote nothing; the unit owns the outcome


def test_systemd_run_failure_is_drift_and_writes_nothing(tmp_path):
    world = in_sync(tmp_path)
    world.host.on_systemd_run = RecordingLauncher(world, returncode=1)
    assert world.run(deploy_text(world)) == DRIFT
    assert "systemd-run failed" in world.err.getvalue()
    assert world.history().entries == []


def test_killed_ssh_side_leaves_status_computable_and_the_unit_running(tmp_path):
    world = in_sync(tmp_path)
    world.host.on_systemd_run = RecordingLauncher(world, mark_active=True)
    world.deps = replace(world.deps, clock=KilledSshSide())
    try:
        world.run(deploy_text(world))
    except KeyboardInterrupt:
        pass
    assert history_phases(world) == []  # the unit has not written anything yet; nothing depends on this process
    assert world.run(f"status {DEPLOY_RUN_ID}", plan_only=True) == OK
    assert world.stdout_json()["status"] == "running"


def test_unit_gone_without_completed_is_indeterminate_not_success(tmp_path):
    world = in_sync(tmp_path)
    from bookfinder_host import history as hi

    hi.append(world.settings.history_file, hi.started_record(run_id=DEPLOY_RUN_ID, unit=UNIT, at="t", target={}, expected_revision=1))
    assert world.run(f"status {DEPLOY_RUN_ID}", plan_only=True) == OK
    assert world.stdout_json()["status"] == "indeterminate"


def test_completed_history_wins_over_an_active_unit(tmp_path):
    world = in_sync(tmp_path)
    assert world.run(deploy_text(world)) == OK
    world.host.unit_states[UNIT] = "active"
    world.out = io.StringIO()
    assert world.run(f"status {DEPLOY_RUN_ID}", plan_only=True) == OK
    assert world.stdout_json()["status"] == "completed:success"


def test_no_unit_and_no_started_record_is_not_started_after_the_grace_period(tmp_path):
    world = in_sync(tmp_path)
    world.host.on_systemd_run = RecordingLauncher(world)  # the unit is never started
    assert world.run(deploy_text(world)) == DRIFT
    assert world.stdout_json() == {"run_id": DEPLOY_RUN_ID, "status": "not-started", "exit_code": DRIFT}


def test_journal_lines_go_to_stderr_and_never_into_the_result(tmp_path):
    world = in_sync(tmp_path)
    world.host.journal = ["unit line one", "unit line two"]
    assert world.run(deploy_text(world)) == OK
    assert "unit line one" in world.err.getvalue()
    assert "unit line" not in world.out.getvalue()
    assert world.stdout_json()["status"] == "completed:success"


def test_unit_body_is_rejected_inside_ssh_original_command(tmp_path):
    world = in_sync(tmp_path)
    launcher = RecordingLauncher(world)
    world.host.on_systemd_run = launcher
    text = deploy_text(world).replace("deploy", "--unit-body deploy", 1)
    assert world.run(text) == BAD_INPUT
    assert "reserved for systemd" in world.err.getvalue()
    assert launcher.calls == []
    assert world.history().entries == []


def test_unit_body_flag_is_refused_without_systemd_invocation_id(tmp_path):
    world = in_sync(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    tokens = [cmd.UNIT_BODY_FLAG, *deploy_text(world).split()]
    assert cmd.main(tokens, {}, out, err, deps=world.deps) == BAD_INPUT
    assert "only from a systemd unit" in err.getvalue()
    assert world.history().entries == []


def test_unit_body_refuses_a_command_that_came_from_ssh(tmp_path):
    world = in_sync(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    tokens = [cmd.UNIT_BODY_FLAG, *deploy_text(world).split()]
    assert cmd.main(tokens, {"INVOCATION_ID": "x", "SSH_ORIGINAL_COMMAND": "plan"}, out, err, deps=world.deps) == BAD_INPUT


def test_unit_body_accepts_only_deploy(tmp_path):
    world = in_sync(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    assert cmd.main([cmd.UNIT_BODY_FLAG, "plan", TAG1, DIGEST_OK], {"INVOCATION_ID": "x"}, out, err, deps=world.deps) == BAD_INPUT


def test_render_deploy_tokens_round_trips_through_the_grammar(tmp_path):
    world = in_sync(tmp_path)
    command = cmd.parse_command(deploy_text(world))
    assert cmd.parse_tokens(cmd.render_deploy_tokens(command)) == command
    cutover = cmd.parse_command(deploy_text(world) + " --cutover")
    assert cmd.parse_tokens(cmd.render_deploy_tokens(cutover)) == cutover


def test_unit_name_is_built_from_the_validated_run_id_only(tmp_path):
    from bookfinder_host import runs

    assert runs.unit_name("5555-1") == "book-finder-deploy-5555-1"


# N7 outcomes that must survive systemd garbage collection (--collect): the unit body always leaves a durable
# outcome once started is written, and status reads the same answer whether the unit failed or is gone.


def _status(world) -> str:
    world.out = io.StringIO()
    assert world.run(f"status {DEPLOY_RUN_ID}", plan_only=True) == OK
    return world.stdout_json()["status"]


def _hold_deploy_lock(world) -> int:
    fd = os.open(world.settings.deploy_lock_file, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_SH)  # a shared holder makes the unit's exclusive wait time out
    return fd


def _started_only(world, run_id=DEPLOY_RUN_ID, unit=UNIT):
    hi.append(world.settings.history_file, hi.started_record(run_id=run_id, unit=unit, at="t0", target={}, expected_revision=1))


def test_unit_that_timed_out_on_the_deploy_lock_stays_completed_drift_through_gc(tmp_path):
    world = in_sync(tmp_path)
    fd = _hold_deploy_lock(world)
    try:
        assert world.run_unit(deploy_text(world))[0] == DRIFT
    finally:
        os.close(fd)
    assert history_phases(world) == ["started", "completed"]
    world.host.unit_states[UNIT] = "failed"
    assert _status(world) == "completed:drift"
    del world.host.unit_states[UNIT]  # systemd --collect has removed the unit
    assert _status(world) == "completed:drift"


def test_missing_state_is_completed_drift_through_gc(tmp_path):
    world = in_sync(tmp_path)
    world.remove_state()
    assert world.run_unit(deploy_text(world))[0] == DRIFT
    world.host.unit_states[UNIT] = "failed"
    assert _status(world) == "completed:drift"
    del world.host.unit_states[UNIT]
    assert _status(world) == "completed:drift"


def test_corrupt_state_is_completed_rejected_with_exit_2(tmp_path):
    world = in_sync(tmp_path)
    Path(world.settings.state_file).write_text("{broken", encoding="utf-8")
    assert world.run_unit(deploy_text(world))[0] == BAD_INPUT
    assert world.history().entries[-1]["exit_code"] == BAD_INPUT
    world.host.unit_states.pop(UNIT, None)
    assert _status(world) == "completed:rejected"


def test_another_indeterminate_run_blocks_this_run_with_exit_8(tmp_path):
    world = in_sync(tmp_path)
    _started_only(world, run_id="7001-1", unit="book-finder-deploy-7001-1")
    code, _, _ = world.run_unit(deploy_text(world))
    assert code == INDETERMINATE
    assert world.history().entries[-1]["result"] == "blocked-indeterminate"
    assert _status(world) == "completed:blocked-indeterminate"


def test_unit_that_failed_before_writing_started_is_not_started_before_and_after_gc(tmp_path):
    world = in_sync(tmp_path)
    world.host.unit_states[UNIT] = "failed"
    assert _status(world) == "not-started"
    del world.host.unit_states[UNIT]
    assert _status(world) == "not-started"


def test_started_without_completed_is_indeterminate_through_gc_and_blocks_the_next_deploy(tmp_path):
    world = in_sync(tmp_path)
    _started_only(world)
    world.host.unit_states[UNIT] = "failed"
    assert _status(world) == "indeterminate"
    del world.host.unit_states[UNIT]
    assert _status(world) == "indeterminate"
    assert world.run(deploy_text(world, run_id="5556-1")) == INDETERMINATE


def test_duplicate_execution_of_an_existing_run_id_writes_nothing(tmp_path):
    world = in_sync(tmp_path)
    assert world.run(deploy_text(world)) == OK
    before = Path(world.settings.history_file).read_text()
    code, _, err = world.run_unit(deploy_text(world))
    assert code == DRIFT
    assert "run id already used" in err
    assert Path(world.settings.history_file).read_text() == before


def test_damaged_history_tail_refuses_the_unit_without_writing(tmp_path):
    world = in_sync(tmp_path)
    Path(world.settings.history_file).write_text('{"run_id": "1-1", "phase": "sta', encoding="utf-8")
    before = Path(world.settings.history_file).read_text()
    assert world.run_unit(deploy_text(world))[0] == INDETERMINATE
    assert Path(world.settings.history_file).read_text() == before
