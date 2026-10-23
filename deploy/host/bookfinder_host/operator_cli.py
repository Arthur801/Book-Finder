"""Operator commands run by a person over their own SSH session as root (see deploy/README.md §5).

Why: these commands change the state that the forced-command path refuses to change (dirty, paused, the first
bootstrap, and resolution of an indeterminate run). Each one takes the deploy lock, writes through the same CAS as the
state machine, requires a non-empty reason, and needs the operator to type the value shown (or pass it again with
--yes-i-verified). None of them is reachable through SSH_ORIGINAL_COMMAND.

Protocol: every mutating command first validates and confirms, then appends operator-started (fsynced) with
op_id, intended and before; only then does it change anything, and it ends with exactly one operator-completed record.
An operator-started without a completed record is indeterminate: every operator command except resolve-run refuses
until resolve-run names that op_id.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TextIO

from bookfinder_host import commands as cmd
from bookfinder_host import config as cfg
from bookfinder_host import history as hi
from bookfinder_host import locks, release_content, runs
from bookfinder_host import manifest as mf
from bookfinder_host import runtime as rt
from bookfinder_host import state as st
from bookfinder_host.exit_codes import BAD_INPUT, DIRTY, DRIFT, INDETERMINATE, OK
from bookfinder_host.safefile import UnsafeFileError, read_regular_file

CRAWLER_FILE_MAX_BYTES = 1 << 20  # run-crawler.sh and crawler.cron are small text files; the same bound as the machine
MAX_REASON_CHARS = 400  # keeps an operator record well under the history line limit
MAX_ERROR_CHARS = 500  # keeps a failed operator-completed record under the history line limit
OPERATION_RESULTS = ("success", "failed")  # what resolve-run may record for an operator operation
OPERATOR_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
UNIT_RE = re.compile(r"[A-Za-z0-9@._-]{1,128}")
# Results an operator may record for an indeterminate run, with the exit code the run would have reported.
RESOLVE_EXIT = {
    "success": OK,
    "rolled-back": 1,
    "failed-migration": 4,
    "failed-down": 5,
    "partial-crawler": 7,
    "drift": DRIFT,
}
# The fixed link that the forced commands and sudoers use. It points at host-versions/<id> (install-host, N4: the swap is atomic, so the link resolves at every crash point).
# Not derived from __file__: the code runs through a resolved path, which is a version directory, not the link.
INSTALLED_HOST_DIR = Path("/opt/book-finder/host")
VERSIONS_DIRNAME = "host-versions"
VERSION_ID_RE = re.compile(r"[0-9a-f]{16}")
LINK_STAGING_PREFIX = "host.new-"
STAGING_PREFIX = ".stage-"
AT_FDCWD = -100
RENAME_EXCHANGE = 2


class UsageError(Exception):
    """The command line does not match the grammar."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # argparse would exit; the caller decides how to report it
        raise UsageError(message)


class Refusal(Exception):
    """The command must not change anything; the exit code says why."""

    def __init__(self, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


class OperationFailed(Exception):
    """A known failure inside an operation. unchanged=True means the failing step verifiably changed nothing."""

    def __init__(self, reason: str, *, unchanged: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        self.unchanged = unchanged


@dataclass
class Context:
    args: argparse.Namespace
    deps: cmd.Deps
    operator: str
    out: TextIO
    err: TextIO
    stdin: TextIO
    host_dir: Path


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="book-finder-admin", description="Operator commands for the Book Finder host.")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--reason", required=True, help="why this change is made; recorded in history")
        p.add_argument("--yes-i-verified", metavar="VALUE", help="the value shown by the command, for scripts")

    boot = sub.add_parser("bootstrap-state", help="create state for the first systemd host (N6)")
    boot.add_argument("--release", required=True)
    boot.add_argument("--web-digest", required=True)
    boot.add_argument("--crawler-digest", required=True)
    boot.add_argument("--systemd-unit", required=True)
    common(boot)

    recon = sub.add_parser("reconcile-schema", help="clear a dirty schema after manual verification (N2)")
    recon.add_argument("--mark-clean", action="store_true", required=True)
    recon.add_argument("--rebuild-release", required=True)
    recon.add_argument("--rebuild-web-digest", required=True)
    recon.add_argument("--expect-schema-digest", required=True)
    common(recon)

    resume = sub.add_parser("resume-crawler", help="resume a paused crawler after its update is verified (N3)")
    resume.add_argument("--crawler-digest", required=True)
    resume.add_argument("--adopt-release", help="after a partial crawler update: the release whose copies are installed")
    resume.add_argument("--adopt-web-digest", help="the web digest of --adopt-release; names its directory under RELEASES_DIR")
    common(resume)

    resolve = sub.add_parser("resolve-run", help="record the outcome of an indeterminate run (N7) or operator operation")
    resolve.add_argument("run_id", help="a run id, or an operator op_id (op-<yyyymmddHHMMSS>-<4 hex>)")
    # Run results and operation results share the flag; each command still checks which set it accepts.
    resolve.add_argument("--result", required=True, choices=sorted(set(RESOLVE_EXIT) | set(OPERATION_RESULTS)))
    common(resolve)

    install = sub.add_parser("install-host", help="install the host program from a checked-out tag (N4)")
    install.add_argument("--source", required=True, help="absolute path to deploy/host of the tag")
    common(install)
    return parser


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    return build_parser().parse_args(list(argv))


def main(
    argv: Sequence[str],
    environ: dict[str, str] | os._Environ[str],
    out: TextIO,
    err: TextIO,
    deps: cmd.Deps | None = None,
    *,
    stdin: TextIO | None = None,
    host_dir: Path | None = None,
) -> int:
    # The forced SSH command must never reach an operator command, even if the key is misused.
    if "SSH_ORIGINAL_COMMAND" in environ:
        err.write("refused: operator commands are not reachable through SSH_ORIGINAL_COMMAND\n")
        return BAD_INPUT
    try:
        args = parse_args(argv)
    except UsageError as exc:
        err.write(f"usage: {exc}\n")
        return BAD_INPUT
    except SystemExit as exc:  # --help
        return int(exc.code or 0)
    try:
        _check_reason(args.reason)
        operator = _operator_name(environ)
        if deps is None:
            # The root check guards the real host configuration; a redirected config is a test or local run only.
            if cmd.CONFIG_ENV not in environ and os.geteuid() != 0:
                raise Refusal(BAD_INPUT, "operator commands must run as root")
            deps = cmd.load_production_deps(cmd.config_path_from(environ))
        ctx = Context(
            args=args,
            deps=deps,
            operator=operator,
            out=out,
            err=err,
            stdin=sys.stdin if stdin is None else stdin,
            host_dir=INSTALLED_HOST_DIR if host_dir is None else host_dir,
        )
        return _under_lock(ctx)
    except Refusal as refusal:
        err.write(f"refused: {refusal.reason}\n")
        return refusal.code
    except OSError as exc:
        # Not "nothing changed": a failure after operator-started leaves that operation open, and history says so.
        err.write(
            f"refused: filesystem error: {exc}; an operation that had already started is shown in history as started "
            "without completed (indeterminate); inspect history.jsonl before retrying\n"
        )
        return DRIFT
    except cfg.ConfigError as exc:
        err.write(f"configuration error: {exc}\n")
        return BAD_INPUT


def _check_reason(reason: str) -> None:
    text = reason.strip()
    if not text:
        raise Refusal(BAD_INPUT, "--reason must not be empty")
    if len(text) > MAX_REASON_CHARS:
        raise Refusal(BAD_INPUT, f"--reason is longer than {MAX_REASON_CHARS} characters")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text):
        raise Refusal(BAD_INPUT, "--reason must be one line of printable text")


def _operator_name(environ) -> str:
    # sudo sets SUDO_USER to the person who ran the command; USER alone would name root.
    name = environ.get("SUDO_USER") or environ.get("USER") or ""
    if OPERATOR_RE.fullmatch(name) is None:
        raise Refusal(BAD_INPUT, "cannot determine the operator name (SUDO_USER or USER)")
    return name


def _under_lock(ctx: Context) -> int:
    settings = ctx.deps.settings
    try:
        with locks.exclusive(settings.deploy_lock_file, settings.lock_timeout_s, ctx.deps.clock):
            if ctx.args.command != "resolve-run":
                _refuse_while_indeterminate(ctx)
            return _HANDLERS[ctx.args.command](ctx)
    except locks.LockTimeout as exc:
        raise Refusal(DRIFT, f"busy: {exc}") from exc


def _refuse_while_indeterminate(ctx: Context) -> None:
    """Only resolve-run may run while an operator operation is open, or while the final history line is damaged.

    Why: an open operation may have changed state or the host, and appending after a damaged final line would make it
    a damaged middle line, which breaks every later read of history.
    """
    records = _read_history_or_refuse(ctx)
    if records.tail_corrupt:
        raise Refusal(DRIFT, "history final line is incomplete; resolve-run repairs it (with its sidecar) before anything else")
    opened = hi.open_operations(records)
    if opened:
        raise Refusal(
            INDETERMINATE,
            f"operator operation(s) {', '.join(opened)} started but have no completed record; "
            f"resolve-run {opened[0]} --result <success|failed> first (nothing was changed)",
        )


def _read_history_or_refuse(ctx: Context) -> hi.Records:
    try:
        return hi.read(ctx.deps.settings.history_file)
    except hi.HistoryCorrupt as exc:
        raise Refusal(DRIFT, f"history is damaged beyond its last line: {exc}") from exc


def _confirm(ctx: Context, expected: str, prompt: str) -> None:
    """The operator must type the value shown; --yes-i-verified repeats it for scripts. Nothing changes otherwise."""
    if ctx.args.yes_i_verified is not None:
        if ctx.args.yes_i_verified != expected:
            raise Refusal(BAD_INPUT, "--yes-i-verified does not match the value shown; nothing was changed")
        return
    ctx.err.write(f"{prompt}\nType {expected} to confirm: ")
    ctx.err.flush()
    typed = ctx.stdin.readline().strip()
    if typed != expected:
        raise Refusal(BAD_INPUT, "confirmation did not match; nothing was changed")


def _new_op_id(ctx: Context) -> str:
    stamp = re.sub(r"\D", "", ctx.deps.clock.now())[:14]  # ISO UTC "2026-10-23T00:00:00Z" -> "20261023000000"
    return f"op-{stamp}-{secrets.token_hex(2)}"


def _complete(ctx: Context, op_id: str, action: str, before, result: str, after, extra: dict | None) -> None:
    hi.append(
        ctx.deps.settings.history_file,
        hi.operator_completed_record(op_id=op_id, action=action, at=ctx.deps.clock.now(), result=result, before=before, after=after, extra=extra),
    )


def _verified_unchanged(check) -> bool:
    try:
        return bool(check())
    except Exception:  # noqa: BLE001 - a failed check cannot prove anything, so the outcome stays unknown
        return False


def _perform(
    ctx: Context,
    action: str,
    *,
    intended: dict,
    before,
    apply: Callable[[], tuple[object, object, dict]],
    verify_unchanged: Callable[[], bool],
    unchanged_note: str = "state unchanged (verified)",
    start_cut: int | None = None,
):
    """The operator protocol: operator-started is durable before apply() changes anything.

    apply() returns (after_summary, value, extra). operator-completed is written only for a success, or for a failure
    that verifiably changed nothing (unchanged is True). Every other failure, including an exception that leaves the
    host or state in an unknown position, writes no completed record: the op stays indeterminate until resolve-run.
    start_cut, when given, means the started record replaces a damaged history tail (see rewrite_with_record).
    """
    deps = ctx.deps
    op_id = _new_op_id(ctx)
    started = hi.operator_started_record(
        op_id=op_id,
        action=action,
        at=deps.clock.now(),
        operator=ctx.operator,
        reason=ctx.args.reason.strip(),
        intended=intended,
        before=before,
    )
    try:
        if start_cut is None:
            hi.append(deps.settings.history_file, started)
        else:
            hi.rewrite_with_record(deps.settings.history_file, start_cut, started)
    except (OSError, ValueError, hi.HistoryCorrupt) as exc:
        raise Refusal(DRIFT, f"could not record the start of {action} ({exc}); nothing was changed") from exc
    try:
        after, value, extra = apply()
    except OperationFailed as failure:
        message, unchanged = failure.reason, failure.unchanged
    except Exception as exc:  # noqa: BLE001 - known enough to report; the verification decides what is claimed
        message, unchanged = f"{action} failed: {exc}", _verified_unchanged(verify_unchanged)
    else:
        try:
            _complete(ctx, op_id, action, before, "success", after, extra)
        except OSError as exc:
            raise Refusal(
                DRIFT,
                f"{action} was applied, but its completion record could not be written ({exc}); the outcome is recorded as "
                f"unknown and op {op_id} stays indeterminate; inspect state and history before doing anything else",
            ) from exc
        return value
    if not unchanged:
        # Only a verified "nothing changed" may be terminalised. Anything else keeps the op open, so plan, deploy and
        # the other operator commands refuse (exit 8) until an operator resolves it.
        raise Refusal(
            DRIFT,
            f"{message}; the outcome is unknown and nothing was recorded as failed. Operator operation "
            f"{op_id} stays open; inspect state, history and the host, then run resolve-run {op_id} --result <success|failed> "
            "--reason ... (it is required before anything else runs)",
        )
    full = f"{message}; {unchanged_note}"
    try:
        _complete(ctx, op_id, action, before, "failed", None, {"error": full[:MAX_ERROR_CHARS]})
    except OSError as exc:
        raise Refusal(DRIFT, f"{full}; the failure could not be recorded in op {op_id} ({exc}); op {op_id} stays indeterminate") from exc
    raise Refusal(DRIFT, full)


def _report(ctx: Context, action: str, **fields) -> int:
    ctx.out.write(json.dumps({"action": action, "result": "done", **fields}, sort_keys=True) + "\n")
    return OK


def _state_revision_on_disk(ctx: Context) -> int | None:
    try:
        return st.load_state(ctx.deps.settings.state_file).revision
    except st.StateMissing:
        return 0
    except st.StateCorrupt:
        return None


def _load_state_or_refuse(ctx: Context) -> st.State:
    try:
        return st.load_state(ctx.deps.settings.state_file)
    except st.StateMissing as exc:
        raise Refusal(DRIFT, "state is missing; bootstrap-state is the only command that creates it") from exc
    except st.StateCorrupt as exc:
        raise Refusal(DRIFT, f"state is unreadable: {exc}") from exc


def _release_metadata(ctx: Context, digest: str) -> mf.ReleaseMetadata:
    reference = f"{ctx.deps.settings.web_image_repository}@{digest}"
    try:
        with tempfile.TemporaryDirectory(prefix="bookfinder-operator-") as scratch:
            return mf.extract_release_metadata(ctx.deps.runner, reference, Path(scratch))
    except mf.ManifestError as exc:
        raise Refusal(BAD_INPUT, f"release metadata rejected: {exc}") from exc


def _check_digest(value: str, what: str) -> str:
    if cmd.DIGEST_RE.fullmatch(value) is None:
        raise Refusal(BAD_INPUT, f"{what} must be sha256:<64 hex>")
    return value


def _check_tag(value: str) -> str:
    if cmd.TAG_RE.fullmatch(value) is None:
        raise Refusal(BAD_INPUT, "release tag is malformed")
    return value


# bootstrap-state (N6: an operator creates the first state; CD never does)


def _bootstrap(ctx: Context) -> int:
    args, deps = ctx.args, ctx.deps
    tag = _check_tag(args.release)
    web_digest = _check_digest(args.web_digest, "web digest")
    crawler_digest = _check_digest(args.crawler_digest, "crawler digest")
    if UNIT_RE.fullmatch(args.systemd_unit) is None:
        raise Refusal(BAD_INPUT, "systemd unit name is malformed")
    try:
        st.load_state(deps.settings.state_file)
    except st.StateMissing:
        pass
    except st.StateCorrupt as exc:
        raise Refusal(DRIFT, f"state already exists and is unreadable: {exc}") from exc
    else:
        raise Refusal(DRIFT, "state already exists; bootstrap-state runs only once per host")
    try:
        active = rt.observe_systemd(deps.runner, args.systemd_unit)
    except rt.ObservationError as exc:
        raise Refusal(DRIFT, f"cannot read the systemd unit: {exc}") from exc
    if not active.running:
        raise Refusal(DRIFT, f"systemd unit {args.systemd_unit} is not active")
    metadata = _release_metadata(ctx, web_digest)
    if not deps.host_api_range[0] <= metadata.release_api <= deps.host_api_range[1]:
        raise Refusal(BAD_INPUT, f"release_api {metadata.release_api} is outside the host range")
    try:
        database_ids = rt.observe_schema(deps.db_query)
    except (rt.ObservationError, cfg.ConfigError) as exc:
        raise Refusal(DRIFT, f"cannot read the migration history: {exc}") from exc
    manifest_ids = [m.id for m in metadata.migrations]
    if database_ids != manifest_ids:
        raise Refusal(
            DRIFT,
            f"database migrations ({len(database_ids)}) are not exactly the release manifest ({len(manifest_ids)}); bootstrap needs an in-sync database",
        )
    runner_bytes, cron_bytes = _read_crawler_files(deps.settings, "bootstrap-state needs both crawler files installed")
    # The state records the crawler digest, so the installed crawler.conf must pin that same digest (N6).
    expected_image = f"{deps.settings.crawler_image_repository}@{crawler_digest}"
    found_image = _crawler_image_line(_read_crawler_conf(deps.settings))
    if found_image != expected_image:
        raise Refusal(
            DRIFT,
            f"crawler.conf has CRAWLER_IMAGE={found_image} but --crawler-digest {crawler_digest} requires CRAWLER_IMAGE={expected_image}; fix crawler.conf or the digest",
        )
    ctx.err.write(
        "trust assumption: the existing database was created by exactly the migration sources of "
        f"{tag} (ids match the manifest; hashes are taken from the manifest)\n"
    )
    _confirm(ctx, web_digest, f"bootstrap state for {tag} with web {web_digest}")
    new_state = st.State(
        revision=0,
        runtime=st.SystemdRuntime(unit=args.systemd_unit, version="pre-cd"),
        previous_runtime=None,
        schema=st.Schema(
            digest=st.schema_digest(list(metadata.migrations)),
            applied=tuple(st.AppliedMigration(m.id, m.source_hash, tag) for m in metadata.migrations),
            rebuild=st.Rebuild(tag=tag, web_digest=web_digest),
            dirty=False,
            dirty_since=None,
            dirty_release=None,
        ),
        crawler=st.Crawler(
            digest=crawler_digest,
            runner_sha256=_sha256_hex(runner_bytes),
            cron_sha256=_sha256_hex(cron_bytes),
            source_release=None,
            paused=None,
        ),
    )
    intended = {
        "release": tag,
        "web_digest": web_digest,
        "crawler_digest": crawler_digest,
        "runtime": {"kind": "systemd", "unit": args.systemd_unit},
        "schema_digest": new_state.schema.digest,
        "applied_count": len(metadata.migrations),
    }

    def apply():
        try:
            stored = _write_cas(deps, new_state, expected_revision=0)
        except OperationFailed as failure:
            raise OperationFailed(f"state appeared while bootstrapping: {failure.reason}", unchanged=True) from failure
        return st.state_summary(stored), stored, {}

    stored = _perform(ctx, "bootstrap-state", intended=intended, before=None, apply=apply, verify_unchanged=lambda: _state_revision_on_disk(ctx) == 0)
    return _report(ctx, "bootstrap-state", revision=stored.revision, release=tag)


# reconcile-schema (N2: only a person who verified the database may clear the dirty flag)


def _reconcile(ctx: Context) -> int:
    args, deps = ctx.args, ctx.deps
    state = _load_state_or_refuse(ctx)
    if not state.schema.dirty:
        raise Refusal(DRIFT, "schema is not dirty; reconcile-schema only clears a dirty schema")
    rebuild_tag = _check_tag(args.rebuild_release)
    rebuild_digest = _check_digest(args.rebuild_web_digest, "rebuild web digest")
    try:
        database_ids = rt.observe_schema(deps.db_query)
    except (rt.ObservationError, cfg.ConfigError) as exc:
        raise Refusal(DRIFT, f"cannot read the migration history: {exc}") from exc
    metadata = _release_metadata(ctx, rebuild_digest)
    manifest = list(metadata.migrations)
    if len(database_ids) > len(manifest) or database_ids != [m.id for m in manifest[: len(database_ids)]]:
        raise Refusal(BAD_INPUT, "divergent: database migrations are not a prefix of the rebuild release manifest")
    recorded = [(entry.id, entry.source_hash) for entry in state.schema.applied]
    if recorded != [(m.id, m.source_hash) for m in manifest[: len(recorded)]] or len(recorded) > len(database_ids):
        raise Refusal(BAD_INPUT, "divergent: recorded migrations do not match the rebuild release manifest")
    prefix = manifest[: len(database_ids)]
    digest = st.schema_digest(prefix)
    ctx.err.write(f"database migrations ({len(database_ids)}):\n")
    for migration_id in database_ids:
        ctx.err.write(f"  {migration_id}\n")
    ctx.err.write(f"schema digest of that prefix: {digest}\n")
    if args.expect_schema_digest != digest:
        raise Refusal(BAD_INPUT, "--expect-schema-digest does not match the digest of the database migrations; nothing was changed")
    _confirm(ctx, digest, "mark the schema clean; the database itself is not modified")
    by_release = state.schema.dirty_release or rebuild_tag
    applied = tuple(
        state.schema.applied[index] if index < len(state.schema.applied) else st.AppliedMigration(m.id, m.source_hash, by_release) for index, m in enumerate(prefix)
    )
    new_schema = st.Schema(
        digest=digest,
        applied=applied,
        rebuild=st.Rebuild(tag=rebuild_tag, web_digest=rebuild_digest),
        dirty=False,
        dirty_since=None,
        dirty_release=None,
    )
    new_state = replace(state, schema=new_schema)
    intended = {"schema_digest": digest, "applied_count": len(prefix), "dirty": False, "rebuild": {"tag": rebuild_tag, "web_digest": rebuild_digest}}

    def apply():
        stored = _write_cas(deps, new_state, expected_revision=state.revision)
        return st.state_summary(stored), stored, {}

    stored = _perform(
        ctx,
        "reconcile-schema",
        intended=intended,
        before=st.state_summary(state),
        apply=apply,
        verify_unchanged=lambda: _state_revision_on_disk(ctx) == state.revision,
    )
    return _report(ctx, "reconcile-schema", revision=stored.revision, schema_digest=digest)


def _write_cas(deps: cmd.Deps, new_state: st.State, expected_revision: int) -> st.State:
    try:
        return st.write_state(deps.settings.state_file, new_state, expected_revision=expected_revision)
    except st.RevisionConflict as exc:
        # write_state checks the revision before it writes, so this write verifiably did not happen.
        raise OperationFailed(f"state changed while the command ran: {exc}", unchanged=True) from exc


# resume-crawler (N3: a person verifies the crawler update before cron may run it again)


def _crawler_image_line(text: str) -> str:
    lines = [line for line in text.split("\n") if line.startswith("CRAWLER_IMAGE=")]
    if len(lines) != 1:
        raise Refusal(DRIFT, "crawler.conf must contain exactly one CRAWLER_IMAGE= line")
    return lines[0][len("CRAWLER_IMAGE=") :]


def _read_crawler_conf(settings: cfg.Settings) -> str:
    try:
        return read_regular_file(settings.crawler_conf, 65536).decode("utf-8")
    except (OSError, UnsafeFileError) as exc:
        raise Refusal(DRIFT, f"crawler.conf cannot be read: {exc}") from exc


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_crawler_files(settings: cfg.Settings, hint: str) -> tuple[bytes, bytes]:
    """The installed run-crawler.sh and crawler.cron, as bytes; the crawler provenance is computed from these."""
    try:
        return (
            read_regular_file(settings.crawler_runner, CRAWLER_FILE_MAX_BYTES),
            read_regular_file(settings.cron_file, CRAWLER_FILE_MAX_BYTES),
        )
    except (OSError, UnsafeFileError) as exc:
        raise Refusal(DRIFT, f"crawler files cannot be read ({hint}): {exc}") from exc


def _adopt_release_files(ctx: Context, adopt_tag: str, adopt_web: str) -> tuple[bytes, bytes]:
    """The release that a partial update is adopted from: complete, valid, and its crawler copies.

    The release directory is named by the web digest, as the unit body names it (RELEASES_DIR/<hex>). Its tag cannot be
    checked here (the directory does not carry it), so the operator's --adopt-release is recorded as asserted.
    """
    release = Path(ctx.deps.settings.releases_dir) / adopt_web.split(":", 1)[1]
    if os.path.islink(release) or not release.is_dir():
        raise Refusal(DRIFT, f"release directory {release} for {adopt_tag} is missing")
    try:
        release_content.validate_tree(release)
    except release_content.ReleaseRejected as exc:
        raise Refusal(DRIFT, f"release directory {release} is rejected: {exc}") from exc
    try:
        return (
            read_regular_file(release / "run-crawler.sh", CRAWLER_FILE_MAX_BYTES),
            read_regular_file(release / "crawler.cron", CRAWLER_FILE_MAX_BYTES),
        )
    except (OSError, UnsafeFileError) as exc:
        raise Refusal(DRIFT, f"release {adopt_tag} does not ship both crawler files: {exc}") from exc


def _resume(ctx: Context) -> int:
    args, deps = ctx.args, ctx.deps
    state = _load_state_or_refuse(ctx)
    if state.crawler.paused is None:
        raise Refusal(DRIFT, "crawler is not paused")
    if state.schema.dirty:
        raise Refusal(DIRTY, "schema is dirty; reconcile-schema must run before the crawler resumes")
    digest = _check_digest(args.crawler_digest, "crawler digest")
    adopting = args.adopt_release is not None or args.adopt_web_digest is not None
    if adopting and (args.adopt_release is None or args.adopt_web_digest is None):
        raise Refusal(BAD_INPUT, "--adopt-release and --adopt-web-digest must be given together")
    if not adopting and digest != state.crawler.digest:
        raise Refusal(
            DRIFT,
            f"state records crawler {state.crawler.digest}; --crawler-digest must be that digest (a different crawler needs --adopt-release and --adopt-web-digest)",
        )
    expected_image = f"{deps.settings.crawler_image_repository}@{digest}"
    if _crawler_image_line(_read_crawler_conf(deps.settings)) != expected_image:
        raise Refusal(DRIFT, f"fix CRAWLER_IMAGE in {deps.settings.crawler_conf} to {expected_image} first")
    installed_runner, installed_cron = _read_crawler_files(deps.settings, "run-crawler.sh and crawler.cron must be installed")
    if adopting:
        adopt_tag = _check_tag(args.adopt_release)
        adopt_web = _check_digest(args.adopt_web_digest, "adopt web digest")
        shipped_runner, shipped_cron = _adopt_release_files(ctx, adopt_tag, adopt_web)
        differing = [
            name for name, have, want in (("run-crawler.sh", installed_runner, shipped_runner), ("crawler.cron", installed_cron, shipped_cron)) if have != want
        ]
        if differing:
            raise Refusal(DRIFT, f"installed {', '.join(differing)} differs from release {adopt_tag}; install that release's copies first")
        new_crawler = st.Crawler(
            digest=digest,
            runner_sha256=_sha256_hex(shipped_runner),
            cron_sha256=_sha256_hex(shipped_cron),
            source_release=st.SourceRelease(tag=adopt_tag, web_digest=adopt_web),
            paused=None,
        )
        intended = {"crawler_digest": digest, "paused": False, "adopted_release": adopt_tag, "adopted_web_digest": adopt_web}
    else:
        if _sha256_hex(installed_runner) != state.crawler.runner_sha256:
            raise Refusal(DRIFT, f"installed {deps.settings.crawler_runner} differs from the crawler recorded in state; see --adopt-release")
        if _sha256_hex(installed_cron) != state.crawler.cron_sha256:
            raise Refusal(DRIFT, f"installed {deps.settings.cron_file} differs from the crawler recorded in state; see --adopt-release")
        new_crawler = replace(state.crawler, paused=None)
        intended = {"crawler_digest": digest, "paused": False}
    _confirm(ctx, digest, f"resume the crawler on {expected_image}")
    new_state = replace(state, crawler=new_crawler)

    def apply():
        stored = _write_cas(deps, new_state, expected_revision=state.revision)
        return st.state_summary(stored), stored, {}

    stored = _perform(
        ctx,
        "resume-crawler",
        intended=intended,
        before=st.state_summary(state),
        apply=apply,
        verify_unchanged=lambda: _state_revision_on_disk(ctx) == state.revision,
    )
    return _report(ctx, "resume-crawler", revision=stored.revision)


# resolve-run (N7: records the end of a run whose outcome could not be observed)


def _run_has_completed(path: str, run_id: str) -> bool:
    return any(entry.get("run_id") == run_id and entry.get("phase") == "completed" for entry in hi.read(path).entries)


def _resolve(ctx: Context) -> int:
    if ctx.args.run_id.startswith(hi.OP_PREFIX):
        return _resolve_operation(ctx)
    return _resolve_run(ctx)


def _resolve_run(ctx: Context) -> int:
    args, deps = ctx.args, ctx.deps
    run_id = args.run_id
    if cmd.RUN_ID_RE.fullmatch(run_id) is None:
        raise Refusal(BAD_INPUT, "run id is malformed")
    if args.result not in RESOLVE_EXIT:
        raise Refusal(BAD_INPUT, f"a run can be recorded as {', '.join(sorted(RESOLVE_EXIT))}")
    records = _read_history_or_refuse(ctx)
    if any(e.get("run_id") == run_id and e.get("phase") == "completed" for e in records.entries):
        raise Refusal(DRIFT, f"run {run_id} already has a completed record")
    if not any(e.get("run_id") == run_id and e.get("phase") == "started" for e in records.entries):
        raise Refusal(DRIFT, f"run {run_id} never started; there is nothing to resolve")
    try:
        unit_state = runs.unit_state(deps.runner, runs.unit_name(run_id))
    except rt.ObservationError as exc:
        raise Refusal(DRIFT, f"cannot read the unit: {exc}") from exc
    if unit_state in hi.ACTIVE_STATES:
        raise Refusal(DRIFT, f"run {run_id} is still active; it is not indeterminate")
    if records.tail_corrupt:
        data = read_regular_file(deps.settings.history_file, hi.MAX_HISTORY_BYTES)
        if data.endswith(b"\n"):
            raise Refusal(DRIFT, "the last history line is damaged but complete; inspect history.jsonl by hand")
    state_summary = {}
    try:
        state_summary = st.state_summary(st.load_state(deps.settings.state_file))
    except (st.StateMissing, st.StateCorrupt):
        pass
    _confirm(ctx, run_id, f"record run {run_id} as {args.result}")
    tail = None
    if records.tail_corrupt:
        # The fragment is kept in a sidecar before history is touched; a failure here leaves history as it was.
        stamp = re.sub(r"[-:]", "", deps.clock.now())
        tail = hi.preserve_tail(deps.settings.history_file, run_id, stamp)
    result = args.result
    record = hi.completed_record(
        run_id=run_id,
        result=result,
        exit_code=RESOLVE_EXIT[result],
        at=deps.clock.now(),
        state_summary=state_summary,
        resolved_by_operator=True,
        operator=ctx.operator,
        reason=args.reason.strip(),
    )
    path = deps.settings.history_file

    def apply():
        hi.append(path, record)
        extra = {"tail_repair": _tail_summary(tail)} if tail is not None else {}
        return {"run_id": run_id, "result": result}, {"run_id": run_id, "result": result}, extra

    intended = {"run_id": run_id, "result": result, "tail_repair": _tail_summary(tail)}
    _perform(
        ctx,
        "resolve-run",
        intended=intended,
        before={"run": "started without completed", "state": state_summary or None},
        apply=apply,
        verify_unchanged=lambda: not _run_has_completed(path, run_id),
        unchanged_note="history unchanged (verified)",
        start_cut=None if tail is None else tail["cut"],
    )
    if state_summary.get("dirty"):
        ctx.err.write("reminder: the schema is still dirty; use reconcile-schema (N2)\n")
    if state_summary.get("crawler_paused"):
        ctx.err.write("reminder: the crawler is still paused; use resume-crawler (N3)\n")
    removed = 0 if tail is None else tail["bytes"]
    return _report(ctx, "resolve-run", run_id=run_id, result=result, truncated_tail_bytes=removed)


def _tail_summary(tail: dict | None) -> dict | None:
    if tail is None:
        return None
    return {"path": tail["path"], "bytes": tail["bytes"], "sha256": tail["sha256"]}


def _resolve_operation(ctx: Context) -> int:
    """Records the outcome of an open operator operation.

    Single append, no operator-started: the only change is the completed record itself, so a crash leaves either the op
    open (nothing recorded) or closed. A damaged tail is repaired in the same atomic rewrite, after its sidecar is kept.
    """
    args, deps = ctx.args, ctx.deps
    op_id = args.run_id
    if hi.OP_ID_RE.fullmatch(op_id) is None:
        raise Refusal(BAD_INPUT, "operation id is malformed")
    if args.result not in OPERATION_RESULTS:
        raise Refusal(BAD_INPUT, f"an operator operation can only be recorded as {' or '.join(OPERATION_RESULTS)}")
    records = _read_history_or_refuse(ctx)
    if op_id not in hi.open_operations(records):
        raise Refusal(DRIFT, f"operation {op_id} is not open; it has no operator-started record without a completed record")
    started = next(e for e in records.entries if e.get("phase") == hi.OPERATOR_STARTED and e.get("op_id") == op_id)
    _confirm(ctx, op_id, f"record operation {op_id} ({started.get('action')}) as {args.result}")
    completed = hi.operator_completed_record(
        op_id=op_id,
        action=started.get("action"),
        at=deps.clock.now(),
        result=args.result,
        before=started.get("before"),
        after={"resolved": args.result},
        extra={"resolved_by_operator": True, "operator": ctx.operator, "reason": args.reason.strip()},
    )
    path = deps.settings.history_file
    tail = None
    if records.tail_corrupt:
        stamp = re.sub(r"[-:]", "", deps.clock.now())
        tail = hi.preserve_tail(path, op_id, stamp)
        completed["tail_repair"] = _tail_summary(tail)
        hi.rewrite_with_record(path, tail["cut"], completed)
    else:
        hi.append(path, completed)
    return _report(ctx, "resolve-run", run_id=op_id, result=args.result, truncated_tail_bytes=0 if tail is None else tail["bytes"])


# install-host (N4: the host program is swapped in one step)


def _install(ctx: Context) -> int:
    args, deps = ctx.args, ctx.deps
    source = Path(args.source)
    if not source.is_absolute():
        raise Refusal(BAD_INPUT, "--source must be an absolute path")
    for name in ("bookfinder_host", "deploy-entry", "book-finder-admin"):
        path = source / name
        if os.path.islink(path) or not os.path.exists(path):
            raise Refusal(BAD_INPUT, f"source is missing {name} (or it is a symlink)")
    try:
        new_low, new_high = cfg.read_host_api_range(source / "bookfinder_host" / "HOST_API_RANGE")
    except cfg.ConfigError as exc:
        raise Refusal(BAD_INPUT, str(exc)) from exc
    # Read through the link, so this is the range of the tree that is currently pointed to.
    current_path = ctx.host_dir / "bookfinder_host" / "HOST_API_RANGE"
    try:
        old_low, old_high = cfg.read_host_api_range(current_path)
        old_text = f"{old_low}-{old_high}"
    except cfg.ConfigError:
        old_text = "none"
    try:
        state = st.load_state(deps.settings.state_file)
    except st.StateMissing:
        state = None
    except st.StateCorrupt as exc:
        raise Refusal(DRIFT, f"state is unreadable: {exc}") from exc
    if state is not None:
        for label, runtime in (("runtime", state.runtime), ("previous_runtime", state.previous_runtime)):
            if isinstance(runtime, st.DockerRuntime) and not new_low <= runtime.release_api <= new_high:
                raise Refusal(
                    BAD_INPUT,
                    f"{label} {runtime.tag} needs release_api {runtime.release_api}, outside the new range {new_low}-{new_high}",
                )
    new_text = f"{new_low}-{new_high}"
    ctx.err.write(f"host_api_range: old={old_text} new={new_text}\n")
    _preflight_install(ctx.host_dir)
    _confirm(ctx, new_text, f"install the host program into {ctx.host_dir}")
    before_pointer = _pointer(ctx.host_dir)

    def apply():
        result = _swap_install(source, ctx.host_dir)
        return {"host_api_range": new_text, "version": result["version"], "previous": result["previous"]}, result, {}

    result = _perform(
        ctx,
        "install-host",
        intended={"host_api_range": new_text, "source": str(source)},
        before={"host_api_range": old_text, "version": _version_of(before_pointer)},
        apply=apply,
        verify_unchanged=lambda: _pointer(ctx.host_dir) == before_pointer,
        unchanged_note="host unchanged (verified)",
    )
    return _report(ctx, "install-host", host_api_range=new_text, version=result["version"], previous=result["previous"])


# install-host swap (N4)
#
# Layout: <root>/host is a symlink to <root>/host-versions/<id>, where <id> is the first 16 hex digits of a hash over the
# installed tree. Every version directory is complete before it gets a name, and the link is replaced with one rename(2),
# so at every crash point <root>/host/deploy-entry resolves to a complete tree: the old one or the new one.
#
# The one case that started as a directory is the first install on a host with the old layout. The new link is made
# beside it, then RENAME_EXCHANGE swaps the directory and the link in a single step, then the directory (now at the link's
# temporary name) moves into host-versions. A crash after the exchange and before that move leaves the old tree under
# <root>/host.new-<token>; the next install refuses and names it, because it is complete but must be moved by hand.


def _no_checkpoint(name: str) -> None:
    """Fault-injection hook for the tests: called after every swap step with the step's name."""


def _fsync_dir(directory: Path | str) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _tree_id(root: Path) -> str:
    """First 16 hex digits of a hash over every directory and file (path, mode, length, bytes) under root, in sorted order."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise OSError(f"{path} is a symlink; installed trees contain only regular files and directories")
        if path.is_dir():
            digest.update(f"d {relative}\n".encode())
            continue
        data = path.read_bytes()
        digest.update(f"f {relative} {stat.S_IMODE(path.stat().st_mode):o} {len(data)}\n".encode())
        digest.update(data)
    return digest.hexdigest()[:16]


def _copy_payload(source: Path, payload: Path) -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(source / "bookfinder_host", payload / "bookfinder_host", ignore=ignore)
    for name in ("deploy-entry", "book-finder-admin"):
        shutil.copy2(source / name, payload / name)
        os.chmod(payload / name, 0o755)


def _fsync_tree(root: Path) -> None:
    directories = [root, *(path for path in root.rglob("*") if path.is_dir())]
    for path in root.rglob("*"):
        if path.is_file():
            _fsync_file(path)
    for directory in directories:
        _fsync_dir(directory)


def _pointer(host: Path) -> tuple[str, str | None]:
    """What <root>/host is right now: a link and its target, a plain (legacy) directory, something else, or missing."""
    if os.path.islink(host):
        return ("link", os.readlink(host))
    if host.is_dir():
        return ("dir", None)
    if os.path.lexists(host):
        return ("other", None)
    return ("missing", None)


def _version_of(pointer: tuple[str, str | None]) -> str | None:
    kind, target = pointer
    return os.path.basename(target) if kind == "link" and target else None


def _leftover_link_directories(root: Path) -> list[Path]:
    return [path for path in root.iterdir() if path.name.startswith(LINK_STAGING_PREFIX) and path.is_dir() and not path.is_symlink()]


def _preflight_install(host: Path) -> None:
    leftovers = _leftover_link_directories(host.parent)
    if leftovers:
        raise Refusal(
            DRIFT,
            f"{leftovers[0]} is left over from an interrupted legacy migration and is a complete host tree; "
            f"move it into {host.parent / VERSIONS_DIRNAME} by hand (rename) and rerun install-host",
        )


def _exchange(first: Path, second: Path) -> None:
    """renameat2(RENAME_EXCHANGE): swaps two paths in one step. Refuses the call rather than falling back to two renames."""
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise OSError(errno.ENOSYS, "renameat2 is not available in this C library")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if renameat2(AT_FDCWD, os.fsencode(first), AT_FDCWD, os.fsencode(second), RENAME_EXCHANGE) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), f"{first} <-> {second}")


def _swap_install(source: Path, host: Path, *, checkpoint=_no_checkpoint) -> dict[str, str | None]:
    """Installs the source tree as the version that <host> points to; returns {"version", "previous"}.

    Steps, each one checkpoint: staged, version-installed, then either link-created and pointer-swapped (normal), or
    legacy-link-created, legacy-exchanged and legacy-moved (first install over a plain directory), then root-synced,
    then pruning, which only removes versions that are neither current nor previous.
    """
    root = host.parent
    versions = root / VERSIONS_DIRNAME
    _preflight_install(host)
    versions.mkdir(mode=0o755, exist_ok=True)
    for stale in versions.iterdir():
        if stale.name.startswith(STAGING_PREFIX):
            shutil.rmtree(stale, ignore_errors=True)  # a staging copy from an interrupted install; nothing points at it
    for stale in root.iterdir():
        if stale.name.startswith(LINK_STAGING_PREFIX) and stale.is_symlink():
            os.unlink(stale)
    staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=versions))
    try:
        payload = staging / "tree"
        payload.mkdir()
        _copy_payload(source, payload)
        _fsync_tree(payload)
        checkpoint("staged")
        version = _tree_id(payload)
        final = versions / version
        if os.path.lexists(final):
            if _tree_id(final) != version:
                raise OSError(f"{final} exists with different content; refusing to overwrite a version")
        else:
            os.rename(payload, final)
            _fsync_dir(versions)
        checkpoint("version-installed")
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    kind, target = _pointer(host)
    if kind == "link" and target is not None and Path(target) == final:
        # Identical content is already current: nothing is swapped and no previous version is recorded or pruned.
        checkpoint("root-synced")
        return {"version": version, "previous": None}
    previous: str | None = None
    token = secrets.token_hex(4)
    if kind == "dir":
        legacy = f"legacy-{time.strftime('%Y%m%d%H%M%S', time.gmtime())}"
        if os.path.lexists(versions / legacy):
            legacy = f"{legacy}-{token}"
        previous = legacy
        temporary = root / f"{LINK_STAGING_PREFIX}{token}"
        os.symlink(final, temporary)
        checkpoint("legacy-link-created")
        try:
            _exchange(temporary, host)
        except OSError as exc:
            os.unlink(temporary)
            raise OSError(exc.errno, f"the legacy host directory cannot be exchanged atomically here ({exc.strerror}); nothing was changed") from exc
        checkpoint("legacy-exchanged")
        os.rename(temporary, versions / legacy)
        _fsync_dir(versions)
        checkpoint("legacy-moved")
    else:
        if kind == "link" and target:
            previous = os.path.basename(target)
        temporary = root / f"{LINK_STAGING_PREFIX}{token}"
        os.symlink(final, temporary)
        checkpoint("link-created")
        os.replace(temporary, host)  # rename(2) over the old link: one atomic step
        checkpoint("pointer-swapped")
    _fsync_dir(root)
    checkpoint("root-synced")
    _prune(versions, keep={version, previous})
    return {"version": version, "previous": previous}


def _prune(versions: Path, keep: set[str | None]) -> None:
    """Removes version directories that are neither current nor previous. Runs after the swap; failures are ignored."""
    for entry in versions.iterdir():
        if entry.name in keep or not entry.is_dir() or entry.is_symlink():
            continue
        if VERSION_ID_RE.fullmatch(entry.name) or entry.name.startswith("legacy-"):
            shutil.rmtree(entry, ignore_errors=True)


_HANDLERS: dict[str, Callable[[Context], int]] = {
    "bootstrap-state": _bootstrap,
    "reconcile-schema": _reconcile,
    "resume-crawler": _resume,
    "resolve-run": _resolve,
    "install-host": _install,
}
