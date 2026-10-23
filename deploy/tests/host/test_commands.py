"""Tests for bookfinder_host.commands: the SSH command grammar, plan/status/deploy gates and their exit codes.

Why: this is the only code that an SSH key can reach. The grammar must reject anything beyond the three commands, and
each gate must fail with its documented exit code before anything changes on the host.
"""

import io
from dataclasses import replace
from pathlib import Path

import pytest
from bookfinder_host import commands as cmd
from bookfinder_host import history as hi
from bookfinder_host import state as st
from bookfinder_host.exit_codes import BAD_INPUT, DIRTY, DRIFT, INDETERMINATE, OK
from bookfinder_host.testing import sample_state
from worlds import (
    CRAWLER,
    DEPLOY_RUN_ID,
    DIGEST_OK,
    H1,
    H2,
    H3,
    ID1,
    ID2,
    ID3,
    RUN_ID_TEXT,
    SYSTEMD_UNIT,
    TAG1,
    WEB1,
    applied,
    make_world,
)

# Grammar


def test_plan_status_and_deploy_parse():
    assert cmd.parse_command(f"plan {TAG1} {DIGEST_OK}") == cmd.PlanCommand(TAG1, DIGEST_OK)
    assert cmd.parse_command(f"status {RUN_ID_TEXT}") == cmd.StatusCommand(RUN_ID_TEXT)
    deploy = cmd.parse_command(
        f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --run-id 4-1 --expect-revision 4 --expect-runtime {WEB1} --expect-schema sha256:{'e' * 64} --chain forward --cutover"
    )
    assert deploy.expect_revision == 4 and deploy.cutover is True and deploy.chain == "forward"
    assert deploy.run_id == "4-1"


def test_deploy_takes_the_run_id_from_cd():
    deploy = cmd.parse_command(
        f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --run-id 777-2 --expect-revision 1 --expect-runtime systemd --expect-schema sha256:{'e' * 64} --chain in-sync"
    )
    assert deploy.run_id == "777-2"


@pytest.mark.parametrize("run_id", ["123456789012345678901-1", "1-12345", "abc-1", "1234", "1-", "1-1;id"])
def test_deploy_rejects_malformed_run_id(run_id):
    with pytest.raises(cmd.UsageError):
        cmd.parse_command(
            f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --run-id {run_id} --expect-revision 1 --expect-runtime systemd --expect-schema sha256:{'e' * 64} --chain in-sync"
        )


def test_deploy_without_run_id_is_rejected():
    with pytest.raises(cmd.UsageError, match="--run-id"):
        cmd.parse_command(f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --expect-revision 1 --expect-runtime systemd --expect-schema sha256:{'e' * 64} --chain in-sync")


def test_deploy_flags_may_come_in_any_order_without_cutover():
    deploy = cmd.parse_command(
        f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --run-id 1-1 --chain in-sync --expect-schema sha256:{'e' * 64} --expect-runtime systemd --expect-revision 9"
    )
    assert deploy.expect_runtime == "systemd" and deploy.cutover is False


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "reboot",
        f"plan {TAG1}",  # missing digest
        f"plan {TAG1} {DIGEST_OK} extra",
        f"plan {TAG1} {DIGEST_OK}; rm -rf /",  # injection with a separator
        f"plan {TAG1} {DIGEST_OK} $(id)",
        f"plan {TAG1} {DIGEST_OK}\nreboot",  # newline cannot smuggle a second command
        f"plan v1.0 {DIGEST_OK}",  # tag without patch
        f"plan 1.0.0 {DIGEST_OK}",  # tag without v
        f"plan {TAG1} sha256:ABC",  # short, uppercase digest
        f"plan {TAG1} sha256:{'a' * 63}",
        f"plan {TAG1} '{DIGEST_OK}",  # unbalanced quote
        "status 12345678901234567890123-1",  # run id too long
        "status abc-1",
        "status 1234",
        f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --expect-revision 1234567890 --expect-runtime systemd --expect-schema sha256:{'e' * 64} --chain in-sync",
        f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --expect-revision 1 --expect-runtime docker --expect-schema sha256:{'e' * 64} --chain in-sync",
        f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --expect-revision 1 --expect-runtime systemd --expect-schema sha256:{'e' * 64} --chain divergent",
        f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --expect-revision 1 --expect-runtime systemd --expect-schema sha256:{'e' * 64}",  # no chain
        f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --expect-revision 1 --expect-revision 2 --expect-runtime systemd --expect-schema sha256:{'e' * 64} --chain in-sync",
        f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --expect-revision=1 --expect-runtime systemd --expect-schema sha256:{'e' * 64} --chain in-sync",
        f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --bogus",
        f"plan {TAG1} {DIGEST_OK} --cutover",
    ],
)
def test_grammar_rejects_everything_else(text):
    with pytest.raises(cmd.UsageError):
        cmd.parse_command(text)


def test_plan_only_mode_refuses_deploy_with_exit_2(tmp_path):
    world = make_world(tmp_path)
    deploy = f"deploy {TAG1} {DIGEST_OK} {CRAWLER} --expect-revision 1 --expect-runtime {WEB1} --expect-schema {world.state.schema.digest} --chain in-sync"
    assert world.run(deploy, plan_only=True) == BAD_INPUT
    assert world.history().entries == []


def test_plan_only_mode_refuses_extra_argv(tmp_path):
    world = make_world(tmp_path)
    assert cmd.main(["--other"], {"SSH_ORIGINAL_COMMAND": f"plan {TAG1} {DIGEST_OK}"}, world.out, world.err, deps=world.deps) == BAD_INPUT


def test_injection_attempt_exits_2_and_runs_no_command(tmp_path):
    world = make_world(tmp_path)
    assert world.run(f"plan {TAG1} {DIGEST_OK}; rm -rf /") == BAD_INPUT
    assert world.host.calls == []


# plan


def test_plan_in_sync_is_deployable_and_prints_one_json_object(tmp_path):
    world = make_world(tmp_path, sample_state(applied=applied((ID1, H1), (ID2, H2))))
    code = world.run(f"plan {TAG1} {DIGEST_OK}")
    assert code == OK
    report = world.stdout_json()
    assert report["classification"] == "in-sync"
    assert report["pending"] == []
    assert report["drift"] == []
    assert report["revision"] == 1
    assert report["target"] == {"tag": TAG1, "web_digest": DIGEST_OK, "release_api": 1}
    assert set(report) >= {"revision", "runtime", "drift", "schema", "crawler", "target", "classification", "pending"}


def test_plan_forward_lists_pending_ids(tmp_path):
    state = sample_state(applied=applied((ID1, H1)))
    world = make_world(tmp_path, state, target=applied((ID1, H1), (ID2, H2), (ID3, H3)))
    assert world.run(f"plan {TAG1} {DIGEST_OK}") == OK
    report = world.stdout_json()
    assert report["classification"] == "forward"
    assert report["pending"] == [ID2, ID3]


def test_plan_schema_ahead_is_deployable(tmp_path):
    state = sample_state(applied=applied((ID1, H1), (ID2, H2)))
    world = make_world(tmp_path, state, target=applied((ID1, H1)))
    assert world.run(f"plan {TAG1} {DIGEST_OK}") == OK
    assert world.stdout_json()["classification"] == "schema-ahead"


def test_plan_divergent_exits_2(tmp_path):
    state = sample_state(applied=applied((ID1, H1)))
    world = make_world(tmp_path, state, target=applied((ID1, H2)))
    assert world.run(f"plan {TAG1} {DIGEST_OK}") == BAD_INPUT
    assert world.stdout_json()["classification"] == "divergent"


def test_plan_release_api_outside_host_range_exits_2(tmp_path):
    world = make_world(tmp_path, release_api="2")
    assert world.run(f"plan {TAG1} {DIGEST_OK}") == BAD_INPUT
    assert world.stdout_json()["target"]["release_api"] == 2


def test_plan_dirty_exits_6(tmp_path):
    state = st.mark_dirty(sample_state(applied=applied((ID1, H1))), TAG1, "t0")
    world = make_world(tmp_path, state, target=applied((ID1, H1)))
    assert world.run(f"plan {TAG1} {DIGEST_OK}") == DIRTY
    assert world.stdout_json()["schema"]["dirty"] is True


def test_plan_database_id_mismatch_is_drift_exit_3(tmp_path):
    world = make_world(tmp_path, sample_state(applied=applied((ID1, H1))), db_ids=[ID1, ID2])
    assert world.run(f"plan {TAG1} {DIGEST_OK}") == DRIFT
    assert any(reason.startswith("schema:") for reason in world.stdout_json()["drift"])


def test_plan_stopped_web_container_is_drift_exit_3(tmp_path):
    world = make_world(tmp_path, running=False)
    assert world.run(f"plan {TAG1} {DIGEST_OK}") == DRIFT
    assert any("not running" in reason for reason in world.stdout_json()["drift"])


def test_plan_without_state_needs_bootstrap_and_touches_nothing(tmp_path):
    world = make_world(tmp_path, state=None)
    assert world.run(f"plan {TAG1} {DIGEST_OK}") == DRIFT
    assert "bootstrap required" in world.err.getvalue()
    assert world.host.calls == []


def test_plan_with_corrupt_state_exits_3(tmp_path):
    world = make_world(tmp_path)
    Path(world.settings.state_file).write_text("{broken", encoding="utf-8")
    assert world.run(f"plan {TAG1} {DIGEST_OK}") == DRIFT


def test_plan_exits_3_when_lock_is_busy(tmp_path):
    world = make_world(tmp_path)
    import fcntl
    import os

    blocker = os.open(world.settings.deploy_lock_file, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(blocker, fcntl.LOCK_EX)
    try:
        assert world.run(f"plan {TAG1} {DIGEST_OK}") == DRIFT
        assert "busy" in world.err.getvalue()
    finally:
        os.close(blocker)


def _started(run_id, unit):
    return hi.started_record(run_id=run_id, unit=unit, at="t0", target={"tag": TAG1}, expected_revision=1)


def test_plan_blocked_by_unresolved_indeterminate_run_exits_8(tmp_path):
    world = make_world(tmp_path)
    hi.append(world.settings.history_file, _started(RUN_ID_TEXT, f"book-finder-deploy-{RUN_ID_TEXT}"))
    assert world.run(f"plan {TAG1} {DIGEST_OK}") == INDETERMINATE
    assert world.stdout_json()["indeterminate"] == [RUN_ID_TEXT]


def test_plan_not_blocked_by_run_whose_unit_is_still_active(tmp_path):
    # An active unit means a deploy is in flight; plan only reports, and the deploy lock (not history) keeps plan out.
    unit = f"book-finder-deploy-{RUN_ID_TEXT}"
    world = make_world(tmp_path, unit_states={unit: "active"})
    hi.append(world.settings.history_file, _started(RUN_ID_TEXT, unit))
    assert world.run(f"plan {TAG1} {DIGEST_OK}") == OK


def test_plan_blocked_by_corrupt_history_tail_exits_8(tmp_path):
    world = make_world(tmp_path)
    Path(world.settings.history_file).write_text('{"run_id": "1-1", "phase": "sta', encoding="utf-8")
    assert world.run(f"plan {TAG1} {DIGEST_OK}") == INDETERMINATE


# status


def test_status_reports_completed_result(tmp_path):
    world = make_world(tmp_path)
    hi.append(world.settings.history_file, _started(RUN_ID_TEXT, "u"))
    hi.append(world.settings.history_file, hi.completed_record(run_id=RUN_ID_TEXT, result="ok", exit_code=0, at="t1", state_summary={}))
    assert world.run(f"status {RUN_ID_TEXT}") == OK
    assert world.stdout_json() == {"run_id": RUN_ID_TEXT, "status": "completed:ok"}


def test_status_reports_running_for_active_unit(tmp_path):
    unit = f"book-finder-deploy-{RUN_ID_TEXT}"
    world = make_world(tmp_path, unit_states={unit: "active"})
    hi.append(world.settings.history_file, _started(RUN_ID_TEXT, unit))
    assert world.run(f"status {RUN_ID_TEXT}") == OK
    assert world.stdout_json()["status"] == "running"


def test_status_reports_indeterminate_for_dead_unit_without_completed(tmp_path):
    world = make_world(tmp_path)
    hi.append(world.settings.history_file, _started(RUN_ID_TEXT, "u"))
    world.run(f"status {RUN_ID_TEXT}")
    assert world.stdout_json()["status"] == "indeterminate"


def test_status_reports_not_started_for_unknown_run(tmp_path):
    world = make_world(tmp_path)
    world.run(f"status {RUN_ID_TEXT}")
    assert world.stdout_json()["status"] == "not-started"


def test_status_prefers_history_over_a_conflicting_unit(tmp_path):
    unit = f"book-finder-deploy-{RUN_ID_TEXT}"
    world = make_world(tmp_path, unit_states={unit: "active"})
    hi.append(world.settings.history_file, _started(RUN_ID_TEXT, unit))
    hi.append(world.settings.history_file, hi.completed_record(run_id=RUN_ID_TEXT, result="failed-down", exit_code=5, at="t1", state_summary={}))
    world.run(f"status {RUN_ID_TEXT}")
    assert world.stdout_json()["status"] == "completed:failed-down"


# deploy gates


def deploy_text(world, *, revision=None, runtime=None, schema=None, chain="in-sync", cutover=False, target=DIGEST_OK, run_id=DEPLOY_RUN_ID):
    state = world.state
    text = (
        f"deploy {TAG1} {target} {CRAWLER} --run-id {run_id} --expect-revision {state.revision if revision is None else revision} "
        f"--expect-runtime {runtime or st.runtime_fingerprint(state.runtime)} "
        f"--expect-schema {schema or state.schema.digest} --chain {chain}"
    )
    return text + (" --cutover" if cutover else "")


def in_sync_world(tmp_path, **kwargs):
    state = sample_state(applied=applied((ID1, H1)))
    return make_world(tmp_path, state, target=applied((ID1, H1)), **kwargs)


def deploy_outcome(world):
    """Returns the last completed record's result and exit code for the run that deploy printed."""
    report = world.stdout_json()
    record = [e for e in world.history().entries if e.get("phase") == "completed" and e["run_id"] == report["run_id"]]
    return report, record


def test_deploy_refuses_a_run_id_with_any_history_and_writes_nothing(tmp_path):
    world = in_sync_world(tmp_path)
    assert world.run(deploy_text(world)) == OK  # first call runs the whole deployment
    before = Path(world.settings.history_file).read_text()
    # A retried SSH call with the same run id must not start a second deployment.
    assert world.run(deploy_text(world)) == DRIFT
    assert "run id already used" in world.err.getvalue()
    assert Path(world.settings.history_file).read_text() == before


def test_deploy_refuses_a_run_id_whose_started_record_has_no_completed(tmp_path):
    world = in_sync_world(tmp_path)
    hi.append(world.settings.history_file, _started(DEPLOY_RUN_ID, f"book-finder-deploy-{DEPLOY_RUN_ID}"))
    before = Path(world.settings.history_file).read_text()
    assert world.run(deploy_text(world)) == DRIFT
    assert Path(world.settings.history_file).read_text() == before


def test_deploy_without_state_needs_bootstrap(tmp_path):
    world = in_sync_world(tmp_path)
    world.remove_state()
    assert world.run(deploy_text(world)) == DRIFT
    assert world.history().entries == []


def test_deploy_refuses_while_history_is_indeterminate(tmp_path):
    world = in_sync_world(tmp_path)
    hi.append(world.settings.history_file, _started(RUN_ID_TEXT, f"book-finder-deploy-{RUN_ID_TEXT}"))
    assert world.run(deploy_text(world)) == INDETERMINATE
    assert len(world.history().entries) == 1


def test_deploy_cas_revision_mismatch_exits_3_and_records_the_run(tmp_path):
    world = in_sync_world(tmp_path)
    assert world.run(deploy_text(world, revision=7)) == DRIFT
    report, completed = deploy_outcome(world)
    assert report["exit_code"] == DRIFT
    assert completed[0]["result"] == "rejected"


def test_deploy_runtime_expectation_mismatch_exits_3(tmp_path):
    world = in_sync_world(tmp_path)
    assert world.run(deploy_text(world, runtime="sha256:" + "5" * 64)) == DRIFT


def test_deploy_schema_expectation_mismatch_exits_3(tmp_path):
    world = in_sync_world(tmp_path)
    assert world.run(deploy_text(world, schema="sha256:" + "5" * 64)) == DRIFT


def test_deploy_dirty_exits_6(tmp_path):
    state = st.mark_dirty(sample_state(applied=applied((ID1, H1))), TAG1, "t0")
    world = make_world(tmp_path, state, target=applied((ID1, H1)))
    assert world.run(deploy_text(world)) == DIRTY


def test_deploy_release_api_outside_range_exits_2(tmp_path):
    state = sample_state(applied=applied((ID1, H1)))
    world = make_world(tmp_path, state, target=applied((ID1, H1)), release_api="9")
    assert world.run(deploy_text(world)) == BAD_INPUT


def test_deploy_divergent_exits_2(tmp_path):
    state = sample_state(applied=applied((ID1, H1)))
    world = make_world(tmp_path, state, target=applied((ID1, H2)))
    assert world.run(deploy_text(world, chain="in-sync")) == BAD_INPUT


def test_deploy_chain_that_differs_from_recomputed_value_exits_3(tmp_path):
    state = sample_state(applied=applied((ID1, H1)))
    world = make_world(tmp_path, state, target=applied((ID1, H1), (ID2, H2)))
    assert world.run(deploy_text(world, chain="in-sync")) == DRIFT


def test_systemd_runtime_without_cutover_is_drift_s5(tmp_path):
    state = replace(sample_state(applied=applied((ID1, H1))), runtime=st.SystemdRuntime(unit=SYSTEMD_UNIT, version="pre-cd"))
    world = make_world(tmp_path, state, target=applied((ID1, H1)), unit_states={SYSTEMD_UNIT: "active"})
    assert world.run(deploy_text(world, runtime="systemd")) == DRIFT


def test_cutover_requires_systemd_runtime(tmp_path):
    world = in_sync_world(tmp_path)
    assert world.run(deploy_text(world, cutover=True)) == DRIFT


def test_cutover_requires_in_sync_chain(tmp_path):
    state = replace(sample_state(applied=applied((ID1, H1))), runtime=st.SystemdRuntime(unit=SYSTEMD_UNIT, version="pre-cd"))
    world = make_world(tmp_path, state, target=applied((ID1, H1), (ID2, H2)), unit_states={SYSTEMD_UNIT: "active"})
    assert world.run(deploy_text(world, runtime="systemd", chain="forward", cutover=True)) == BAD_INPUT


def test_deploy_observed_runtime_drift_exits_3(tmp_path):
    world = in_sync_world(tmp_path, running=False)
    assert world.run(deploy_text(world)) == DRIFT


def test_valid_deploy_runs_the_state_machine_to_success(tmp_path):
    world = in_sync_world(tmp_path)
    assert world.run(deploy_text(world)) == OK
    report, completed = deploy_outcome(world)
    assert completed[0]["result"] == "success"
    assert report["exit_code"] == OK and report["status"] == "completed:success"
    started = [e for e in world.history().entries if e.get("phase") == "started"]
    assert started and started[0]["expected_revision"] == 1


def test_valid_cutover_runs_the_state_machine(tmp_path):
    state = replace(sample_state(applied=applied((ID1, H1))), runtime=st.SystemdRuntime(unit=SYSTEMD_UNIT, version="pre-cd"))
    world = make_world(tmp_path, state, target=applied((ID1, H1)), unit_states={SYSTEMD_UNIT: "active"})
    assert world.run(deploy_text(world, runtime="systemd", cutover=True)) == OK
    assert deploy_outcome(world)[1][0]["result"] == "success"
    assert isinstance(world.load_state().runtime, st.DockerRuntime)


def test_deploy_lock_busy_exits_3(tmp_path):
    world = in_sync_world(tmp_path)
    import fcntl
    import os

    blocker = os.open(world.settings.deploy_lock_file, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(blocker, fcntl.LOCK_SH)
    try:
        assert world.run(deploy_text(world)) == DRIFT
        assert world.history().entries == []
    finally:
        os.close(blocker)


# entry-level behaviour


def test_test_hook_is_refused_for_root(tmp_path, monkeypatch):
    fakes = tmp_path / "fakes.json"
    fakes.write_text("{}")
    monkeypatch.setattr(cmd.os, "geteuid", lambda: 0)
    out, err = io.StringIO(), io.StringIO()
    code = cmd.main([], {"SSH_ORIGINAL_COMMAND": f"plan {TAG1} {DIGEST_OK}", cmd.TEST_HOOK_ENV: str(fakes)}, out, err)
    assert code == BAD_INPUT
    assert "root" in err.getvalue()


def test_missing_production_configuration_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr(cmd, "DEFAULT_CONFIG", tmp_path / "absent.conf")
    out, err = io.StringIO(), io.StringIO()
    assert cmd.main([], {"SSH_ORIGINAL_COMMAND": f"status {RUN_ID_TEXT}"}, out, err) == BAD_INPUT
