"""Release and deploy helpers for .github/workflows/cd.yml. Standard library only.

Why: the workflow passes every value through env and calls one subcommand per step. The rules that decide whether a
release record, a host plan, an applied manifest or a deploy result is trusted live here, where the tests can reach them.
The workflow keeps only the git, docker, gh and ssh calls and their ordering. Every subcommand validates its inputs
strictly and fails before writing an output, so an injected or malformed value never reaches a shell or the host.
"""

import argparse
import hashlib
import itertools
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
REPO = "Arthur801/Book-Finder"
SIGNER_WORKFLOW = "Arthur801/Book-Finder/.github/workflows/cd.yml"
WEB_REPO = "ghcr.io/arthur801/book-finder-web"
CRAWLER_REPO = "ghcr.io/arthur801/book-finder-crawler"
CHAINS = ("in-sync", "forward", "schema-ahead")
MAX_METADATA_BYTES = 64 * 1024
MAX_SQL_BYTES = 4 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
MAX_SUMMARY_PLAN_BYTES = 64 * 1024
# Matches the host's N3/N7 timing: the SSH side polls every 30 s and gives a missing started record a grace period.
POLL_INTERVAL_S = 30.0
NOT_STARTED_GRACE_S = 120.0
FOLLOW_TIMEOUT_S = 150 * 60.0
TAG_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")
RUN_ID_RE = re.compile(r"[0-9]{1,20}-[0-9]{1,4}")
REVISION_RE = re.compile(r"[0-9]{1,9}")
MIGRATION_ID_RE = re.compile(r"[0-9]{14}_[A-Za-z0-9]+")
SOURCE_HASH_RE = re.compile(r"[0-9a-f]{64}")
MANIFEST_LINE_RE = re.compile(r"([0-9]{14}_[A-Za-z0-9]+) ([0-9a-f]{64})")
RELEASE_API_RE = re.compile(rb"[0-9]{1,4}\n")
CONTAINER_ID_RE = re.compile(r"[0-9a-f]{12,64}")
WEB_REF_RE = re.compile(re.escape(WEB_REPO) + r"@sha256:[0-9a-f]{64}")
IMAGE_REF_RE = re.compile(rf"(?:{re.escape(WEB_REPO)}|{re.escape(CRAWLER_REPO)})@sha256:[0-9a-f]{{64}}")
IMAGE_TAG_REF_RE = re.compile(rf"(?:{re.escape(WEB_REPO)}|{re.escape(CRAWLER_REPO)}):{TAG_RE.pattern}")
# A build pushes here first; the release tag is created only after the staging digest is attested and verified.
STAGING_TAG_RE = re.compile(r"build-[0-9]{1,20}-[0-9]{1,4}")
RELEASE_KEYS = {"schema_version", "tag", "commit", "web_digest", "crawler_digest", "release_api", "migrations", "sql_assets"}
PLAN_KEYS = {"revision", "runtime", "drift", "schema", "crawler", "compose_version", "target", "classification", "pending"}
TERMINAL_PREFIX = "completed:"


class CdError(Exception):
    """A value or file failed validation. The message is safe to print; it never echoes a whole untrusted value."""


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str]], Result]


def system_runner(argv: Sequence[str]) -> Result:
    """Runs one command without a shell. Tests inject a fake instead."""
    completed = subprocess.run(list(argv), capture_output=True, text=True, check=False, timeout=900)
    return Result(completed.returncode, completed.stdout, completed.stderr)


# Validation helpers


def check(pattern: re.Pattern[str], value: object, what: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise CdError(f"{what} is malformed")
    return value


def check_tag(value: object) -> str:
    tag = check(TAG_RE, value, "tag")
    if len(tag) > 100:
        raise CdError("tag is too long")
    return tag


def check_int(value: object, low: int, high: int, what: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise CdError(f"{what} is out of range")
    return value


def check_ascending(ids: Sequence[str]) -> None:
    for previous, current in itertools.pairwise(ids):
        if current == previous:
            raise CdError("duplicate migration id")
        if not current > previous:
            raise CdError("migration ids are not ascending")


@dataclass(frozen=True)
class Migration:
    id: str
    source_hash: str


def parse_manifest(data: bytes) -> list[Migration]:
    """One "<id> <source_hash>" line per migration, ascending, newline-terminated (the same rules as manifest.sh)."""
    if len(data) > MAX_METADATA_BYTES:
        raise CdError("migrations.txt is larger than 64 KiB")
    if data and not data.endswith(b"\n"):
        raise CdError("migrations.txt does not end with a newline")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise CdError("migrations.txt is not ASCII") from exc
    lines = text.split("\n")[:-1] if text else []
    migrations: list[Migration] = []
    for line in lines:
        match = MANIFEST_LINE_RE.fullmatch(line)
        if match is None:
            raise CdError("migrations.txt has a malformed line")
        migrations.append(Migration(match.group(1), match.group(2)))
    check_ascending([migration.id for migration in migrations])
    return migrations


def render_manifest(migrations: Sequence[Migration]) -> str:
    return "".join(f"{migration.id} {migration.source_hash}\n" for migration in migrations)


def schema_digest(migrations: Sequence[Migration]) -> str:
    """Same as the host's schema digest: sha256 of the canonical manifest text."""
    return "sha256:" + hashlib.sha256(render_manifest(migrations).encode("ascii")).hexdigest()


def read_regular_file(path: Path, max_bytes: int) -> bytes:
    """Reads a regular file that is not a symlink. lstat rejects links before any byte is read; O_NOFOLLOW closes the race."""
    try:
        info = os.lstat(path)
    except FileNotFoundError as exc:
        raise CdError(f"missing file: {path.name}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise CdError(f"{path.name} is not a regular file (or is a symlink)")
    if info.st_size > max_bytes:
        raise CdError(f"{path.name} is larger than {max_bytes} bytes")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise CdError(f"{path.name} is larger than {max_bytes} bytes")
    return data


def read_json_file(path: Path, max_bytes: int = MAX_JSON_BYTES) -> Any:
    data = read_regular_file(path, max_bytes)
    try:
        return json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise CdError(f"{path.name} is not valid JSON") from exc


def _reject_constant(name: str) -> None:
    raise CdError(f"JSON constant {name} is not allowed")


def parse_release_api(data: bytes) -> int:
    if RELEASE_API_RE.fullmatch(data) is None:
        raise CdError("RELEASE_API is malformed")
    value = int(data.strip())
    if value < 1:
        raise CdError("RELEASE_API must be at least 1")
    return value


# Release record (release.json)


@dataclass
class ReleaseRecord:
    tag: str
    commit: str
    web_digest: str
    crawler_digest: str
    release_api: int
    migrations: list[Migration]
    sql_assets: dict[str, str] = field(default_factory=dict)

    def to_obj(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "tag": self.tag,
            "commit": self.commit,
            "web_digest": self.web_digest,
            "crawler_digest": self.crawler_digest,
            "release_api": self.release_api,
            "migrations": [{"id": m.id, "source_hash": m.source_hash} for m in self.migrations],
            "sql_assets": dict(sorted(self.sql_assets.items())),
        }

    def text(self) -> str:
        return json.dumps(self.to_obj(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"

    @property
    def ids(self) -> list[str]:
        return [m.id for m in self.migrations]


def release_from_obj(obj: object) -> ReleaseRecord:
    if not isinstance(obj, dict) or set(obj) != RELEASE_KEYS:
        raise CdError("release.json keys do not match the schema")
    if type(obj["schema_version"]) is not int or obj["schema_version"] != SCHEMA_VERSION:
        raise CdError("release.json schema_version is not supported")
    raw_migrations = obj["migrations"]
    if not isinstance(raw_migrations, list) or not raw_migrations:
        raise CdError("release.json needs a non-empty migrations list")
    migrations: list[Migration] = []
    for item in raw_migrations:
        if not isinstance(item, dict) or set(item) != {"id", "source_hash"}:
            raise CdError("release.json migration entries must have id and source_hash")
        migrations.append(Migration(check(MIGRATION_ID_RE, item["id"], "migration id"), check(SOURCE_HASH_RE, item["source_hash"], "source_hash")))
    check_ascending([migration.id for migration in migrations])
    raw_assets = obj["sql_assets"]
    if not isinstance(raw_assets, dict) or set(raw_assets) != {f"{m.id}.sql" for m in migrations}:
        raise CdError("sql_assets must list exactly one <id>.sql per migration")
    sql_assets = {name: check(SHA256_HEX_RE, digest, "sql sha256") for name, digest in raw_assets.items()}
    return ReleaseRecord(
        tag=check_tag(obj["tag"]),
        commit=check(COMMIT_RE, obj["commit"], "commit"),
        web_digest=check(DIGEST_RE, obj["web_digest"], "web digest"),
        crawler_digest=check(DIGEST_RE, obj["crawler_digest"], "crawler digest"),
        release_api=check_int(obj["release_api"], 1, 9999, "release_api"),
        migrations=migrations,
        sql_assets=sql_assets,
    )


def load_release(path: Path) -> ReleaseRecord:
    return release_from_obj(read_json_file(path))


def build_release(
    tag: str,
    commit: str,
    web_digest: str,
    crawler_digest: str,
    release_dir: Path,
    assets_dir: Path,
) -> ReleaseRecord:
    """Validates an extracted release directory and writes the upload set (release.json, migrations.txt, <id>.sql)."""
    check_tag(tag)
    check(COMMIT_RE, commit, "commit")
    check(DIGEST_RE, web_digest, "web digest")
    check(DIGEST_RE, crawler_digest, "crawler digest")
    manifest_bytes = read_regular_file(release_dir / "migrations.txt", MAX_METADATA_BYTES)
    migrations = parse_manifest(manifest_bytes)
    if not migrations:
        raise CdError("the release has no migrations")
    release_api = parse_release_api(read_regular_file(release_dir / "RELEASE_API", 16))
    sql_dir = release_dir / "sql"
    if not stat.S_ISDIR(os.lstat(sql_dir).st_mode):
        raise CdError("sql/ is not a directory")
    expected_names = {f"{m.id}.sql" for m in migrations}
    if set(os.listdir(sql_dir)) != expected_names:
        raise CdError("sql/ must contain exactly one <id>.sql per migration")
    sql_data: dict[str, bytes] = {}
    sql_assets: dict[str, str] = {}
    for name in sorted(expected_names):
        data = read_regular_file(sql_dir / name, MAX_SQL_BYTES)
        sql_data[name] = data
        sql_assets[name] = hashlib.sha256(data).hexdigest()
    record = ReleaseRecord(tag, commit, web_digest, crawler_digest, release_api, migrations, sql_assets)
    if assets_dir.exists() and any(assets_dir.iterdir()):
        raise CdError("the assets directory must be empty")
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "release.json").write_text(record.text(), encoding="utf-8")
    (assets_dir / "migrations.txt").write_bytes(manifest_bytes)
    for name, data in sql_data.items():
        (assets_dir / name).write_bytes(data)
    return record


def compare_releases(expected: ReleaseRecord, actual: ReleaseRecord) -> list[str]:
    """Names of the fields that differ. An empty list means the published release matches the one just built."""
    expected_obj, actual_obj = expected.to_obj(), actual.to_obj()
    return sorted(key for key in expected_obj if expected_obj[key] != actual_obj.get(key))


def extract_release(image: str, dest: Path, runner: Runner) -> None:
    """Copies migrations.txt, RELEASE_API and sql/<id>.sql out of a web image without running it.

    docker cp runs without -L, so a symlink inside the image arrives as a link; read_regular_file then rejects it.
    Only the named files are copied: compose files and anything else in /opt/release never enter the workflow.
    """
    if WEB_REF_RE.fullmatch(image) is None:
        raise CdError("extract-release takes a web image by digest only")
    dest.mkdir(parents=True, exist_ok=False)
    if runner(["docker", "pull", image]).returncode != 0:
        raise CdError("docker pull failed for the web image")
    created = runner(["docker", "create", "--pull=never", image])
    if created.returncode != 0:
        raise CdError("docker create failed for the web image")
    container = created.stdout.strip()
    check(CONTAINER_ID_RE, container, "container id")
    try:

        def copy(source: str, target: Path) -> None:
            if runner(["docker", "cp", f"{container}:{source}", str(target)]).returncode != 0:
                raise CdError(f"docker cp failed for {Path(source).name}")

        copy("/opt/release/migrations.txt", dest / "migrations.txt")
        copy("/opt/release/RELEASE_API", dest / "RELEASE_API")
        migrations = parse_manifest(read_regular_file(dest / "migrations.txt", MAX_METADATA_BYTES))
        parse_release_api(read_regular_file(dest / "RELEASE_API", 16))
        (dest / "sql").mkdir()
        for migration in migrations:
            copy(f"/opt/release/sql/{migration.id}.sql", dest / "sql" / f"{migration.id}.sql")
    finally:
        runner(["docker", "rm", "-f", container])


# Images and attestations


def image_state(ref: str, runner: Runner) -> tuple[str, str | None]:
    """("absent", None) only for a registry "not found"; any other failure is an error, so a flaky registry never looks absent."""
    if IMAGE_REF_RE.fullmatch(ref) is None and IMAGE_TAG_REF_RE.fullmatch(ref) is None:
        raise CdError("image reference is outside the CD repositories")
    result = runner(["docker", "buildx", "imagetools", "inspect", "--format", "{{json .Manifest}}", ref])
    if result.returncode != 0:
        text = (result.stdout + result.stderr).lower()
        if "not found" in text or "manifest unknown" in text:
            return "absent", None
        raise CdError("cannot inspect the image in the registry")
    try:
        manifest = json.loads(result.stdout)
    except ValueError as exc:
        raise CdError("imagetools returned no manifest JSON") from exc
    if not isinstance(manifest, dict):
        raise CdError("imagetools returned no manifest JSON")
    return "present", check(DIGEST_RE, manifest.get("digest"), "manifest digest")


def verify_attestation(ref: str, tag: str, commit: str, runner: Runner) -> None:
    """I7: a reused image must carry a provenance attestation from this workflow, for this tag's commit."""
    if IMAGE_REF_RE.fullmatch(ref) is None:
        raise CdError("attestation ref must be <repository>@sha256:<digest>")
    check_tag(tag)
    check(COMMIT_RE, commit, "commit")
    argv = [
        "gh",
        "attestation",
        "verify",
        f"oci://{ref}",
        "--repo",
        REPO,
        "--signer-workflow",
        SIGNER_WORKFLOW,
        "--source-ref",
        f"refs/tags/{tag}",
        "--source-digest",
        commit,
        "--deny-self-hosted-runners",
    ]
    if runner(argv).returncode != 0:
        raise CdError(f"attestation verification failed for {ref.split('@', 1)[0]}; never rebuild over an existing tag")


def check_staging_tag(value: object) -> str:
    return check(STAGING_TAG_RE, value, "staging tag")


def confirm_release_digest(ref: str, attested: str, runner: Runner) -> str:
    """The commit check after `imagetools create`: the release tag must resolve to the digest that was attested.

    A mismatch means the release tag now points at an unattested digest. This function cannot undo that; the message says so.
    """
    check(DIGEST_RE, attested, "attested digest")
    state, digest = image_state(ref, runner)
    if state != "present" or digest is None:
        raise CdError("the release tag is missing after the commit")
    if digest != attested:
        raise CdError(
            f"the release tag resolves to {digest}, not the attested {attested}; the tag is on an unattested digest and must be deleted by hand before any rerun"
        )
    return digest


def release_state(tag: str, runner: Runner) -> str:
    check_tag(tag)
    result = runner(["gh", "release", "view", tag, "--json", "isDraft", "--jq", ".isDraft"])
    if result.returncode != 0:
        if "release not found" in result.stderr.lower():
            return "absent"
        raise CdError("cannot read the release state")
    value = result.stdout.strip()
    if value == "true":
        return "draft"
    if value == "false":
        return "published"
    raise CdError("gh returned an unexpected release state")


def publish_release(tag: str, assets_dir: Path, runner: Runner) -> str:
    """Immutable flow (N-plan section 6): draft, upload, publish. A draft is resumed; a published release must match.

    Returns "published" when this call publishes, or "already-published" when the release was already public and identical.
    """
    expected = load_release(assets_dir / "release.json")
    if expected.tag != tag:
        raise CdError("release.json tag does not match the tag being published")
    files = sorted(str(path) for path in assets_dir.iterdir())
    state = release_state(tag, runner)
    if state == "published":
        with tempfile.TemporaryDirectory(prefix="cd-release-") as scratch:
            if runner(["gh", "release", "download", tag, "--pattern", "release.json", "--dir", scratch]).returncode != 0:
                raise CdError("cannot download the published release.json")
            differing = compare_releases(expected, load_release(Path(scratch) / "release.json"))
        if differing:
            raise CdError(f"published release differs from this build in: {', '.join(differing)}")
        return "already-published"
    if state == "absent":
        notes = f"Web image {expected.web_digest}. Crawler image {expected.crawler_digest}. Built from commit {expected.commit}."
        created = runner(["gh", "release", "create", tag, "--draft", "--verify-tag", "--title", tag, "--notes", notes])
        if created.returncode != 0:
            raise CdError("gh release create failed")
    if runner(["gh", "release", "upload", tag, *files, "--clobber"]).returncode != 0:
        raise CdError("uploading the release assets failed")
    if runner(["gh", "release", "edit", tag, "--draft=false"]).returncode != 0:
        raise CdError("publishing the release failed")
    return "published"


# Host plan


def expected_pending(ids: Sequence[str], applied_last: str | None, chain: str) -> list[str]:
    """The target migrations the host must still apply, derived from the chain (I4, N5). Used by plan and SQL checks."""
    if chain not in CHAINS:
        raise CdError("chain is not accepted")
    if chain == "schema-ahead":
        if applied_last is None or applied_last in ids:
            raise CdError("schema-ahead needs an applied migration the target does not contain")
        return []
    if applied_last is not None and applied_last not in ids:
        raise CdError("applied migration is not in the target release")
    start = 0 if applied_last is None else ids.index(applied_last) + 1
    pending = list(ids[start:])
    if chain == "in-sync" and pending:
        raise CdError("in-sync chain has pending migrations")
    if chain == "forward" and not pending:
        raise CdError("forward chain has no pending migrations")
    return pending


def plan_outputs(plan: object, host_exit: int, release: ReleaseRecord, tag: str, web_digest: str, cutover: bool) -> dict[str, str]:
    """Validates the host's plan JSON (exit 0 only) and returns the workflow outputs. Refuses anything it cannot prove."""
    if host_exit != 0:
        raise CdError(f"host plan exited {host_exit}; see the summary for the reported state")
    if not isinstance(plan, dict) or set(plan) != PLAN_KEYS:
        raise CdError("plan JSON keys do not match the host contract")
    check_tag(tag)
    check(DIGEST_RE, web_digest, "web digest")
    if release.tag != tag or release.web_digest != web_digest:
        raise CdError("the target release record does not match the requested tag and digest")
    target = plan["target"]
    if target != {"tag": tag, "web_digest": web_digest, "release_api": release.release_api}:
        raise CdError("host plan target does not match the release record")
    chain = plan["classification"]
    if chain == "divergent":
        raise CdError("chain is divergent; nothing can be deployed")
    if chain not in CHAINS:
        raise CdError("chain is not accepted")
    schema = plan["schema"]
    if not isinstance(schema, dict) or schema.get("dirty") is not False:
        raise CdError("schema is dirty; resolve it on the host first")
    if plan["drift"] != []:
        raise CdError("host reports drift")
    crawler = plan["crawler"]
    if not isinstance(crawler, dict) or set(crawler) != {"paused", "digest"} or crawler["paused"] is not None:
        raise CdError("crawler is paused or the plan crawler block is malformed")
    state_crawler = check(DIGEST_RE, crawler["digest"], "state crawler digest")
    revision = plan["revision"]
    if type(revision) is not int:
        raise CdError("revision is malformed")
    check(REVISION_RE, str(revision), "revision")
    applied_last = schema.get("applied_last")
    if applied_last is not None:
        check(MIGRATION_ID_RE, applied_last, "applied_last")
    schema_digest_value = check(DIGEST_RE, schema.get("digest"), "schema digest")
    rebuild = schema.get("rebuild")
    if not isinstance(rebuild, dict) or set(rebuild) != {"tag", "web_digest"}:
        raise CdError("schema.rebuild is malformed")
    rebuild_tag = check_tag(rebuild["tag"])
    rebuild_digest = check(DIGEST_RE, rebuild["web_digest"], "rebuild digest")
    pending = plan["pending"]
    if not isinstance(pending, list):
        raise CdError("pending is malformed")
    for migration_id in pending:
        check(MIGRATION_ID_RE, migration_id, "pending id")
    if pending != expected_pending(release.ids, applied_last, chain):
        raise CdError("host pending list does not match the target release")
    runtime = plan["runtime"]
    if not isinstance(runtime, dict) or not isinstance(runtime.get("state"), dict):
        raise CdError("runtime block is malformed")
    state = runtime["state"]
    if state.get("kind") == "docker":
        runtime_digest = check(DIGEST_RE, state.get("web_digest"), "runtime web digest")
        expect_runtime = runtime_digest
        runtime_kind = "docker"
    elif state.get("kind") == "systemd":
        runtime_digest = "none"
        expect_runtime = "systemd"
        runtime_kind = "systemd"
    else:
        raise CdError("runtime kind is not accepted")
    # cutover rules: the first switch to docker is explicit, only in-sync, and never with a docker runtime already.
    if cutover:
        if runtime_kind != "systemd":
            raise CdError("cutover was requested but the runtime is already docker")
        if chain != "in-sync":
            raise CdError("cutover is only accepted for an in-sync chain")
        cutover_ok = "true"
    else:
        if runtime_kind == "systemd":
            raise CdError("runtime is systemd; the first switch must be requested with cutover")
        cutover_ok = "false"
    crawler_for_deploy = state_crawler if chain == "schema-ahead" else release.crawler_digest
    return {
        "revision": str(revision),
        "expect_runtime": expect_runtime,
        "expect_schema": schema_digest_value,
        "chain": chain,
        "pending": " ".join(pending) or "none",
        "applied_last": applied_last or "none",
        "rebuild_tag": rebuild_tag,
        "rebuild_web_digest": rebuild_digest,
        "runtime_web_digest": runtime_digest,
        "state_crawler_digest": state_crawler,
        "crawler_for_deploy": crawler_for_deploy,
        "cutover_ok": cutover_ok,
    }


def applied_manifest(rebuild_manifest: bytes, applied_last: str | None, expected_digest: str) -> bytes:
    """A = the rebuild image's manifest cut after applied_last (N1). Its digest must equal the state's schema digest."""
    check(DIGEST_RE, expected_digest, "expected digest")
    migrations = parse_manifest(rebuild_manifest)
    if applied_last is None:
        kept: list[Migration] = []
    else:
        check(MIGRATION_ID_RE, applied_last, "applied_last")
        ids = [m.id for m in migrations]
        if applied_last not in ids:
            raise CdError("applied_last is not in the rebuild image's manifest")
        kept = migrations[: ids.index(applied_last) + 1]
    text = render_manifest(kept).encode("ascii")
    if schema_digest(kept) != expected_digest:
        raise CdError("the rebuild image cannot reproduce the production schema digest (N1)")
    return text


def fence_for(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def pending_sql_summary(release: ReleaseRecord, sql_dir: Path, applied_last: str | None, chain: str, pending: list[str]) -> str:
    """Reads the pending SQL from the target release's assets (N8). Every file must match release.json before it is shown."""
    if pending != expected_pending(release.ids, applied_last, chain):
        raise CdError("pending list does not match the target release")
    if not pending:
        return "## Pending migrations\n\nNo migrations are pending. Nothing is applied to the database.\n"
    lines = ["## Pending migrations (from the target release assets)", ""]
    for migration_id in pending:
        name = f"{migration_id}.sql"
        data = read_regular_file(sql_dir / name, MAX_SQL_BYTES)
        if hashlib.sha256(data).hexdigest() != release.sql_assets[name]:
            raise CdError(f"{name} does not match release.json")
        text = data.decode("utf-8", errors="replace")
        fence = fence_for(text)
        lines += [f"### {migration_id}", "", f"{fence}sql", text.rstrip("\n"), fence, ""]
    lines.append("The SQL is for review only. The image's efbundle applies the migrations; this file is not executed.")
    return "\n".join(lines) + "\n"


def summarize_compat(report_path: Path) -> str:
    try:
        report = read_json_file(report_path, MAX_JSON_BYTES)
    except CdError:
        return "## Migration compat check\n\nNo report was written; the check failed before it started.\n"
    lines = [
        "## Migration compat check",
        "",
        f"- forward_ok: `{str(report['forward_ok']).lower()}`",
        f"- classification: `{report['classification']}`",
        f"- pending: {', '.join(report['pending']) or 'none'}",
        f"- runtime smoke (informational): `{report['runtime_smoke']['result']}`",
        "",
        "| check | result | detail |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {check_['name']} | {check_['result']} | {check_['detail']} |" for check_ in report["checks"]]
    return "\n".join(lines) + "\n"


def decision_summary(outputs: dict[str, str]) -> str:
    lines = [
        "## Decision",
        "",
        f"- chain: `{outputs['chain']}`",
        f"- pending: {outputs['pending']}",
        f"- cutover: `{outputs['cutover_ok']}`",
        f"- crawler for deploy: `{outputs['crawler_for_deploy']}`",
    ]
    if outputs["chain"] == "schema-ahead":
        lines.append("- schema-ahead: no migration runs, and the crawler stays on the current digest (S7).")
    return "\n".join(lines) + "\n"


def plan_summary(raw: str, host_exit: int) -> str:
    """Summary text written before any validation, so a failed plan still shows the host's JSON."""
    body = raw[:MAX_SUMMARY_PLAN_BYTES]
    fence = fence_for(body)
    lines = ["## CD plan", "", f"- host exit code: `{host_exit}`", "", f"{fence}json", body.rstrip("\n"), fence, ""]
    return "\n".join(lines) + "\n"


# Deploy result following (N7)


@dataclass(frozen=True)
class Outcome:
    ok: bool
    status: str
    message: str


def parse_status(text: str, run_id: str) -> str | None:
    """The last JSON line that names this run; anything else is "no answer yet" (SSH errors and partial output)."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        obj = json.loads(lines[-1])
    except ValueError:
        return None
    if not isinstance(obj, dict) or obj.get("run_id") != run_id or not isinstance(obj.get("status"), str):
        return None
    return obj["status"]


def follow_deploy(
    run_id: str,
    first_output: str,
    poll: Callable[[], str],
    now: Callable[[], float],
    sleep: Callable[[float], None],
    interval: float = POLL_INTERVAL_S,
    grace: float = NOT_STARTED_GRACE_S,
    timeout: float = FOLLOW_TIMEOUT_S,
) -> Outcome:
    """Decides the CD result from the host's status (history is the source of truth, N7). poll() runs `status <run_id>`."""
    check(RUN_ID_RE, run_id, "run id")
    start = now()
    status = parse_status(first_output, run_id)
    while True:
        elapsed = now() - start
        if status is not None:
            if status == "completed:success":
                return Outcome(True, status, "deploy completed")
            if status.startswith(TERMINAL_PREFIX):
                return Outcome(False, status, "deploy finished with a failure result; see the host journal and history")
            if status == "indeterminate":
                return Outcome(False, status, "indeterminate: manual resolve-run required; do not re-dispatch")
            if status == "not-started" and elapsed >= grace:
                return Outcome(False, status, "not-started: nothing changed; safe to re-dispatch")
            if status not in ("running", "not-started"):
                return Outcome(False, status, "unexpected status from the host")
        if elapsed >= timeout:
            return Outcome(False, status or "unknown", f"still not finished after {int(timeout // 60)} minutes; poll status {run_id} later")
        sleep(interval)
        status = parse_status(poll(), run_id)


def status_ssh_argv(host: str, key: str, known_hosts: str, run_id: str) -> list[str]:
    return [
        "ssh",
        "-i",
        key,
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=30",
        host,
        f"status {run_id}",
    ]


# Subcommands


def write_outputs(path: str | None, values: dict[str, str]) -> None:
    lines = []
    for key, value in values.items():
        if "\n" in value or "\r" in value:
            raise CdError(f"output {key} contains a newline")
        lines.append(f"{key}={value}\n")
    text = "".join(lines)
    if path is None:
        sys.stdout.write(text)
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def append_text(path: str | None, text: str) -> None:
    if path is None:
        sys.stdout.write(text)
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def _cmd_validate_tag(args: argparse.Namespace) -> None:
    write_outputs(args.github_output, {"tag": check_tag(args.tag)})


def _cmd_build_release_json(args: argparse.Namespace) -> None:
    record = build_release(args.tag, args.commit, args.web_digest, args.crawler_digest, Path(args.release_dir), Path(args.assets_dir))
    print(f"wrote {len(record.migrations)} migrations, release.json, migrations.txt and {len(record.sql_assets)} sql assets")


def _cmd_extract_release(args: argparse.Namespace) -> None:
    extract_release(args.image, Path(args.dest), system_runner)
    print("extracted migrations.txt, RELEASE_API and sql/ (regular files only)")


def _cmd_compare_release_json(args: argparse.Namespace) -> None:
    differing = compare_releases(load_release(Path(args.expected)), load_release(Path(args.actual)))
    if differing:
        raise CdError(f"published release.json differs in: {', '.join(differing)}")
    print("published release.json matches the one just built")


def _cmd_validate_release_json(args: argparse.Namespace) -> None:
    record = load_release(Path(args.file))
    if args.tag is not None and record.tag != args.tag:
        raise CdError("release.json tag does not match")
    if args.commit is not None and record.commit != args.commit:
        raise CdError("release.json commit does not match")
    if args.web_digest is not None and record.web_digest != args.web_digest:
        raise CdError("release.json web digest does not match")
    write_outputs(
        args.github_output,
        {
            "tag": record.tag,
            "commit": record.commit,
            "web_digest": record.web_digest,
            "crawler_digest": record.crawler_digest,
            "release_api": str(record.release_api),
        },
    )


def _cmd_release_state(args: argparse.Namespace) -> None:
    print(release_state(args.tag, system_runner))


def _cmd_publish_release(args: argparse.Namespace) -> None:
    print(publish_release(args.tag, Path(args.assets_dir), system_runner))


def _cmd_image_state(args: argparse.Namespace) -> None:
    state, digest = image_state(args.ref, system_runner)
    write_outputs(args.github_output, {"exists": "true" if state == "present" else "false", "digest": digest or "none"})


def _cmd_verify_attestation(args: argparse.Namespace) -> None:
    verify_attestation(args.ref, args.tag, args.commit, system_runner)
    print("attestation verified")


def _cmd_validate_staging_tag(args: argparse.Namespace) -> None:
    check_staging_tag(args.tag)
    print("staging tag is valid")


def _cmd_confirm_release(args: argparse.Namespace) -> None:
    digest = confirm_release_digest(args.ref, args.digest, system_runner)
    print(f"release tag resolves to the attested digest {digest}")


def _cmd_plan_outputs(args: argparse.Namespace) -> None:
    plan_path = Path(args.plan_file)
    # The whole file is parsed (capped at 1 MiB); only the summary copy is truncated.
    raw = read_regular_file(plan_path, MAX_JSON_BYTES).decode("utf-8", errors="replace") if plan_path.exists() else ""
    append_text(args.summary, plan_summary(raw, args.host_exit))
    if args.host_exit != 0:
        raise CdError(f"host plan exited {args.host_exit}")
    try:
        plan = json.loads(raw)
    except ValueError as exc:
        raise CdError("host plan output is not JSON") from exc
    release = load_release(Path(args.release_json))
    outputs = plan_outputs(plan, args.host_exit, release, args.tag, args.web_digest, args.cutover == "true")
    write_outputs(args.github_output, outputs)
    append_text(args.summary, decision_summary(outputs))


def _cmd_applied_manifest(args: argparse.Namespace) -> None:
    data = applied_manifest(
        read_regular_file(Path(args.rebuild_migrations), MAX_METADATA_BYTES), None if args.applied_last == "none" else args.applied_last, args.expected_digest
    )
    Path(args.out).write_bytes(data)
    print(f"applied manifest has {len(parse_manifest(data))} migrations and matches the state digest")


def _cmd_pending_sql_summary(args: argparse.Namespace) -> None:
    release = load_release(Path(args.release_json))
    pending = [] if args.pending == "none" else args.pending.split(" ")
    for migration_id in pending:
        check(MIGRATION_ID_RE, migration_id, "pending id")
    applied_last = None if args.applied_last == "none" else args.applied_last
    append_text(args.summary, pending_sql_summary(release, Path(args.sql_dir), applied_last, args.chain, pending))


def _cmd_summarize_compat(args: argparse.Namespace) -> None:
    append_text(args.summary, summarize_compat(Path(args.report)))


def _cmd_deploy_follow(args: argparse.Namespace) -> None:
    first = Path(args.first_output).read_text(encoding="utf-8") if args.first_output and Path(args.first_output).exists() else ""

    def poll() -> str:
        argv = status_ssh_argv(args.host, args.key, args.known_hosts, args.run_id)
        result = system_runner(argv)
        return result.stdout if result.returncode == 0 else ""

    outcome = follow_deploy(args.run_id, first, poll, time.monotonic, time.sleep)
    append_text(args.summary, f"## Deploy result\n\n- run: `{args.run_id}`\n- status: `{outcome.status}`\n- {outcome.message}\n")
    if not outcome.ok:
        raise CdError(outcome.message)
    print(outcome.message)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    github_output = os.environ.get("GITHUB_OUTPUT")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")

    p = sub.add_parser("validate-tag")
    p.add_argument("--tag", required=True)
    p.add_argument("--github-output", default=github_output)
    p.set_defaults(func=_cmd_validate_tag)

    p = sub.add_parser("build-release-json")
    for flag in ("--tag", "--commit", "--web-digest", "--crawler-digest", "--release-dir", "--assets-dir"):
        p.add_argument(flag, required=True)
    p.set_defaults(func=_cmd_build_release_json)

    p = sub.add_parser("extract-release")
    p.add_argument("--image", required=True)
    p.add_argument("--dest", required=True)
    p.set_defaults(func=_cmd_extract_release)

    p = sub.add_parser("compare-release-json")
    p.add_argument("--expected", required=True)
    p.add_argument("--actual", required=True)
    p.set_defaults(func=_cmd_compare_release_json)

    p = sub.add_parser("validate-release-json")
    p.add_argument("--file", required=True)
    p.add_argument("--tag")
    p.add_argument("--commit")
    p.add_argument("--web-digest")
    p.add_argument("--github-output", default=github_output)
    p.set_defaults(func=_cmd_validate_release_json)

    p = sub.add_parser("release-state")
    p.add_argument("--tag", required=True)
    p.set_defaults(func=_cmd_release_state)

    p = sub.add_parser("publish-release")
    p.add_argument("--tag", required=True)
    p.add_argument("--assets-dir", required=True)
    p.set_defaults(func=_cmd_publish_release)

    p = sub.add_parser("image-state")
    p.add_argument("--ref", required=True)
    p.add_argument("--github-output", default=github_output)
    p.set_defaults(func=_cmd_image_state)

    p = sub.add_parser("verify-attestation")
    p.add_argument("--ref", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--commit", required=True)
    p.set_defaults(func=_cmd_verify_attestation)

    p = sub.add_parser("validate-staging-tag")
    p.add_argument("--tag", required=True)
    p.set_defaults(func=_cmd_validate_staging_tag)

    p = sub.add_parser("confirm-release")
    p.add_argument("--ref", required=True)
    p.add_argument("--digest", required=True)
    p.set_defaults(func=_cmd_confirm_release)

    p = sub.add_parser("plan-outputs")
    p.add_argument("--plan-file", required=True)
    p.add_argument("--host-exit", type=int, required=True)
    p.add_argument("--release-json", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--web-digest", required=True)
    p.add_argument("--cutover", choices=("true", "false"), required=True)
    p.add_argument("--github-output", default=github_output)
    p.add_argument("--summary", default=step_summary)
    p.set_defaults(func=_cmd_plan_outputs)

    p = sub.add_parser("applied-manifest")
    p.add_argument("--rebuild-migrations", required=True)
    p.add_argument("--applied-last", required=True, help="a migration id, or 'none'")
    p.add_argument("--expected-digest", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=_cmd_applied_manifest)

    p = sub.add_parser("pending-sql-summary")
    p.add_argument("--release-json", required=True)
    p.add_argument("--sql-dir", required=True)
    p.add_argument("--applied-last", required=True)
    p.add_argument("--chain", choices=CHAINS, required=True)
    p.add_argument("--pending", required=True, help="space-separated ids, or 'none'")
    p.add_argument("--summary", default=step_summary)
    p.set_defaults(func=_cmd_pending_sql_summary)

    p = sub.add_parser("summarize-compat")
    p.add_argument("--report", required=True)
    p.add_argument("--summary", default=step_summary)
    p.set_defaults(func=_cmd_summarize_compat)

    p = sub.add_parser("deploy-follow")
    p.add_argument("--run-id", required=True)
    p.add_argument("--first-output", default="")
    p.add_argument("--host", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--known-hosts", required=True)
    p.add_argument("--summary", default=step_summary)
    p.set_defaults(func=_cmd_deploy_follow)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except CdError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
