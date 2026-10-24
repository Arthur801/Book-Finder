"""Real implementations of the state-machine ports, built on the injectable Runner.

Why: each adapter is a thin argv builder, so the exact docker, aws and systemctl commands are visible in one place and
can be checked by tests without running them. No adapter passes a secret in argv.
"""

import http.client
import os
import re
import stat
import tempfile
import urllib.error
import urllib.request
from collections.abc import Mapping

from bookfinder_host import config as cfg
from bookfinder_host import runtime as rt
from bookfinder_host.manifest import CONTAINER_RELEASE_DIR
from bookfinder_host.ports import EffectFailed, Effects, Runner
from bookfinder_host.release_content import COMPOSE_CA_BUNDLE
from bookfinder_host.safefile import read_regular_file

_CONTAINER_ID_RE = re.compile(r"[0-9a-f]{12,64}")
# Runs inside the crawler image with no network: it proves the image can import its stack and read its page list.
CRAWLER_SMOKE_SCRIPT = "import psycopg, curl_cffi, bs4; from books_crawler.page_list import load_page_urls, DEFAULT_PAGES_FILE; load_page_urls(DEFAULT_PAGES_FILE)"
MAX_CONFIG_BYTES = 65536


def _checked(result, what: str) -> None:
    if result.returncode != 0:
        raise EffectFailed(f"{what} failed: {result.stderr.strip()[:500]}")


class RealDocker:
    def __init__(self, runner: Runner, ca_bundle: str | None = None) -> None:
        self._runner = runner
        self._ca_bundle = ca_bundle

    def pull(self, reference: str) -> None:
        _checked(self._runner.run(["docker", "pull", reference]), "docker pull")

    def extract_release(self, reference: str, dest) -> None:
        # Created but never started, so nothing from the image runs; docker cp without -L copies symlinks as links,
        # which the release validator then refuses without following them.
        created = self._runner.run(["docker", "create", "--pull=never", reference])
        _checked(created, "docker create")
        container = created.stdout.strip()
        if _CONTAINER_ID_RE.fullmatch(container) is None:
            raise EffectFailed("docker create returned an unexpected container id")
        try:
            # dest does not exist yet, so docker cp creates it and copies the directory's contents into it.
            _checked(self._runner.run(["docker", "cp", f"{container}:{CONTAINER_RELEASE_DIR}", str(dest)]), "docker cp")
        finally:
            self._runner.run(["docker", "rm", container])

    def run_efbundle(self, reference: str, env_file: str) -> int:
        # The env file carries the secrets; docker copies it into the container config at create time.
        result = self._runner.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                *cfg.ca_bundle_mount_args(self._ca_bundle),
                "--env-file",
                env_file,
                "--entrypoint",
                "/app/efbundle",
                reference,
            ]
        )
        return result.returncode

    def smoke_crawler(self, reference: str) -> int:
        result = self._runner.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--network",
                "none",
                "--entrypoint",
                "python",
                reference,
                "-c",
                CRAWLER_SMOKE_SCRIPT,
            ]
        )
        return result.returncode

    def web_containers(self, project: str) -> list[str]:
        try:
            return rt.web_container_ids(self._runner, project)
        except rt.ObservationError as exc:
            raise EffectFailed(str(exc)) from exc

    def logs(self, container: str, tail: int) -> str:
        # docker logs replays the container's stdout and stderr on separate streams; both are returned, and the caller keeps the last lines.
        result = self._runner.run(["docker", "logs", "--tail", str(tail), container])
        _checked(result, "docker logs")
        return result.stdout + result.stderr


class RealCompose:
    """Every command that touches the web service uses one file set: the release's compose file, plus the CA override
    when DB_CA_BUNDLE is configured. The version and probe calls never add the override: it names service web, which
    the capability probe's own file does not define.
    """

    def __init__(self, runner: Runner, ca_bundle: str | None = None) -> None:
        self._runner = runner
        self._ca_bundle = ca_bundle

    def version(self) -> str:
        result = self._runner.run(["docker", "compose", "version", "--short"])
        _checked(result, "docker compose version")
        return result.stdout

    def config_json(self, compose_file: str) -> str:
        result = self._runner.run(["docker", "compose", "-f", compose_file, "config", "--format", "json"])
        _checked(result, "docker compose config")
        return result.stdout

    def _web_files(self, compose_file: str) -> tuple[list[str], dict[str, str]]:
        """The -f arguments for the release, and the environment the override file reads (DB_CA_BUNDLE)."""
        if self._ca_bundle is None:
            return ["-f", compose_file], {}
        override = os.path.join(os.path.dirname(compose_file), COMPOSE_CA_BUNDLE)
        return ["-f", compose_file, "-f", override], {"DB_CA_BUNDLE": self._ca_bundle}

    def up(self, compose_file: str, project: str, env: Mapping[str, str]) -> None:
        files, extra = self._web_files(compose_file)
        _checked(
            self._runner.run(["docker", "compose", "-p", project, *files, "up", "-d", "--remove-orphans"], env={**env, **extra}),
            "docker compose up",
        )

    def down(self, compose_file: str, project: str, env: Mapping[str, str]) -> None:
        files, extra = self._web_files(compose_file)
        _checked(self._runner.run(["docker", "compose", "-p", project, *files, "down"], env={**env, **extra}), "docker compose down")


class RealAws:
    def __init__(self, runner: Runner, region: str, aws_cli: str = "aws") -> None:
        self._runner = runner
        self._region = region
        self._aws = aws_cli

    def create_snapshot(self, instance_id: str, snapshot_id: str) -> None:
        _checked(
            self._runner.run(
                [
                    self._aws,
                    "rds",
                    "create-db-snapshot",
                    "--region",
                    self._region,
                    "--db-instance-identifier",
                    instance_id,
                    "--db-snapshot-identifier",
                    snapshot_id,
                ]
            ),
            "create-db-snapshot",
        )

    def wait_snapshot_available(self, snapshot_id: str) -> None:
        # The waiter polls for up to about an hour; the production runner's timeout is set above that.
        _checked(
            self._runner.run([self._aws, "rds", "wait", "db-snapshot-available", "--region", self._region, "--db-snapshot-identifier", snapshot_id]),
            "wait db-snapshot-available",
        )


class RealSsm:
    def __init__(self, runner: Runner, region: str, aws_cli: str = "aws") -> None:
        self._runner = runner
        self._region = region
        self._aws = aws_cli

    def get_parameter(self, name: str) -> str:
        # The value comes back on stdout only; it is never echoed into an error message.
        result = self._runner.run(
            [
                self._aws,
                "ssm",
                "get-parameter",
                "--region",
                self._region,
                "--name",
                name,
                "--with-decryption",
                "--query",
                "Parameter.Value",
                "--output",
                "text",
            ]
        )
        if result.returncode != 0:
            raise EffectFailed(f"reading parameter {name} failed")
        return result.stdout.rstrip("\n")


class RealSystemd:
    def __init__(self, runner: Runner) -> None:
        self._runner = runner

    def stop(self, unit: str) -> None:
        _checked(self._runner.run(["systemctl", "stop", unit]), "systemctl stop")

    def start(self, unit: str) -> None:
        _checked(self._runner.run(["systemctl", "start", unit]), "systemctl start")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


class RealHttp:
    def __init__(self, user_agent: str | None = None) -> None:
        # Why: urllib otherwise sends "Python-urllib/3.x", which the production edge answers with 403. Every request names the
        # host explicitly; a caller that sets its own User-Agent keeps it.
        self._user_agent = user_agent if user_agent is not None else cfg.host_user_agent()

    def status(self, url: str, headers: Mapping[str, str], timeout_s: float) -> int:
        sent = dict(headers)
        if not any(name.lower() == "user-agent" for name in sent):
            sent["User-Agent"] = self._user_agent
        # A redirect is reported as its own status: following it could turn a broken app into a passing check.
        request = urllib.request.Request(url, headers=sent, method="GET")
        try:
            with _OPENER.open(request, timeout=timeout_s) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError):
            return 0


class RealFiles:
    def ensure_dir(self, path: str, mode: int) -> None:
        os.makedirs(path, mode=mode, exist_ok=True)
        os.chmod(path, mode)

    def read_bytes(self, path: str) -> bytes:
        return read_regular_file(path, MAX_CONFIG_BYTES)

    def write_atomic(self, path: str, data: bytes, mode: int | None) -> None:
        # Why: a torn file would be read by cron or docker; rename is atomic and mkstemp starts at 0600, so a secret
        # is never readable by others while it is being written.
        if mode is None:
            try:
                mode = stat.S_IMODE(os.stat(path).st_mode)
            except FileNotFoundError:
                mode = 0o644
        directory = os.path.dirname(os.path.abspath(path))
        fd, temporary = tempfile.mkstemp(prefix=".tmp-", dir=directory)
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def remove(self, path: str) -> None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def build_effects(runner: Runner, settings: cfg.Settings) -> Effects:
    return Effects(
        docker=RealDocker(runner, settings.db_ca_bundle),
        compose=RealCompose(runner, settings.db_ca_bundle),
        aws=RealAws(runner, settings.aws_region, settings.aws_cli),
        ssm=RealSsm(runner, settings.aws_region, settings.aws_cli),
        systemd=RealSystemd(runner),
        http=RealHttp(),
        files=RealFiles(),
    )
