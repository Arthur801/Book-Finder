"""Injectable effects: running external commands and reading the clock.

Why: the host talks to docker, systemd, aws and the clock. Routing those through these small interfaces lets the unit
tests use fakes, so no test starts a container or waits on a real timer.
"""

import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

# Commands run with a fixed PATH so the forced-command environment cannot change which binaries run.
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    def run(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> CommandResult: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...

    def epoch(self) -> float: ...

    def now(self) -> str: ...


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
