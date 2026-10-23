"""End-to-end tests that run deploy/host/deploy-entry as a real subprocess.

Why: the forced SSH command invokes the script, not the module, so the argv handling, the exit status and the stdout
contract are only proven by running it. docker, systemd, aws and psql are replaced by the TEST-ONLY fakes file.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from bookfinder_host import history as hi
from bookfinder_host import state as st
from bookfinder_host.manifest import Migration
from bookfinder_host.testing import FakeHost, sample_state, write_fakes_file, write_release

REPO_ROOT = Path(__file__).resolve().parents[3]
ENTRY = REPO_ROOT / "deploy" / "host" / "deploy-entry"
ID1 = "20261010174616_EnablePgvector"
H1 = "a" * 64
TAG = "v1.0.0"
DIGEST = "sha256:" + "d" * 64
RUN_ID = "1234-5"


@pytest.fixture
def fakes(tmp_path):
    state = sample_state(applied=[Migration(ID1, H1)])
    release = write_release(tmp_path / "release", [Migration(ID1, H1)])
    paths = {
        "state_file": str(tmp_path / "state.json"),
        "history_file": str(tmp_path / "history.jsonl"),
        "deploy_lock_file": str(tmp_path / "deploy.lock"),
        "web_image_repository": "ghcr.io/example/book-finder-web",
        "psql_image": "docker.io/library/postgres@sha256:" + "f" * 64,
        "database_url_parameter": "/book-finder/prod/database-url",
        "aws_region": "ap-northeast-1",
        "systemd_unit": "book-finder.service",
        "compose_project": "book-finder",
        "lock_timeout_s": 0.5,
    }
    host = FakeHost(release_dir=release, db_ids=[ID1])
    path = write_fakes_file(tmp_path / "fakes.json", settings=paths, host=host, now="2026-10-23T00:00:00Z", epoch=1_800_000_000.0)
    Path(paths["state_file"]).write_text(json.dumps(st.state_to_json(state)), encoding="utf-8")
    return {"fakes": path, "paths": paths, "state": state}


def run_entry(fakes, command, *extra_args):
    env = {"PATH": os.environ["PATH"], "BOOKFINDER_HOST_TEST_FAKES": str(fakes["fakes"]), "SSH_ORIGINAL_COMMAND": command}
    return subprocess.run(
        [sys.executable, str(ENTRY), *extra_args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )


def test_plan_prints_one_json_object_and_exits_0(fakes):
    done = run_entry(fakes, f"plan {TAG} {DIGEST}", "--plan-only")
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout)
    assert report["classification"] == "in-sync"
    assert report["drift"] == []
    assert done.stdout.count("\n") == 1


def test_deploy_is_refused_by_plan_key(fakes):
    done = run_entry(
        fakes,
        f"deploy {TAG} {DIGEST} {DIGEST} --expect-revision 1 --expect-runtime {fakes['state'].runtime.web_digest} --expect-schema {fakes['state'].schema.digest} --chain in-sync",
        "--plan-only",
    )
    assert done.returncode == 2
    assert not Path(fakes["paths"]["history_file"]).exists()


def test_injection_through_the_entry_exits_2(fakes, tmp_path):
    marker = tmp_path / "pwned"
    done = run_entry(fakes, f"plan {TAG} {DIGEST}; touch {marker}", "--plan-only")
    assert done.returncode == 2
    assert not marker.exists()


def test_status_of_unknown_run_is_not_started(fakes):
    done = run_entry(fakes, f"status {RUN_ID}", "--plan-only")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"run_id": RUN_ID, "status": "not-started"}


def test_deploy_through_entry_records_the_run_and_stops_at_the_stub(fakes):
    state = fakes["state"]
    command = (
        f"deploy {TAG} {DIGEST} {DIGEST} --expect-revision {state.revision} "
        f"--expect-runtime {st.runtime_fingerprint(state.runtime)} --expect-schema {state.schema.digest} --chain in-sync"
    )
    done = run_entry(fakes, command)
    assert done.returncode == 2
    report = json.loads(done.stdout)
    assert report["result"] == "not-implemented"
    records = hi.read(fakes["paths"]["history_file"]).entries
    assert [r["phase"] for r in records] == ["started", "completed"]


def test_without_test_hook_and_without_host_conf_the_entry_refuses(tmp_path):
    env = {"PATH": os.environ["PATH"], "SSH_ORIGINAL_COMMAND": f"plan {TAG} {DIGEST}"}
    done = subprocess.run([sys.executable, str(ENTRY), "--plan-only"], capture_output=True, text=True, env=env, check=False, timeout=60)
    assert done.returncode == 2
    assert "configuration error" in done.stderr


def test_entry_script_is_executable():
    assert os.access(ENTRY, os.X_OK)
