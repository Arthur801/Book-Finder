"""Tests for bookfinder_host.runtime: observing what is actually running (I1) and comparing it with state.

Why: state can lag reality after a crash or a manual change. Every comparison here reports drift instead of trusting
the recorded value, so a deploy never proceeds on a false picture.
"""

import pytest
from bookfinder_host import runtime as rt
from bookfinder_host import state as st
from bookfinder_host.manifest import Migration
from bookfinder_host.ports import CommandResult
from bookfinder_host.testing import ScriptedRunner, ok, sample_state

REPO = "ghcr.io/example/book-finder-web"
WEB1 = "sha256:" + "1" * 64
IMAGE_ID = "sha256:" + "9" * 64
CID = "0123456789ab"
ID1 = "20261010174616_EnablePgvector"
ID2 = "20261010174654_Catalog"


def docker_runner(running="true", image=IMAGE_ID, ps=CID, ref_image=IMAGE_ID):
    return ScriptedRunner(
        [
            (("docker", "ps"), lambda argv: ok(ps + "\n")),
            (("docker", "inspect"), lambda argv: ok(f"{running} {image}\n")),
            (("docker", "image", "inspect"), lambda argv: ok(ref_image + "\n")),
        ]
    )


def test_observe_docker_reads_running_flag_and_image_id():
    observed = rt.observe_docker(docker_runner())
    assert observed == rt.ObservedRuntime(kind="docker", running=True, image_id=IMAGE_ID, containers=1)


def test_observe_docker_with_no_container_is_not_running():
    observed = rt.observe_docker(docker_runner(ps="\n"))
    assert observed == rt.ObservedRuntime(kind="docker", running=False, image_id=None, containers=0)


def test_observe_docker_selects_the_service_by_compose_labels_not_compose_ps():
    runner = docker_runner()
    rt.observe_docker(runner, project="book-finder", service="web")
    listing = runner.calls_argv()[0]
    assert listing[:3] == ["docker", "ps", "-a"]
    assert "label=com.docker.compose.project=book-finder" in listing
    assert "label=com.docker.compose.service=web" in listing
    assert all(argv[:2] != ["docker", "compose"] for argv in runner.calls_argv())


def test_multiple_web_containers_are_reported_as_drift_without_inspecting_them():
    runner = docker_runner(ps="aaaaaaaaaaaa\nbbbbbbbbbbbb\n")
    observed = rt.observe_docker(runner)
    assert observed.containers == 2 and observed.running is False
    state_runtime = sample_state(web_digest=WEB1).runtime
    assert rt.check_runtime_matches(state_runtime, observed, runner, REPO) == ["runtime: multiple web containers"]
    assert all(argv[:2] != ["docker", "inspect"] for argv in runner.calls_argv())


def test_observe_docker_rejects_malformed_container_id():
    with pytest.raises(rt.ObservationError):
        rt.observe_docker(docker_runner(ps="not-an-id\n"))


def test_image_id_for_rejects_a_tag_reference_before_calling_docker():
    runner = docker_runner()
    with pytest.raises(rt.ObservationError):
        rt.image_id_for(runner, f"{REPO}:v1.0.0")
    assert runner.calls_argv() == []


def test_observe_docker_rejects_unexpected_inspect_output():
    with pytest.raises(rt.ObservationError):
        rt.observe_docker(docker_runner(running="maybe"))


def test_observe_docker_fails_when_compose_fails():
    runner = ScriptedRunner([(("docker", "ps"), lambda argv: CommandResult(1, "", "daemon down"))])
    with pytest.raises(rt.ObservationError):
        rt.observe_docker(runner)


def test_image_id_for_reads_the_local_image_id():
    runner = ScriptedRunner([(("docker", "image", "inspect"), lambda argv: ok(IMAGE_ID + "\n"))])
    assert rt.image_id_for(runner, f"{REPO}@{WEB1}") == IMAGE_ID
    assert runner.calls_argv()[0][-1] == f"{REPO}@{WEB1}"


def test_observe_systemd_active_and_inactive():
    active = ScriptedRunner([(("systemctl", "is-active"), lambda argv: ok("active\n"))])
    inactive = ScriptedRunner([(("systemctl", "is-active"), lambda argv: CommandResult(3, "inactive\n", ""))])
    assert rt.observe_systemd(active, "book-finder.service") == rt.ObservedRuntime("systemd", True, None)
    assert rt.observe_systemd(inactive, "book-finder.service") == rt.ObservedRuntime("systemd", False, None)


def test_observe_systemd_rejects_unknown_output():
    runner = ScriptedRunner([(("systemctl", "is-active"), lambda argv: ok("weird\n"))])
    with pytest.raises(rt.ObservationError):
        rt.observe_systemd(runner, "book-finder.service")


def test_docker_runtime_matching_state_has_no_drift():
    state_runtime = sample_state(web_digest=WEB1).runtime
    observed = rt.ObservedRuntime("docker", True, IMAGE_ID)
    assert rt.check_runtime_matches(state_runtime, observed, docker_runner(), REPO) == []


def test_drift_reports_kind_mismatch_stopped_container_and_wrong_image():
    state_runtime = sample_state(web_digest=WEB1).runtime
    reasons = rt.check_runtime_matches(state_runtime, rt.ObservedRuntime("systemd", True, None), docker_runner(), REPO)
    assert any("kind" in reason for reason in reasons)

    stopped = rt.check_runtime_matches(state_runtime, rt.ObservedRuntime("docker", False, IMAGE_ID), docker_runner(), REPO)
    assert any("not running" in reason for reason in stopped)

    wrong = rt.check_runtime_matches(
        state_runtime,
        rt.ObservedRuntime("docker", True, "sha256:" + "8" * 64),
        docker_runner(ref_image=IMAGE_ID),
        REPO,
    )
    assert any("image" in reason for reason in wrong)


def test_systemd_runtime_is_matched_by_active_unit():
    state_runtime = st.SystemdRuntime(unit="book-finder.service", version="pre-cd")
    assert rt.check_runtime_matches(state_runtime, rt.ObservedRuntime("systemd", True, None), None, REPO) == []
    assert rt.check_runtime_matches(state_runtime, rt.ObservedRuntime("systemd", False, None), None, REPO) != []


def test_observe_schema_returns_sorted_ids_and_checks_format():
    def query(sql):
        assert 'FROM "__EFMigrationsHistory"' in sql
        return f"{ID2}\n{ID1}\n"

    assert rt.observe_schema(query) == [ID1, ID2]


def test_observe_schema_rejects_malformed_ids():
    with pytest.raises(rt.ObservationError):
        rt.observe_schema(lambda sql: "not an id\n")


def test_observe_schema_rejects_duplicate_ids():
    with pytest.raises(rt.ObservationError):
        rt.observe_schema(lambda sql: f"{ID1}\n{ID1}\n")


def test_schema_matches_when_id_sequences_are_equal():
    state = sample_state(applied=[Migration(ID1, "a" * 64), Migration(ID2, "b" * 64)])
    assert rt.check_schema_matches(state.schema, [ID1, ID2]) == []


def test_schema_drift_when_database_has_extra_or_missing_ids():
    state = sample_state(applied=[Migration(ID1, "a" * 64)])
    extra = rt.check_schema_matches(state.schema, [ID1, ID2])
    missing = rt.check_schema_matches(sample_state(applied=[Migration(ID1, "a" * 64), Migration(ID2, "b" * 64)]).schema, [ID1])
    assert extra and missing
    assert all(reason.startswith("schema:") for reason in extra + missing)
