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
from bookfinder_host.manifest import CONTAINER_RELEASE_DIR
from bookfinder_host.ports import EffectFailed, Effects, Runner
from bookfinder_host.safefile import read_regular_file

_CONTAINER_ID_RE = re.compile(r"[0-9a-f]{12,64}")
# Runs inside the crawler image with no network: it proves the image can import its stack and read its page list.
CRAWLER_SMOKE_SCRIPT = "import psycopg, curl_cffi, bs4; from books_crawler.page_list import load_page_urls, DEFAULT_PAGES_FILE; load_page_urls(DEFAULT_PAGES_FILE)"
MAX_CONFIG_BYTES = 65536


def _checked(result, what: str) -> None:
    if result.returncode != 0:
        raise EffectFailed(f"{what} failed: {result.stderr.strip()[:500]}")


class RealDocker:
    def __init__(self, runner: Runner) -> None:
        self._runner = runner

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
        result = self._runner.run(["docker", "run", "--rm", "--pull=never", "--env-file", env_file, "--entrypoint", "/app/efbundle", reference])
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


class RealCompose:
    def __init__(self, runner: Runner) -> None:
        self._runner = runner

    def up(self, compose_file: str, project: str, env: Mapping[str, str]) -> None:
        _checked(
            self._runner.run(["docker", "compose", "-p", project, "-f", compose_file, "up", "-d", "--remove-orphans"], env=env),
            "docker compose up",
        )

    def down(self, compose_file: str, project: str, env: Mapping[str, str]) -> None:
        _checked(self._runner.run(["docker", "compose", "-p", project, "-f", compose_file, "down"], env=env), "docker compose down")


class RealAws:
    def __init__(self, runner: Runner, region: str) -> None:
        self._runner = runner
        self._region = region

    def create_snapshot(self, instance_id: str, snapshot_id: str) -> None:
        _checked(
            self._runner.run(
                [
                    "aws",
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
            self._runner.run(["aws", "rds", "wait", "db-snapshot-available", "--region", self._region, "--db-snapshot-identifier", snapshot_id]),
            "wait db-snapshot-available",
        )


class RealSsm:
    def __init__(self, runner: Runner, region: str) -> None:
        self._runner = runner
        self._region = region

    def get_parameter(self, name: str) -> str:
        # The value comes back on stdout only; it is never echoed into an error message.
        result = self._runner.run(
            [
                "aws",
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
    def status(self, url: str, headers: Mapping[str, str], timeout_s: float) -> int:
        # A redirect is reported as its own status: following it could turn a broken app into a passing check.
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
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
        docker=RealDocker(runner),
        compose=RealCompose(runner),
        aws=RealAws(runner, settings.aws_region),
        ssm=RealSsm(runner, settings.aws_region),
        systemd=RealSystemd(runner),
        http=RealHttp(),
        files=RealFiles(),
    )
