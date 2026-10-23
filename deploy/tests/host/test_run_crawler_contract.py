"""Contract between crawler/deploy/run-crawler.sh and the host's state file.

Why: the wrapper reads state.json with its own python snippet, so the field names it reads (crawler.paused,
schema.dirty) are a second copy of the host schema. These tests write the state through the host package itself and run
the real wrapper against it; if the host renames a field, the wrapper fails closed here instead of on the server.
"""

import dataclasses
import json
import os
import subprocess
from pathlib import Path

import pytest
from bookfinder_host import state as st
from bookfinder_host.testing import sample_state

SCRIPT = Path(__file__).resolve().parents[3] / "crawler" / "deploy" / "run-crawler.sh"
TAG = "v1.0.0"

STUBS = """
aws() { printf 'postgresql://test:secret@example.invalid/db\\n'; }
chown() { :; }
docker() {
    printf 'start\\n' >> "$CALLS"
    printf 'end\\n' >> "$CALLS"
    return 0
}
"""


@pytest.fixture
def wrapper(tmp_path):
    config = tmp_path / "crawler.conf"
    config.write_text("CRAWLER_IMAGE=crawler:test\nAWS_REGION=test-region\nDATABASE_URL_PARAMETER=/test/db\n")
    stubs = tmp_path / "stubs.sh"
    stubs.write_text(STUBS)
    env = {
        **os.environ,
        "BASH_ENV": str(stubs),
        "CRAWLER_CONFIG_FILE": str(config),
        "CRAWLER_STATE_DIR": str(tmp_path / "state"),
        "CRAWLER_RUNTIME_DIR": str(tmp_path / "runtime"),
        "CALLS": str(tmp_path / "calls"),
        "DB_MAINTENANCE_LOCK": str(tmp_path / "db-maintenance.lock"),
        "BOOKFINDER_STATE_FILE": str(tmp_path / "state.json"),
        "DB_MAINTENANCE_WAIT_S": "1",
    }
    return tmp_path, env


def host_state_file(root, state):
    """Writes the state with the host's own writer, so the file has exactly the fields the host produces."""
    st.write_state(root / "state.json", dataclasses.replace(state, revision=0), expected_revision=0)


def run_wrapper(env):
    return subprocess.run(["bash", str(SCRIPT), "daily"], env=env, capture_output=True, text=True, check=False)


def test_host_written_paused_state_is_skipped_with_exit_6(wrapper):
    root, env = wrapper
    base = sample_state()
    paused = dataclasses.replace(base, crawler=dataclasses.replace(base.crawler, paused=st.Pause("t0", TAG, "forward migration")))
    host_state_file(root, paused)
    result = run_wrapper(env)
    assert result.returncode == 6, result.stderr
    assert "skipped=paused" in result.stdout
    assert not (root / "calls").exists()


def test_host_written_dirty_state_is_skipped_with_exit_6(wrapper):
    root, env = wrapper
    host_state_file(root, st.mark_dirty(sample_state(), TAG, "t0"))
    result = run_wrapper(env)
    assert result.returncode == 6, result.stderr
    assert "skipped=dirty" in result.stdout
    assert not (root / "calls").exists()


def test_host_written_clean_state_runs(wrapper):
    root, env = wrapper
    host_state_file(root, sample_state())
    result = run_wrapper(env)
    assert result.returncode == 0, result.stderr
    assert (root / "calls").read_text() == "start\nend\n"


def test_wrapper_reads_the_fields_the_host_writes(wrapper):
    # Guards the wording of the contract itself: the file must hold the two keys the wrapper reads, at the paths it reads.
    root, _ = wrapper
    host_state_file(root, sample_state())
    data = json.loads((root / "state.json").read_text(encoding="utf-8"))
    assert "paused" in data["crawler"]
    assert "dirty" in data["schema"]
