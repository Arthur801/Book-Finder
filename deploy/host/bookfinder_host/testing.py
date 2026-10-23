"""Scripted fakes for the host program; used by the unit tests and by the TEST-ONLY fakes hook in commands.py.

Why: unit tests must never start docker, systemd or psql, and a scripted runner also records every argv so tests can
assert which commands were (or were not) issued.
"""

from collections.abc import Callable, Mapping, Sequence

from bookfinder_host.manifest import Migration
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


def sample_state(
    applied: Sequence[Migration] = (),
    revision: int = 1,
    tag: str = "v1.0.0",
    web_digest: str = "sha256:" + "1" * 64,
):
    """A valid docker-runtime state; tests and the demo hook build on it."""
    from bookfinder_host import state as st

    entries = tuple(st.AppliedMigration(m.id, m.source_hash, tag) for m in applied)
    runtime = st.DockerRuntime(
        tag=tag,
        release_api=1,
        web_digest=web_digest,
        crawler_digest="sha256:" + "3" * 64,
        compose_sha256="e" * 64,
        release_dir=f"/opt/book-finder/releases/{tag}",
    )
    schema = st.Schema(
        digest=st.schema_digest(list(applied)),
        applied=entries,
        rebuild=st.Rebuild(tag=tag, web_digest=web_digest),
        dirty=False,
        dirty_since=None,
        dirty_release=None,
    )
    crawler = st.Crawler(digest="sha256:" + "3" * 64, paused=None)
    return st.State(revision=revision, runtime=runtime, previous_runtime=None, schema=schema, crawler=crawler)
