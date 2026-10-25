"""Real implementations of the state-machine ports, built on the injectable Runner.

Why: each adapter is a thin argv builder, so the exact docker, aws and systemctl commands are visible in one place and
can be checked by tests without running them. No adapter passes a secret in argv.
"""

import contextlib
import http.client
import os
import queue
import re
import secrets
import stat
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence

from bookfinder_host import config as cfg
from bookfinder_host import runtime as rt
from bookfinder_host.manifest import CONTAINER_RELEASE_DIR
from bookfinder_host.ports import Child, EffectFailed, Effects, Runner, child_environment
from bookfinder_host.release_content import COMPOSE_CA_BUNDLE
from bookfinder_host.safefile import read_regular_file

_CONTAINER_ID_RE = re.compile(r"[0-9a-f]{12,64}")
# Runs inside the crawler image with no network: it proves the image can import its stack and read its page list.
CRAWLER_SMOKE_SCRIPT = "import psycopg, curl_cffi, bs4; from books_crawler.page_list import load_page_urls, DEFAULT_PAGES_FILE; load_page_urls(DEFAULT_PAGES_FILE)"
MAX_CONFIG_BYTES = 65536
# The migration container's output kept for the journal: the last part only, so a chatty migration cannot fill the disk.
MAX_CHILD_OUTPUT_BYTES = 1 << 16
# Connection options for the lock session. Keepalives let a silently dropped network show up as a dead session within
# about a minute (idle 30 s, then 3 probes 10 s apart), so the holder cannot keep the lock across a broken link.
LOCK_SESSION_OPTIONS = "connect_timeout=10&keepalives=1&keepalives_idle=30&keepalives_interval=10&keepalives_count=3&application_name=bookfinder-deploy-lock"
# psql inside the holder container: no -c, so it reads its commands from stdin and stays connected for the whole run.
PSQL_SESSION_SCRIPT = 'exec psql -X -At -v ON_ERROR_STOP=1 "$DATABASE_URL"'
# Time for docker to start the container and psql to connect, on top of the lock wait itself.
LOCK_START_GRACE_S = 60.0
LOCK_RELEASE_TIMEOUT_S = 10.0
SESSION_CLOSE_TIMEOUT_S = 10.0
_PASSWORD_IN_TEXT = re.compile(r"(?i)password\s*=\s*\S+")


def _checked(result, what: str) -> None:
    if result.returncode != 0:
        raise EffectFailed(f"{what} failed: {result.stderr.strip()[:500]}")


def _read_tail(fd: int, limit: int) -> str:
    """The last limit bytes of a file that a child process may still be writing to.

    Why pread: a seek on the shared file description would move the child's write offset.
    """
    size = os.fstat(fd).st_size
    data = os.pread(fd, min(size, limit), max(0, size - limit))
    return data.decode("utf-8", errors="replace")


class _Child:
    """A started container (efbundle). Its output goes to an unlinked file, so it can be read while the process runs."""

    def __init__(self, process: subprocess.Popen, output, name: str, runner: Runner) -> None:
        self._process = process
        self._output = output
        self._name = name
        self._runner = runner

    def poll(self) -> int | None:
        return self._process.poll()

    def terminate(self) -> None:
        # docker kill names the container, so the stop reaches it even when the docker client is already gone.
        self._runner.run(["docker", "kill", "--signal", "TERM", self._name])
        if self._process.poll() is None:
            self._process.terminate()

    def kill(self) -> None:
        self._runner.run(["docker", "kill", "--signal", "KILL", self._name])
        if self._process.poll() is None:
            self._process.kill()

    def output(self) -> str:
        return _read_tail(self._output.fileno(), MAX_CHILD_OUTPUT_BYTES)


class _Session:
    """A long-lived psql process: commands go in on stdin, and a reader thread queues stdout lines for expect().

    Why a thread: a blocked read on the pipe could never time out, and a heartbeat must answer within a deadline.
    """

    def __init__(self, process: subprocess.Popen, stderr) -> None:
        self._process = process
        self._stderr = stderr
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        try:
            for line in self._process.stdout:
                self._lines.put(line.rstrip("\n"))
        except (OSError, ValueError):
            pass
        finally:
            self._lines.put(None)

    def send(self, text: str) -> None:
        try:
            self._process.stdin.write(text)
            self._process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise EffectFailed("lock session is not accepting commands") from exc

    def read_until(self, marker: str, timeout_s: float) -> list[str]:
        """The lines printed before marker. Raises EffectFailed on timeout or when the process ends first."""
        deadline = time.monotonic() + timeout_s
        lines: list[str] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EffectFailed(f"lock session gave no reply within {timeout_s:g} s")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                raise EffectFailed(f"lock session gave no reply within {timeout_s:g} s") from None
            if line is None:
                raise EffectFailed("lock session ended")
            if line == marker:
                return lines
            lines.append(line)

    def stderr_tail(self) -> str:
        return _read_tail(self._stderr.fileno(), 2048)

    def alive(self) -> bool:
        return self._process.poll() is None

    def kill(self) -> None:
        if self._process.poll() is None:
            self._process.kill()
        self._process.wait()

    def close(self) -> None:
        """Ends the session by closing stdin (psql then exits, and the server ends the session); kills it when it lingers."""
        try:
            self._process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self._process.wait(timeout=SESSION_CLOSE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self.kill()


class ProcessLauncher:
    """Starts the host's long-lived children. Every child gets the fixed environment, never a shell."""

    def __init__(self, runner: Runner) -> None:
        self._runner = runner

    def spawn(self, argv: Sequence[str], *, name: str, env: Mapping[str, str] | None = None) -> _Child:
        # Closed by the handle (_Child), which outlives this call; a with-block would close it too early.
        output = tempfile.TemporaryFile()  # noqa: SIM115
        try:
            process = subprocess.Popen(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=child_environment(env),
                close_fds=True,
            )
        except OSError as exc:
            output.close()
            raise EffectFailed(f"cannot start {argv[0]}: {exc.strerror or exc}") from None
        return _Child(process, output, name, self._runner)

    def open_session(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> _Session:
        # Closed by the session (_Session), which outlives this call.
        stderr = tempfile.TemporaryFile()  # noqa: SIM115
        try:
            process = subprocess.Popen(
                list(argv),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                env=child_environment(env),
                close_fds=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            stderr.close()
            raise EffectFailed(f"cannot start {argv[0]}: {exc.strerror or exc}") from None
        return _Session(process, stderr)


class RealDocker:
    def __init__(self, runner: Runner, ca_bundle: str | None = None, launcher: ProcessLauncher | None = None) -> None:
        self._runner = runner
        self._ca_bundle = ca_bundle
        self._launcher = launcher if launcher is not None else ProcessLauncher(runner)

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

    def start_efbundle(self, reference: str, env_file: str) -> Child:
        # The env file carries the secrets; docker copies it into the container config at create time. The name lets
        # the host stop the container itself (docker kill) when the lock is lost, instead of trusting the docker client.
        name = f"bookfinder-migration-{secrets.token_hex(6)}"
        return self._launcher.spawn(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--name",
                name,
                *cfg.ca_bundle_mount_args(self._ca_bundle),
                "--env-file",
                env_file,
                "--entrypoint",
                "/app/efbundle",
                reference,
            ],
            name=name,
        )

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


class RealLockHolder:
    """Holds the database advisory lock in a psql session run from the pinned psql image (the same image db_query uses).

    The URL is read from SSM here and passed only through the environment, never in argv. The session runs
    `pg_advisory_lock` with a server-side lock_timeout, so a busy lock (a crawler holding it shared) ends the session by
    itself; the host-side deadline is a backstop that removes the container by name.
    """

    def __init__(
        self,
        runner: Runner,
        launcher: ProcessLauncher,
        ssm,
        parameter: str,
        psql_image: str,
        ca_bundle: str | None = None,
    ) -> None:
        self._runner = runner
        self._launcher = launcher
        self._ssm = ssm
        self._parameter = parameter
        self._psql_image = psql_image
        self._ca_bundle = ca_bundle
        self._session: _Session | None = None
        self._name = ""
        self._url = ""
        self._seq = 0

    def acquire(self, key: int, timeout_s: float) -> None:
        if self._session is not None:
            raise EffectFailed("this host run already holds the migration lock")
        if not isinstance(key, int) or not (0 <= key < 2**63):
            raise EffectFailed("lock key must be a non-negative bigint")
        if not (timeout_s > 0 and timeout_s < 3600):
            raise EffectFailed("lock timeout must be between 0 and 3600 seconds")
        self._url = self._database_url()
        self._name = f"bookfinder-deploy-lock-{secrets.token_hex(6)}"
        argv = [
            "docker",
            "run",
            "-i",
            "--rm",
            "--pull=never",
            "--name",
            self._name,
            *cfg.ca_bundle_mount_args(self._ca_bundle),
            "-e",
            "DATABASE_URL",
            "--entrypoint",
            "/bin/sh",
            self._psql_image,
            "-c",
            PSQL_SESSION_SCRIPT,
        ]
        session = self._launcher.open_session(argv, env={"DATABASE_URL": self._url})
        self._session = session
        try:
            session.send(f"SET lock_timeout = '{int(timeout_s * 1000)}ms';\n")
            marker = self._marker("acquire")
            session.send(f"SELECT 'acquired', pg_advisory_lock({key});\n\\echo {marker}\n")
            lines = session.read_until(marker, timeout_s + LOCK_START_GRACE_S)
            if not any(line.startswith("acquired") for line in lines):
                raise EffectFailed("lock session did not confirm the lock")
        except EffectFailed as exc:
            message = self._describe(f"migration lock not acquired: {exc}", session)
            self._discard()
            raise EffectFailed(message) from None

    def heartbeat(self, timeout_s: float) -> None:
        session = self._require()
        marker = self._marker("heartbeat")
        session.send(f"SELECT 1;\n\\echo {marker}\n")
        lines = session.read_until(marker, timeout_s)
        if "1" not in lines:
            raise EffectFailed("lock session answered a heartbeat without the expected result")

    def alive(self) -> bool:
        return self._session is not None and self._session.alive()

    def release(self) -> None:
        session = self._session
        if session is None:
            return
        try:
            if session.alive():
                marker = self._marker("release")
                session.send(f"SELECT pg_advisory_unlock_all();\n\\echo {marker}\n")
                session.read_until(marker, LOCK_RELEASE_TIMEOUT_S)
        finally:
            self._discard()

    def _require(self) -> _Session:
        if self._session is None:
            raise EffectFailed("no migration lock session")
        return self._session

    def _marker(self, purpose: str) -> str:
        self._seq += 1
        return f"__bookfinder_{purpose}_{self._seq}_{secrets.token_hex(4)}__"

    def _database_url(self) -> str:
        raw = self._ssm.get_parameter(self._parameter).strip()
        if not raw.startswith(("postgres://", "postgresql://")) or any(c.isspace() for c in raw):
            raise EffectFailed("database URL parameter is empty or malformed")
        separator = "&" if "?" in raw else "?"
        return raw + separator + LOCK_SESSION_OPTIONS

    def _describe(self, message: str, session: _Session) -> str:
        """The message with the session's stderr tail, with the URL and any password masked; the URL never appears."""
        tail = session.stderr_tail().strip()[-300:]
        tail = _PASSWORD_IN_TEXT.sub("password=***", tail)
        if self._url:
            tail = tail.replace(self._url, "***")
        text = " ".join(message.split())
        if tail:
            text += "; psql: " + " ".join(tail.split())
        return text

    def _discard(self) -> None:
        """Ends the session and removes its container by name; never raises, so release failures cannot hide a result."""
        session = self._session
        self._session = None
        if session is not None:
            # Best effort: the server drops the session when the process is gone.
            with contextlib.suppress(OSError):
                session.close()
        if self._name:
            self._runner.run(["docker", "rm", "-f", self._name])


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
    launcher = ProcessLauncher(runner)
    ssm = RealSsm(runner, settings.aws_region, settings.aws_cli)
    return Effects(
        docker=RealDocker(runner, settings.db_ca_bundle, launcher),
        compose=RealCompose(runner, settings.db_ca_bundle),
        aws=RealAws(runner, settings.aws_region, settings.aws_cli),
        ssm=ssm,
        systemd=RealSystemd(runner),
        http=RealHttp(),
        files=RealFiles(),
        lock_holder=RealLockHolder(runner, launcher, ssm, settings.database_url_parameter, settings.psql_image, settings.db_ca_bundle),
    )
