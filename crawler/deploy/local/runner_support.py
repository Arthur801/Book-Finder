"""Host-side helpers for the local crawler runner (standard library only; the runner calls them with ``python3 -I``).

Subcommands:
    state-gate                       EC2 deploy state JSON on stdin -> ``ok``, ``paused`` or ``dirty``.
    rewrite-url --port P --rds-host H --ca-path C --env-file F
                                     database URL on stdin -> a 600 env file with ``DATABASE_URL`` for the tunnel.
    port-ready PORT                  exit 0 when 127.0.0.1:PORT accepts a connection.
    write-runner-record ...          a terminal record for a lifecycle failure outside the container: prints it as one
                                     JSON line on stdout and writes it atomically to --path (runner-owned, no secrets).

The database URL is read from stdin only, never argv. Errors name the problem, never a value.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit, urlunsplit

PG_SCHEMES = frozenset({"postgresql", "postgres"})
# Keys this module owns; any other query parameter of the secret is kept as written.
TLS_QUERY_KEYS = frozenset({"host", "hostaddr", "port", "sslmode", "sslrootcert"})
ENDPOINT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*")

# Runner terminal records. The provider is fixed by the mode (the same mapping as the runner's case statement).
RUNNER_PROVIDERS = {"daily": "BOOKS_COM_TW", "first_book": "BOOKS_COM_TW", "pages": "BOOKS_COM_TW", "kingstone": "KINGSTONE"}
# reason -> (allowed exit codes, allowed alert_reasons); the runner writes a record only for these.
RUNNER_RULES = {
    "ORPHAN_WRITER": ({13, 14}, {("orphan",), ("orphan", "hard_limit")}),
    "HARD_LIMIT": ({20}, {("hard_limit",)}),
    "SIGNAL_STOP": ({21}, {("signal_stop",)}),
    "CLIENT_LOST": ({22}, {("orphan",)}),
}
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
CONTAINER_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
CONTAINER_ID_RE = re.compile(r"[0-9a-f]{12,64}")


class RunnerSupportError(Exception):
    """A check failed. The message is safe to print."""


def state_gate(text: str) -> str:
    """The same rule as ``crawler/deploy/run-crawler.sh``: paused wins over dirty; anything unreadable fails closed."""
    try:
        state = json.loads(text)
        if state["crawler"]["paused"] is not None:
            return "paused"
        if state["schema"]["dirty"] is True:
            return "dirty"
        return "ok"
    except ValueError, KeyError, TypeError:
        raise RunnerSupportError("EC2 deploy state is unreadable") from None


def _normal_host(host: str) -> str:
    return host.lower().rstrip(".")


def rewrite_url(secret: str, *, port: int, rds_host: str, ca_path: str) -> str:
    """Point the secret's URL at the local tunnel while keeping the RDS endpoint as the TLS host name.

    libpq uses ``host`` for certificate name checking and ``hostaddr`` for the address it connects to, so the
    connection goes through 127.0.0.1 and the certificate is still verified against the RDS endpoint. Userinfo and
    path are copied byte for byte: a password must already be percent-encoded, and it is never decoded here.
    """
    value = secret.removesuffix("\n")
    if not value or "\n" in value or "\r" in value or value == "None":
        raise RunnerSupportError("DATABASE_URL is empty or malformed")
    if not ENDPOINT_RE.fullmatch(rds_host):
        raise RunnerSupportError("RDS endpoint is malformed")
    if not 1 <= port <= 65535:
        raise RunnerSupportError("local tunnel port is out of range")
    try:
        parts = urlsplit(value)
    except ValueError:
        raise RunnerSupportError("DATABASE_URL is not a valid URL") from None
    if parts.scheme not in PG_SCHEMES:
        raise RunnerSupportError("DATABASE_URL must be a PostgreSQL URL")
    if parts.fragment or "#" in parts.netloc:
        raise RunnerSupportError("DATABASE_URL must percent-encode '#' in the password")
    userinfo, has_userinfo, hostport = parts.netloc.rpartition("@")
    if "[" in hostport or hostport.count(":") > 1:
        raise RunnerSupportError("DATABASE_URL host must be a plain host name")
    host = hostport.partition(":")[0]
    if not host or _normal_host(host) != _normal_host(rds_host):
        raise RunnerSupportError("DATABASE_URL host must be the RDS endpoint in the runner configuration")
    kept = [pair for pair in parts.query.split("&") if pair and pair.split("=", 1)[0] not in TLS_QUERY_KEYS]
    kept += [
        "hostaddr=127.0.0.1",
        "sslmode=verify-full",
        "sslrootcert=" + quote(ca_path, safe="/"),
    ]
    netloc = (userinfo + "@" if has_userinfo else "") + f"{host}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "&".join(kept), ""))


def write_env_file(path: str, url: str) -> None:
    """Write ``DATABASE_URL`` into an existing file, owner-only. The runner creates the file with mktemp."""
    fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(f"DATABASE_URL={url}\n")


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_runner_record(
    *,
    run_id: str,
    mode: str,
    exit_code: int,
    reason: str,
    alert_reasons,
    started_at: str,
    finished_at: str | None = None,
    container_name: str | None = None,
    container_id: str | None = None,
) -> dict:
    """The runner's terminal record. It holds no secret: every value is an identifier, a code, or a timestamp.

    ``counts`` is null because the runner cannot see the crawler's counters; the container's own record owns them.
    """
    try:
        provider = RUNNER_PROVIDERS[mode]
    except KeyError:
        raise RunnerSupportError("runner mode is unknown") from None
    codes, alert_sets = RUNNER_RULES.get(reason, (set(), set()))
    if exit_code not in codes or tuple(alert_reasons) not in alert_sets:
        raise RunnerSupportError("runner record reason, exit code and alert reasons do not agree")
    try:
        uuid.UUID(str(run_id))
    except ValueError:
        raise RunnerSupportError("runner run_id is not a UUID") from None
    if not UTC_RE.fullmatch(started_at):
        raise RunnerSupportError("runner started_at is not an ISO8601 UTC time")
    if container_name is not None and not CONTAINER_NAME_RE.fullmatch(container_name):
        raise RunnerSupportError("container name is malformed")
    if container_id is not None and not CONTAINER_ID_RE.fullmatch(container_id):
        raise RunnerSupportError("container id is malformed")
    return {
        "run_id": str(run_id),
        "provider": provider,
        "mode": mode,
        "status": "FAILED",
        "exit_code": exit_code,
        "reason": reason,
        "alert_reasons": list(alert_reasons),
        "started_at": started_at,
        "finished_at": finished_at or _utc_now(),
        "container": {"name": container_name, "cid": container_id},
        "counts": None,
        "source": "runner",
    }


def write_runner_record(path: str, record: dict) -> None:
    """Write the record through a temporary file in the same directory: fsync, then rename, then fsync the directory."""
    directory = os.path.dirname(path) or "."
    fd, temp = tempfile.mkstemp(dir=directory, prefix=".runner-record.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def port_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="runner_support.py")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("state-gate")
    rewrite = commands.add_parser("rewrite-url")
    rewrite.add_argument("--port", type=int, required=True)
    rewrite.add_argument("--rds-host", required=True)
    rewrite.add_argument("--ca-path", required=True)
    rewrite.add_argument("--env-file", required=True)
    ready = commands.add_parser("port-ready")
    ready.add_argument("port", type=int)
    terminal = commands.add_parser("write-runner-record")
    terminal.add_argument("--path", required=True)
    terminal.add_argument("--run-id", required=True)
    terminal.add_argument("--mode", required=True)
    terminal.add_argument("--exit-code", type=int, required=True)
    terminal.add_argument("--reason", required=True)
    terminal.add_argument("--alert-reasons", required=True, help="comma-separated")
    terminal.add_argument("--started-at", required=True)
    terminal.add_argument("--container-name", default="")
    terminal.add_argument("--container-id", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "state-gate":
            print(state_gate(sys.stdin.read()))
            return 0
        if args.command == "rewrite-url":
            url = rewrite_url(sys.stdin.read(), port=args.port, rds_host=args.rds_host, ca_path=args.ca_path)
            write_env_file(args.env_file, url)
            return 0
        if args.command == "write-runner-record":
            record = build_runner_record(
                run_id=args.run_id,
                mode=args.mode,
                exit_code=args.exit_code,
                reason=args.reason,
                alert_reasons=args.alert_reasons.split(","),
                started_at=args.started_at,
                container_name=args.container_name or None,
                container_id=args.container_id or None,
            )
            # The terminal line goes out even when the file cannot be written; the runner reports that case.
            print(json.dumps(record, sort_keys=True), flush=True)
            write_runner_record(args.path, record)
            return 0
        return 0 if port_ready(args.port) else 1
    except RunnerSupportError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError:
        print("runner record could not be written", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
