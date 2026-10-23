"""Scripted fakes for the host program; used by the unit tests and by the TEST-ONLY fakes hook in commands.py.

Why: unit tests must never start docker, systemd or psql, and a scripted runner also records every argv so tests can
assert which commands were (or were not) issued.
"""

from collections.abc import Callable, Mapping, Sequence

from bookfinder_host.ports import CommandResult

Handler = Callable[[Sequence[str]], CommandResult]


class ScriptedRunner:
    def __init__(self, rules: Sequence[tuple[Sequence[str], Handler]]) -> None:
        self._rules = [(tuple(prefix), handler) for prefix, handler in rules]
        self.calls: list[tuple[list[str], Mapping[str, str] | None]] = []

    def calls_argv(self) -> list[list[str]]:
        return [argv for argv, _ in self.calls]

    def run(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> CommandResult:
        self.calls.append((list(argv), env))
        for prefix, handler in self._rules:
            if tuple(argv[: len(prefix)]) == prefix:
                return handler(argv)
        raise AssertionError(f"unexpected command: {list(argv)}")


class FakeClock:
    """Monotonic time that only advances when sleep() is called, so polling loops finish instantly."""

    def __init__(self, start: float = 0.0, epoch: float = 1_800_000_000.0, now: str = "2026-10-23T00:00:00Z") -> None:
        self._time = start
        self._epoch = epoch
        self._now = now

    def monotonic(self) -> float:
        return self._time

    def sleep(self, seconds: float) -> None:
        self._time += seconds

    def epoch(self) -> float:
        return self._epoch

    def now(self) -> str:
        return self._now


def ok(stdout: str = "") -> CommandResult:
    return CommandResult(0, stdout, "")
