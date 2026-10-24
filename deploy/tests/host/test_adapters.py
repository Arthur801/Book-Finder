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
from bookfinder_host.ports import CommandResult, EffectFailed


class Recorder:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.calls: list[tuple[list[str], dict | None]] = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def run(self, argv, *, env=None):
        self.calls.append((list(argv), env))
        return CommandResult(self.returncode, self.stdout, self.stderr)


def test_efbundle_runs_the_pinned_image_with_the_env_file_and_no_pull():
    runner = Recorder()
    code = adapters.RealDocker(runner).run_efbundle("ghcr.io/x/web@sha256:" + "1" * 64, "/run/book-finder/web-1.env")
    assert code == 0
    argv, env = runner.calls[0]
    assert argv == [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--env-file",
        "/run/book-finder/web-1.env",
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
    runner = Recorder()
    adapters.RealDocker(runner, ca_bundle=CA).run_efbundle("ghcr.io/x/web@sha256:" + "1" * 64, "/run/book-finder/web-1.env")
    argv, _ = runner.calls[0]
    assert argv[:6] == ["docker", "run", "--rm", "--pull=never", "--mount", f"type=bind,src={CA},dst={CA},readonly"]
    assert argv[6:] == [
        "--env-file",
        "/run/book-finder/web-1.env",
        "--entrypoint",
        "/app/efbundle",
        "ghcr.io/x/web@sha256:" + "1" * 64,
    ]


def test_efbundle_without_ca_bundle_has_no_mount():
    runner = Recorder()
    adapters.RealDocker(runner, ca_bundle=None).run_efbundle("ghcr.io/x/web@sha256:" + "1" * 64, "/run/book-finder/web-1.env")
    assert "--mount" not in runner.calls[0][0]


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
