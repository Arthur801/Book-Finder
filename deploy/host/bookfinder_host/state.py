"""Production state (/var/lib/book-finder/state.json): strict parsing, CAS writes, and pure transitions.

Why: the state records what the host believes is running and applied. It is parsed strictly so an unknown or missing
key fails loudly, written atomically so a crash never leaves a torn file, and revisioned so a stale caller cannot
overwrite a newer decision (S4).
"""

import json
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from bookfinder_host.manifest import Migration, schema_digest
from bookfinder_host.safefile import UnsafeFileError, read_regular_file

MAX_STATE_BYTES = 1 << 20
_TAG_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_ID_RE = re.compile(r"[0-9]{14}_[A-Za-z0-9]+")
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_UNIT_RE = re.compile(r"[A-Za-z0-9@._-]{1,128}")
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")


class StateMissing(Exception):
    """No state file exists; the first cutover must bootstrap it (N6)."""


class StateCorrupt(Exception):
    """The state file exists but cannot be trusted."""


class RevisionConflict(Exception):
    """The on-disk revision is not the one the caller expected (S4)."""


@dataclass(frozen=True)
class DockerRuntime:
    tag: str
    release_api: int
    web_digest: str
    crawler_digest: str
    compose_sha256: str
    release_dir: str
    kind = "docker"


@dataclass(frozen=True)
class SystemdRuntime:
    unit: str
    version: str
    kind = "systemd"


Runtime = DockerRuntime | SystemdRuntime


@dataclass(frozen=True)
class AppliedMigration:
    id: str
    source_hash: str
    by_release: str


@dataclass(frozen=True)
class Rebuild:
    tag: str
    web_digest: str


@dataclass(frozen=True)
class Schema:
    digest: str
    applied: tuple[AppliedMigration, ...]
    rebuild: Rebuild
    dirty: bool
    dirty_since: str | None
    dirty_release: str | None


@dataclass(frozen=True)
class Pause:
    since: str
    release: str
    reason: str


@dataclass(frozen=True)
class SourceRelease:
    """The release whose run-crawler.sh and crawler.cron were installed last (crawler provenance)."""

    tag: str
    web_digest: str


@dataclass(frozen=True)
class Crawler:
    """What the host believes the crawler runs. Its provenance is recorded here, not derived from the web runtime.

    runner_sha256 and cron_sha256 are hashes of the installed files; resume-crawler compares them with the disk.
    source_release is None only before the first systemd bootstrap.
    """

    digest: str
    runner_sha256: str
    cron_sha256: str
    source_release: SourceRelease | None
    paused: Pause | None


@dataclass(frozen=True)
class State:
    revision: int
    runtime: Runtime
    previous_runtime: Runtime | None
    schema: Schema
    crawler: Crawler


def applied_migrations(state: State) -> list[Migration]:
    return [Migration(entry.id, entry.source_hash) for entry in state.schema.applied]


def runtime_fingerprint(runtime: Runtime) -> str:
    """What --expect-runtime compares against: the web image digest, or the literal "systemd" before cutover."""
    if isinstance(runtime, DockerRuntime):
        return runtime.web_digest
    return "systemd"


def replace_revision(state: State, revision: int) -> State:
    return replace(state, revision=revision)


def state_summary(state: State) -> dict[str, Any]:
    """Short form written to history; it deliberately omits paths and digests of crawler secrets."""
    return {
        "revision": state.revision,
        "runtime": runtime_fingerprint(state.runtime),
        "schema_digest": state.schema.digest,
        "dirty": state.schema.dirty,
        "crawler_paused": state.crawler.paused is not None,
    }


# Pure transitions: each returns a new State and never mutates its input.


def mark_dirty(state: State, release: str, now: str) -> State:
    if state.schema.dirty:
        raise ValueError("schema is already dirty; keep the existing evidence")
    schema = replace(state.schema, dirty=True, dirty_since=now, dirty_release=release)
    return replace(state, schema=schema)


def mark_migrated(state: State, target_tag: str, target_web_digest: str, target_migrations: Sequence[Migration]) -> State:
    """Records a successful forward migration; old entries keep the release that first applied them."""
    existing = state.schema.applied
    target = list(target_migrations)
    if len(target) < len(existing):
        raise ValueError("target manifest is shorter than the applied set")
    for old, new in zip(existing, target):
        if (old.id, old.source_hash) != (new.id, new.source_hash):
            raise ValueError(f"applied migration {old.id} does not match the target manifest")
    applied = existing + tuple(AppliedMigration(m.id, m.source_hash, target_tag) for m in target[len(existing) :])
    schema = Schema(
        digest=schema_digest(target),
        applied=applied,
        rebuild=Rebuild(tag=target_tag, web_digest=target_web_digest),
        dirty=False,
        dirty_since=None,
        dirty_release=None,
    )
    return replace(state, schema=schema)


def pause_crawler(state: State, release: str, reason: str, now: str) -> State:
    if state.crawler.paused is not None:
        raise ValueError("crawler is already paused; keep the existing pause record")
    return replace(state, crawler=replace(state.crawler, paused=Pause(since=now, release=release, reason=reason)))


def resume_crawler(state: State) -> State:
    return replace(state, crawler=replace(state.crawler, paused=None))


def promote_runtime(state: State, new_runtime: Runtime) -> State:
    return replace(state, runtime=new_runtime, previous_runtime=state.runtime)


# Serialization. Every object is checked against an exact key set so typos fail instead of being ignored.


def _exact(obj: Any, keys: set[str], where: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise StateCorrupt(f"{where} must be an object")
    if set(obj) != keys:
        raise StateCorrupt(f"{where} keys must be exactly {sorted(keys)}, got {sorted(obj)}")
    return obj


def _text(value: Any, pattern: re.Pattern[str], where: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise StateCorrupt(f"{where} is malformed: {value!r}")
    return value


def _nonempty(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise StateCorrupt(f"{where} must be a short non-empty string")
    return value


def _integer(value: Any, where: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise StateCorrupt(f"{where} must be an integer >= {minimum}")
    return value


def runtime_to_json(runtime: Runtime) -> dict[str, Any]:
    if isinstance(runtime, DockerRuntime):
        return {
            "kind": "docker",
            "tag": runtime.tag,
            "release_api": runtime.release_api,
            "web_digest": runtime.web_digest,
            "crawler_digest": runtime.crawler_digest,
            "compose_sha256": runtime.compose_sha256,
            "release_dir": runtime.release_dir,
        }
    return {"kind": "systemd", "unit": runtime.unit, "version": runtime.version}


def _runtime_from_json(obj: Any, where: str) -> Runtime:
    if not isinstance(obj, dict) or "kind" not in obj:
        raise StateCorrupt(f"{where} must be an object with a kind")
    if obj["kind"] == "docker":
        data = _exact(obj, {"kind", "tag", "release_api", "web_digest", "crawler_digest", "compose_sha256", "release_dir"}, where)
        return DockerRuntime(
            tag=_text(data["tag"], _TAG_RE, f"{where}.tag"),
            release_api=_integer(data["release_api"], f"{where}.release_api"),
            web_digest=_text(data["web_digest"], _DIGEST_RE, f"{where}.web_digest"),
            crawler_digest=_text(data["crawler_digest"], _DIGEST_RE, f"{where}.crawler_digest"),
            compose_sha256=_text(data["compose_sha256"], _SHA256_HEX_RE, f"{where}.compose_sha256"),
            release_dir=_nonempty(data["release_dir"], f"{where}.release_dir"),
        )
    if obj["kind"] == "systemd":
        data = _exact(obj, {"kind", "unit", "version"}, where)
        return SystemdRuntime(
            unit=_text(data["unit"], _UNIT_RE, f"{where}.unit"),
            version=_nonempty(data["version"], f"{where}.version"),
        )
    raise StateCorrupt(f"{where}.kind must be docker or systemd")


def source_release_to_json(source: SourceRelease | None) -> dict[str, Any] | None:
    if source is None:
        return None
    return {"tag": source.tag, "web_digest": source.web_digest}


def _source_release_from_json(obj: Any) -> SourceRelease | None:
    if obj is None:
        return None
    data = _exact(obj, {"tag", "web_digest"}, "crawler.source_release")
    return SourceRelease(
        tag=_text(data["tag"], _TAG_RE, "crawler.source_release.tag"),
        web_digest=_text(data["web_digest"], _DIGEST_RE, "crawler.source_release.web_digest"),
    )


def pause_to_json(pause: Pause | None) -> dict[str, Any] | None:
    if pause is None:
        return None
    return {"since": pause.since, "release": pause.release, "reason": pause.reason}


def _pause_from_json(obj: Any) -> Pause | None:
    if obj is None:
        return None
    data = _exact(obj, {"since", "release", "reason"}, "crawler.paused")
    return Pause(
        since=_nonempty(data["since"], "crawler.paused.since"),
        release=_nonempty(data["release"], "crawler.paused.release"),
        reason=_nonempty(data["reason"], "crawler.paused.reason"),
    )


def state_to_json(state: State) -> dict[str, Any]:
    schema = state.schema
    return {
        "revision": state.revision,
        "runtime": runtime_to_json(state.runtime),
        "previous_runtime": None if state.previous_runtime is None else runtime_to_json(state.previous_runtime),
        "schema": {
            "digest": schema.digest,
            "applied": [{"id": entry.id, "source_hash": entry.source_hash, "by_release": entry.by_release} for entry in schema.applied],
            "rebuild": {"tag": schema.rebuild.tag, "web_digest": schema.rebuild.web_digest},
            "dirty": schema.dirty,
            "dirty_since": schema.dirty_since,
            "dirty_release": schema.dirty_release,
        },
        "crawler": {
            "digest": state.crawler.digest,
            "runner_sha256": state.crawler.runner_sha256,
            "cron_sha256": state.crawler.cron_sha256,
            "source_release": source_release_to_json(state.crawler.source_release),
            "paused": pause_to_json(state.crawler.paused),
        },
    }


def state_from_json(obj: Any) -> State:
    data = _exact(obj, {"revision", "runtime", "previous_runtime", "schema", "crawler"}, "state")
    schema_obj = _exact(data["schema"], {"digest", "applied", "rebuild", "dirty", "dirty_since", "dirty_release"}, "schema")
    if not isinstance(schema_obj["applied"], list):
        raise StateCorrupt("schema.applied must be a list")
    applied = []
    for index, entry in enumerate(schema_obj["applied"]):
        item = _exact(entry, {"id", "source_hash", "by_release"}, f"schema.applied[{index}]")
        applied.append(
            AppliedMigration(
                id=_text(item["id"], _ID_RE, f"schema.applied[{index}].id"),
                source_hash=_text(item["source_hash"], _HASH_RE, f"schema.applied[{index}].source_hash"),
                by_release=_text(item["by_release"], _TAG_RE, f"schema.applied[{index}].by_release"),
            )
        )
    migrations = [Migration(entry.id, entry.source_hash) for entry in applied]
    if [m.id for m in migrations] != sorted({m.id for m in migrations}):
        raise StateCorrupt("schema.applied must be unique and ascending by id")
    digest = _text(schema_obj["digest"], _DIGEST_RE, "schema.digest")
    if digest != schema_digest(migrations):
        raise StateCorrupt("schema.digest does not match schema.applied")
    rebuild_obj = _exact(schema_obj["rebuild"], {"tag", "web_digest"}, "schema.rebuild")
    dirty = schema_obj["dirty"]
    if not isinstance(dirty, bool):
        raise StateCorrupt("schema.dirty must be a boolean")
    dirty_since = schema_obj["dirty_since"]
    dirty_release = schema_obj["dirty_release"]
    if dirty:
        if not isinstance(dirty_since, str) or not isinstance(dirty_release, str):
            raise StateCorrupt("dirty schema must record dirty_since and dirty_release")
    elif dirty_since is not None or dirty_release is not None:
        raise StateCorrupt("clean schema must not record dirty metadata")
    crawler_obj = _exact(data["crawler"], {"digest", "runner_sha256", "cron_sha256", "source_release", "paused"}, "crawler")
    previous = data["previous_runtime"]
    return State(
        revision=_integer(data["revision"], "revision"),
        runtime=_runtime_from_json(data["runtime"], "runtime"),
        previous_runtime=None if previous is None else _runtime_from_json(previous, "previous_runtime"),
        schema=Schema(
            digest=digest,
            applied=tuple(applied),
            rebuild=Rebuild(
                tag=_text(rebuild_obj["tag"], _TAG_RE, "schema.rebuild.tag"),
                web_digest=_text(rebuild_obj["web_digest"], _DIGEST_RE, "schema.rebuild.web_digest"),
            ),
            dirty=dirty,
            dirty_since=dirty_since,
            dirty_release=dirty_release,
        ),
        crawler=Crawler(
            digest=_text(crawler_obj["digest"], _DIGEST_RE, "crawler.digest"),
            runner_sha256=_text(crawler_obj["runner_sha256"], _SHA256_HEX_RE, "crawler.runner_sha256"),
            cron_sha256=_text(crawler_obj["cron_sha256"], _SHA256_HEX_RE, "crawler.cron_sha256"),
            source_release=_source_release_from_json(crawler_obj["source_release"]),
            paused=_pause_from_json(crawler_obj["paused"]),
        ),
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StateCorrupt(f"duplicate key in state: {key}")
        result[key] = value
    return result


def load_state(path: str | os.PathLike[str]) -> State:
    try:
        data = read_regular_file(path, MAX_STATE_BYTES)
    except FileNotFoundError as exc:
        raise StateMissing(os.fspath(path)) from exc
    except UnsafeFileError as exc:
        raise StateCorrupt(str(exc)) from exc
    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, ValueError) as exc:
        # StateCorrupt from the duplicate-key hook is not a ValueError, so it passes through unchanged.
        raise StateCorrupt(f"state is not valid JSON: {exc}") from exc
    return state_from_json(obj)


def _current_revision(path: str | os.PathLike[str]) -> int:
    try:
        return load_state(path).revision
    except StateMissing:
        return 0


def _fsync_directory(directory: str) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_state(path: str | os.PathLike[str], state: State, expected_revision: int) -> State:
    """Replaces the state file if its revision is expected_revision; the stored revision becomes expected_revision + 1.

    Why: callers hold the deploy lock, and the revision check still catches a caller that read an older state before
    another decision was recorded. The rename is atomic and the directory is fsynced so the new name survives a crash.
    """
    path = os.fspath(path)
    current = _current_revision(path)
    if current != expected_revision:
        raise RevisionConflict(f"state revision is {current}, expected {expected_revision}")
    if state.revision != expected_revision:
        raise ValueError("the state passed to write_state must carry the expected revision; it is bumped on write")
    stored = replace(state, revision=expected_revision + 1)
    text = json.dumps(state_to_json(stored), indent=2, sort_keys=True) + "\n"
    # Re-parse before writing so the file on disk is always one load_state accepts.
    if state_from_json(json.loads(text)) != stored:
        raise StateCorrupt("state does not round-trip through its own serializer")
    directory = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    _fsync_directory(directory)
    return stored
