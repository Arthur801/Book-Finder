"""Tests for bookfinder_host.adapters: argv builders, the no-redirect HTTP probe, and atomic file writes.

Why: the adapters are the only place where the host's real docker, aws and systemctl commands are spelled out. Their
argv is asserted exactly so a flag such as --pull=never or --network none cannot be dropped silently, and no secret
value appears in any argv list.
"""

import http.server
import os
import stat
import threading
from typing import ClassVar

import pytest
from bookfinder_host import adapters, config
from bookfinder_host.ports import CommandResult, EffectFailed, MigrationConnectionActive, ResidualContainer


class Recorder:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.calls: list[tuple[list[str], dict | None]] = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def run(self, argv, *, env=None):
        self.calls.append((list(argv), env))
        return CommandResult(self.returncode, self.stdout, self.stderr)


def test_efbundle_starts_the_pinned_image_with_the_env_file_and_no_pull_and_a_name():
    launcher = FakeLauncher()
    adapters.RealDocker(Recorder(), launcher=launcher).start_efbundle("ghcr.io/x/web@sha256:" + "1" * 64, "/run/book-finder/migrate-1.env")
    argv, env, name = launcher.spawned[0]
    assert name.startswith("bookfinder-migration-")
    assert argv == [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--label",
        "com.bookfinder.role=efbundle",
        "--env-file",
        "/run/book-finder/migrate-1.env",
        "--entrypoint",
        "/app/efbundle",
        "ghcr.io/x/web@sha256:" + "1" * 64,
    ]
    assert env is None


def test_crawler_smoke_runs_without_network_and_imports_the_stack():
    runner = Recorder()
    adapters.RealDocker(runner).smoke_crawler("ghcr.io/x/crawler@sha256:" + "2" * 64)
    argv, _ = runner.calls[0]
    assert argv[:4] == ["docker", "run", "--rm", "--pull=never"]
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[argv.index("--entrypoint") + 1] == "python"
    assert "load_page_urls(DEFAULT_PAGES_FILE)" in argv[-1]


def test_web_logs_are_read_by_container_id_with_a_tail_limit_and_both_streams_kept():
    runner = Recorder(stdout="out line\n", stderr="err line\n")
    text = adapters.RealDocker(runner).logs("0123456789ab", 80)
    assert runner.calls[0][0] == ["docker", "logs", "--tail", "80", "0123456789ab"]
    assert text == "out line\nerr line\n"


def test_failed_web_logs_raise_effect_failed_with_a_short_message():
    with pytest.raises(EffectFailed, match="docker logs failed"):
        adapters.RealDocker(Recorder(returncode=1, stderr="no such container")).logs("0123456789ab", 80)


def test_web_containers_are_found_by_compose_labels_and_a_bad_listing_is_an_effect_failure():
    runner = Recorder(stdout="0123456789ab\n")
    assert adapters.RealDocker(runner).web_containers("book-finder") == ["0123456789ab"]
    argv = runner.calls[0][0]
    assert "label=com.docker.compose.project=book-finder" in argv and "label=com.docker.compose.service=web" in argv
    with pytest.raises(EffectFailed, match="unexpected container id"):
        adapters.RealDocker(Recorder(stdout="not-an-id\n")).web_containers("book-finder")


def test_extract_release_creates_without_starting_copies_without_follow_and_always_removes():
    runner = Recorder(stdout="0123456789ab\n")
    adapters.RealDocker(runner).extract_release("ghcr.io/x/web@sha256:" + "1" * 64, "/tmp/payload-not-used")
    assert runner.calls[0][0] == ["docker", "create", "--pull=never", "ghcr.io/x/web@sha256:" + "1" * 64]
    assert runner.calls[1][0] == ["docker", "cp", "0123456789ab:/opt/release", "/tmp/payload-not-used"]
    assert "-L" not in runner.calls[1][0]
    assert runner.calls[2][0] == ["docker", "rm", "0123456789ab"]


def test_extract_release_removes_the_container_even_when_copy_fails():
    class CopyFails(Recorder):
        def run(self, argv, *, env=None):
            if argv[:2] == ["docker", "cp"]:
                self.calls.append((list(argv), env))
                return CommandResult(1, "", "no space")
            return super().run(argv, env=env)

    runner = CopyFails(stdout="0123456789ab\n")
    with pytest.raises(EffectFailed):
        adapters.RealDocker(runner).extract_release("ghcr.io/x/web@sha256:" + "1" * 64, "/tmp/x")
    assert runner.calls[-1][0] == ["docker", "rm", "0123456789ab"]


def test_extract_release_refuses_an_unexpected_container_id():
    with pytest.raises(EffectFailed):
        adapters.RealDocker(Recorder(stdout="; rm -rf /\n")).extract_release("ghcr.io/x/web@sha256:" + "1" * 64, "/tmp/x")


def test_compose_up_passes_the_image_and_env_file_through_the_environment_only():
    runner = Recorder()
    env = {"WEB_IMAGE": "ghcr.io/x/web@sha256:" + "1" * 64, "WEB_ENV_FILE": "/run/book-finder/web-1.env"}
    adapters.RealCompose(runner).up("/opt/book-finder/releases/abc/compose.prod.yaml", "book-finder", env)
    argv, passed = runner.calls[0]
    assert argv == ["docker", "compose", "-p", "book-finder", "-f", "/opt/book-finder/releases/abc/compose.prod.yaml", "up", "-d", "--remove-orphans"]
    assert passed == env


def test_ssm_value_is_read_with_decryption_and_never_echoed_on_failure():
    runner = Recorder(returncode=1, stderr="AccessDenied")
    with pytest.raises(EffectFailed) as excinfo:
        adapters.RealSsm(runner, "ap-northeast-1").get_parameter("/book-finder/prod/jwt-key")
    argv, _ = runner.calls[0]
    assert "--with-decryption" in argv and "--name" in argv
    assert "AccessDenied" not in str(excinfo.value)  # aws stderr is not copied into the reason


def test_ssm_value_strips_only_the_trailing_newline():
    runner = Recorder(stdout="value-with-spaces  \n")
    assert adapters.RealSsm(runner, "ap-northeast-1").get_parameter("/x") == "value-with-spaces  "


def test_snapshot_wait_uses_the_waiter_with_the_same_id():
    runner = Recorder()
    adapters.RealAws(runner, "ap-northeast-1").wait_snapshot_available("book-finder-pre-v1-0-0-20261023000000")
    argv, _ = runner.calls[0]
    assert argv == [
        "aws",
        "rds",
        "wait",
        "db-snapshot-available",
        "--region",
        "ap-northeast-1",
        "--db-snapshot-identifier",
        "book-finder-pre-v1-0-0-20261023000000",
    ]


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("X-Forwarded-Proto") == "https" and self.path == "/":
            self.send_response(200)
        elif self.path == "/redirect":
            self.send_response(301)
            self.send_header("Location", "/")
        else:
            self.send_response(307)
            self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *args):  # keep test output quiet
        pass


@pytest.fixture
def local_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_http_probe_passes_the_forwarded_proto_header(local_server):
    assert adapters.RealHttp().status(local_server + "/", {"X-Forwarded-Proto": "https"}, 5) == 200


def test_http_probe_reports_a_redirect_as_its_own_status_instead_of_following_it(local_server):
    assert adapters.RealHttp().status(local_server + "/", {}, 5) == 307


def test_http_probe_reports_a_redirect_path_as_301_without_following(local_server):
    assert adapters.RealHttp().status(local_server + "/redirect", {}, 5) == 301


class _Recording(http.server.BaseHTTPRequestHandler):
    seen: ClassVar[list[dict[str, str]]] = []

    def do_GET(self):
        _Recording.seen.append({name.lower(): value for name, value in self.headers.items()})
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def recording_server():
    _Recording.seen = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Recording)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", _Recording.seen
    finally:
        server.shutdown()
        server.server_close()


def test_http_probe_sends_the_host_user_agent_not_the_urllib_default(recording_server):
    url, seen = recording_server
    assert adapters.RealHttp(user_agent="book-finder-deploy/7").status(url + "/", {}, 5) == 200
    assert seen[0]["user-agent"] == "book-finder-deploy/7"


def test_default_http_probe_user_agent_is_the_host_api_max(recording_server):
    url, seen = recording_server
    assert adapters.RealHttp().status(url + "/", {}, 5) == 200
    _, high = config.read_host_api_range()
    assert seen[0]["user-agent"] == f"book-finder-deploy/{high}"
    assert "python-urllib" not in seen[0]["user-agent"].lower()


def test_http_probe_keeps_a_caller_provided_user_agent_in_any_case(recording_server):
    url, seen = recording_server
    adapters.RealHttp(user_agent="book-finder-deploy/7").status(url + "/", {"user-agent": "custom/1"}, 5)
    adapters.RealHttp(user_agent="book-finder-deploy/7").status(url + "/", {"User-Agent": "custom/2"}, 5)
    assert [entry["user-agent"] for entry in seen] == ["custom/1", "custom/2"]


def test_http_probe_keeps_the_no_redirect_rule_with_the_user_agent(local_server):
    assert adapters.RealHttp(user_agent="book-finder-deploy/7").status(local_server + "/", {}, 5) == 307


def test_host_user_agent_names_the_product_and_the_highest_supported_release_api(tmp_path):
    range_file = tmp_path / "HOST_API_RANGE"
    range_file.write_text("1 4\n")
    assert config.host_user_agent(range_file) == "book-finder-deploy/4"


def test_http_probe_returns_zero_when_nothing_listens():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    server.server_close()
    assert adapters.RealHttp().status(f"http://127.0.0.1:{port}/", {}, 1) == 0


def test_atomic_write_keeps_an_existing_mode_when_none_is_given(tmp_path):
    target = tmp_path / "crawler.conf"
    target.write_text("old")
    os.chmod(target, 0o640)
    adapters.RealFiles().write_atomic(str(target), b"new", None)
    assert target.read_text() == "new"
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o640
    assert sorted(p.name for p in tmp_path.iterdir()) == ["crawler.conf"]  # no temporary file left behind


def test_atomic_write_uses_the_explicit_mode_for_a_new_secret_file(tmp_path):
    target = tmp_path / "web-1.env"
    adapters.RealFiles().write_atomic(str(target), b"K=v\n", 0o600)
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600


def test_remove_ignores_a_missing_file(tmp_path):
    adapters.RealFiles().remove(str(tmp_path / "absent.env"))


def test_ensure_dir_sets_the_mode_even_under_a_umask(tmp_path):
    path = tmp_path / "run"
    adapters.RealFiles().ensure_dir(str(path), 0o700)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o700


CA = "/etc/book-finder/global-bundle.pem"
RELEASE = "/opt/book-finder/releases/abc/compose.prod.yaml"


def test_efbundle_mounts_the_ca_bundle_read_only_only_when_configured():
    launcher = FakeLauncher()
    adapters.RealDocker(Recorder(), ca_bundle=CA, launcher=launcher).start_efbundle("ghcr.io/x/web@sha256:" + "1" * 64, "/run/book-finder/migrate-1.env")
    argv, _, name = launcher.spawned[0]
    assert argv[:12] == [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--label",
        "com.bookfinder.role=efbundle",
        "--mount",
        f"type=bind,src={CA},dst={CA},readonly",
        "--env-file",
        "/run/book-finder/migrate-1.env",
    ]
    assert argv[12:] == ["--entrypoint", "/app/efbundle", "ghcr.io/x/web@sha256:" + "1" * 64]


def test_efbundle_without_ca_bundle_has_no_mount():
    launcher = FakeLauncher()
    adapters.RealDocker(Recorder(), ca_bundle=None, launcher=launcher).start_efbundle("ghcr.io/x/web@sha256:" + "1" * 64, "/run/book-finder/migrate-1.env")
    assert "--mount" not in launcher.spawned[0][0]


def test_compose_up_without_ca_bundle_uses_only_the_release_compose_file():
    runner = Recorder()
    adapters.RealCompose(runner).up(RELEASE, "book-finder", {"WEB_IMAGE": "x"})
    argv, passed = runner.calls[0]
    assert argv == ["docker", "compose", "-p", "book-finder", "-f", RELEASE, "up", "-d", "--remove-orphans"]
    assert passed == {"WEB_IMAGE": "x"}


def test_compose_up_with_ca_bundle_adds_the_override_file_and_passes_the_path_in_env():
    runner = Recorder()
    adapters.RealCompose(runner, ca_bundle=CA).up(RELEASE, "book-finder", {"WEB_IMAGE": "x"})
    argv, passed = runner.calls[0]
    override = "/opt/book-finder/releases/abc/compose.ca-bundle.yaml"
    assert argv == [
        "docker",
        "compose",
        "-p",
        "book-finder",
        "-f",
        RELEASE,
        "-f",
        override,
        "up",
        "-d",
        "--remove-orphans",
    ]
    assert passed == {"WEB_IMAGE": "x", "DB_CA_BUNDLE": CA}


def test_compose_down_uses_the_same_file_set_as_up():
    runner = Recorder()
    adapters.RealCompose(runner, ca_bundle=CA).down(RELEASE, "book-finder", {"WEB_IMAGE": "x"})
    argv, passed = runner.calls[0]
    assert argv == [
        "docker",
        "compose",
        "-p",
        "book-finder",
        "-f",
        RELEASE,
        "-f",
        "/opt/book-finder/releases/abc/compose.ca-bundle.yaml",
        "down",
    ]
    assert passed == {"WEB_IMAGE": "x", "DB_CA_BUNDLE": CA}


def test_compose_config_probe_renders_only_the_file_it_is_given():
    # The capability probe renders its own one-service file; the web override names service web and does not belong there.
    runner = Recorder(stdout="{}")
    adapters.RealCompose(runner, ca_bundle=CA).config_json("/run/book-finder/.probe-x/compose.yaml")
    assert runner.calls[0][0] == ["docker", "compose", "-f", "/run/book-finder/.probe-x/compose.yaml", "config", "--format", "json"]


def test_efbundle_child_reports_exit_code_and_output_and_is_stopped_by_name():
    import sys
    import time

    runner = Recorder()
    child = adapters.ProcessLauncher(runner).spawn(
        [sys.executable, "-c", "import sys; print('applying 1', flush=True); sys.stderr.write('permission denied\\n'); sys.stderr.flush(); sys.exit(3)"],
        name="bookfinder-migration-test",
    )
    for _ in range(500):
        if child.poll() is not None:
            break
        time.sleep(0.01)
    assert child.poll() == 3
    assert child.output() == "applying 1\npermission denied\n"
    child.kill()
    assert runner.calls[-1][0] == ["docker", "kill", "--signal", "KILL", "bookfinder-migration-test"]


def test_efbundle_output_keeps_only_the_tail_of_a_chatty_migration():
    import sys

    child = adapters.ProcessLauncher(Recorder()).spawn([sys.executable, "-c", "print('x' * 200000)"], name="bookfinder-migration-tail")
    while child.poll() is None:
        pass
    assert len(child.output()) <= adapters.MAX_CHILD_OUTPUT_BYTES


# Lock holder: the psql session that keeps the migration lock (plan v12 §8, item 1).


class FakeLauncher:
    """Records what the host would start, without starting anything (no docker, no psql)."""

    def __init__(self) -> None:
        self.spawned: list[tuple[list[str], dict | None, str]] = []
        self.sessions: list[FakeSession] = []
        self.script: dict = {}

    def spawn(self, argv, *, name, env=None):
        self.spawned.append((list(argv), env, name))
        return FakeChild()

    def open_session(self, argv, *, env=None):
        session = FakeSession(self.script)
        self.sessions.append(session)
        self.spawned.append((list(argv), env, ""))
        return session


class FakeChild:
    def poll(self):
        return 0


class FakeSession:
    """A psql session stand-in: a sent command is answered from script by a key it contains.

    A script value of None means the session ends (no reply, the process is gone). A list is the reply lines.
    """

    def __init__(self, script: dict) -> None:
        self.script = script
        self.sent: list[str] = []
        self.pending: list[str] | None = None
        self.closed = False
        self.dead = False

    def send(self, text: str) -> None:
        self.sent.append(text)
        self.pending = None
        for key, lines in self.script.items():
            if key in text:
                self.pending = lines
                if lines is None:
                    self.dead = True
                break

    def read_until(self, marker: str, timeout_s: float) -> list[str]:
        if self.pending is None:
            raise EffectFailed("lock session ended")
        return list(self.pending)

    def stderr_tail(self) -> str:
        return ""

    def alive(self) -> bool:
        return not self.dead and not self.closed

    def kill(self) -> None:
        self.dead = True

    def close(self) -> None:
        self.closed = True


PSQL_IMAGE = "docker.io/pgvector/pgvector@sha256:" + "a" * 64
DB_URL = "postgresql://owner:pw-SECRET-7@db.internal:5432/book_finder?sslmode=verify-full"


class FakeSsm:
    def __init__(self, value: str) -> None:
        self.value = value

    def get_parameter(self, name: str) -> str:
        return self.value


def lock_holder(launcher, ssm_value=DB_URL, runner=None):
    return adapters.RealLockHolder(runner or Recorder(), launcher, FakeSsm(ssm_value), "/book-finder/prod/db-url", PSQL_IMAGE)


def test_lock_session_runs_psql_from_the_pinned_image_with_the_url_only_in_the_environment():
    launcher = FakeLauncher()
    launcher.script = {"pg_advisory_lock": ["acquired|"]}
    lock_holder(launcher).acquire(2026102501, 60.0)
    argv, env, _ = launcher.spawned[0]
    name = argv[argv.index("--name") + 1]
    assert argv == [
        "docker",
        "run",
        "-i",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--label",
        "com.bookfinder.role=deploy-lock",
        "-e",
        "DATABASE_URL",
        "--entrypoint",
        "/bin/sh",
        PSQL_IMAGE,
        "-c",
        adapters.PSQL_SESSION_SCRIPT,
    ]
    assert adapters.PSQL_SESSION_SCRIPT == 'exec psql -X -At -v ON_ERROR_STOP=1 "$DATABASE_URL"'
    assert all("pw-SECRET-7" not in part and "postgresql://" not in part for part in argv)
    assert env["DATABASE_URL"].startswith(DB_URL + "&")
    assert "keepalives=1&keepalives_idle=30&keepalives_interval=10&keepalives_count=3" in env["DATABASE_URL"]


def test_lock_session_sends_a_server_side_lock_timeout_and_the_exclusive_advisory_lock():
    launcher = FakeLauncher()
    launcher.script = {"pg_advisory_lock": ["acquired|"]}
    lock_holder(launcher).acquire(2026102501, 60.0)
    session = launcher.sessions[0]
    assert session.sent[0] == "SET lock_timeout = '60000ms';\n"
    assert "SELECT 'acquired', pg_advisory_lock(2026102501);" in session.sent[1]


def test_lock_url_gets_keepalive_options_after_an_existing_query_string_with_ampersand():
    launcher = FakeLauncher()
    launcher.script = {"pg_advisory_lock": ["acquired|"]}
    lock_holder(launcher, ssm_value="postgres://owner@db.internal/book_finder").acquire(2026102501, 60.0)
    assert launcher.spawned[0][1]["DATABASE_URL"].startswith("postgres://owner@db.internal/book_finder?connect_timeout=10")


def test_lock_refuses_a_malformed_url_without_echoing_it():
    launcher = FakeLauncher()
    with pytest.raises(EffectFailed) as info:
        lock_holder(launcher, ssm_value="mysql://owner:pw-SECRET-7@x/y").acquire(2026102501, 60.0)
    assert "pw-SECRET-7" not in str(info.value)
    assert launcher.spawned == []


def test_lock_not_taken_within_the_timeout_removes_the_session_and_its_container():
    launcher = FakeLauncher()
    launcher.script = {"pg_advisory_lock": None}  # psql ended before confirming: the server's lock timeout ended it
    runner = Recorder()
    holder = lock_holder(launcher, runner=runner)
    with pytest.raises(EffectFailed) as info:
        holder.acquire(2026102501, 60.0)
    assert "migration lock not acquired" in str(info.value)
    assert "pw-SECRET-7" not in str(info.value)
    assert launcher.sessions[0].closed
    name = launcher.spawned[0][0][launcher.spawned[0][0].index("--name") + 1]
    assert ["docker", "rm", "-f", name] in [argv for argv, _ in runner.calls]
    assert holder.alive() is False


def test_lock_refuses_a_second_acquire_in_the_same_run():
    launcher = FakeLauncher()
    launcher.script = {"pg_advisory_lock": ["acquired|"]}
    holder = lock_holder(launcher)
    holder.acquire(2026102501, 60.0)
    with pytest.raises(EffectFailed):
        holder.acquire(2026102501, 60.0)


def test_heartbeat_sends_select_one_and_accepts_the_reply():
    launcher = FakeLauncher()
    launcher.script = {"pg_advisory_lock": ["acquired|"], "SELECT 1;": ["1"]}
    holder = lock_holder(launcher)
    holder.acquire(2026102501, 60.0)
    holder.heartbeat(10.0)
    assert any("SELECT 1;" in text for text in launcher.sessions[0].sent)


def test_heartbeat_without_the_expected_result_is_a_lost_session():
    launcher = FakeLauncher()
    launcher.script = {"pg_advisory_lock": ["acquired|"], "SELECT 1;": ["0"]}
    holder = lock_holder(launcher)
    holder.acquire(2026102501, 60.0)
    with pytest.raises(EffectFailed):
        holder.heartbeat(10.0)


def test_heartbeat_with_no_reply_is_a_lost_session():
    launcher = FakeLauncher()
    launcher.script = {"pg_advisory_lock": ["acquired|"], "SELECT 1;": None}
    holder = lock_holder(launcher)
    holder.acquire(2026102501, 60.0)
    with pytest.raises(EffectFailed):
        holder.heartbeat(10.0)
    assert holder.alive() is False


def test_release_unlocks_all_closes_the_session_and_removes_the_container():
    launcher = FakeLauncher()
    launcher.script = {"pg_advisory_lock": ["acquired|"], "pg_advisory_unlock_all": []}
    runner = Recorder()
    holder = lock_holder(launcher, runner=runner)
    holder.acquire(2026102501, 60.0)
    holder.release()
    session = launcher.sessions[0]
    assert any("pg_advisory_unlock_all()" in text for text in session.sent)
    assert session.closed
    assert runner.calls[-1][0][:3] == ["docker", "rm", "-f"]
    holder.release()  # a second release is a no-op
    assert len(launcher.sessions) == 1


def test_release_after_the_session_died_still_clears_the_holder():
    launcher = FakeLauncher()
    launcher.script = {"pg_advisory_lock": ["acquired|"], "SELECT 1;": None}
    holder = lock_holder(launcher)
    holder.acquire(2026102501, 60.0)
    with pytest.raises(EffectFailed):
        holder.heartbeat(1.0)
    holder.release()
    assert holder.alive() is False


def test_lock_failure_message_keeps_the_stderr_tail_with_the_password_masked(monkeypatch):
    launcher = FakeLauncher()
    launcher.script = {"pg_advisory_lock": None}
    monkeypatch.setattr(FakeSession, "stderr_tail", lambda self: "FATAL: password authentication failed; password=pw-SECRET-7\n")
    with pytest.raises(EffectFailed) as info:
        lock_holder(launcher).acquire(2026102501, 60.0)
    assert "pw-SECRET-7" not in str(info.value)
    assert "password=***" in str(info.value)


# DEP-B21: the residual listing, the removal by id, and the server-side check that the migration connection is gone.

CONTAINER_A = "0123456789ab"
CONTAINER_B = "fedcba987654"


def test_residual_containers_are_listed_by_role_label_with_state_and_name():
    runner = Recorder(stdout=f"{CONTAINER_A}\texited\tbookfinder-migration-old1\n{CONTAINER_B}\trunning\tbookfinder-migration-old2\n")
    found = adapters.RealDocker(runner).residual_containers("efbundle")
    assert found == [
        ResidualContainer(container_id=CONTAINER_A, name="bookfinder-migration-old1", state="exited"),
        ResidualContainer(container_id=CONTAINER_B, name="bookfinder-migration-old2", state="running"),
    ]
    argv = runner.calls[0][0]
    assert argv[:3] == ["docker", "ps", "-a"] and "label=com.bookfinder.role=efbundle" in argv


def test_residual_listing_with_no_containers_is_empty_and_a_failed_listing_is_an_effect_failure():
    assert adapters.RealDocker(Recorder(stdout="")).residual_containers("deploy-lock") == []
    with pytest.raises(EffectFailed, match="docker ps failed"):
        adapters.RealDocker(Recorder(returncode=1, stderr="cannot connect")).residual_containers("efbundle")


def test_residual_listing_refuses_an_unknown_role_a_foreign_name_or_a_bad_id():
    with pytest.raises(EffectFailed, match="unknown container role"):
        adapters.RealDocker(Recorder()).residual_containers("web")
    with pytest.raises(EffectFailed, match="unexpected container listing"):
        adapters.RealDocker(Recorder(stdout=f"{CONTAINER_A}\texited\tsomeone-else\n")).residual_containers("efbundle")
    with pytest.raises(EffectFailed, match="unexpected container listing"):
        adapters.RealDocker(Recorder(stdout="not-an-id\texited\tbookfinder-migration-x\n")).residual_containers("efbundle")


def test_remove_container_takes_a_plain_id_only():
    runner = Recorder()
    adapters.RealDocker(runner).remove_container(CONTAINER_A)
    assert runner.calls[0][0] == ["docker", "rm", CONTAINER_A]
    with pytest.raises(EffectFailed):
        adapters.RealDocker(Recorder()).remove_container("bookfinder-migration-x")
    with pytest.raises(EffectFailed, match="docker rm failed"):
        adapters.RealDocker(Recorder(returncode=1, stderr="busy")).remove_container(CONTAINER_A)


def test_the_lock_holder_and_efbundle_carry_their_role_labels_so_a_later_run_can_find_them():
    launcher = FakeLauncher()
    launcher.script = {"pg_advisory_lock": ["acquired|"]}
    lock_holder(launcher).acquire(2026102501, 60.0)
    argv = launcher.spawned[0][0]
    assert argv[argv.index("--label") + 1] == "com.bookfinder.role=deploy-lock"


class CountSession:
    """Answers each pg_stat_activity query with the next count from a list; the other commands are answered as usual."""

    def __init__(self, counts) -> None:
        self.counts = list(counts)
        self.pending: list[str] | None = None
        self.queries = 0
        self.closed = False

    def send(self, text: str) -> None:
        self.pending = None
        if "pg_stat_activity" in text:
            self.queries += 1
            if self.counts:
                self.pending = [str(self.counts.pop(0))]
        else:
            self.pending = []

    def read_until(self, marker: str, timeout_s: float) -> list[str]:
        if self.pending is None:
            raise EffectFailed("lock session ended")
        return list(self.pending)

    def alive(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


def held_holder_with(session, monkeypatch):
    holder = lock_holder(FakeLauncher())
    holder._session = session  # the session is only inspected here, not started
    holder._name = "bookfinder-deploy-lock-test"
    monkeypatch.setattr(adapters, "MIGRATION_CONNECTION_POLL_S", 0.0)
    return holder


def test_connection_wait_returns_once_the_server_counts_no_migration_session(monkeypatch):
    session = CountSession([2, 1, 0])
    holder = held_holder_with(session, monkeypatch)
    holder.wait_migration_connections_gone("bookfinder-efbundle", 60.0)
    assert session.queries == 3


def test_connection_wait_sends_the_exact_application_name_query(monkeypatch):
    session = CountSession([0])
    sent = []
    original = session.send
    monkeypatch.setattr(session, "send", lambda text: (sent.append(text), original(text)))
    holder = held_holder_with(session, monkeypatch)
    holder.wait_migration_connections_gone("bookfinder-efbundle", 60.0)
    assert sent[0].startswith("SELECT count(*) FROM pg_stat_activity WHERE application_name = 'bookfinder-efbundle';\n")


def test_connection_wait_raises_active_at_the_deadline_while_the_session_is_still_there(monkeypatch):
    session = CountSession([1] * 100000)
    holder = held_holder_with(session, monkeypatch)
    with pytest.raises(MigrationConnectionActive, match="still active after 0.05 s"):
        holder.wait_migration_connections_gone("bookfinder-efbundle", 0.05)
    assert holder.alive() is True  # the lock session is not ended by the check; the holder keeps the lock


def test_connection_wait_refuses_a_malformed_name_and_a_dead_session(monkeypatch):
    holder = held_holder_with(CountSession([0]), monkeypatch)
    with pytest.raises(EffectFailed, match="malformed"):
        holder.wait_migration_connections_gone("bookfinder'; DROP", 60.0)
    dead = held_holder_with(CountSession([]), monkeypatch)
    with pytest.raises(EffectFailed, match="lock session ended"):
        dead.wait_migration_connections_gone("bookfinder-efbundle", 60.0)
    unheld = lock_holder(FakeLauncher())
    with pytest.raises(EffectFailed, match="no migration lock session"):
        unheld.wait_migration_connections_gone("bookfinder-efbundle", 60.0)
