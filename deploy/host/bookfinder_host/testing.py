"""Scripted fakes for the host program; used by the unit tests and by the TEST-ONLY fakes hook in commands.py.

Why: unit tests must never start docker, systemd or psql, and a scripted runner also records every argv so tests can
assert which commands were (or were not) issued.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

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


IMAGE_ID = "sha256:" + "9" * 64
CONTAINER_ID = "0123456789ab"


class FakeHost:
    """Answers the external commands the host issues, from a description of a machine.

    Why: plan and deploy must be exercised end to end without a docker daemon, systemd, or AWS. Unlisted commands fail
    the test loudly instead of quietly succeeding.
    """

    def __init__(
        self,
        *,
        release_dir: Path | None = None,
        db_ids: list[str] | None = None,
        running: bool = True,
        running_image_id: str = IMAGE_ID,
        local_image_id: str = IMAGE_ID,
        unit_states: dict[str, str] | None = None,
        database_url: str = "postgres://fake@db.internal/book_finder",
    ) -> None:
        self.release_dir = release_dir
        self.db_ids = db_ids or []
        self.running = running
        self.running_image_id = running_image_id
        self.local_image_id = local_image_id
        # Maps a transient unit name to its ActiveState; unknown units report LoadState=not-found.
        self.unit_states = unit_states or {}
        self.database_url = database_url
        self.calls: list[list[str]] = []

    def run(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> CommandResult:
        command = list(argv)
        self.calls.append(command)
        if command[:2] == ["docker", "create"]:
            return ok(CONTAINER_ID + "\n")
        if command[:2] == ["docker", "rm"]:
            return ok()
        if command[:2] == ["docker", "cp"]:
            return self._copy(command[2], Path(command[3]))
        if command[0] == "aws":
            return ok(self.database_url + "\n")
        if command[:2] == ["docker", "run"]:
            return ok("".join(f"{migration_id}\n" for migration_id in self.db_ids))
        if command[:3] == ["docker", "compose", "-p"]:
            return ok(CONTAINER_ID + "\n" if self.running else "\n")
        if command[:2] == ["docker", "inspect"]:
            return ok(f"{'true' if self.running else 'false'} {self.running_image_id}\n")
        if command[:3] == ["docker", "image", "inspect"]:
            return ok(self.local_image_id + "\n")
        if command[:2] == ["systemctl", "is-active"]:
            return ok(("active" if self.unit_states.get(command[2]) == "active" else "inactive") + "\n")
        if command[:2] == ["systemctl", "show"]:
            unit = command[-1]
            if unit not in self.unit_states:
                return ok("LoadState=not-found\nActiveState=inactive\n")
            return ok(f"LoadState=loaded\nActiveState={self.unit_states[unit]}\n")
        raise AssertionError(f"unexpected command: {command}")

    def _copy(self, source: str, dest: Path) -> CommandResult:
        name = source.rsplit("/", 1)[-1]
        if self.release_dir is None or not (self.release_dir / name).is_file():
            return CommandResult(1, "", f"no such file: {name}")
        dest.write_bytes((self.release_dir / name).read_bytes())
        return ok()


def write_release(directory: Path, migrations: Sequence[Migration], release_api: str = "1") -> Path:
    from bookfinder_host.manifest import render_manifest

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "migrations.txt").write_text(render_manifest(list(migrations)), encoding="utf-8")
    (directory / "RELEASE_API").write_text(release_api + "\n", encoding="utf-8")
    return directory


def write_fakes_file(path: Path, *, settings: dict, host: FakeHost, now: str, epoch: float) -> Path:
    """Serializes the TEST-ONLY fakes description consumed by commands.load_deps (see BOOKFINDER_HOST_TEST_FAKES)."""
    document = {
        "settings": settings,
        "release_dir": str(host.release_dir) if host.release_dir else None,
        "db_ids": host.db_ids,
        "running": host.running,
        "running_image_id": host.running_image_id,
        "local_image_id": host.local_image_id,
        "unit_states": host.unit_states,
        "database_url": host.database_url,
        "now": now,
        "epoch": epoch,
    }
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def fakes_from_file(path: str | Path) -> tuple[dict, FakeHost, FakeClock]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    release_dir = Path(document["release_dir"]) if document.get("release_dir") else None
    host = FakeHost(
        release_dir=release_dir,
        db_ids=document.get("db_ids", []),
        running=document.get("running", True),
        running_image_id=document.get("running_image_id", IMAGE_ID),
        local_image_id=document.get("local_image_id", IMAGE_ID),
        unit_states=document.get("unit_states", {}),
        database_url=document.get("database_url", "postgres://fake@db.internal/book_finder"),
    )
    clock = FakeClock(epoch=document.get("epoch", 1_800_000_000.0), now=document.get("now", "2026-10-23T00:00:00Z"))
    return document, host, clock
