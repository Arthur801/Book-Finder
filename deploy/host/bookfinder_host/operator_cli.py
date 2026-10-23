"""Operator commands run by a person over their own SSH session as root (plan section 2, M3c).

Why: these commands change the state that the forced-command path refuses to change (dirty, paused, the first
bootstrap, and resolution of an indeterminate run). Each one takes the deploy lock, writes through the same CAS as the
state machine, requires a non-empty reason, and needs the operator to type the value shown (or pass it again with
--yes-i-verified). None of them is reachable through SSH_ORIGINAL_COMMAND.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TextIO

from bookfinder_host import commands as cmd
from bookfinder_host import config as cfg
from bookfinder_host import history as hi
from bookfinder_host import locks, runs
from bookfinder_host import manifest as mf
from bookfinder_host import runtime as rt
from bookfinder_host import state as st
from bookfinder_host.exit_codes import BAD_INPUT, DIRTY, DRIFT, OK
from bookfinder_host.safefile import UnsafeFileError, read_regular_file

MAX_REASON_CHARS = 400  # keeps an operator record well under the history line limit
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
INSTALLED_HOST_DIR = Path(__file__).resolve().parents[1]


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
    common(resume)

    resolve = sub.add_parser("resolve-run", help="record the outcome of an indeterminate run (N7)")
    resolve.add_argument("run_id")
    resolve.add_argument("--result", required=True, choices=sorted(RESOLVE_EXIT))
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
            return _HANDLERS[ctx.args.command](ctx)
    except locks.LockTimeout as exc:
        raise Refusal(DRIFT, f"busy: {exc}") from exc


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


def _record(ctx: Context, action: str, before, after) -> None:
    hi.append(
        ctx.deps.settings.history_file,
        {
            "phase": "operator",
            "action": action,
            "at": ctx.deps.clock.now(),
            "operator": ctx.operator,
            "reason": ctx.args.reason.strip(),
            "before": before,
            "after": after,
        },
    )


def _report(ctx: Context, action: str, **fields) -> int:
    ctx.out.write(json.dumps({"action": action, "result": "done", **fields}, sort_keys=True) + "\n")
    return OK


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


# bootstrap-state (N6)


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
        crawler=st.Crawler(digest=crawler_digest, paused=None),
    )
    try:
        stored = st.write_state(deps.settings.state_file, new_state, expected_revision=0)
    except st.RevisionConflict as exc:
        raise Refusal(DRIFT, f"state appeared while bootstrapping: {exc}") from exc
    _record(ctx, "bootstrap-state", None, st.state_summary(stored))
    return _report(ctx, "bootstrap-state", revision=stored.revision, release=tag)


# reconcile-schema (N2)


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
    stored = _write_cas(deps, new_state, state)
    _record(ctx, "reconcile-schema", st.state_summary(state), st.state_summary(stored))
    return _report(ctx, "reconcile-schema", revision=stored.revision, schema_digest=digest)


def _write_cas(deps: cmd.Deps, new_state: st.State, current: st.State) -> st.State:
    try:
        return st.write_state(deps.settings.state_file, new_state, expected_revision=current.revision)
    except st.RevisionConflict as exc:
        raise Refusal(DRIFT, f"state changed while the command ran: {exc}") from exc


# resume-crawler (N3)


def _crawler_image_line(text: str) -> str:
    lines = [line for line in text.split("\n") if line.startswith("CRAWLER_IMAGE=")]
    if len(lines) != 1:
        raise Refusal(DRIFT, "crawler.conf must contain exactly one CRAWLER_IMAGE= line")
    return lines[0][len("CRAWLER_IMAGE=") :]


def _resume(ctx: Context) -> int:
    args, deps = ctx.args, ctx.deps
    state = _load_state_or_refuse(ctx)
    if state.crawler.paused is None:
        raise Refusal(DRIFT, "crawler is not paused")
    if state.schema.dirty:
        raise Refusal(DIRTY, "schema is dirty; reconcile-schema must run before the crawler resumes")
    digest = _check_digest(args.crawler_digest, "crawler digest")
    if not isinstance(state.runtime, st.DockerRuntime):
        raise Refusal(DRIFT, "the runtime is not a release directory; the crawler cannot be verified against it")
    expected_image = f"{deps.settings.crawler_image_repository}@{digest}"
    try:
        conf = read_regular_file(deps.settings.crawler_conf, 65536).decode("utf-8")
    except (OSError, UnsafeFileError) as exc:
        raise Refusal(DRIFT, f"crawler.conf cannot be read: {exc}") from exc
    if _crawler_image_line(conf) != expected_image:
        raise Refusal(DRIFT, f"fix CRAWLER_IMAGE in {deps.settings.crawler_conf} to {expected_image} first")
    release_copy = Path(state.runtime.release_dir) / "run-crawler.sh"
    try:
        shipped = read_regular_file(release_copy, 1 << 20)
        installed = read_regular_file(deps.settings.crawler_runner, 1 << 20)
    except (OSError, UnsafeFileError) as exc:
        raise Refusal(DRIFT, f"run-crawler.sh cannot be compared with the release copy: {exc}") from exc
    if hashlib.sha256(shipped).digest() != hashlib.sha256(installed).digest():
        raise Refusal(DRIFT, f"installed {deps.settings.crawler_runner} differs from {release_copy}; reinstall it from the release")
    _confirm(ctx, digest, f"resume the crawler on {expected_image}")
    new_state = replace(state, crawler=st.Crawler(digest=digest, paused=None))
    stored = _write_cas(deps, new_state, state)
    _record(ctx, "resume-crawler", st.state_summary(state), st.state_summary(stored))
    return _report(ctx, "resume-crawler", revision=stored.revision)


# resolve-run (N7)


def _resolve(ctx: Context) -> int:
    args, deps = ctx.args, ctx.deps
    run_id = args.run_id
    if cmd.RUN_ID_RE.fullmatch(run_id) is None:
        raise Refusal(BAD_INPUT, "run id is malformed")
    try:
        records = hi.read(deps.settings.history_file)
    except hi.HistoryCorrupt as exc:
        raise Refusal(DRIFT, f"history is damaged beyond its last line: {exc}") from exc
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
    removed = 0
    if records.tail_corrupt:
        removed = hi.repair_unterminated_tail(deps.settings.history_file)
    result = args.result
    hi.append(
        deps.settings.history_file,
        hi.completed_record(
            run_id=run_id,
            result=result,
            exit_code=RESOLVE_EXIT[result],
            at=deps.clock.now(),
            state_summary=state_summary,
            resolved_by_operator=True,
            operator=ctx.operator,
            reason=args.reason.strip(),
        ),
    )
    if state_summary.get("dirty"):
        ctx.err.write("reminder: the schema is still dirty; use reconcile-schema (N2)\n")
    if state_summary.get("crawler_paused"):
        ctx.err.write("reminder: the crawler is still paused; use resume-crawler (N3)\n")
    return _report(ctx, "resolve-run", run_id=run_id, result=result, truncated_tail_bytes=removed)


# install-host (N4)


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
    _confirm(ctx, new_text, f"install the host program into {ctx.host_dir}")
    _swap_install(source, ctx.host_dir)
    _record(ctx, "install-host", {"host_api_range": old_text}, {"host_api_range": new_text})
    return _report(ctx, "install-host", host_api_range=new_text, previous_kept=str(ctx.host_dir.parent / f"{ctx.host_dir.name}.prev"))


def _swap_install(source: Path, target: Path) -> None:
    """Copies the tree beside the target and renames it into place, keeping the previous install as <target>.prev."""
    parent = target.parent
    staging = Path(tempfile.mkdtemp(prefix=".host-new-", dir=parent))
    try:
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        shutil.copytree(source / "bookfinder_host", staging / "bookfinder_host", ignore=ignore)
        for name in ("deploy-entry", "book-finder-admin"):
            shutil.copy2(source / name, staging / name)
            os.chmod(staging / name, 0o755)
        previous = parent / f"{target.name}.prev"
        if previous.exists() or os.path.islink(previous):
            shutil.rmtree(previous)
        moved_old = target.exists()
        if moved_old:
            os.rename(target, previous)
        try:
            os.rename(staging, target)
        except OSError:
            if moved_old:
                os.rename(previous, target)  # put the working install back before reporting
            raise
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


_HANDLERS: dict[str, Callable[[Context], int]] = {
    "bootstrap-state": _bootstrap,
    "reconcile-schema": _reconcile,
    "resume-crawler": _resume,
    "resolve-run": _resolve,
    "install-host": _install,
}
