"""The deploy state machine (steps 1-7 of the deploy flow, deploy/README.md §1.1), executed inside the transient unit (N7: the unit, not the SSH session, owns the run).

Why: every outcome is decided here and written to history exactly once. Each step that changes the host is ordered so
that a crash at any point leaves state the next run can see and refuse (dirty, paused, indeterminate). A crash is
deliberately not converted into a known result: the run stays indeterminate until an operator resolves it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from bookfinder_host import config as cfg
from bookfinder_host import history as hi
from bookfinder_host import locks
from bookfinder_host import manifest as mf
from bookfinder_host import runtime as rt
from bookfinder_host import state as st
from bookfinder_host.exit_codes import BAD_INPUT, DRIFT, FAILED_DOWN, FAILED_MIGRATION, OK, PARTIAL_CRAWLER, ROLLED_BACK
from bookfinder_host.images import is_digest_ref
from bookfinder_host.ports import EffectFailed, Effects
from bookfinder_host.release_content import COMPOSE_CA_BUNDLE, COMPOSE_FILE, ReleaseRejected, compose_sha256_of, validate_tree
from bookfinder_host.safefile import UnsafeFileError, read_regular_file

if TYPE_CHECKING:
    from bookfinder_host.commands import DeployCommand, Deps

LOCAL_URL = "http://127.0.0.1:5000/"
LOCAL_HEADERS = {"X-Forwarded-Proto": "https"}
PROBE_TRIES = 3  # step 1: three tries, 5 s each, before a run is refused as drift
PROBE_TIMEOUT_S = 5.0
PROBE_INTERVAL_S = 1.0
HEALTH_BUDGET_S = 90.0  # step 5: the new runtime gets 90 s to answer
HEALTH_INTERVAL_S = 2.0
LOG_TAIL_LINES = 80  # the last lines journaled after a failed switch (web container log) or failed migration (efbundle)
# efbundle reads its connection from this variable, in the migration env file; the web env file uses the same name.
MIGRATION_ENV_NAME = "ConnectionStrings__DefaultConnection"
# A connection string's Password= part is masked on its own too, because the same password can appear outside the string.
_PASSWORD_PART = re.compile(r"(?i)password\s*=\s*([^;]*)")
CRAWLER_KEY = "CRAWLER_IMAGE="
# Outcome per sub-step, recorded in the completed record so resume-crawler can tell what already took effect.
CRAWLER_SUBSTEPS = ("image", "smoke", "run_crawler", "crawler_cron", "crawler_conf")
# A schema-ahead deploy never touches the crawler, so its sub-steps are recorded as one marker.
SCHEMA_AHEAD_SUBSTEPS = "skipped (schema-ahead)"
MAX_RUNNER_BYTES = 1 << 20


class _Stop(Exception):
    """Ends the run with a known outcome: exit code, history result and the human-readable reason."""

    def __init__(self, code: int, result: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.result = result
        self.reason = reason


def finish_run(
    deps: Deps,
    out: TextIO,
    err: TextIO,
    run_id: str,
    state: st.State | None,
    code: int,
    result: str,
    reason: str,
    snapshot_id: str | None = None,
    crawler_substeps: dict[str, str] | str | None = None,
) -> int:
    """Writes the single completed record for a run (N7: one end per run, so the history can never say two things); the history line never holds secrets or free text.

    state is None when the run ends before a state was read (lock busy, state missing or corrupt); the summary is then
    empty, since no state was observed.
    """
    hi.append(
        deps.settings.history_file,
        hi.completed_record(
            run_id=run_id,
            result=result,
            exit_code=code,
            at=deps.clock.now(),
            state_summary={} if state is None else st.state_summary(state),
            snapshot_id=snapshot_id,
            crawler_substeps=crawler_substeps,
        ),
    )
    out.write(json.dumps({"run_id": run_id, "result": result, "exit_code": code}, sort_keys=True) + "\n")
    err.write(reason + "\n")
    return code


@dataclass
class _Run:
    command: DeployCommand
    state: st.State
    deps: Deps
    run_id: str
    target: mf.ReleaseMetadata
    out: TextIO
    err: TextIO
    release_dir: Path | None = None
    compose_sha256: str = ""
    env_path: str = ""
    # Only set when SSM_MIGRATION_CONNECTION is configured: efbundle then reads this file instead of env_path.
    migrate_env_path: str = ""
    snapshot_id: str | None = None
    crawler_substeps: dict[str, str] | str | None = None
    # Every secret string rendered into this run's env file, longest first; diagnostics mask them before anything is written.
    secrets: tuple[str, ...] = ()

    @property
    def effects(self) -> Effects:
        return self.deps.effects

    @property
    def settings(self) -> cfg.Settings:
        return self.deps.settings

    @property
    def tag(self) -> str:
        return self.command.tag

    @property
    def web_ref(self) -> str:
        return f"{self.settings.web_image_repository}@{self.command.web_digest}"

    @property
    def crawler_ref(self) -> str:
        return f"{self.settings.crawler_image_repository}@{self.command.crawler_digest}"

    def save(self, new: st.State) -> None:
        # Every write is a compare-and-set on the revision this run last saw (S4: a concurrent writer cannot be silently overwritten); the file is durable before the next step.
        self.state = st.write_state(self.settings.state_file, new, expected_revision=self.state.revision)

    def finish(self, code: int, result: str, reason: str) -> int:
        return finish_run(
            self.deps,
            self.out,
            self.err,
            self.run_id,
            self.state,
            code,
            result,
            reason,
            self.snapshot_id,
            self.crawler_substeps,
        )


def run_state_machine(
    command: DeployCommand,
    state: st.State,
    deps: Deps,
    run_id: str,
    target: mf.ReleaseMetadata,
    out: TextIO,
    err: TextIO,
) -> int:
    run = _Run(command=command, state=state, deps=deps, run_id=run_id, target=target, out=out, err=err)
    try:
        return _execute(run)
    except _Stop as stop:
        return run.finish(stop.code, stop.result, stop.reason)
    finally:
        # The env file holds the three secrets; it is removed on every path, after compose or rollback is done.
        # Docker copies the values into the container config at create time, so a reboot does not need the file.
        _discard_env(run)


# The capability probe: a one-service compose file whose env_file uses format: raw, and a value that interpolation,
# quoting or comment handling would change. Only `config` runs, so nothing is started.
PROBE_SERVICE = "probe"
PROBE_NAME = "PROBE"
PROBE_VALUE = "a$B${HOME}'\"#x"
PROBE_COMPOSE = """services:
  probe:
    image: alpine:3
    env_file:
      - path: ./probe.env
        format: raw
"""


def compose_raw_env_check(compose, run_dir: Path) -> tuple[str, str | None]:
    """Returns (docker compose version --short or a reason, refusal message or None).

    Why: a Compose without raw env_file support would interpolate the secrets, so the host asks the installed Compose
    to render the probe and checks the value it returns. Any failure, missing key or changed value is a refusal.
    """
    try:
        version = compose.version().strip() or "unknown"
    except EffectFailed as exc:
        version = f"unknown ({exc})"
    if not compose_supports_raw_env_file(compose, run_dir):
        return version, f"docker compose does not support env_file format: raw (found {version})"
    return version, None


def compose_supports_raw_env_file(compose, run_dir: Path) -> bool:
    os.makedirs(run_dir, mode=0o700, exist_ok=True)
    # mkdtemp creates the directory with mode 0700; the probe never outlives this call.
    probe_dir = Path(tempfile.mkdtemp(prefix=".probe-", dir=run_dir))
    try:
        (probe_dir / "compose.yaml").write_text(PROBE_COMPOSE, encoding="utf-8")
        (probe_dir / "probe.env").write_text(f"{PROBE_NAME}={PROBE_VALUE}\n", encoding="utf-8")
        try:
            rendered = json.loads(compose.config_json(str(probe_dir / "compose.yaml")))
            value = rendered["services"][PROBE_SERVICE]["environment"][PROBE_NAME]
        except (EffectFailed, ValueError, KeyError, TypeError):
            return False
        # `config --format json` writes each literal $ as $$ (verified with Compose 5.6.0). An interpolated value cannot
        # equal either form, because $B is blanked and ${HOME} expanded before the comparison.
        return value in (PROBE_VALUE, PROBE_VALUE.replace("$", "$$"))
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)


def _execute(r: _Run) -> int:
    # Step 0 (the gates ran in commands.py): a crawler left paused by an earlier failure needs a human first.
    if r.state.crawler.paused is not None:
        raise _Stop(DRIFT, "drift", "crawler is paused by an earlier run; resume-crawler must run first")
    # Before any change: an old Compose must not get as far as the migration.
    _version, problem = compose_raw_env_check(r.effects.compose, Path(r.settings.run_dir))
    if problem is not None:
        raise _Stop(BAD_INPUT, "rejected", problem)
    # Step 1: the current runtime must be healthy before anything changes.
    if not _probe_tries(r):
        raise _Stop(DRIFT, "drift", "current runtime failed its health check; nothing was changed")
    # Step 2: release content, only after approval, never taken from the plan.
    _materialize_release(r)
    # Step 3: secrets for the migration container and for the web container.
    _render_env(r)
    # Step 4: forward only.
    if r.command.chain == "forward":
        _forward_migration(r)
    # Step 5: switch the runtime; the failure branch is step 7.
    failure = _switch(r)
    if failure is not None:
        _web_failed(r, failure)
    # Step 6: crawler update, then promote the runtime.
    return _finish_success_path(r)


# Step 1


def _probe_tries(r: _Run) -> bool:
    for attempt in range(PROBE_TRIES):
        if r.effects.http.status(LOCAL_URL, LOCAL_HEADERS, PROBE_TIMEOUT_S) == 200:
            return True
        if attempt < PROBE_TRIES - 1:
            r.deps.clock.sleep(PROBE_INTERVAL_S)
    return False


def _wait_for_200(r: _Run, url: str, headers: Mapping[str, str]) -> int:
    """Polls until the URL answers 200 or the budget runs out; returns the last status (0 when no response arrived)."""
    deadline = r.deps.clock.monotonic() + HEALTH_BUDGET_S
    while True:
        status = r.effects.http.status(url, headers, PROBE_TIMEOUT_S)
        if status == 200:
            return status
        if r.deps.clock.monotonic() >= deadline:
            return status
        r.deps.clock.sleep(HEALTH_INTERVAL_S)


def _public_url(r: _Run) -> str:
    return r.settings.public_url.rstrip("/") + "/"


@dataclass(frozen=True)
class _HealthFailure:
    stage: str  # "local" or "public": the first check that never answered 200
    status: int  # the last status seen; 0 when no response arrived


def _health(r: _Run) -> _HealthFailure | None:
    """Local port first (the app itself), then the public URL through nginx and TLS. The switch and the rollback both use this."""
    local = _wait_for_200(r, LOCAL_URL, LOCAL_HEADERS)
    if local != 200:
        return _HealthFailure("local", local)
    public = _wait_for_200(r, _public_url(r), {})
    if public != 200:
        return _HealthFailure("public", public)
    return None


def _journal_health_failure(r: _Run, failure: _HealthFailure, *, rollback: bool) -> None:
    prefix = "rollback health check" if rollback else "health check"
    status = "0 (no response)" if failure.status == 0 else str(failure.status)
    r.err.write(f"{prefix} failed at the {failure.stage} stage; last status {status}\n")
    if failure.stage == "public" and 400 <= failure.status < 500:
        # Why: a 4xx from the edge while the local port answers 200 means the request itself was refused (for example a
        # User-Agent rule in nginx or a WAF), not that the app is down. Say so in the journal, where it can be found next time.
        r.err.write(f"stage=public status={failure.status} \u2014 the edge refused the request; check nginx/WAF rules for the User-Agent\n")


def _journal_container_log(r: _Run) -> None:
    """The last lines of the web container log, with secrets masked. Failure here is a one-line note: diagnostics never block the rollback."""
    try:
        ids = r.effects.docker.web_containers(r.settings.compose_project)
        if len(ids) != 1:
            r.err.write(f"container log unavailable: found {len(ids)} web containers\n")
            return
        text = r.effects.docker.logs(ids[0], LOG_TAIL_LINES)
    except EffectFailed as exc:
        note = " ".join(_mask(str(exc), r.secrets).split())
        r.err.write(f"container log unavailable: {note}\n")
        return
    lines = _mask(text, r.secrets).splitlines()[-LOG_TAIL_LINES:]
    r.err.write(f"web container log, last {len(lines)} lines:\n")
    for line in lines:
        r.err.write(line + "\n")


def _journal_efbundle_output(r: _Run, output: str) -> None:
    """The last lines of efbundle's output, masked like the container log. Without it a failed migration has no cause in the journal."""
    lines = _mask(output, r.secrets).splitlines()[-LOG_TAIL_LINES:]
    r.err.write(f"efbundle output, last {len(lines)} lines:\n")
    for line in lines:
        r.err.write(line + "\n")


def _secret_strings(values: list[str]) -> tuple[str, ...]:
    found = set()
    for value in values:
        found.add(value)
        found.update(part for part in _PASSWORD_PART.findall(value) if part)
    return tuple(sorted(found, key=len, reverse=True))


def _mask(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        text = text.replace(secret, "***")
    return text


# Step 2


def _materialize_release(r: _Run) -> None:
    releases = Path(r.settings.releases_dir)
    try:
        r.effects.files.ensure_dir(str(releases), 0o755)
    except OSError as exc:
        raise _Stop(DRIFT, "drift", f"cannot create the releases directory: {exc}") from exc
    final = releases / r.command.web_digest.split(":", 1)[1]
    staging = Path(tempfile.mkdtemp(prefix=".extract-", dir=releases))
    try:
        payload = staging / "payload"
        try:
            r.effects.docker.extract_release(r.web_ref, payload)
        except EffectFailed as exc:
            raise _Stop(DRIFT, "drift", f"release content could not be extracted: {exc}") from exc
        try:
            content = validate_tree(payload)
        except ReleaseRejected as exc:
            raise _Stop(BAD_INPUT, "rejected", f"release content rejected: {exc}") from exc
        _check_metadata_matches(payload, r.target)
        if r.settings.db_ca_bundle is not None and not content.ca_bundle_override:
            # Refused before the release is moved into place: a web container without the override would not reach RDS.
            raise _Stop(BAD_INPUT, "rejected", f"release has no {COMPOSE_CA_BUNDLE} but DB_CA_BUNDLE is configured")
        if os.path.lexists(final):
            # Releases are immutable: an existing directory for this digest must carry the same compose file.
            try:
                existing = compose_sha256_of(final)
            except (OSError, UnsafeFileError) as exc:
                raise _Stop(DRIFT, "drift", f"existing release directory is unreadable: {exc}") from exc
            if existing != content.compose_sha256:
                raise _Stop(DRIFT, "drift", "existing release directory has a different compose file")
        else:
            os.rename(payload, final)
            _fsync_directory(releases)
        r.release_dir = final
        r.compose_sha256 = content.compose_sha256
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _check_metadata_matches(payload: Path, target: mf.ReleaseMetadata) -> None:
    try:
        migrations = mf.read_manifest_file(payload / "migrations.txt")
        release_api = mf.read_release_api(payload / "RELEASE_API")
    except mf.ManifestError as exc:
        raise _Stop(BAD_INPUT, "rejected", f"release metadata rejected: {exc}") from exc
    if tuple(migrations) != tuple(target.migrations) or release_api != target.release_api:
        raise _Stop(BAD_INPUT, "rejected", "release content does not match the metadata read at plan time")


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# Step 3


def _read_secret(r: _Run, env_name: str, parameter: str) -> str:
    try:
        value = r.effects.ssm.get_parameter(parameter)
    except EffectFailed as exc:
        raise _Stop(DRIFT, "drift", f"reading {parameter} failed: {exc}") from exc
    # Values are never logged; only the variable name appears in the reason.
    if not value or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise _Stop(BAD_INPUT, "rejected", f"{env_name} must be a non-empty single-line value")
    return value


def _render_env(r: _Run, *, include_migration: bool = True) -> None:
    # Why the migration connection is read here, with the web secrets, even for a deploy that runs no migration: one
    # place reads and validates every SSM value, and a failing read is drift before anything is written.
    # Rollback passes include_migration=False: it only follows non-forward chains, which never run efbundle.
    sources = (
        ("ConnectionStrings__DefaultConnection", r.settings.ssm_db_connection),
        ("OPENAIAPI_KEY", r.settings.ssm_openai_key),
        ("Jwt__SigningKey", r.settings.ssm_jwt_key),
    )
    web = [(env_name, _read_secret(r, env_name, parameter)) for env_name, parameter in sources]
    migration = None
    if include_migration and r.settings.ssm_migration_connection is not None:
        migration = _read_secret(r, MIGRATION_ENV_NAME, r.settings.ssm_migration_connection)
    # Union, not replacement: secrets masked earlier in the run stay masked even when this call reads fewer of them.
    r.secrets = _secret_strings([*r.secrets, *(value for _, value in web), *([migration] if migration is not None else [])])
    r.env_path = os.path.join(r.settings.run_dir, f"web-{r.run_id}.env")
    try:
        r.effects.files.ensure_dir(r.settings.run_dir, 0o700)
        r.effects.files.write_atomic(r.env_path, "".join(f"{name}={value}\n" for name, value in web).encode("utf-8"), 0o600)
        if migration is not None:
            # A separate file: the migration connection never reaches the web container's environment.
            r.migrate_env_path = os.path.join(r.settings.run_dir, f"migrate-{r.run_id}.env")
            r.effects.files.write_atomic(r.migrate_env_path, f"{MIGRATION_ENV_NAME}={migration}\n".encode(), 0o600)
    except (EffectFailed, OSError) as exc:
        raise _Stop(DRIFT, "drift", f"writing the environment files failed: {exc}") from exc


def _discard_env(r: _Run) -> None:
    for path in (r.env_path, r.migrate_env_path):
        if path:
            r.effects.files.remove(path)


# Step 4


def _forward_migration(r: _Run) -> None:
    # 4a: exclusive, so no crawler (which takes the same lock shared) can run while the schema changes (N3).
    try:
        with locks.exclusive(r.settings.db_maintenance_lock, r.deps.maintenance_timeout_s, r.deps.clock):
            _migrate_locked(r)
    except locks.LockTimeout as exc:
        raise _Stop(DRIFT, "drift", f"db-maintenance lock stayed busy: {exc}") from exc


def _migrate_locked(r: _Run) -> None:
    # 4b: pause before the snapshot, so the crawler cannot start between the snapshot and the migration (N3).
    r.save(st.pause_crawler(r.state, release=r.tag, reason=f"forward migration to {r.tag}", now=r.deps.clock.now()))
    # 4c: a recovery point only; restoring it is an L4 manual action.
    snapshot_id = _snapshot_name(r.tag, r.deps.clock.now())
    try:
        r.effects.aws.create_snapshot(r.settings.rds_instance_id, snapshot_id)
        r.effects.aws.wait_snapshot_available(snapshot_id)
    except EffectFailed as exc:
        # Nothing has been migrated and the schema is not dirty, so resuming the crawler is safe here (documented choice).
        r.save(st.resume_crawler(r.state))
        raise _Stop(DRIFT, "drift", f"snapshot failed; nothing was migrated and the crawler was resumed: {exc}") from exc
    r.snapshot_id = snapshot_id
    # 4d: the dirty flag must be on disk before the migration container starts (I3).
    r.save(st.mark_dirty(r.state, release=r.tag, now=r.deps.clock.now()))
    # 4e: success requires both the exit code and the database ids.
    try:
        exit_code: int | None
        output: str
        exit_code, output = r.effects.docker.run_efbundle(r.web_ref, r.migrate_env_path or r.env_path)
    except EffectFailed:
        exit_code, output = None, ""
    applied = _applied_ids_or_none(r)
    if exit_code == 0 and applied == [m.id for m in r.target.migrations]:
        r.save(st.mark_migrated(r.state, r.tag, r.command.web_digest, r.target.migrations))
        return
    _journal_efbundle_output(r, output)
    # Dirty and paused stay set; only the human reconcile-schema and resume-crawler commands clear them (N2, N3: a person must verify the schema and the crawler first).
    raise _Stop(
        FAILED_MIGRATION,
        "failed-migration",
        f"efbundle exit {exit_code}; the database ids do not match the target; schema stays dirty, crawler stays paused",
    )


def _applied_ids_or_none(r: _Run) -> list[str] | None:
    try:
        return rt.observe_schema(r.deps.db_query)
    except (rt.ObservationError, cfg.ConfigError):
        return None


def _snapshot_name(tag: str, now: str) -> str:
    # RDS identifiers allow letters, digits and single hyphens, so dots and repeated hyphens are normalized.
    slug = re.sub(r"-+", "-", tag.lower().replace(".", "-")).strip("-")
    stamp = re.sub(r"\D", "", now)
    return f"book-finder-pre-{slug}-{stamp}"


# Step 5


def _compose_path(r: _Run) -> str:
    assert r.release_dir is not None  # step 2 always sets it before step 5
    return os.path.join(r.release_dir, COMPOSE_FILE)


def _compose_env(web_ref: str, env_path: str) -> dict[str, str]:
    # The compose file in the release reads these two variables; the env file itself is passed by path only.
    return {"WEB_IMAGE": web_ref, "WEB_ENV_FILE": env_path}


def _switch(r: _Run) -> str | None:
    runtime = r.state.runtime
    try:
        if isinstance(runtime, st.SystemdRuntime):
            # Cutover: the systemd service holds port 5000, so it must stop before compose can bind it.
            r.effects.systemd.stop(runtime.unit)
        r.effects.compose.up(_compose_path(r), r.settings.compose_project, _compose_env(r.web_ref, r.env_path))
    except EffectFailed as exc:
        return f"switch failed: {exc}"
    failure = _health(r)
    if failure is not None:
        # Before compose down or the rollback: the failed container, and its log, disappear once the rollback starts.
        _journal_health_failure(r, failure, rollback=False)
        _journal_container_log(r)
        return "health check failed after the switch"
    return None


# Step 7


def _web_failed(r: _Run, reason: str) -> None:
    if r.command.chain == "forward":
        # I5: after a migration there is no automatic rollback. The old release may not understand the new schema.
        raise _Stop(
            FAILED_DOWN,
            "failed-down",
            f"{reason}; the migration is applied (snapshot {r.snapshot_id}), so there is no automatic rollback (I5); "
            "the crawler stays paused; manual recovery required",
        )
    _rollback(r, reason)


def _rollback(r: _Run, reason: str) -> None:
    previous = r.state.runtime
    project = r.settings.compose_project
    try:
        if isinstance(previous, st.SystemdRuntime):
            try:
                r.effects.compose.down(_compose_path(r), project, _compose_env(r.web_ref, r.env_path))
            except EffectFailed:
                pass  # the start below and the health check decide the outcome
            r.effects.systemd.start(previous.unit)
        else:
            old_compose = os.path.join(previous.release_dir, COMPOSE_FILE)
            try:
                if compose_sha256_of(previous.release_dir) != previous.compose_sha256:
                    raise _Stop(FAILED_DOWN, "failed-down", "previous compose file does not match state; no rollback")
            except (OSError, UnsafeFileError) as exc:
                raise _Stop(FAILED_DOWN, "failed-down", f"previous release is unreadable; no rollback: {exc}") from exc
            if r.settings.db_ca_bundle is not None and not os.path.isfile(os.path.join(previous.release_dir, COMPOSE_CA_BUNDLE)):
                # The previous release predates the CA override, so starting it would leave web without the bundle (no RDS).
                raise _Stop(
                    FAILED_DOWN,
                    "failed-down",
                    f"{reason}; the previous release has no {COMPOSE_CA_BUNDLE} but DB_CA_BUNDLE is configured; rollback not possible",
                )
            try:
                _render_env(r, include_migration=False)
            except _Stop as stop:
                raise _Stop(FAILED_DOWN, "failed-down", f"rollback could not render its environment: {stop.reason}") from stop
            old_ref = f"{r.settings.web_image_repository}@{previous.web_digest}"
            r.effects.compose.up(old_compose, project, _compose_env(old_ref, r.env_path))
    except EffectFailed as exc:
        raise _Stop(FAILED_DOWN, "failed-down", f"rollback could not start the previous runtime: {exc}") from exc
    failure = _health(r)
    if failure is None:
        raise _Stop(ROLLED_BACK, "rolled-back", f"{reason}; restored the previous runtime")
    _journal_health_failure(r, failure, rollback=True)
    raise _Stop(FAILED_DOWN, "failed-down", f"{reason}; the previous runtime failed its health check; manual recovery required")


# Step 6


def _docker_runtime(r: _Run, crawler_digest: str) -> st.DockerRuntime:
    return st.DockerRuntime(
        tag=r.tag,
        release_api=r.target.release_api,
        web_digest=r.command.web_digest,
        crawler_digest=crawler_digest,
        compose_sha256=r.compose_sha256,
        release_dir=str(r.release_dir),
    )


def _finish_schema_ahead(r: _Run) -> int:
    """Web only: the crawler keeps its current digest and gets no pull, install or conf rewrite."""
    crawler_digest = r.state.crawler.digest
    r.save(st.promote_runtime(r.state, _docker_runtime(r, crawler_digest)))
    r.crawler_substeps = SCHEMA_AHEAD_SUBSTEPS
    return r.finish(OK, "success", f"web is on the target release; the crawler stays on {crawler_digest} (schema-ahead)")


def _finish_success_path(r: _Run) -> int:
    if r.command.chain == "schema-ahead":
        return _finish_schema_ahead(r)
    problem, substeps = _update_crawler(r)
    r.crawler_substeps = substeps
    crawler: st.Crawler | None = None
    if problem is None:
        try:
            crawler = _recorded_crawler(r, substeps)
        except (EffectFailed, OSError, UnsafeFileError) as exc:
            problem = f"provenance failed: {exc}"
    if crawler is not None:
        promoted = st.promote_runtime(r.state, _docker_runtime(r, r.command.crawler_digest))
        r.save(replace(promoted, crawler=crawler))
        return r.finish(OK, "success", "web and crawler are on the target release")
    # Partial: the crawler keeps the provenance it had, because half-installed files are not recorded as provenance.
    crawler_digest = r.state.crawler.digest
    promoted = st.promote_runtime(r.state, _docker_runtime(r, crawler_digest))
    # The web runtime is already serving the new release, so it is promoted; the crawler stays out of cron (N3).
    if r.command.chain != "forward":
        promoted = st.pause_crawler(promoted, release=r.tag, reason="crawler update failed", now=r.deps.clock.now())
    r.save(promoted)
    return r.finish(
        PARTIAL_CRAWLER,
        "partial-crawler",
        f"web is on the target release; crawler update failed ({problem}); crawler stays paused; resume-crawler (L4) is required",
    )


def _recorded_crawler(r: _Run, steps: dict[str, str]) -> st.Crawler:
    """The provenance of a fully successful crawler update.

    A file the release does not ship was not touched, so its hash stays as recorded. The hashes are read back from the
    installed files, not from the release, so the record describes what is on disk.
    """
    previous = r.state.crawler
    runner = _installed_sha256(r.settings.crawler_runner) if steps["run_crawler"] == "ok" else previous.runner_sha256
    cron = _installed_sha256(r.settings.cron_file) if steps["crawler_cron"] == "ok" else previous.cron_sha256
    return st.Crawler(
        digest=r.command.crawler_digest,
        runner_sha256=runner,
        cron_sha256=cron,
        source_release=st.SourceRelease(tag=r.tag, web_digest=r.command.web_digest),
        paused=None,
    )


def _installed_sha256(path: str) -> str:
    # The same bound the install used (MAX_RUNNER_BYTES); the config reader's 64 KiB cap would refuse a valid runner.
    return hashlib.sha256(read_regular_file(path, MAX_RUNNER_BYTES)).hexdigest()


def rewrite_crawler_image(data: bytes, reference: str) -> bytes:
    """Replaces the single CRAWLER_IMAGE= line; every other line stays byte-identical."""
    if not is_digest_ref(reference):
        raise ValueError("crawler reference must be pinned by digest")
    lines = data.decode("utf-8").split("\n")
    matches = [index for index, line in enumerate(lines) if line.startswith(CRAWLER_KEY)]
    if len(matches) != 1:
        raise ValueError("crawler.conf must contain exactly one CRAWLER_IMAGE= line")
    lines[matches[0]] = CRAWLER_KEY + reference
    return "\n".join(lines).encode("utf-8")


def _update_crawler(r: _Run) -> tuple[str | None, dict[str, str]]:
    """Runs the crawler sub-steps in their fixed order and returns (problem or None, outcome of every sub-step).

    Why this order: run-crawler.sh is the file that checks paused and dirty before a run, so it must be in place before
    cron can start a new crawler. crawler.conf names the image, so it is rewritten last, after the other two succeed.
    """
    steps = {name: "not-run" for name in CRAWLER_SUBSTEPS}
    release = r.release_dir
    assert release is not None  # step 2 always sets it
    problem = (
        _attempt(steps, "image", lambda: r.effects.docker.pull(r.crawler_ref))
        or _attempt(steps, "smoke", lambda: _smoke_or_raise(r))
        or _optional_install(r, steps, "run_crawler", release / "run-crawler.sh", r.settings.crawler_runner, 0o755)
        or _optional_install(r, steps, "crawler_cron", release / "crawler.cron", r.settings.cron_file, 0o644)
        or _attempt(steps, "crawler_conf", lambda: _rewrite_conf(r))
    )
    return problem, steps


def _attempt(steps: dict[str, str], name: str, action) -> str | None:
    try:
        action()
    except (EffectFailed, OSError, UnsafeFileError, ValueError) as exc:
        steps[name] = "failed"
        return f"{name} failed: {exc}"
    steps[name] = "ok"
    return None


def _smoke_or_raise(r: _Run) -> None:
    if r.effects.docker.smoke_crawler(r.crawler_ref) != 0:
        raise EffectFailed("crawler smoke test exited non-zero")


def _optional_install(r: _Run, steps: dict[str, str], name: str, source: Path, dest: str, mode: int) -> str | None:
    if not os.path.lexists(source):
        steps[name] = "skipped"  # the release does not ship this file
        return None
    return _attempt(steps, name, lambda: r.effects.files.write_atomic(dest, read_regular_file(source, MAX_RUNNER_BYTES), mode))


def _rewrite_conf(r: _Run) -> None:
    conf = r.settings.crawler_conf
    r.effects.files.write_atomic(conf, rewrite_crawler_image(r.effects.files.read_bytes(conf), r.crawler_ref), None)
