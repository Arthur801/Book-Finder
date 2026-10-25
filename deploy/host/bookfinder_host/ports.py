"""Injectable effects: running external commands, reading the clock, and the state-machine ports.

Why: the host talks to docker, systemd, aws, the network and the filesystem. Routing those through these small
interfaces lets the unit tests use fakes, so no test starts a container, calls AWS or waits on a real timer.
"""

import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

# Commands run with a fixed PATH so the forced-command environment cannot change which binaries run.
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class EffectFailed(Exception):
    """An external effect reported failure. Messages never carry secret values."""


class MigrationConnectionActive(EffectFailed):
    """A server session of the migration (application_name = efbundle) is still there at the deadline."""


# Container labels the host uses to find its own containers again after a crash (the deploy-start residual check).
ROLE_LABEL = "com.bookfinder.role"
EFBUNDLE_ROLE = "efbundle"
LOCK_HOLDER_ROLE = "deploy-lock"


@dataclass(frozen=True)
class ResidualContainer:
    container_id: str
    name: str
    state: str  # docker's State column: running, paused, restarting, created, exited, dead, ...


class Runner(Protocol):
    def run(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> CommandResult: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...

    def epoch(self) -> float: ...

    def now(self) -> str: ...


class Docker(Protocol):
    def pull(self, reference: str) -> None: ...

    def extract_release(self, reference: str, dest: Path) -> None:
        """Copies /opt/release out of the image into dest, which must not exist yet."""

    def start_efbundle(self, reference: str, env_file: str) -> "Child":
        """Starts the migration container without waiting; the caller polls the handle and stops it on lock loss."""

    def smoke_crawler(self, reference: str) -> int:
        """Returns the exit code of the crawler import smoke test (no network)."""

    def web_containers(self, project: str) -> list[str]:
        """The ids of the project's web containers, stopped ones included; raises EffectFailed."""

    def logs(self, container: str, tail: int) -> str:
        """The last tail lines of a container's logs, stdout and stderr together; raises EffectFailed."""

    def residual_containers(self, role: str) -> list[ResidualContainer]:
        """The containers (stopped ones included) labelled with this host role; raises EffectFailed."""

    def remove_container(self, container: str) -> None:
        """Removes a stopped container by id; raises EffectFailed."""


class Child(Protocol):
    """A started external process that the host watches and may stop. Its output is kept for the journal."""

    def poll(self) -> int | None:
        """The exit code once the process has ended, otherwise None."""

    def terminate(self) -> None:
        """Asks the process to stop (SIGTERM, delivered to the container as well)."""

    def kill(self) -> None:
        """Stops the process and any container it started, without asking."""

    def output(self) -> str:
        """The process output so far (stdout and stderr together, the last part only)."""


class LockHolder(Protocol):
    """Holds the database advisory migration lock for as long as the forward migration runs.

    Why a long-lived session: a session-level advisory lock is released by PostgreSQL when its session ends, so the
    holder being alive is what keeps the crawler out. The host therefore heartbeats it while the migration runs.
    """

    def acquire(self, key: int, timeout_s: float) -> None:
        """Takes the exclusive lock, waiting at most timeout_s; raises EffectFailed when it is not taken."""

    def heartbeat(self, timeout_s: float) -> None:
        """Proves the holder session still answers; raises EffectFailed when it does not within timeout_s."""

    def alive(self) -> bool:
        """True while the holder's process is still running."""

    def wait_migration_connections_gone(self, application_name: str, timeout_s: float) -> None:
        """Waits, while the lock is held, until no server session named application_name is left.

        Raises MigrationConnectionActive when one is still there at the deadline, and EffectFailed when the holder
        cannot answer (the caller then keeps its own result).
        """

    def release(self) -> None:
        """Releases the lock and ends the holder session; raises EffectFailed when the holder cannot be stopped cleanly."""


class Compose(Protocol):
    def version(self) -> str:
        """The output of `docker compose version --short`."""

    def config_json(self, compose_file: str) -> str:
        """The output of `docker compose -f <file> config --format json`; nothing is started."""

    def up(self, compose_file: str, project: str, env: Mapping[str, str]) -> None: ...

    def down(self, compose_file: str, project: str, env: Mapping[str, str]) -> None: ...


class Aws(Protocol):
    def create_snapshot(self, instance_id: str, snapshot_id: str) -> None: ...

    def wait_snapshot_available(self, snapshot_id: str) -> None: ...


class Ssm(Protocol):
    def get_parameter(self, name: str) -> str: ...


class Systemd(Protocol):
    def stop(self, unit: str) -> None: ...

    def start(self, unit: str) -> None: ...


class Http(Protocol):
    def status(self, url: str, headers: Mapping[str, str], timeout_s: float) -> int:
        """Returns the HTTP status, or 0 when no response arrived. Redirects are not followed."""


class Files(Protocol):
    def ensure_dir(self, path: str, mode: int) -> None: ...

    def read_bytes(self, path: str) -> bytes: ...

    def write_atomic(self, path: str, data: bytes, mode: int | None) -> None:
        """Replaces path atomically; mode None keeps the existing file's mode."""

    def remove(self, path: str) -> None: ...


@dataclass(frozen=True)
class Effects:
    docker: Docker
    compose: Compose
    aws: Aws
    ssm: Ssm
    systemd: Systemd
    http: Http
    files: Files
    lock_holder: LockHolder


def child_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment every child process gets: the fixed PATH, UTF-8 and HOME, plus the caller's extra variables."""
    child_env = {"PATH": SAFE_PATH, "LANG": "C.UTF-8"}
    if "HOME" in os.environ:
        child_env["HOME"] = os.environ["HOME"]
    child_env.update(extra or {})
    return child_env


class SubprocessRunner:
    """Runs argv lists directly, never through a shell, so arguments cannot inject commands."""

    def __init__(self, timeout_s: float = 900.0) -> None:
        self._timeout_s = timeout_s

    def run(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> CommandResult:
        try:
            done = subprocess.run(
                list(argv),
                capture_output=True,
                text=True,
                env=child_environment(env),
                timeout=self._timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(returncode=124, stdout="", stderr=f"timed out: {argv[0]}")
        return CommandResult(done.returncode, done.stdout, done.stderr)


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def epoch(self) -> float:
        return time.time()

    def now(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
