"""Python port of deploy/lib/manifest.sh: release migration manifests and their chain relations.

Why: the host must reach the same verdict as the bash compat check on every manifest. The rules here mirror the bash
functions one for one, and tests/host/test_manifest_parity.py keeps the two in step.
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from bookfinder_host.images import is_digest_ref
from bookfinder_host.ports import Runner
from bookfinder_host.safefile import UnsafeFileError, read_regular_file

MAX_BYTES = 65536
RELEASE_API_MAX_BYTES = 16
CONTAINER_RELEASE_DIR = "/opt/release"
# Migration identity is (id, source_hash) per N5; the SQL hash is audit-only and never appears here.
_LINE_RE = re.compile(r"[0-9]{14}_[A-Za-z0-9]+ [0-9a-f]{64}")
_RELEASE_API_RE = re.compile(rb"[0-9]{1,4}\n")
_CONTAINER_ID_RE = re.compile(r"[0-9a-f]{12,64}")

Classification = Literal["in-sync", "forward", "schema-ahead", "divergent"]


class ManifestError(Exception):
    """A manifest or release metadata file failed validation."""


@dataclass(frozen=True)
class Migration:
    id: str
    source_hash: str


@dataclass(frozen=True)
class ReleaseMetadata:
    migrations: tuple[Migration, ...]
    release_api: int


def parse_manifest(data: bytes) -> list[Migration]:
    if data and not data.endswith(b"\n"):
        raise ManifestError("manifest does not end with a newline")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ManifestError("manifest is not ASCII") from exc
    lines = text.split("\n")[:-1] if text else []
    migrations: list[Migration] = []
    for line in lines:
        if _LINE_RE.fullmatch(line) is None:
            raise ManifestError(f"malformed manifest line: {line!r}")
        migration_id, source_hash = line.split(" ")
        # Plain str comparison on ASCII is bytewise, matching the bash LC_ALL=C comparison.
        if migrations and migration_id == migrations[-1].id:
            raise ManifestError(f"duplicate migration id: {migration_id}")
        if migrations and not migration_id > migrations[-1].id:
            raise ManifestError(f"migration ids are not ascending: {migration_id} after {migrations[-1].id}")
        migrations.append(Migration(migration_id, source_hash))
    return migrations


def read_manifest_file(path: str | Path) -> list[Migration]:
    try:
        data = read_regular_file(path, MAX_BYTES)
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest is missing: {path}") from exc
    except UnsafeFileError as exc:
        raise ManifestError(str(exc)) from exc
    return parse_manifest(data)


def render_manifest(migrations: Sequence[Migration]) -> str:
    return "".join(f"{migration.id} {migration.source_hash}\n" for migration in migrations)


def schema_digest(migrations: Sequence[Migration]) -> str:
    """Digest over the canonical manifest text, equal to manifest_schema_digest for the same content."""
    return "sha256:" + hashlib.sha256(render_manifest(migrations).encode("ascii")).hexdigest()


def _shared_prefix(applied: Sequence[Migration], target: Sequence[Migration]) -> int:
    index = 0
    while index < len(applied) and index < len(target) and applied[index] == target[index]:
        index += 1
    return index


def classify(applied: Sequence[Migration], target: Sequence[Migration]) -> Classification:
    shared = _shared_prefix(applied, target)
    if shared == len(applied) and shared == len(target):
        return "in-sync"
    if shared == len(applied) and len(applied) < len(target):
        return "forward"
    if shared == len(target) and len(target) < len(applied):
        return "schema-ahead"
    return "divergent"


def pending(applied: Sequence[Migration], target: Sequence[Migration]) -> list[Migration]:
    classification = classify(applied, target)
    if classification not in ("in-sync", "forward"):
        raise ValueError(f"pending needs a forward or in-sync pair, got {classification}")
    return list(target[len(applied) :])


def read_release_api(path: Path) -> int:
    try:
        data = read_regular_file(path, RELEASE_API_MAX_BYTES)
    except FileNotFoundError as exc:
        raise ManifestError(f"RELEASE_API is missing: {path}") from exc
    except UnsafeFileError as exc:
        raise ManifestError(str(exc)) from exc
    if _RELEASE_API_RE.fullmatch(data) is None:
        raise ManifestError("RELEASE_API must be 1-4 digits and a newline")
    return int(data.rstrip(b"\n"))


def extract_release_metadata(runner: Runner, image_ref: str, dest_dir: Path) -> ReleaseMetadata:
    """Copies the two metadata files out of a created (never started) container.

    Why: docker cp without -L copies a symlink as a link, which would point into the host. Each copied file is checked
    with lstat before it is opened, so a link is rejected without reading what it points to.
    """
    if not is_digest_ref(image_ref):
        raise ManifestError(f"image reference must be <repository>@sha256:<digest>: {image_ref!r}")
    # Pull first and create with --pull=never, so the metadata always comes from the digest that was named.
    pulled = runner.run(["docker", "pull", image_ref])
    if pulled.returncode != 0:
        raise ManifestError(f"docker pull failed for {image_ref}: {pulled.stderr.strip()}")
    created = runner.run(["docker", "create", "--pull=never", image_ref])
    if created.returncode != 0:
        raise ManifestError(f"docker create failed: {created.stderr.strip()}")
    container_id = created.stdout.strip()
    if _CONTAINER_ID_RE.fullmatch(container_id) is None:
        raise ManifestError("docker create returned an unexpected container id")
    try:
        for name in ("migrations.txt", "RELEASE_API"):
            copied = runner.run(["docker", "cp", f"{container_id}:{CONTAINER_RELEASE_DIR}/{name}", str(dest_dir / name)])
            if copied.returncode != 0:
                raise ManifestError(f"docker cp failed for {name}: {copied.stderr.strip()}")
        migrations = read_manifest_file(dest_dir / "migrations.txt")
        release_api = read_release_api(dest_dir / "RELEASE_API")
    finally:
        # The container was never started, so removing it has no effect on the running host; a failed rm is harmless.
        runner.run(["docker", "rm", container_id])
    return ReleaseMetadata(tuple(migrations), release_api)
