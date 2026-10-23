"""Exercise the host wrapper without AWS, Docker, root, or website requests."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "run-crawler.sh"


@pytest.fixture
def host(tmp_path):
    config = tmp_path / "crawler.conf"
    config.write_text("CRAWLER_IMAGE=crawler:test\nAWS_REGION=test-region\nDATABASE_URL_PARAMETER=/test/db\n")
    # Bash functions override external services even though the wrapper sets a fixed PATH.
    stubs = tmp_path / "stubs.sh"
    stubs.write_text("""
aws() {
    printf 'aws\\n' >> "$AWS_CALLS"
    printf 'postgresql://test:secret@example.invalid/db\\n'
}
chown() { :; }
docker() {
    printf 'start\\n' >> "$CALLS"
    local previous='' item
    for item in "$@"; do
        if [[ "$previous" == --env-file ]]; then
            [[ $(stat -c %a "$item") == 600 ]] || return 8
            [[ $(cat "$item") == DATABASE_URL=postgresql://test:secret@example.invalid/db ]] || return 9
        fi
        previous=$item
    done
    sleep "${DOCKER_DELAY:-0}"
    printf 'end\\n' >> "$CALLS"
    return "${DOCKER_RESULT:-0}"
}
""")
    env = {
        **os.environ,
        "BASH_ENV": str(stubs),
        "CRAWLER_CONFIG_FILE": str(config),
        "CRAWLER_STATE_DIR": str(tmp_path / "state"),
        "CRAWLER_RUNTIME_DIR": str(tmp_path / "runtime"),
        "CALLS": str(tmp_path / "calls"),
        "AWS_CALLS": str(tmp_path / "aws-calls"),
        # N3: every test uses its own maintenance lock and state file; the wait is short so timeouts stay fast.
        "DB_MAINTENANCE_LOCK": str(tmp_path / "db-maintenance.lock"),
        "BOOKFINDER_STATE_FILE": str(tmp_path / "state.json"),
        "DB_MAINTENANCE_WAIT_S": "1",
    }
    return tmp_path, env


def write_state(root, *, paused=None, dirty=False):
    state = {
        "revision": 3,
        "crawler": {"digest": "sha256:" + "3" * 64, "paused": paused},
        "schema": {"dirty": dirty},
    }
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")


PAUSE = {"since": "2026-10-23T00:00:00Z", "release": "v1.1.0", "reason": "forward migration"}


def execute(env, *args):
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False)


def test_daily_keeps_exit_code_and_removes_secret_file(host):
    root, env = host
    result = execute({**env, "DOCKER_RESULT": "7"}, "daily")
    assert result.returncode == 7
    assert "exit_code=7" in result.stdout
    assert "secret" not in result.stdout + result.stderr
    assert list((root / "runtime").iterdir()) == []
    assert not (root / "state" / "pages-last-success").exists()


def test_pages_schedule_survives_new_process_and_becomes_due(host):
    root, env = host
    assert execute(env, "pages", "--scheduled").returncode == 0
    state = root / "state" / "pages-last-success"
    assert state.exists()
    result = execute(env, "pages", "--scheduled")
    assert "schedule=not-due" in result.stdout
    assert (root / "calls").read_text() == "start\nend\n"
    state.write_text(str(int(time.time()) - 259201))
    assert execute(env, "pages", "--scheduled").returncode == 0
    assert (root / "calls").read_text() == "start\nend\nstart\nend\n"


def test_failed_pages_does_not_advance_schedule(host):
    root, env = host
    result = execute({**env, "DOCKER_RESULT": "1"}, "pages", "--scheduled")
    assert result.returncode == 1
    assert not (root / "state" / "pages-last-success").exists()
    assert execute(env, "pages", "--scheduled").returncode == 0


def test_daily_and_pages_share_a_lock(host):
    root, env = host
    env = {**env, "DOCKER_DELAY": "0.2"}
    first = subprocess.Popen(["bash", str(SCRIPT), "daily"], env=env, stdout=subprocess.PIPE)
    second = subprocess.Popen(["bash", str(SCRIPT), "pages"], env=env, stdout=subprocess.PIPE)
    first.communicate(timeout=10)
    second.communicate(timeout=10)
    assert first.returncode == second.returncode == 0
    assert (root / "calls").read_text() == "start\nend\nstart\nend\n"


def test_absent_state_keeps_pre_cd_behaviour(host):
    root, env = host
    result = execute(env, "daily")
    assert result.returncode == 0
    assert "state=absent" in result.stdout
    assert (root / "calls").read_text() == "start\nend\n"


def test_paused_state_skips_before_docker(host):
    root, env = host
    write_state(root, paused=PAUSE)
    result = execute(env, "daily")
    assert result.returncode == 6
    assert "skipped=paused" in result.stdout
    assert not (root / "calls").exists()


def test_dirty_schema_skips_before_docker(host):
    root, env = host
    write_state(root, dirty=True)
    result = execute(env, "pages", "--scheduled")
    assert result.returncode == 6
    assert "skipped=dirty" in result.stdout
    assert not (root / "calls").exists()


def test_clean_state_runs(host):
    root, env = host
    write_state(root)
    assert execute(env, "daily").returncode == 0
    assert (root / "calls").read_text() == "start\nend\n"


def test_unreadable_state_fails_closed(host):
    root, env = host
    (root / "state.json").write_text("{not json", encoding="utf-8")
    result = execute(env, "daily")
    assert result.returncode == 2
    assert "state=unreadable" in result.stderr
    assert not (root / "calls").exists()


def test_lock_is_taken_before_state_is_read(host):
    root, env = host
    lock = root / "db-maintenance.lock"
    # A deploy holds the lock exclusively and pauses the crawler while the crawler is still waiting. Reading state
    # before the lock would miss that pause and start the run.
    holder = subprocess.Popen(["flock", "-x", str(lock), "sleep", "3"])
    time.sleep(0.3)
    env = {**env, "DB_MAINTENANCE_WAIT_S": "10"}
    waiter = subprocess.Popen(["bash", str(SCRIPT), "daily"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.5)
    write_state(root, paused=PAUSE)
    stdout, _ = waiter.communicate(timeout=20)
    holder.wait(timeout=10)
    assert waiter.returncode == 6
    assert "skipped=paused" in stdout
    assert not (root / "calls").exists()


def test_maintenance_lock_is_held_while_the_container_runs(host):
    root, env = host
    env = {**env, "DOCKER_DELAY": "1.5"}
    runner = subprocess.Popen(["bash", str(SCRIPT), "daily"], env=env, stdout=subprocess.PIPE, text=True)
    time.sleep(0.7)
    probe = subprocess.run(["flock", "-n", "-x", str(root / "db-maintenance.lock"), "true"], check=False)
    assert probe.returncode != 0, "a deploy could take the migration lock while a crawler container runs"
    runner.communicate(timeout=20)
    assert runner.returncode == 0


def test_maintenance_wait_timeout_exits_3(host):
    root, env = host
    holder = subprocess.Popen(["flock", "-x", str(root / "db-maintenance.lock"), "sleep", "5"])
    time.sleep(0.3)
    try:
        result = execute(env, "daily")
    finally:
        holder.wait(timeout=10)
    assert result.returncode == 3
    assert "maintenance=busy" in result.stderr
    assert not (root / "calls").exists()


def disable(root, value):
    """Appends the switch to crawler.conf, as an operator would on the host."""
    with (root / "crawler.conf").open("a", encoding="utf-8") as handle:
        handle.write(f"CRAWLER_ENABLED={value}\n")


def test_crawler_enabled_true_runs_as_before(host):
    root, env = host
    disable(root, "true")
    result = execute(env, "daily")
    assert result.returncode == 0
    assert "skipped=disabled" not in result.stdout
    assert (root / "calls").read_text() == "start\nend\n"


def test_crawler_disabled_exits_before_any_external_work(host):
    root, env = host
    disable(root, "false")
    # An unreadable state file would make the wrapper exit 2 if it were read; the disabled switch must win first.
    write_state(root)
    (root / "state.json").write_text("{not json", encoding="utf-8")
    result = execute(env, "pages", "--scheduled")
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith(" mode=pages skipped=disabled\n")
    assert not (root / "calls").exists()
    assert not (root / "aws-calls").exists()
    assert not (root / "state").exists()
    assert not (root / "runtime").exists()
    assert not (root / "db-maintenance.lock").exists()


def test_crawler_disabled_daily_does_not_touch_pages_schedule(host):
    root, env = host
    disable(root, "false")
    assert execute(env, "daily").returncode == 0
    assert not (root / "state" / "pages-last-success").exists()


@pytest.mark.parametrize("value", ["no", "False", "TRUE", "1", ""])
def test_crawler_enabled_rejects_invalid_values(host, value):
    root, env = host
    disable(root, value)
    result = execute(env, "daily")
    assert result.returncode == 2
    assert "CRAWLER_ENABLED" in result.stderr
    assert "true" in result.stderr and "false" in result.stderr
    assert "skipped=disabled" not in result.stdout
    assert not (root / "calls").exists()
    assert not (root / "aws-calls").exists()
    assert not (root / "state").exists()
