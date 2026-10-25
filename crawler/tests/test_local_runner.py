"""Exercise the local crawler runner without SSH, AWS, Docker, or any network.

``ssh``, ``docker`` and ``aws`` are fakes placed first on PATH. They record their arguments under ``FAKE_DIR``, keep
container state in files, and never leave the machine. The tunnel fake listens on 127.0.0.1 only, so the runner's
port check can pass without reaching RDS.
"""

import importlib.util
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import time
import uuid
from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict

CRAWLER = Path(__file__).resolve().parents[1]
RUNNER = CRAWLER / "deploy" / "local" / "run-local-crawler.sh"
SUPPORT = CRAWLER / "deploy" / "local" / "runner_support.py"
CONTAINER = "book-finder-crawler-active"
SECRET = "SECRETMARK"
SECRET_URL = f"postgresql://crawler:{SECRET}%40x@db.test.example:5432/bookfinder?sslmode=require&application_name=crawler"
CA_CONTAINER_PATH = "/etc/book-finder/rds-ca-bundle.pem"

DOCKER = """#!/bin/bash
# Fake docker: records calls, keeps container state in files, and copies the env file it was given.
set -u
dir=$FAKE_DIR
containers="$dir/containers"
mkdir -p "$containers"
cmd=${1:-}
shift || true
case $cmd in
    ps)
        [[ -z ${DOCKER_PS_FAIL:-} ]] || exit 1
        for f in "$containers"/*; do
            [[ -e $f ]] || continue
            printf '%s\\t%s\\n' "$(basename "$f")" "$(cat "$f")"
        done
        ;;
    run)
        printf 'run\\n' >> "$dir/docker-calls"
        printf '%s\\n' "$@" > "$dir/run-argv"
        env_file=
        prev=
        for arg in "$@"; do
            if [[ $prev == --env-file ]]; then env_file=$arg; fi
            prev=$arg
        done
        [[ $(stat -c %a "$env_file") == 600 ]] || exit 8
        cp "$env_file" "$dir/env-seen"
        echo running > "$containers/{container}"
        if [[ -n ${DOCKER_CLIENT_LOST:-} ]]; then exit 1; fi  # the client dies, the container keeps running
        if [[ -n ${DOCKER_HANG:-} ]]; then
            while [[ $(cat "$containers/{container}") == running ]]; do sleep 0.1; done
            exit 137
        fi
        sleep "${DOCKER_DELAY:-0}"
        echo exited > "$containers/{container}"
        exit "${DOCKER_RESULT:-0}"
        ;;
    stop)
        printf 'stop %s\\n' "$*" >> "$dir/docker-calls"
        if [[ ${DOCKER_STOP_WORKS:-1} == 1 ]]; then echo exited > "$containers/${@: -1}"; fi
        ;;
    kill)
        printf 'kill %s\\n' "$*" >> "$dir/docker-calls"
        if [[ ${DOCKER_KILL_WORKS:-1} == 1 ]]; then echo exited > "$containers/${@: -1}"; fi
        ;;
    unpause)
        printf 'unpause %s\\n' "$*" >> "$dir/docker-calls"
        ;;
    rm)
        printf 'rm %s\\n' "$*" >> "$dir/docker-calls"
        rm -f -- "$containers/${@: -1}"
        ;;
    *)
        echo "unexpected docker command: $cmd" >&2
        exit 99
        ;;
esac
""".replace("{container}", CONTAINER)

SSH = """#!/bin/bash
# Fake ssh: a tunnel (-N) holds a loopback listener like a real forward; any other call reads the EC2 state file.
set -u
dir=$FAKE_DIR
if [[ " $* " == *" -N "* ]]; then
    printf '%s\\n' "$@" > "$dir/ssh-tunnel-argv"
    port=
    prev=
    for arg in "$@"; do
        if [[ $prev == -L ]]; then port=${arg#127.0.0.1:}; port=${port%%:*}; fi
        prev=$arg
    done
    if [[ -n ${SSH_FORWARD_FAIL:-} ]]; then
        echo 'bind: address already in use' >&2
        exit 255
    fi
    echo $$ > "$dir/ssh-pid"
    if [[ -n ${SSH_NO_LISTEN:-} ]]; then exec sleep 3600; fi
    exec python3 -I -c 'import socket, sys, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(sys.argv[1])))
s.listen()
time.sleep(3600)' "$port"
fi
printf '%s\\n' "$@" > "$dir/ssh-state-argv"
[[ -z ${SSH_STATE_FAIL:-} ]] || exit 255
cat "$STATE_SOURCE"
"""

AWS = """#!/bin/bash
# Fake aws: prints the secret the way --output text does, and records its own argv.
set -u
printf '%s\\n' "$@" > "$FAKE_DIR/aws-argv"
[[ -z ${AWS_FAIL:-} ]] || { echo 'ParameterNotFound' >&2; exit 255; }
printf '%s\\n' "$SECRET_VALUE"
"""


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Local:
    """One isolated runner setup: its own directories, fakes, and configuration file."""

    def __init__(self, root: Path):
        self.root = root
        self.fake = root / "fakes"
        self.fake.mkdir()
        self.bin = root / "bin"
        self.bin.mkdir()
        for name, body in (("docker", DOCKER), ("ssh", SSH), ("aws", AWS)):
            path = self.bin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        self.artifacts = root / "artifacts"
        self.artifacts.mkdir()
        self.artifacts.chmod(0o777)  # the container user is UID 10001; see README for the host setup
        self.ca = root / "rds-ca.pem"
        self.ca.write_text("-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n", encoding="utf-8")
        self.ca.chmod(0o644)
        self.secret_file = root / "db-url"
        self.secret_file.write_text(SECRET_URL + "\n", encoding="utf-8")
        self.secret_file.chmod(0o600)
        self.state_source = root / "ec2-state.json"
        self.write_state()
        self.conf = root / "crawler-local.conf"
        self.values = {
            "CRAWLER_ENABLED": "true",
            "CRAWLER_IMAGE": "books:test",
            "KINGSTONE_CRAWLER_IMAGE": "kingstone:test",
            "CRAWLER_LOCAL_ARTIFACTS_DIR": str(self.artifacts),
            "EC2_SSH_HOST": "ec2-test",
            "EC2_STATE_FILE": "/var/lib/book-finder/state.json",
            "RDS_ENDPOINT": "db.test.example",
            "LOCAL_DB_PORT": str(free_port()),
            "DB_CA_BUNDLE": str(self.ca),
            "DB_SECRET_SOURCE": "file",
            "DB_SECRET_FILE": str(self.secret_file),
            "AWS_PROFILE": "bookfinder-crawler",
            "AWS_REGION": "ap-northeast-1",
            "DATABASE_URL_PARAMETER": "/test/crawler-database-url",
            "CRAWLER_LOCAL_STATE_DIR": str(root / "state"),
            "CRAWLER_LOCAL_RUNTIME_DIR": str(root / "runtime"),
            "CRAWLER_RUN_HARD_LIMIT_SECONDS": "60",
            "BOOKS_RUN_HARD_LIMIT_SECONDS": "60",
            "CRAWLER_STOP_GRACE_SECONDS": "1",
            "TUNNEL_WAIT_SECONDS": "5",
        }

    def write_state(self, text=None, *, paused=None, dirty=False):
        if text is None:
            text = json.dumps({"revision": 3, "crawler": {"paused": paused}, "schema": {"dirty": dirty}})
        self.state_source.write_text(text, encoding="utf-8")

    def write_conf(self, **overrides):
        values = {**self.values, **overrides}
        lines = [f"{key}={shlex.quote(str(value))}" for key, value in values.items() if value is not None]
        self.conf.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def env(self, **extra):
        env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(self.root / "home"),
            "CRAWLER_LOCAL_CONF": str(self.conf),
            "FAKE_DIR": str(self.fake),
            "STATE_SOURCE": str(self.state_source),
            "SECRET_VALUE": SECRET_URL,
        }
        env.update({key: str(value) for key, value in extra.items()})
        return env

    def popen(self, mode, **extra):
        return subprocess.Popen(
            ["bash", str(RUNNER), mode],
            env=self.env(**extra),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def run(self, mode, *args, **extra):
        return subprocess.run(
            ["bash", str(RUNNER), mode, *args],
            env=self.env(**extra),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def calls(self):
        path = self.fake / "docker-calls"
        return path.read_text().splitlines() if path.exists() else []

    def container_state(self):
        path = self.fake / "containers" / CONTAINER
        return path.read_text().strip() if path.exists() else None

    def set_container(self, state):
        (self.fake / "containers").mkdir(exist_ok=True)
        (self.fake / "containers" / CONTAINER).write_text(state + "\n", encoding="utf-8")

    def run_argv(self):
        return (self.fake / "run-argv").read_text().splitlines()

    def runtime_leftovers(self):
        runtime = self.root / "runtime"
        return sorted(path.name for path in runtime.iterdir()) if runtime.exists() else []

    def fake_outputs_without_secret(self):
        """All text the fakes recorded plus the runner's own log must not contain the secret."""
        return [path.read_text() for path in self.fake.iterdir() if path.is_file() and path.name != "env-seen"]


@pytest.fixture
def local(tmp_path):
    setup = Local(tmp_path)
    setup.write_conf()
    return setup


def value_after(argv, flag):
    return argv[argv.index(flag) + 1]


def assert_no_docker_or_secret_work(local):
    assert not (local.fake / "docker-calls").exists()
    assert not (local.fake / "aws-argv").exists()


RECORD_KEYS = {
    "run_id",
    "provider",
    "mode",
    "status",
    "exit_code",
    "reason",
    "alert_reasons",
    "started_at",
    "finished_at",
    "container",
    "counts",
    "source",
}
ISO_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def runner_record_path(local, mode):
    return local.artifacts / "runner" / f"{mode}-last-run.json"


def alert_lines(text):
    return [line for line in text.splitlines() if line.startswith("ALERT ")]


def stdout_json_records(text):
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


def assert_terminal_record(local, stdout, stderr, *, mode, provider, exit_code, reason, alerts, container):
    """The runner's own record and ALERT line for a lifecycle failure outside the container."""
    path = runner_record_path(local, mode)
    text = path.read_text(encoding="utf-8")
    record = json.loads(text)
    assert set(record) == RECORD_KEYS
    assert record["status"] == "FAILED"
    assert record["source"] == "runner"
    assert record["mode"] == mode
    assert record["provider"] == provider
    assert record["exit_code"] == exit_code
    assert record["reason"] == reason
    assert record["alert_reasons"] == alerts
    assert record["container"] == container
    assert record["counts"] is None  # the crawler's counts are unknown to the runner
    uuid.UUID(record["run_id"])
    assert ISO_UTC.fullmatch(record["started_at"]) and ISO_UTC.fullmatch(record["finished_at"])
    assert record["started_at"] <= record["finished_at"]
    assert stdout_json_records(stdout) == [record]  # the same record, once, on stdout
    assert alert_lines(stderr) == [f"ALERT reasons={','.join(alerts)} mode={mode} last_run={path}"]
    assert SECRET not in text and "postgresql" not in text
    assert SECRET not in stdout and SECRET not in stderr
    return record


# --- disabled switch, usage and configuration -------------------------------------------------------------------


def test_disabled_makes_no_external_call_and_skips_validation(local):
    local.write_conf(CRAWLER_ENABLED="false", CRAWLER_IMAGE=None, EC2_SSH_HOST=None, DB_CA_BUNDLE=None)
    result = local.run("daily")
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith(" mode=daily skipped=disabled\n")
    assert not (local.fake / "ssh-state-argv").exists()
    assert not (local.fake / "ssh-tunnel-argv").exists()
    assert_no_docker_or_secret_work(local)
    assert not (local.root / "state").exists()
    assert not (local.root / "runtime").exists()


@pytest.mark.parametrize("value", ["no", "False", "TRUE", "1", ""])
def test_crawler_enabled_rejects_invalid_values(local, value):
    local.write_conf(CRAWLER_ENABLED=value)
    result = local.run("daily")
    assert result.returncode == 10
    assert "CRAWLER_ENABLED" in result.stderr
    assert "skipped=disabled" not in result.stdout
    assert not (local.fake / "ssh-state-argv").exists()
    assert_no_docker_or_secret_work(local)


@pytest.mark.parametrize("args", [[], ["daily", "extra"], ["weekly"], ["DAILY"]])
def test_usage_errors_exit_10(local, args):
    result = subprocess.run(
        ["bash", str(RUNNER), *args],
        env=local.env(),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 10
    assert "usage: run-local-crawler.sh" in result.stderr
    assert not (local.fake / "ssh-state-argv").exists()


@pytest.mark.parametrize(
    ("mode", "key"),
    [
        ("kingstone", "KINGSTONE_CRAWLER_IMAGE"),
        ("daily", "CRAWLER_IMAGE"),
        ("daily", "EC2_SSH_HOST"),
        ("pages", "EC2_STATE_FILE"),
        ("first_book", "RDS_ENDPOINT"),
        ("kingstone", "CRAWLER_LOCAL_ARTIFACTS_DIR"),
        ("daily", "DB_CA_BUNDLE"),
        ("daily", "DB_SECRET_SOURCE"),
        ("daily", "LOCAL_DB_PORT"),
    ],
)
def test_missing_required_value_exits_10_before_any_external_work(local, mode, key):
    local.write_conf(**{key: None})
    result = local.run(mode)
    assert result.returncode == 10, result.stderr
    assert key in result.stderr
    assert not (local.fake / "ssh-state-argv").exists()
    assert_no_docker_or_secret_work(local)


@pytest.mark.parametrize(
    ("mode", "key", "value"),
    [
        ("daily", "LOCAL_DB_PORT", "80"),
        ("daily", "LOCAL_DB_PORT", "65536"),
        ("daily", "LOCAL_DB_PORT", "15432;rm"),
        ("daily", "RDS_ENDPOINT", "db.example -o ProxyCommand=x"),
        ("daily", "EC2_STATE_FILE", "/var/lib/a b/state.json"),
        ("daily", "CRAWLER_LOCAL_ARTIFACTS_DIR", "relative/artifacts"),
        ("daily", "BOOKS_RUN_HARD_LIMIT_SECONDS", "0"),
        ("kingstone", "CRAWLER_RUN_HARD_LIMIT_SECONDS", "0"),
        ("kingstone", "CRAWLER_RUN_HARD_LIMIT_SECONDS", "9000s"),
        ("daily", "DB_SECRET_SOURCE", "vault"),
        ("daily", "CRAWLER_IMAGE", "books:test extra"),
    ],
)
def test_malformed_value_exits_10(local, mode, key, value):
    local.write_conf(**{key: value})
    result = local.run(mode)
    assert result.returncode == 10, result.stderr
    assert key in result.stderr
    assert_no_docker_or_secret_work(local)


@pytest.mark.parametrize("bundle_kind", ["symlink", "unreadable", "relative"])
def test_ca_bundle_checks_exit_10(local, bundle_kind):
    if bundle_kind == "symlink":
        link = local.root / "link.pem"
        link.symlink_to(local.ca)
        local.write_conf(DB_CA_BUNDLE=str(link))
    elif bundle_kind == "unreadable":
        local.ca.chmod(0o600)
    else:
        local.write_conf(DB_CA_BUNDLE="rds-ca.pem")
    result = local.run("daily")
    assert result.returncode == 10
    assert "DB_CA_BUNDLE" in result.stderr
    assert_no_docker_or_secret_work(local)


def test_artifacts_directory_owned_by_someone_else_is_refused(local):
    local.artifacts.chmod(0o755)
    result = local.run("daily")
    assert result.returncode == 10
    assert "10001" in result.stderr
    assert_no_docker_or_secret_work(local)


# --- EC2 deploy state gate ---------------------------------------------------------------------------------------


def test_state_is_read_read_only_over_ssh_with_batch_mode(local):
    assert local.run("daily").returncode == 0
    argv = (local.fake / "ssh-state-argv").read_text().splitlines()
    assert "BatchMode=yes" in argv
    assert argv[-3:] == ["ec2-test", "cat", "/var/lib/book-finder/state.json"]


def test_unreadable_state_fails_closed(local):
    result = local.run("daily", SSH_STATE_FAIL="1")
    assert result.returncode == 12, result.stderr
    assert "state=unreadable" in result.stderr
    assert_no_docker_or_secret_work(local)


def test_corrupt_state_fails_closed(local):
    local.write_state("{not json")
    result = local.run("daily")
    assert result.returncode == 12
    assert "state=unreadable" in result.stdout + result.stderr
    assert_no_docker_or_secret_work(local)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [({"paused": {"since": "2026-10-23T00:00:00Z"}}, "paused"), ({"dirty": True}, "dirty")],
)
@pytest.mark.parametrize("mode", ["daily", "kingstone"])
def test_paused_or_dirty_state_skips_before_any_container_or_secret(local, kwargs, reason, mode):
    local.write_state(json.dumps({"crawler": {"paused": kwargs.get("paused")}, "schema": {"dirty": kwargs.get("dirty", False)}}))
    result = local.run(mode)
    assert result.returncode == 6
    assert f"skipped={reason}" in result.stdout
    assert_no_docker_or_secret_work(local)
    assert local.runtime_leftovers() == []


def test_clean_state_runs(local):
    result = local.run("daily")
    assert result.returncode == 0, result.stderr
    assert len(local.calls()) == 2  # run and rm


# --- orphan writer check -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["running", "restarting", "paused", "removing"])
def test_live_writer_refuses_to_start(local, state):
    local.set_container(state)
    result = local.run("daily")
    assert result.returncode == 13
    assert "ORPHAN_WRITER" in result.stderr
    assert "run" not in local.calls()
    assert not (local.fake / "aws-argv").exists()


@pytest.mark.parametrize("state", ["exited", "dead", "created"])
def test_stopped_writer_is_removed_then_the_run_continues(local, state):
    local.set_container(state)
    result = local.run("daily")
    assert result.returncode == 0, result.stderr
    calls = local.calls()
    assert calls.index(f"rm {CONTAINER}") < calls.index("run")
    assert local.container_state() is None


def test_docker_unavailable_during_orphan_check_exits_18(local):
    result = local.run("daily", DOCKER_PS_FAIL="1")
    assert result.returncode == 18
    assert "run" not in local.calls()


# --- DB secret ---------------------------------------------------------------------------------------------------


def test_ssm_secret_uses_the_profile_and_never_reaches_argv_or_output(local):
    local.write_conf(DB_SECRET_SOURCE="ssm")
    result = local.run("daily")
    assert result.returncode == 0, result.stderr
    argv = (local.fake / "aws-argv").read_text().splitlines()
    assert value_after(argv, "--profile") == "bookfinder-crawler"
    assert value_after(argv, "--name") == "/test/crawler-database-url"
    assert "--with-decryption" in argv
    assert value_after(argv, "--region") == "ap-northeast-1"
    for text in local.fake_outputs_without_secret() + [result.stdout, result.stderr]:
        assert SECRET not in text
    assert SECRET in (local.fake / "env-seen").read_text()


def test_file_secret_is_read_and_the_env_file_is_removed(local):
    result = local.run("daily")
    assert result.returncode == 0, result.stderr
    assert local.runtime_leftovers() == []
    for text in local.fake_outputs_without_secret() + [result.stdout, result.stderr]:
        assert SECRET not in text


@pytest.mark.parametrize("mode_bits", [0o644, 0o640, 0o400])
def test_file_secret_with_wrong_mode_is_refused(local, mode_bits):
    local.secret_file.chmod(mode_bits)
    result = local.run("daily")
    assert result.returncode == 15
    assert "mode 600" in result.stderr
    assert "run" not in local.calls()
    assert SECRET not in result.stdout + result.stderr


def test_file_secret_that_is_a_symlink_is_refused(local):
    target = local.root / "real-url"
    target.write_text(SECRET_URL, encoding="utf-8")
    target.chmod(0o600)
    local.secret_file.unlink()
    local.secret_file.symlink_to(target)
    result = local.run("daily")
    assert result.returncode == 15
    assert "symbolic link" in result.stderr


def test_ssm_failure_is_refused_without_a_container(local):
    local.write_conf(DB_SECRET_SOURCE="ssm")
    result = local.run("daily", AWS_FAIL="1")
    assert result.returncode == 15
    assert "run" not in local.calls()


def test_empty_secret_is_refused(local):
    local.write_conf(DB_SECRET_SOURCE="ssm")
    result = local.run("daily", SECRET_VALUE="")
    assert result.returncode == 15
    assert "run" not in local.calls()


def test_secret_for_another_host_is_refused_and_not_printed(local):
    other = SECRET_URL.replace("db.test.example", "other.example.invalid")
    local.secret_file.write_text(other, encoding="utf-8")
    local.secret_file.chmod(0o600)
    result = local.run("daily")
    assert result.returncode == 17
    assert "RDS endpoint" in result.stderr
    assert "run" not in local.calls()
    assert SECRET not in result.stdout + result.stderr


# --- URL rewrite (helper) -------------------------------------------------------------------------------------


def load_support():
    spec = importlib.util.spec_from_file_location("runner_support", SUPPORT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rewrite_keeps_the_endpoint_for_tls_and_points_the_port_at_the_tunnel():
    support = load_support()
    url = support.rewrite_url(SECRET_URL, port=15432, rds_host="db.test.example", ca_path=CA_CONTAINER_PATH)
    info = conninfo_to_dict(url)
    assert info["host"] == "db.test.example"
    assert info["hostaddr"] == "127.0.0.1"
    assert info["port"] == "15432"
    assert info["sslmode"] == "verify-full"
    assert info["sslrootcert"] == CA_CONTAINER_PATH
    assert info["user"] == "crawler"
    assert info["dbname"] == "bookfinder"
    assert info["application_name"] == "crawler"


def test_rewrite_keeps_special_characters_in_the_password_percent_encoded():
    support = load_support()
    password = "a%40b%3Ac%2Fd%23e%25f%2Bg"  # @ : / # % + as they must appear in a URL
    source = f"postgresql://crawler:{password}@db.test.example:5432/bookfinder?sslmode=require"
    url = support.rewrite_url(source + "\n", port=15432, rds_host="db.test.example", ca_path=CA_CONTAINER_PATH)
    assert f"crawler:{password}@db.test.example:15432/" in url
    assert conninfo_to_dict(url)["password"] == "a@b:c/d#e%f+g"


def test_rewrite_replaces_any_tls_or_host_parameters_the_secret_already_had():
    support = load_support()
    source = "postgres://u:p@db.test.example/app?hostaddr=10.0.0.9&sslmode=disable&connect_timeout=5&host=evil"
    url = support.rewrite_url(source, port=16000, rds_host="DB.test.example.", ca_path=CA_CONTAINER_PATH)
    assert url.count("hostaddr=") == 1 and "10.0.0.9" not in url
    assert url.count("sslmode=") == 1 and "disable" not in url
    assert "connect_timeout=5" in url
    assert "host=evil" not in url
    assert conninfo_to_dict(url)["host"] == "db.test.example"


@pytest.mark.parametrize(
    "source",
    [
        "",
        "\n",
        "None",
        "postgresql://u:p@db.test.example/app\nextra",
        "mysql://u:p@db.test.example/app",
        "postgresql://u:p@other.example/app",
        "postgresql://u:p@[::1]/app",
        "postgresql://u:p@db.test.example:5432:5432/app",
        "postgresql://u:p@db.test.example/app#fragment",
    ],
)
def test_rewrite_rejects_malformed_or_foreign_urls(source):
    support = load_support()
    with pytest.raises(support.RunnerSupportError):
        support.rewrite_url(source, port=15432, rds_host="db.test.example", ca_path=CA_CONTAINER_PATH)


def test_env_file_is_written_owner_only_and_only_holds_database_url(tmp_path):
    support = load_support()
    target = tmp_path / "env"
    target.write_text("")
    target.chmod(0o600)
    support.write_env_file(str(target), "postgresql://u:p@db.test.example:15432/app")
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.read_text() == "DATABASE_URL=postgresql://u:p@db.test.example:15432/app\n"


def test_state_gate_matches_the_ec2_rule():
    support = load_support()
    assert support.state_gate('{"crawler": {"paused": null}, "schema": {"dirty": false}}') == "ok"
    assert support.state_gate('{"crawler": {"paused": {"since": "x"}}, "schema": {"dirty": true}}') == "paused"
    assert support.state_gate('{"crawler": {"paused": null}, "schema": {"dirty": true}}') == "dirty"
    for broken in ["", "{", '{"crawler": {}}']:
        with pytest.raises(support.RunnerSupportError):
            support.state_gate(broken)


def test_port_ready_reports_a_listener_and_its_absence():
    support = load_support()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        assert support.port_ready(listener.getsockname()[1]) is True
    assert support.port_ready(free_port()) is False


# --- tunnel ------------------------------------------------------------------------------------------------------


def test_tunnel_arguments_and_cleanup(local):
    result = local.run("kingstone")
    assert result.returncode == 0, result.stderr
    argv = (local.fake / "ssh-tunnel-argv").read_text().splitlines()
    assert "ExitOnForwardFailure=yes" in argv
    assert "BatchMode=yes" in argv
    assert "ServerAliveInterval=30" in argv and "ServerAliveCountMax=3" in argv
    port = local.values["LOCAL_DB_PORT"]
    assert value_after(argv, "-L") == f"127.0.0.1:{port}:db.test.example:5432"
    assert argv[-1] == "ec2-test"
    ssh_pid = int((local.fake / "ssh-pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(ssh_pid, 0)
    assert local.runtime_leftovers() == []


def test_forward_failure_never_starts_the_container(local):
    result = local.run("daily", SSH_FORWARD_FAIL="1")
    assert result.returncode == 16, result.stderr
    assert "run" not in local.calls()
    assert local.runtime_leftovers() == []


def test_tunnel_that_never_answers_is_stopped_and_fails(local):
    # ssh stays alive but never listens: the bounded wait must give up, stop ssh, and start no container.
    local.write_conf(TUNNEL_WAIT_SECONDS="1")
    result = local.run("daily", SSH_NO_LISTEN="1")
    assert result.returncode == 16, result.stderr
    assert "run" not in local.calls()
    assert local.runtime_leftovers() == []


# --- container arguments -----------------------------------------------------------------------------------------


def test_kingstone_container_arguments(local):
    result = local.run("kingstone")
    assert result.returncode == 0, result.stderr
    argv = local.run_argv()
    assert "--rm=false" in argv and "--pull=never" in argv and "--init" in argv
    assert value_after(argv, "--name") == CONTAINER
    assert value_after(argv, "--network") == "host"
    labels = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--label"]
    assert labels == [
        "com.bookfinder.role=catalog-crawler",
        "com.bookfinder.mode=kingstone",
        "com.bookfinder.provider=KINGSTONE",
    ]
    assert value_after(argv, "--cidfile").startswith(str(local.root / "runtime"))
    assert value_after(argv, "--env-file").startswith(str(local.root / "runtime"))
    assert f"type=bind,src={local.artifacts},dst=/app/crawler/artifacts" in argv
    assert f"type=bind,src={local.ca},dst={CA_CONTAINER_PATH},readonly" in argv
    assert "CRAWLER_RUN_HARD_LIMIT_SECONDS=60" in argv
    assert argv[-1] == "kingstone:test"
    assert "books:test" not in argv


@pytest.mark.parametrize(
    ("mode", "module", "provider"),
    [
        ("daily", "books_crawler", "BOOKS_COM_TW"),
        ("pages", "books_crawler.pages", "BOOKS_COM_TW"),
        ("first_book", "books_crawler.first_book", "BOOKS_COM_TW"),
    ],
)
def test_books_modes_use_the_books_image_and_their_module(local, mode, module, provider):
    result = local.run(mode)
    assert result.returncode == 0, result.stderr
    argv = local.run_argv()
    assert argv[-2:] == ["books:test", module]
    assert "kingstone:test" not in argv
    assert f"com.bookfinder.provider={provider}" in argv
    assert value_after(argv, "--env") == "CRAWLER_FETCHER=curl"


@pytest.mark.parametrize("code", [0, 1, 2])
def test_container_exit_code_is_returned(local, code):
    result = local.run("daily", DOCKER_RESULT=str(code))
    assert result.returncode == code
    assert f"container=end exit_code={code}" in result.stdout
    assert local.runtime_leftovers() == []
    assert local.container_state() is None  # the finished container was removed
    # The container owns its own results: a normal end writes no runner record and prints no runner ALERT.
    assert not (local.artifacts / "runner").exists()
    assert alert_lines(result.stderr) == []
    assert stdout_json_records(result.stdout) == []


@pytest.mark.parametrize("scenario", ["success", "container-failed", "forward-failed", "paused"])
def test_env_file_and_cid_file_are_removed_on_every_path(local, scenario):
    extra = {}
    if scenario == "container-failed":
        extra["DOCKER_RESULT"] = "1"
    if scenario == "forward-failed":
        extra["SSH_FORWARD_FAIL"] = "1"
    if scenario == "paused":
        local.write_state(json.dumps({"crawler": {"paused": {"since": "x"}}, "schema": {"dirty": False}}))
    local.run("daily", **extra)
    assert local.runtime_leftovers() == []


# --- watchdog and writer fencing ---------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["kingstone", "daily"])
def test_watchdog_stops_the_container_at_the_hard_limit(local, mode):
    key = "CRAWLER_RUN_HARD_LIMIT_SECONDS" if mode == "kingstone" else "BOOKS_RUN_HARD_LIMIT_SECONDS"
    local.write_conf(**{key: "1"})
    started = time.monotonic()
    result = local.run(mode, DOCKER_HANG="1")
    assert result.returncode == 20, result.stderr
    assert time.monotonic() - started < 30
    calls = local.calls()
    assert any(call.startswith("stop ") for call in calls)
    assert not any(call.startswith("kill ") for call in calls)
    assert f"rm {CONTAINER}" in calls
    assert local.runtime_leftovers() == []


def test_watchdog_kills_when_stop_does_not_work(local):
    local.write_conf(CRAWLER_RUN_HARD_LIMIT_SECONDS="1")
    result = local.run("kingstone", DOCKER_HANG="1", DOCKER_STOP_WORKS="0")
    assert result.returncode == 20, result.stderr
    calls = local.calls()
    assert any(call.startswith("kill ") for call in calls)
    assert calls.index(f"rm {CONTAINER}") > max(i for i, call in enumerate(calls) if call.startswith("kill "))


def test_a_container_that_outlives_its_client_is_stopped_and_recorded_as_client_lost(local):
    result = local.run("kingstone", DOCKER_CLIENT_LOST="1")
    assert result.returncode == 22, result.stderr
    assert "ALERT reasons=orphan" in result.stderr
    assert any(call.startswith("stop ") for call in local.calls())
    assert local.container_state() is None or local.container_state() != "running"
    record = json.loads((local.artifacts / "runner" / "kingstone-last-run.json").read_text(encoding="utf-8"))
    assert (record["reason"], record["exit_code"], record["alert_reasons"]) == ("CLIENT_LOST", 22, ["orphan"])


def test_writer_that_cannot_be_confirmed_stopped_is_an_orphan_and_blocks_the_next_start(local):
    local.write_conf(CRAWLER_RUN_HARD_LIMIT_SECONDS="1")
    result = local.run("kingstone", DOCKER_HANG="1", DOCKER_STOP_WORKS="0", DOCKER_KILL_WORKS="0")
    assert result.returncode == 14, result.stderr
    assert "ORPHAN_WRITER" in result.stdout + result.stderr
    assert local.container_state() == "running"
    assert not any(call.startswith("rm ") for call in local.calls())
    # The next start is refused by the orphan check, before any secret is read.
    (local.fake / "aws-argv").unlink(missing_ok=True)
    second = local.run("kingstone")
    assert second.returncode == 13
    assert not (local.fake / "aws-argv").exists()


def test_sigterm_stops_the_container_and_cleans_up(local):
    proc = local.popen("daily", DOCKER_HANG="1")
    deadline = time.monotonic() + 30
    while not (local.fake / "docker-calls").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    proc.send_signal(signal.SIGTERM)
    _, stderr = proc.communicate(timeout=60)
    assert proc.returncode == 21, stderr
    assert any(call.startswith("stop ") for call in local.calls())
    assert local.container_state() is None
    assert local.runtime_leftovers() == []
    ssh_pid = int((local.fake / "ssh-pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(ssh_pid, 0)


def test_second_run_is_refused_while_the_first_holds_run_lock(local):
    first = local.popen("daily", DOCKER_DELAY="3")
    deadline = time.monotonic() + 30
    while not (local.fake / "docker-calls").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    second = local.run("pages")
    assert second.returncode == 11, second.stderr
    assert "run.lock" in second.stderr
    first.communicate(timeout=60)
    assert first.returncode == 0
    # After the first run finished the lock is free again.
    assert local.run("first_book").returncode == 0


# --- runner ALERT and terminal record (lifecycle failures outside the container) -------------------------------


def test_startup_orphan_writes_alert_and_runner_record(local):
    local.set_container("running")
    result = local.run("daily")
    assert result.returncode == 13, result.stderr
    assert_terminal_record(
        local,
        result.stdout,
        result.stderr,
        mode="daily",
        provider="BOOKS_COM_TW",
        exit_code=13,
        reason="ORPHAN_WRITER",
        alerts=["orphan"],
        container={"name": CONTAINER, "cid": None},
    )
    assert "run" not in local.calls()
    assert not (local.fake / "aws-argv").exists()


@pytest.mark.parametrize(
    ("mode", "key", "provider"),
    [
        ("kingstone", "CRAWLER_RUN_HARD_LIMIT_SECONDS", "KINGSTONE"),
        ("daily", "BOOKS_RUN_HARD_LIMIT_SECONDS", "BOOKS_COM_TW"),
    ],
)
def test_watchdog_stop_at_hard_limit_writes_alert_and_runner_record(local, mode, key, provider):
    local.write_conf(**{key: "1"})
    result = local.run(mode, DOCKER_HANG="1")
    assert result.returncode == 20, result.stderr
    assert_terminal_record(
        local,
        result.stdout,
        result.stderr,
        mode=mode,
        provider=provider,
        exit_code=20,
        reason="HARD_LIMIT",
        alerts=["hard_limit"],
        container={"name": CONTAINER, "cid": None},
    )


def test_unconfirmed_writer_after_hard_limit_alerts_orphan_and_hard_limit(local):
    local.write_conf(CRAWLER_RUN_HARD_LIMIT_SECONDS="1")
    result = local.run("kingstone", DOCKER_HANG="1", DOCKER_STOP_WORKS="0", DOCKER_KILL_WORKS="0")
    assert result.returncode == 14, result.stderr
    assert local.container_state() == "running"
    assert_terminal_record(
        local,
        result.stdout,
        result.stderr,
        mode="kingstone",
        provider="KINGSTONE",
        exit_code=14,
        reason="ORPHAN_WRITER",
        alerts=["orphan", "hard_limit"],
        container={"name": CONTAINER, "cid": None},
    )


def test_unconfirmed_writer_after_sigterm_alerts_orphan_only(local):
    proc = local.popen("kingstone", DOCKER_HANG="1", DOCKER_STOP_WORKS="0", DOCKER_KILL_WORKS="0")
    deadline = time.monotonic() + 30
    while not (local.fake / "docker-calls").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    proc.send_signal(signal.SIGTERM)
    stdout, stderr = proc.communicate(timeout=60)
    assert proc.returncode == 14, stderr
    assert local.container_state() == "running"
    assert_terminal_record(
        local,
        stdout,
        stderr,
        mode="kingstone",
        provider="KINGSTONE",
        exit_code=14,
        reason="ORPHAN_WRITER",
        alerts=["orphan"],
        container={"name": CONTAINER, "cid": None},
    )


def test_sigterm_writes_signal_stop_alert_and_runner_record(local):
    proc = local.popen("kingstone", DOCKER_HANG="1")
    deadline = time.monotonic() + 30
    while not (local.fake / "docker-calls").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    proc.send_signal(signal.SIGTERM)
    stdout, stderr = proc.communicate(timeout=60)
    assert proc.returncode == 21, stderr
    assert local.container_state() is None
    assert_terminal_record(
        local,
        stdout,
        stderr,
        mode="kingstone",
        provider="KINGSTONE",
        exit_code=21,
        reason="SIGNAL_STOP",
        alerts=["signal_stop"],
        container={"name": CONTAINER, "cid": None},
    )


def test_runner_record_that_cannot_be_written_keeps_the_exit_code(local):
    (local.artifacts / "runner").write_text("not a directory", encoding="utf-8")
    local.set_container("running")
    result = local.run("daily")
    assert result.returncode == 13, result.stderr
    assert "WARNING: runner record was not written" in result.stderr
    assert alert_lines(result.stderr) == [f"ALERT reasons=orphan mode=daily last_run={runner_record_path(local, 'daily')}"]
    assert len(stdout_json_records(result.stdout)) == 1
    assert SECRET not in result.stdout + result.stderr


@pytest.fixture
def support_module():
    return load_support()


def test_build_runner_record_accepts_only_the_known_reason_exit_and_alert_combinations(support_module):
    base = {
        "run_id": str(uuid.uuid4()),
        "mode": "kingstone",
        "started_at": "2026-10-25T01:00:00Z",
        "container_name": CONTAINER,
    }
    record = support_module.build_runner_record(**base, exit_code=20, reason="HARD_LIMIT", alert_reasons=["hard_limit"], container_id=None)
    assert record["provider"] == "KINGSTONE" and record["container"] == {"name": CONTAINER, "cid": None}
    bad = [
        {"exit_code": 20, "reason": "WHATEVER", "alert_reasons": ["hard_limit"]},
        {"exit_code": 13, "reason": "HARD_LIMIT", "alert_reasons": ["hard_limit"]},
        {"exit_code": 14, "reason": "ORPHAN_WRITER", "alert_reasons": ["hard_limit"]},
        {"exit_code": 21, "reason": "SIGNAL_STOP", "alert_reasons": []},
    ]
    for fields in bad:
        with pytest.raises(support_module.RunnerSupportError):
            support_module.build_runner_record(**base, container_id=None, **fields)
    with pytest.raises(support_module.RunnerSupportError):
        support_module.build_runner_record(**{**base, "mode": "weekly"}, exit_code=20, reason="HARD_LIMIT", alert_reasons=["hard_limit"], container_id=None)
    with pytest.raises(support_module.RunnerSupportError):
        support_module.build_runner_record(
            **{**base, "container_name": "name with space"},
            exit_code=20,
            reason="HARD_LIMIT",
            alert_reasons=["hard_limit"],
            container_id=None,
        )


def test_write_runner_record_is_atomic_owner_readable_and_leaves_no_temporary_file(tmp_path, support_module):
    record = support_module.build_runner_record(
        run_id=str(uuid.uuid4()),
        mode="pages",
        exit_code=21,
        reason="SIGNAL_STOP",
        alert_reasons=["signal_stop"],
        started_at="2026-10-25T01:00:00Z",
        container_name=None,
        container_id=None,
    )
    target = tmp_path / "pages-last-run.json"
    target.write_text("previous", encoding="utf-8")
    support_module.write_runner_record(str(target), record)
    assert json.loads(target.read_text(encoding="utf-8")) == record
    assert target.stat().st_mode & 0o777 == 0o644
    assert sorted(path.name for path in tmp_path.iterdir()) == ["pages-last-run.json"]


def test_write_runner_record_cli_prints_the_record_and_writes_it(local):
    run_id = str(uuid.uuid4())
    target = local.root / "cli" / "daily-last-run.json"
    target.parent.mkdir()
    result = subprocess.run(
        [
            "python3",
            "-I",
            str(SUPPORT),
            "write-runner-record",
            "--path",
            str(target),
            "--run-id",
            run_id,
            "--mode",
            "daily",
            "--exit-code",
            "14",
            "--reason",
            "ORPHAN_WRITER",
            "--alert-reasons",
            "orphan,hard_limit",
            "--started-at",
            "2026-10-25T01:00:00Z",
            "--container-name",
            CONTAINER,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    printed = json.loads(result.stdout)
    assert printed == json.loads(target.read_text(encoding="utf-8"))
    assert printed["alert_reasons"] == ["orphan", "hard_limit"]
    assert printed["provider"] == "BOOKS_COM_TW" and printed["source"] == "runner"


def test_example_configuration_parses_and_holds_no_secret():
    example = RUNNER.parent / "crawler-local.conf.example"
    assert subprocess.run(["bash", "-n", str(example)], check=False).returncode == 0
    text = example.read_text(encoding="utf-8")
    assert "postgresql://" not in text and SECRET not in text
