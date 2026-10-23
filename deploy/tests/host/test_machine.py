"""Tests for bookfinder_host.machine: one test per branch of the deploy state machine (deploy/README.md §1.1).

Why: the state machine is the only code that changes the production host. Each test checks the exit code, the
completed result, the order of effects (pause before snapshot, dirty before efbundle, stop before up, and so on),
the final state, and that the env file with secrets is removed and never printed.
"""

import dataclasses
import fcntl
import hashlib
import json
import os
import stat
from pathlib import Path

import pytest
from bookfinder_host import commands as cmd
from bookfinder_host import history as hi
from bookfinder_host import machine
from bookfinder_host import state as st
from bookfinder_host.exit_codes import BAD_INPUT, DRIFT, FAILED_DOWN, FAILED_MIGRATION, OK, PARTIAL_CRAWLER, ROLLED_BACK
from bookfinder_host.manifest import Migration
from bookfinder_host.release_content import COMPOSE_FILE
from bookfinder_host.testing import FAKE_COMPOSE, sample_state, write_release
from worlds import (
    CRAWLER,
    CRAWLER2,
    DIGEST_OK,
    H1,
    H2,
    ID1,
    ID2,
    PUBLIC_URL,
    SYSTEMD_UNIT,
    TAG1,
    TAG2,
    WEB1,
    applied,
    make_world,
)

LOCAL = machine.LOCAL_URL
PUBLIC = PUBLIC_URL + "/"
RUN_ID = "5555-1"
SECRET_MARKERS = ("secret-for-",)


def deploy_text(world, *, chain="in-sync", cutover=False, target=DIGEST_OK, crawler=CRAWLER2, run_id=RUN_ID, tag=TAG2, expect_schema=None):
    state = world.state
    runtime = "systemd" if cutover else st.runtime_fingerprint(state.runtime)
    return (
        f"deploy {tag} {target} {crawler} --run-id {run_id} --expect-revision {state.revision} "
        f"--expect-runtime {runtime} --expect-schema {expect_schema or state.schema.digest} --chain {chain}" + (" --cutover" if cutover else "")
    )


def env_path(world, run_id=RUN_ID) -> Path:
    return Path(world.settings.run_dir) / f"web-{run_id}.env"


def index_of(trace: list[str], prefix: str, start: int = 0) -> int:
    for position in range(start, len(trace)):
        if trace[position].startswith(prefix):
            return position
    raise AssertionError(f"{prefix!r} not in trace after {start}: {trace}")


def assert_no_secret_leaks(world, *texts: str) -> None:
    history = Path(world.settings.history_file).read_text() if Path(world.settings.history_file).exists() else ""
    for text in (*texts, history):
        for marker in SECRET_MARKERS:
            assert marker not in text


def lock_is_free(path: str) -> bool:
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


def completed_records(world):
    return [e for e in world.history().entries if e.get("phase") == "completed"]


def in_sync_world(tmp_path, **kwargs):
    state = sample_state(applied=applied((ID1, H1)))
    return make_world(tmp_path, state, target=applied((ID1, H1)), **kwargs)


def forward_world(tmp_path, **kwargs):
    state = sample_state(applied=applied((ID1, H1)))
    world = make_world(tmp_path, state, target=applied((ID1, H1), (ID2, H2)), **kwargs)
    world.fx.docker.efbundle_db_ids = [ID1, ID2]
    return world


def cutover_world(tmp_path, **kwargs):
    state = dataclasses.replace(sample_state(applied=applied((ID1, H1))), runtime=st.SystemdRuntime(unit=SYSTEMD_UNIT, version="pre-cd"))
    return make_world(tmp_path, state, target=applied((ID1, H1)), unit_states={SYSTEMD_UNIT: "active"}, **kwargs)


def with_old_release(world, *, sha_matches: bool = True) -> Path:
    """Gives the current docker runtime a real release directory, so rollback can verify its compose file."""
    release = world.tmp_path / "releases" / "old"
    write_release(release, [], "1", compose="services:\n  web:\n    image: old\n")
    digest = hashlib.sha256((release / COMPOSE_FILE).read_bytes()).hexdigest()
    if not sha_matches:
        digest = "0" * 64
    runtime = dataclasses.replace(world.state.runtime, release_dir=str(release), compose_sha256=digest)
    world.state = dataclasses.replace(world.state, runtime=runtime)
    world.write_state(world.state)
    return release


def set_setting(world, **changes) -> None:
    world.deps = dataclasses.replace(world.deps, settings=dataclasses.replace(world.deps.settings, **changes))


def crawler_substeps(world) -> dict:
    return completed_records(world)[-1]["crawler_substeps"]


def only_web_failures_on_target(world, up_failures: int = 1) -> None:
    """The target's compose up fails before any health check, so the rollback's compose up and its health pass."""
    world.fx.compose.up_failures = up_failures


# In-sync docker deployment: the happy path and its order


def test_in_sync_success_runs_steps_in_order_and_leaves_clean_state(tmp_path):
    world = in_sync_world(tmp_path)
    code, out, err = world.run_unit(deploy_text(world))
    assert code == OK, err
    trace = world.fx.trace
    health = index_of(trace, f"http {LOCAL}")
    extract = index_of(trace, "docker.extract")
    env_write = index_of(trace, f"files.write {env_path(world)}")
    up = index_of(trace, "compose.up")
    public = index_of(trace, f"http {PUBLIC}", up)
    pull = index_of(trace, "docker.pull")
    assert health < extract < env_write < up < public < pull
    assert json.loads(out) == {"run_id": RUN_ID, "result": "success", "exit_code": OK}

    final = world.load_state()
    assert final.runtime.web_digest == DIGEST_OK and isinstance(final.runtime, st.DockerRuntime)
    assert final.previous_runtime == sample_state(applied=applied((ID1, H1))).runtime
    assert final.crawler.digest == CRAWLER2 and final.crawler.paused is None
    assert final.schema.dirty is False and final.schema.applied == world.state.schema.applied
    assert final.revision == world.state.revision + 1
    record = completed_records(world)[-1]
    assert record["result"] == "success" and record["exit_code"] == OK and "state_summary" in record
    assert "snapshot_id" not in record
    assert not env_path(world).exists()
    assert "CRAWLER_IMAGE=" in Path(world.settings.crawler_conf).read_text()
    assert f"CRAWLER_IMAGE={world.settings.crawler_image_repository}@{CRAWLER2}" in Path(world.settings.crawler_conf).read_text()
    assert_no_secret_leaks(world, out, err)


def test_in_sync_success_never_calls_aws_or_efbundle(tmp_path):
    world = in_sync_world(tmp_path)
    assert world.run_unit(deploy_text(world))[0] == OK
    assert not [t for t in world.fx.trace if t.startswith(("aws.", "docker.efbundle"))]
    assert world.fx.docker.env_files_seen == []


def test_env_file_exists_while_compose_reads_it_and_is_removed_at_the_end(tmp_path):
    world = in_sync_world(tmp_path)
    seen = {}
    world.fx.compose.on_up = lambda: seen.setdefault("up_env_exists", env_path(world).exists())
    assert world.run_unit(deploy_text(world))[0] == OK
    # The file exists while compose reads it and is gone once the run ends; its contents are checked in the forward test.
    assert seen["up_env_exists"] is True
    assert not env_path(world).exists()
    up_env = world.fx.compose.up_calls[0][1]
    assert up_env["WEB_ENV_FILE"] == str(env_path(world))
    assert up_env["WEB_IMAGE"] == f"{world.settings.web_image_repository}@{DIGEST_OK}"


# Step 1 and step 2 refusals


def test_step1_health_failure_is_drift_and_changes_nothing(tmp_path):
    world = in_sync_world(tmp_path)
    world.fx.http.script[LOCAL] = [503]
    code, _out, err = world.run_unit(deploy_text(world))
    assert code == DRIFT
    assert "current runtime failed its health check" in err
    assert not [t for t in world.fx.trace if t.startswith(("compose.", "docker.", "ssm.", "files.write"))]
    assert world.fx.http.calls.count((LOCAL, {"X-Forwarded-Proto": "https"})) == 3
    assert world.load_state() == world.state
    assert completed_records(world)[-1]["result"] == "drift"


def test_paused_crawler_from_an_earlier_run_refuses_the_deploy(tmp_path):
    world = in_sync_world(tmp_path)
    world.write_state(st.pause_crawler(world.state, release=TAG1, reason="earlier", now="t0"))
    code, _, err = world.run_unit(deploy_text(world))
    assert code == DRIFT and "resume-crawler" in err
    assert not any(t.startswith(("compose.", "docker.", "files.write")) for t in world.fx.trace)


def test_extraction_failure_is_drift_before_anything_changes(tmp_path):
    world = in_sync_world(tmp_path)
    world.fx.docker.extract_error = "docker cp failed"
    code, _, err = world.run_unit(deploy_text(world))
    assert code == DRIFT
    assert "could not be extracted" in err
    assert not any(t.startswith("compose.") for t in world.fx.trace)


def test_release_with_a_symlink_is_refused_and_its_target_is_never_read(tmp_path):
    world = in_sync_world(tmp_path)
    bad = tmp_path / "bad-release"
    write_release(bad, [Migration(ID1, H1)])
    (bad / "evil").symlink_to("/etc/shadow")
    world.fx.docker.release_tree = bad
    code, _, err = world.run_unit(deploy_text(world))
    assert code == BAD_INPUT
    assert "not a regular file or directory: evil" in err
    assert not any(t.startswith("compose.") for t in world.fx.trace)
    assert completed_records(world)[-1]["result"] == "rejected"


def test_release_larger_than_two_mebibytes_is_refused(tmp_path):
    world = in_sync_world(tmp_path)
    big = tmp_path / "big-release"
    write_release(big, [Migration(ID1, H1)])
    (big / "payload.bin").write_bytes(b"\0" * ((2 << 20) + 1))
    world.fx.docker.release_tree = big
    code, _, err = world.run_unit(deploy_text(world))
    assert code == BAD_INPUT and "larger than" in err


def test_existing_release_directory_with_a_different_compose_file_is_drift(tmp_path):
    world = in_sync_world(tmp_path)
    existing = Path(world.settings.releases_dir) / DIGEST_OK.split(":", 1)[1]
    write_release(existing, [Migration(ID1, H1)], compose="services:\n  web:\n    image: other\n")
    code, _, err = world.run_unit(deploy_text(world))
    assert code == DRIFT and "different compose file" in err
    assert not any(t.startswith("compose.") for t in world.fx.trace)


def test_existing_release_directory_with_the_same_compose_file_is_reused(tmp_path):
    world = in_sync_world(tmp_path)
    existing = Path(world.settings.releases_dir) / DIGEST_OK.split(":", 1)[1]
    write_release(existing, [Migration(ID1, H1)], compose=FAKE_COMPOSE)
    assert world.run_unit(deploy_text(world))[0] == OK
    assert world.fx.compose.up_calls[0][0] == str(existing / COMPOSE_FILE)


def test_secret_value_with_a_newline_is_refused_and_no_env_file_is_left(tmp_path):
    world = in_sync_world(tmp_path)
    world.fx.ssm.values[world.settings.ssm_openai_key] = "line-one\nline-two"
    code, out, err = world.run_unit(deploy_text(world))
    assert code == BAD_INPUT
    assert "OPENAIAPI_KEY must be a non-empty single-line value" in err
    assert "line-one" not in err and "line-one" not in out
    assert not env_path(world).exists()
    assert not any(t.startswith("compose.") for t in world.fx.trace)


def test_ssm_read_failure_is_drift(tmp_path):
    world = in_sync_world(tmp_path)
    world.fx.ssm.missing.add(world.settings.ssm_jwt_key)
    code, _, err = world.run_unit(deploy_text(world))
    assert code == DRIFT and "reading" in err
    assert not env_path(world).exists()


# Step 5 to 7 for in-sync and schema-ahead: rollback


def test_in_sync_compose_failure_rolls_back_to_the_previous_release(tmp_path):
    world = in_sync_world(tmp_path)
    old = with_old_release(world)
    only_web_failures_on_target(world)
    code, _, err = world.run_unit(deploy_text(world))
    assert code == ROLLED_BACK and "restored the previous runtime" in err
    ups = world.fx.compose.up_calls
    assert len(ups) == 2
    assert ups[1][0] == str(old / COMPOSE_FILE)
    assert ups[1][1]["WEB_IMAGE"] == f"{world.settings.web_image_repository}@{WEB1}"
    final = world.load_state()
    assert final == world.state  # rollback writes nothing: the runtime was never promoted
    assert completed_records(world)[-1]["result"] == "rolled-back"
    assert not env_path(world).exists()


def test_post_switch_public_health_failure_rolls_back(tmp_path):
    world = in_sync_world(tmp_path)
    with_old_release(world)
    world.fx.http.responder = lambda url: 503 if url == PUBLIC and len(world.fx.compose.up_calls) == 1 else 200
    code, _, _err = world.run_unit(deploy_text(world))
    assert code == ROLLED_BACK
    assert len(world.fx.compose.up_calls) == 2


def test_rollback_refused_when_the_previous_compose_file_does_not_match_state(tmp_path):
    world = in_sync_world(tmp_path)
    with_old_release(world, sha_matches=False)
    only_web_failures_on_target(world)
    code, _, err = world.run_unit(deploy_text(world))
    assert code == FAILED_DOWN and "does not match state; no rollback" in err
    assert len(world.fx.compose.up_calls) == 1  # only the target was started


def test_rollback_health_failure_is_failed_down(tmp_path):
    world = in_sync_world(tmp_path)
    with_old_release(world)
    world.fx.compose.up_failures = 1
    world.fx.http.responder = lambda url: 503 if len(world.fx.compose.up_calls) == 2 else 200
    code, _, err = world.run_unit(deploy_text(world))
    assert code == FAILED_DOWN and "manual recovery required" in err
    assert completed_records(world)[-1]["result"] == "failed-down"


def test_schema_ahead_web_failure_also_rolls_back(tmp_path):
    state = sample_state(applied=applied((ID1, H1), (ID2, H2)))
    world = make_world(tmp_path, state, target=applied((ID1, H1)))
    with_old_release(world)
    only_web_failures_on_target(world)
    assert world.run_unit(deploy_text(world, chain="schema-ahead", crawler=CRAWLER))[0] == ROLLED_BACK


# Schema-ahead keeps the crawler: no pull, install or conf rewrite, and the digest must be the current one


def schema_ahead_world(tmp_path):
    state = sample_state(applied=applied((ID1, H1), (ID2, H2)))
    return make_world(tmp_path, state, target=applied((ID1, H1)))


def test_schema_ahead_success_skips_the_crawler_and_keeps_its_digest(tmp_path):
    world = schema_ahead_world(tmp_path)
    conf_before = Path(world.settings.crawler_conf).read_text()
    assert world.run_unit(deploy_text(world, chain="schema-ahead", crawler=CRAWLER))[0] == OK
    record = completed_records(world)[-1]
    assert (record["result"], record["exit_code"]) == ("success", OK)
    assert record["crawler_substeps"] == "skipped (schema-ahead)"
    assert world.load_state().crawler.digest == CRAWLER
    assert world.load_state().crawler == world.state.crawler
    assert world.load_state().runtime.crawler_digest == CRAWLER
    assert world.load_state().schema.rebuild == world.state.schema.rebuild
    crawler_paths = {world.settings.crawler_runner, world.settings.cron_file, world.settings.crawler_conf}
    assert not [t for t in world.fx.trace if t.startswith("docker.pull") or t.split(" ", 1)[-1] in crawler_paths]
    assert Path(world.settings.crawler_conf).read_text() == conf_before


def test_schema_ahead_with_another_crawler_is_rejected_by_the_unit_gate(tmp_path):
    world = schema_ahead_world(tmp_path)
    before = world.load_state()
    code, _, err = world.run_unit(deploy_text(world, chain="schema-ahead", crawler=CRAWLER2))
    assert code == BAD_INPUT
    assert f"schema-ahead keeps the current crawler ({CRAWLER})" in err
    record = completed_records(world)[-1]
    assert (record["result"], record["exit_code"]) == ("rejected", BAD_INPUT)
    assert world.load_state() == before
    assert not [t for t in world.fx.trace if t.startswith(("docker.pull", "docker.extract", "compose.up", "files.write", "aws."))]


# Cutover: systemd to docker


def test_cutover_stops_systemd_before_compose_up_and_promotes_docker(tmp_path):
    world = cutover_world(tmp_path)
    code, _, err = world.run_unit(deploy_text(world, cutover=True))
    assert code == OK, err
    trace = world.fx.trace
    assert index_of(trace, f"systemd.stop {SYSTEMD_UNIT}") < index_of(trace, "compose.up")
    assert not any(t.startswith("systemd.start") for t in trace)
    final = world.load_state()
    assert isinstance(final.runtime, st.DockerRuntime) and final.runtime.web_digest == DIGEST_OK
    assert final.previous_runtime == st.SystemdRuntime(unit=SYSTEMD_UNIT, version="pre-cd")
    assert completed_records(world)[-1]["result"] == "success"


def test_cutover_compose_failure_brings_the_systemd_unit_back(tmp_path):
    world = cutover_world(tmp_path)
    world.fx.compose.up_failures = 1
    code, _, _err = world.run_unit(deploy_text(world, cutover=True))
    assert code == ROLLED_BACK
    trace = world.fx.trace
    down = index_of(trace, "compose.down")
    start = index_of(trace, f"systemd.start {SYSTEMD_UNIT}", down)
    assert down < start
    assert isinstance(world.load_state().runtime, st.SystemdRuntime)


def test_cutover_stop_failure_is_treated_as_a_switch_failure(tmp_path):
    world = cutover_world(tmp_path)
    world.fx.systemd.stop_error = "unit busy"
    code, _, _err = world.run_unit(deploy_text(world, cutover=True))
    assert code == ROLLED_BACK
    assert not any(t.startswith("compose.up") for t in world.fx.trace)
    assert index_of(world.fx.trace, f"systemd.start {SYSTEMD_UNIT}") > index_of(world.fx.trace, f"systemd.stop {SYSTEMD_UNIT}")


def test_cutover_rollback_start_failure_is_failed_down(tmp_path):
    world = cutover_world(tmp_path)
    world.fx.compose.up_failures = 1
    world.fx.systemd.start_error = "start failed"
    code, _, _err = world.run_unit(deploy_text(world, cutover=True))
    assert code == FAILED_DOWN


# Forward migration: the chain that changes the schema


def test_forward_success_orders_pause_snapshot_dirty_efbundle_and_releases_the_lock(tmp_path):
    world = forward_world(tmp_path)
    snapshots = {}
    world.fx.aws.on_create = lambda: snapshots.update(
        paused_at_snapshot=world.load_state().crawler.paused is not None, dirty_at_snapshot=world.load_state().schema.dirty
    )

    def at_efbundle(reference, env_file):
        state = world.load_state()
        snapshots.update(dirty_at_efbundle=state.schema.dirty, paused_at_efbundle=state.crawler.paused is not None)
        snapshots["env_mode"] = stat.S_IMODE(os.stat(env_file).st_mode)
        snapshots["env_lines"] = [line.split("=", 1)[0] for line in Path(env_file).read_text().splitlines()]

    world.fx.docker.efbundle_hook = at_efbundle
    world.fx.compose.on_up = lambda: snapshots.update(
        lock_free_at_up=lock_is_free(world.settings.db_maintenance_lock),
        dirty_at_up=world.load_state().schema.dirty,
        applied_at_up=[e.id for e in world.load_state().schema.applied],
    )
    code, out, err = world.run_unit(deploy_text(world, chain="forward", tag=TAG2))
    assert code == OK, err
    trace = world.fx.trace
    create = index_of(trace, "aws.create")
    wait = index_of(trace, "aws.wait", create)
    efbundle = index_of(trace, "docker.efbundle")
    up = index_of(trace, "compose.up")
    assert create < wait < efbundle < up

    assert snapshots["paused_at_snapshot"] is True and snapshots["dirty_at_snapshot"] is False
    assert snapshots["dirty_at_efbundle"] is True and snapshots["paused_at_efbundle"] is True
    assert snapshots["env_mode"] == 0o600
    assert snapshots["env_lines"] == ["ConnectionStrings__DefaultConnection", "OPENAIAPI_KEY", "Jwt__SigningKey"]
    assert snapshots["lock_free_at_up"] is True  # the maintenance lock was released before the switch
    assert snapshots["dirty_at_up"] is False and snapshots["applied_at_up"] == [ID1, ID2]

    final = world.load_state()
    assert final.schema.dirty is False and final.crawler.paused is None
    assert final.schema.rebuild.tag == TAG2 and final.schema.rebuild.web_digest == DIGEST_OK
    assert [e.id for e in final.schema.applied] == [ID1, ID2]
    assert final.runtime.web_digest == DIGEST_OK and final.previous_runtime.web_digest == WEB1
    assert final.crawler.digest == CRAWLER2
    record = completed_records(world)[-1]
    assert record["result"] == "success" and record["snapshot_id"].startswith("book-finder-pre-v1-1-0-2026")
    assert not env_path(world).exists()
    assert_no_secret_leaks(world, out, err)


def test_forward_snapshot_failure_resumes_crawler_and_migrates_nothing(tmp_path):
    world = forward_world(tmp_path)
    world.fx.aws.create_error = "access denied"
    code, _, err = world.run_unit(deploy_text(world, chain="forward", tag=TAG2))
    assert code == DRIFT
    assert "snapshot failed; nothing was migrated and the crawler was resumed" in err
    assert not any(t.startswith("docker.efbundle") for t in world.fx.trace)
    final = world.load_state()
    assert final.crawler.paused is None and final.schema.dirty is False
    assert [e.id for e in final.schema.applied] == [ID1]
    assert completed_records(world)[-1]["result"] == "drift"
    assert not env_path(world).exists()


def test_forward_snapshot_wait_failure_is_also_a_snapshot_failure(tmp_path):
    world = forward_world(tmp_path)
    world.fx.aws.wait_error = "snapshot failed"
    assert world.run_unit(deploy_text(world, chain="forward", tag=TAG2))[0] == DRIFT
    assert world.load_state().crawler.paused is None


def test_forward_efbundle_nonzero_keeps_dirty_and_paused_and_touches_no_runtime(tmp_path):
    world = forward_world(tmp_path)
    world.fx.docker.efbundle_rc = 1
    code, _out, err = world.run_unit(deploy_text(world, chain="forward", tag=TAG2))
    assert code == FAILED_MIGRATION and "schema stays dirty" in err
    final = world.load_state()
    assert final.schema.dirty is True and final.schema.dirty_release == TAG2
    assert final.crawler.paused is not None and final.crawler.paused.release == TAG2
    assert final.runtime == world.state.runtime and final.previous_runtime is None
    assert not any(t.startswith(("compose.", "systemd.")) for t in world.fx.trace)
    assert completed_records(world)[-1]["result"] == "failed-migration"
    assert lock_is_free(world.settings.db_maintenance_lock)
    assert not env_path(world).exists()


def test_forward_exit_zero_with_wrong_database_ids_is_failed_migration(tmp_path):
    world = forward_world(tmp_path)
    world.fx.docker.efbundle_db_ids = [ID1]  # the database did not reach the target
    code, _, _err = world.run_unit(deploy_text(world, chain="forward", tag=TAG2))
    assert code == FAILED_MIGRATION
    assert world.load_state().schema.dirty is True


def test_forward_web_failure_never_rolls_back(tmp_path):
    world = forward_world(tmp_path)
    with_old_release(world)
    only_web_failures_on_target(world)
    code, _, err = world.run_unit(deploy_text(world, chain="forward", tag=TAG2))
    assert code == FAILED_DOWN
    assert "no automatic rollback (I5)" in err and "manual recovery required" in err
    assert len(world.fx.compose.up_calls) == 1
    final = world.load_state()
    assert final.crawler.paused is not None and final.schema.dirty is False
    assert completed_records(world)[-1]["snapshot_id"]


def test_forward_crawler_failure_is_partial_and_keeps_the_crawler_paused(tmp_path):
    world = forward_world(tmp_path)
    world.fx.docker.smoke_rc = 1
    conf_before = Path(world.settings.crawler_conf).read_text()
    code, _, err = world.run_unit(deploy_text(world, chain="forward", tag=TAG2))
    assert code == PARTIAL_CRAWLER and "crawler stays paused" in err
    final = world.load_state()
    assert final.runtime.web_digest == DIGEST_OK  # the web is serving the new release
    assert final.crawler.paused is not None and final.crawler.digest == CRAWLER
    assert Path(world.settings.crawler_conf).read_text() == conf_before
    assert completed_records(world)[-1]["result"] == "partial-crawler"


def test_forward_lock_busy_is_drift_before_any_state_change(tmp_path):
    world = forward_world(tmp_path)
    world.deps = dataclasses.replace(world.deps, maintenance_timeout_s=0.01)
    fd = os.open(world.settings.db_maintenance_lock, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_SH)
    try:
        code, _, err = world.run_unit(deploy_text(world, chain="forward", tag=TAG2))
    finally:
        os.close(fd)
    assert code == DRIFT and "db-maintenance lock stayed busy" in err
    assert world.load_state() == world.state


# Crawler step


def test_in_sync_crawler_failure_promotes_web_and_pauses_the_crawler(tmp_path):
    world = in_sync_world(tmp_path)
    world.fx.docker.smoke_rc = 1
    code, _, _err = world.run_unit(deploy_text(world))
    assert code == PARTIAL_CRAWLER
    final = world.load_state()
    assert final.runtime.web_digest == DIGEST_OK
    assert final.crawler.paused is not None and final.crawler.paused.reason == "crawler update failed"
    assert final.crawler.digest == CRAWLER


def test_crawler_config_missing_is_partial_crawler(tmp_path):
    world = in_sync_world(tmp_path)
    Path(world.settings.crawler_conf).unlink()
    assert world.run_unit(deploy_text(world))[0] == PARTIAL_CRAWLER


def test_crawler_pull_failure_is_partial_crawler(tmp_path):
    world = in_sync_world(tmp_path)
    world.fx.docker.pull_error = "manifest unknown"
    assert world.run_unit(deploy_text(world))[0] == PARTIAL_CRAWLER
    assert not any(t.startswith("docker.smoke") for t in world.fx.trace)


def test_crawler_files_are_installed_with_their_modes_when_the_release_has_them(tmp_path):
    world = in_sync_world(tmp_path)
    release = tmp_path / "release-with-crawler"
    write_release(release, [Migration(ID1, H1)])
    (release / "run-crawler.sh").write_text("#!/bin/sh\necho crawl\n")
    (release / "crawler.cron").write_text("0 3 * * * root /opt/book-finder/run-crawler.sh\n")
    world.fx.docker.release_tree = release
    assert world.run_unit(deploy_text(world))[0] == OK
    # Order: run-crawler.sh first (it is the guard), then the cron file, then crawler.conf last.
    trace = world.fx.trace
    run_write = index_of(trace, f"files.write {world.settings.crawler_runner}")
    cron_write = index_of(trace, f"files.write {world.settings.cron_file}")
    conf_write = index_of(trace, f"files.write {world.settings.crawler_conf}")
    assert run_write < cron_write < conf_write
    assert crawler_substeps(world) == {
        "image": "ok",
        "smoke": "ok",
        "run_crawler": "ok",
        "crawler_cron": "ok",
        "crawler_conf": "ok",
    }
    assert stat.S_IMODE(os.stat(world.settings.crawler_runner).st_mode) == 0o755
    assert stat.S_IMODE(os.stat(world.settings.cron_file).st_mode) == 0o644
    assert Path(world.settings.crawler_runner).read_text() == "#!/bin/sh\necho crawl\n"


def test_crawler_steps_not_shipped_by_the_release_are_skipped_and_recorded(tmp_path):
    world = in_sync_world(tmp_path)
    assert world.run_unit(deploy_text(world))[0] == OK
    assert crawler_substeps(world) == {
        "image": "ok",
        "smoke": "ok",
        "run_crawler": "skipped",
        "crawler_cron": "skipped",
        "crawler_conf": "ok",
    }


def test_run_crawler_install_failure_stops_the_sequence_and_records_it(tmp_path):
    world = in_sync_world(tmp_path)
    set_setting(world, crawler_runner=str(tmp_path / "missing-dir" / "run-crawler.sh"))
    release = tmp_path / "release-with-crawler"
    write_release(release, [Migration(ID1, H1)])
    (release / "run-crawler.sh").write_text("#!/bin/sh\n")
    (release / "crawler.cron").write_text("0 3 * * * root x\n")
    world.fx.docker.release_tree = release
    conf_before = Path(world.settings.crawler_conf).read_text()
    code, _, err = world.run_unit(deploy_text(world))
    assert code == PARTIAL_CRAWLER and "run_crawler failed" in err
    assert crawler_substeps(world) == {
        "image": "ok",
        "smoke": "ok",
        "run_crawler": "failed",
        "crawler_cron": "not-run",
        "crawler_conf": "not-run",
    }
    assert Path(world.settings.crawler_conf).read_text() == conf_before
    assert not any(t.startswith("files.write") and t.endswith("crawler.conf") for t in world.fx.trace)
    final = world.load_state()
    assert final.crawler.digest == CRAWLER and final.crawler.paused is not None


def test_cron_install_failure_keeps_the_old_conf_and_records_the_earlier_sub_steps(tmp_path):
    world = in_sync_world(tmp_path)
    set_setting(world, cron_file=str(tmp_path / "missing-dir" / "cron"))
    release = tmp_path / "release-with-cron"
    write_release(release, [Migration(ID1, H1)])
    (release / "run-crawler.sh").write_text("#!/bin/sh\n")
    (release / "crawler.cron").write_text("0 3 * * * root x\n")
    world.fx.docker.release_tree = release
    conf_before = Path(world.settings.crawler_conf).read_text()
    assert world.run_unit(deploy_text(world))[0] == PARTIAL_CRAWLER
    substeps = crawler_substeps(world)
    assert substeps["run_crawler"] == "ok" and substeps["crawler_cron"] == "failed" and substeps["crawler_conf"] == "not-run"
    assert Path(world.settings.crawler_conf).read_text() == conf_before
    assert world.load_state().crawler.paused is not None


def test_conf_failure_after_both_installs_is_recorded_last(tmp_path):
    world = in_sync_world(tmp_path)
    Path(world.settings.crawler_conf).unlink()
    release = tmp_path / "release-with-both"
    write_release(release, [Migration(ID1, H1)])
    (release / "run-crawler.sh").write_text("#!/bin/sh\n")
    (release / "crawler.cron").write_text("0 3 * * * root x\n")
    world.fx.docker.release_tree = release
    assert world.run_unit(deploy_text(world))[0] == PARTIAL_CRAWLER
    assert crawler_substeps(world) == {
        "image": "ok",
        "smoke": "ok",
        "run_crawler": "ok",
        "crawler_cron": "ok",
        "crawler_conf": "failed",
    }
    assert world.load_state().crawler.digest == CRAWLER


def test_smoke_failure_stops_before_any_install(tmp_path):
    world = in_sync_world(tmp_path)
    world.fx.docker.smoke_rc = 1
    assert world.run_unit(deploy_text(world))[0] == PARTIAL_CRAWLER
    assert crawler_substeps(world) == {
        "image": "ok",
        "smoke": "failed",
        "run_crawler": "not-run",
        "crawler_cron": "not-run",
        "crawler_conf": "not-run",
    }


def shipped_crawler_release(tmp_path, runner: str | None, cron: str | None, name: str = "release-crawler"):
    release = tmp_path / name
    write_release(release, [Migration(ID1, H1)])
    if runner is not None:
        (release / "run-crawler.sh").write_text(runner)
    if cron is not None:
        (release / "crawler.cron").write_text(cron)
    return release


def test_success_records_the_hashes_of_the_installed_files_and_the_source_release(tmp_path):
    world = in_sync_world(tmp_path)
    runner, cron = "#!/bin/sh\necho crawl\n", "0 3 * * * root /opt/book-finder/run-crawler.sh\n"
    world.fx.docker.release_tree = shipped_crawler_release(tmp_path, runner, cron)
    assert world.run_unit(deploy_text(world))[0] == OK
    crawler = world.load_state().crawler
    assert crawler.digest == CRAWLER2 and crawler.paused is None
    assert crawler.runner_sha256 == hashlib.sha256(Path(world.settings.crawler_runner).read_bytes()).hexdigest()
    assert crawler.cron_sha256 == hashlib.sha256(Path(world.settings.cron_file).read_bytes()).hexdigest()
    assert crawler.source_release == st.SourceRelease(tag=TAG2, web_digest=DIGEST_OK)


def test_a_file_the_release_does_not_ship_keeps_its_recorded_hash(tmp_path):
    world = in_sync_world(tmp_path)
    before = world.state.crawler
    world.fx.docker.release_tree = shipped_crawler_release(tmp_path, "#!/bin/sh\necho new\n", None)
    assert world.run_unit(deploy_text(world))[0] == OK
    crawler = world.load_state().crawler
    assert crawler.runner_sha256 == hashlib.sha256(b"#!/bin/sh\necho new\n").hexdigest()
    assert crawler.cron_sha256 == before.cron_sha256
    assert crawler.source_release == st.SourceRelease(tag=TAG2, web_digest=DIGEST_OK)


def test_a_runner_larger_than_the_config_cap_is_still_recorded(tmp_path):
    # The config reader caps reads at 64 KiB; the runner may be 1 MiB, so its provenance must not depend on that cap.
    world = in_sync_world(tmp_path)
    runner = "#!/bin/sh\n" + "# padding\n" * 10_000
    assert len(runner) > 65536
    world.fx.docker.release_tree = shipped_crawler_release(tmp_path, runner, None)
    assert world.run_unit(deploy_text(world))[0] == OK
    assert world.load_state().crawler.runner_sha256 == hashlib.sha256(runner.encode()).hexdigest()


def test_a_partial_crawler_update_keeps_the_old_provenance(tmp_path):
    world = in_sync_world(tmp_path)
    before = world.state.crawler
    set_setting(world, cron_file=str(tmp_path / "missing-dir" / "cron"))
    world.fx.docker.release_tree = shipped_crawler_release(tmp_path, "#!/bin/sh\necho new\n", "0 3 * * * root x\n")
    assert world.run_unit(deploy_text(world))[0] == PARTIAL_CRAWLER
    crawler = world.load_state().crawler
    assert (crawler.digest, crawler.runner_sha256, crawler.cron_sha256, crawler.source_release) == (
        before.digest,
        before.runner_sha256,
        before.cron_sha256,
        before.source_release,
    )
    assert crawler.paused is not None


def test_crawler_conf_rewrite_keeps_other_lines_and_mode(tmp_path):
    world = in_sync_world(tmp_path)
    conf = Path(world.settings.crawler_conf)
    os.chmod(conf, 0o640)
    # The operator's pause switch must survive a deploy that rewrites CRAWLER_IMAGE (#101).
    conf.write_text(conf.read_text() + "CRAWLER_ENABLED=false\n", encoding="utf-8")
    assert world.run_unit(deploy_text(world))[0] == OK
    lines = conf.read_text().splitlines()
    assert lines == [
        f"CRAWLER_IMAGE={world.settings.crawler_image_repository}@{CRAWLER2}",
        "SCHEDULE=0 3 * * *",
        "CRAWLER_ENABLED=false",
    ]
    assert stat.S_IMODE(os.stat(conf).st_mode) == 0o640


def test_rewrite_crawler_image_requires_exactly_one_key_line():
    with pytest.raises(ValueError):
        machine.rewrite_crawler_image(b"SCHEDULE=1\n", f"repo@{CRAWLER2}")
    with pytest.raises(ValueError):
        machine.rewrite_crawler_image(b"CRAWLER_IMAGE=a\nCRAWLER_IMAGE=b\n", f"repo@{CRAWLER2}")
    with pytest.raises(ValueError):
        machine.rewrite_crawler_image(b"CRAWLER_IMAGE=a\n", "repo:latest")


def test_rewrite_crawler_image_is_byte_identical_outside_the_key_line():
    data = b"# header\r\nCRAWLER_IMAGE=old\nSCHEDULE=0 3 * * *\nCRAWLER_ENABLED=false\n"
    assert (
        machine.rewrite_crawler_image(data, f"repo@{CRAWLER2}") == f"# header\r\nCRAWLER_IMAGE=repo@{CRAWLER2}\nSCHEDULE=0 3 * * *\nCRAWLER_ENABLED=false\n".encode()
    )


@pytest.mark.parametrize(
    ("tag", "stamp", "expected"),
    [
        ("v1.0.0", "2026-10-23T01:02:03Z", "book-finder-pre-v1-0-0-20261023010203"),
        ("v1.0.0-rc.1", "2026-10-23T01:02:03Z", "book-finder-pre-v1-0-0-rc-1-20261023010203"),
        ("v1.0.0-.x", "2026-10-23T01:02:03Z", "book-finder-pre-v1-0-0-x-20261023010203"),
    ],
)
def test_snapshot_name_is_a_valid_rds_identifier(tag, stamp, expected):
    assert machine._snapshot_name(tag, stamp) == expected


# Crash: a BaseException during the migration must leave the run indeterminate


def test_crash_during_efbundle_writes_no_completed_record_and_blocks_later_runs(tmp_path):
    world = forward_world(tmp_path)
    world.fx.docker.efbundle_raises = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        world.run_unit(deploy_text(world, chain="forward", tag=TAG2))
    records = world.history().entries
    assert [e["phase"] for e in records] == ["started"]
    state = world.load_state()
    assert state.schema.dirty is True and state.crawler.paused is not None
    assert not env_path(world).exists()
    assert lock_is_free(world.settings.db_maintenance_lock)

    assert world.run(f"status {RUN_ID}") == OK
    assert json.loads(world.out.getvalue().splitlines()[-1])["status"] == "indeterminate"
    plan = f"plan {TAG2} {DIGEST_OK}"
    assert world.run(plan, plan_only=True) == 8
    assert world.run(deploy_text(world, run_id="5556-1", chain="forward", tag=TAG2)) == 8


def test_status_of_a_finished_run_comes_from_history_even_when_the_unit_is_gone(tmp_path):
    world = in_sync_world(tmp_path)
    assert world.run(deploy_text(world)) == OK
    world.host.unit_states.clear()
    world.out.truncate(0)
    world.out.seek(0)
    assert world.run(f"status {cmd.parse_command(deploy_text(world)).run_id}") == OK
    assert "completed:success" in world.out.getvalue()
    assert hi.read(world.settings.history_file).entries[-1]["phase"] == "completed"


# Compose minimum (raw env_file needs it) and verbatim secrets


def test_probe_that_is_interpolated_refuses_before_anything_changes(tmp_path):
    world = in_sync_world(tmp_path)
    world.fx.compose.config_mode = "interpolated"
    code, _out, err = world.run_unit(deploy_text(world))
    assert code == BAD_INPUT
    assert "docker compose does not support env_file format: raw (found 2.40.0)" in err
    assert not [t for t in world.fx.trace if t.startswith(("compose.", "ssm."))]
    assert not env_path(world).exists()
    assert world.load_state() == world.state
    assert completed_records(world)[-1]["result"] == "rejected"
    assert completed_records(world)[-1]["exit_code"] == BAD_INPUT


def test_probe_error_refuses(tmp_path):
    world = in_sync_world(tmp_path)
    world.fx.compose.config_mode = "error"
    code, _out, err = world.run_unit(deploy_text(world))
    assert code == BAD_INPUT
    assert "does not support env_file format: raw" in err


@pytest.mark.parametrize("version", ["2.30.0", "v2.31.4", "2.40.0\n", "garbage"])
def test_a_capable_compose_is_accepted_whatever_its_version_text(tmp_path, version):
    world = in_sync_world(tmp_path)
    world.fx.compose_version = version
    assert world.run_unit(deploy_text(world))[0] == OK


def test_plan_refuses_a_compose_that_fails_the_probe_and_reports_its_version(tmp_path):
    world = in_sync_world(tmp_path)
    world.fx.compose.config_mode = "missing-key"
    world.fx.compose_version = "2.10.0"
    assert world.run(f"plan {TAG2} {DIGEST_OK}", plan_only=True) == BAD_INPUT
    assert "docker compose does not support env_file format: raw (found 2.10.0)" in world.err.getvalue()
    assert world.stdout_json()["compose_version"] == "2.10.0"
    assert world.stdout_json()["refused"].startswith("docker compose does not support")


def test_secret_values_reach_the_env_file_verbatim(tmp_path):
    world = in_sync_world(tmp_path)
    jwt = "a$ABC${HOME}#'\"\\ =" + "0" * 32
    db = "Host=db;Password=p$W\"d'\\ = #x"
    openai = "sk-$ABC${HOME}\"'\\ ="
    world.fx.ssm.values.update({world.settings.ssm_db_connection: db, world.settings.ssm_openai_key: openai, world.settings.ssm_jwt_key: jwt})
    seen = {}
    world.fx.compose.on_up = lambda: seen.setdefault("env", env_path(world).read_bytes())
    assert world.run_unit(deploy_text(world))[0] == OK
    # No escaping and no quoting: the file holds exactly the bytes SSM returned, one value per line.
    assert seen["env"] == f"ConnectionStrings__DefaultConnection={db}\nOPENAIAPI_KEY={openai}\nJwt__SigningKey={jwt}\n".encode()


def test_carriage_return_in_a_secret_is_refused(tmp_path):
    world = in_sync_world(tmp_path)
    world.fx.ssm.values[world.settings.ssm_jwt_key] = "value\rwith-cr"
    code, out, err = world.run_unit(deploy_text(world))
    assert code == BAD_INPUT
    assert "Jwt__SigningKey must be a non-empty single-line value" in err
    assert "with-cr" not in err and "with-cr" not in out
    assert not env_path(world).exists()


# DB_CA_BUNDLE: the web override is required by the release, and rollback needs the previous release to carry it too

CA_PATH = "/etc/book-finder/global-bundle.pem"
CA_OVERRIDE = "compose.ca-bundle.yaml"


def test_configured_bundle_rejects_a_release_without_the_override_before_anything_changes(tmp_path):
    world = in_sync_world(tmp_path)
    set_setting(world, db_ca_bundle=CA_PATH)
    before = world.state
    code, _, err = world.run_unit(deploy_text(world))
    assert code == BAD_INPUT and f"no {CA_OVERRIDE}" in err
    assert world.fx.compose.up_calls == []
    assert not Path(world.settings.releases_dir, DIGEST_OK.split(":", 1)[1]).exists()
    assert world.load_state() == before
    assert completed_records(world)[-1]["result"] == "rejected"


def test_configured_bundle_deploys_a_release_that_ships_the_override(tmp_path):
    world = in_sync_world(tmp_path)
    set_setting(world, db_ca_bundle=CA_PATH)
    (world.host.release_dir / CA_OVERRIDE).write_text("services: {}\n", encoding="utf-8")
    code, _, err = world.run_unit(deploy_text(world))
    assert code == OK, err
    assert len(world.fx.compose.up_calls) == 1


def test_configured_bundle_refuses_rollback_to_a_release_without_the_override(tmp_path):
    world = in_sync_world(tmp_path)
    with_old_release(world)
    (world.host.release_dir / CA_OVERRIDE).write_text("services: {}\n", encoding="utf-8")
    set_setting(world, db_ca_bundle=CA_PATH)
    only_web_failures_on_target(world)
    code, _, err = world.run_unit(deploy_text(world))
    assert code == FAILED_DOWN and f"no {CA_OVERRIDE}" in err and "rollback not possible" in err
    assert len(world.fx.compose.up_calls) == 1  # only the target was started
    assert completed_records(world)[-1]["result"] == "failed-down"


def test_configured_bundle_rolls_back_to_a_release_that_ships_the_override(tmp_path):
    world = in_sync_world(tmp_path)
    old = with_old_release(world)
    (old / CA_OVERRIDE).write_text("services: {}\n", encoding="utf-8")
    (world.host.release_dir / CA_OVERRIDE).write_text("services: {}\n", encoding="utf-8")
    set_setting(world, db_ca_bundle=CA_PATH)
    only_web_failures_on_target(world)
    code, _, _err = world.run_unit(deploy_text(world))
    assert code == ROLLED_BACK
    assert len(world.fx.compose.up_calls) == 2
