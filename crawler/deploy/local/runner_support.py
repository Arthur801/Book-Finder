"""Host-side helpers for the local crawler runner (standard library only; the runner calls them with ``python3 -I``).

Subcommands:
    state-gate                       EC2 deploy state JSON on stdin -> ``ok``, ``paused`` or ``dirty``.
    rewrite-url --port P --rds-host H --ca-path C --env-file F
                                     database URL on stdin -> a 600 env file with ``DATABASE_URL`` for the tunnel.
    port-ready PORT                  exit 0 when 127.0.0.1:PORT accepts a connection.

The database URL is read from stdin only, never argv. Errors name the problem, never a value.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
from urllib.parse import quote, urlsplit, urlunsplit

PG_SCHEMES = frozenset({"postgresql", "postgres"})
# Keys this module owns; any other query parameter of the secret is kept as written.
TLS_QUERY_KEYS = frozenset({"host", "hostaddr", "port", "sslmode", "sslrootcert"})
ENDPOINT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*")


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
    args = parser.parse_args(argv)
    try:
        if args.command == "state-gate":
            print(state_gate(sys.stdin.read()))
            return 0
        if args.command == "rewrite-url":
            url = rewrite_url(sys.stdin.read(), port=args.port, rds_host=args.rds_host, ca_path=args.ca_path)
            write_env_file(args.env_file, url)
            return 0
        return 0 if port_ready(args.port) else 1
    except RunnerSupportError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
