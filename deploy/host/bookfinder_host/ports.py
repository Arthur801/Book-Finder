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

    def run_efbundle(self, reference: str, env_file: str) -> int:
        """Returns the exit code of the migration container."""

    def smoke_crawler(self, reference: str) -> int:
        """Returns the exit code of the crawler import smoke test (no network)."""


class Compose(Protocol):
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


class SubprocessRunner:
    """Runs argv lists directly, never through a shell, so arguments cannot inject commands."""

    def __init__(self, timeout_s: float = 900.0) -> None:
        self._timeout_s = timeout_s

    def run(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> CommandResult:
        child_env = {"PATH": SAFE_PATH, "LANG": "C.UTF-8"}
        if "HOME" in os.environ:
            child_env["HOME"] = os.environ["HOME"]
        child_env.update(env or {})
        try:
            done = subprocess.run(
                list(argv),
                capture_output=True,
                text=True,
                env=child_env,
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
