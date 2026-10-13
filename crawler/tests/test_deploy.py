"""Exercise the host wrapper without AWS, Docker, root, or website requests."""

import os
from pathlib import Path
import subprocess
import time

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "run-crawler.sh"


@pytest.fixture
def host(tmp_path):
    config = tmp_path / "crawler.conf"
    config.write_text(
        "CRAWLER_IMAGE=crawler:test\nAWS_REGION=test-region\nDATABASE_URL_PARAMETER=/test/db\n"
    )
    # Bash functions override external services even though the wrapper sets a fixed PATH.
    stubs = tmp_path / "stubs.sh"
    stubs.write_text('''
aws() { printf 'postgresql://test:secret@example.invalid/db\\n'; }
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
''')
    env = {
        **os.environ,
        "BASH_ENV": str(stubs),
        "CRAWLER_CONFIG_FILE": str(config),
        "CRAWLER_STATE_DIR": str(tmp_path / "state"),
        "CRAWLER_RUNTIME_DIR": str(tmp_path / "runtime"),
        "CALLS": str(tmp_path / "calls"),
    }
    return tmp_path, env


def execute(env, *args):
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)


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
