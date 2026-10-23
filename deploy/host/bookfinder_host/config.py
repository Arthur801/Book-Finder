"""Host configuration (/etc/book-finder/host.conf) and the production psql query.

Why: the forced command runs as root and must not execute configuration. The file is parsed as data with a fixed key
set; values are limited to a character set with no shell meaning, so the file cannot smuggle a second command.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bookfinder_host.images import is_digest_ref, is_repository
from bookfinder_host.ports import Runner
from bookfinder_host.safefile import UnsafeFileError, read_regular_file

DEFAULT_CONFIG_PATH = "/etc/book-finder/host.conf"
HOST_API_RANGE_PATH = Path(__file__).with_name("HOST_API_RANGE")
_VALUE_RE = re.compile(r"[A-Za-z0-9@/:._=+,-]{1,512}")
_LINE_RE = re.compile(r"([A-Z_]+)=(.*)")
_REQUIRED = {
    "STATE_FILE",
    "HISTORY_FILE",
    "DEPLOY_LOCK_FILE",
    "WEB_IMAGE_REPOSITORY",
    "PSQL_IMAGE",
    "DATABASE_URL_PARAMETER",
    "AWS_REGION",
    "SYSTEMD_UNIT",
}
_OPTIONAL = {"COMPOSE_PROJECT": "book-finder", "LOCK_TIMEOUT_S": "10"}
# The psql container runs one fixed command; the SQL is passed as a single argv element and never interpolated.
_PSQL_SCRIPT = 'psql -X -At -v ON_ERROR_STOP=1 "$DATABASE_URL" -c "$1"'


class ConfigError(Exception):
    """The configuration is missing, malformed, or contains a value that is not allowed."""


@dataclass(frozen=True)
class Settings:
    state_file: str
    history_file: str
    deploy_lock_file: str
    web_image_repository: str
    psql_image: str
    database_url_parameter: str
    aws_region: str
    systemd_unit: str
    compose_project: str
    lock_timeout_s: float


def parse_settings(text: str) -> Settings:
    values: dict[str, str] = {}
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_RE.fullmatch(line)
        if match is None:
            raise ConfigError(f"host.conf line {number} is not KEY=VALUE")
        key, value = match.groups()
        if key in values:
            raise ConfigError(f"duplicate key in host.conf: {key}")
        if key not in _REQUIRED and key not in _OPTIONAL:
            raise ConfigError(f"unknown key in host.conf: {key}")
        if _VALUE_RE.fullmatch(value) is None:
            raise ConfigError(f"value for {key} contains characters that are not allowed")
        values[key] = value
    missing = sorted(_REQUIRED - set(values))
    if missing:
        raise ConfigError(f"host.conf is missing: {', '.join(missing)}")
    values = {**_OPTIONAL, **values}
    if not is_repository(values["WEB_IMAGE_REPOSITORY"]):
        raise ConfigError("WEB_IMAGE_REPOSITORY must be a repository without a tag or digest")
    if not is_digest_ref(values["PSQL_IMAGE"]):
        raise ConfigError("PSQL_IMAGE must be pinned by digest (<repository>@sha256:<digest>)")
    try:
        timeout = float(values["LOCK_TIMEOUT_S"])
    except ValueError as exc:
        raise ConfigError("LOCK_TIMEOUT_S must be a number") from exc
    return Settings(
        state_file=values["STATE_FILE"],
        history_file=values["HISTORY_FILE"],
        deploy_lock_file=values["DEPLOY_LOCK_FILE"],
        web_image_repository=values["WEB_IMAGE_REPOSITORY"],
        psql_image=values["PSQL_IMAGE"],
        database_url_parameter=values["DATABASE_URL_PARAMETER"],
        aws_region=values["AWS_REGION"],
        systemd_unit=values["SYSTEMD_UNIT"],
        compose_project=values["COMPOSE_PROJECT"],
        lock_timeout_s=timeout,
    )


def load_settings(path: str | Path = DEFAULT_CONFIG_PATH) -> Settings:
    try:
        data = read_regular_file(path, 65536)
    except FileNotFoundError as exc:
        raise ConfigError(f"host configuration is missing: {path}") from exc
    except UnsafeFileError as exc:
        raise ConfigError(str(exc)) from exc
    return parse_settings(data.decode("utf-8"))


def read_host_api_range(path: str | Path = HOST_API_RANGE_PATH) -> tuple[int, int]:
    """The host supports release_api values from min through max inclusive (N4)."""
    try:
        text = read_regular_file(path, 64).decode("ascii")
    except (OSError, UnsafeFileError, UnicodeDecodeError) as exc:
        raise ConfigError(f"HOST_API_RANGE cannot be read: {exc}") from exc
    parts = text.strip().split(" ")
    if not text.endswith("\n") or len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ConfigError("HOST_API_RANGE must be 'min max' followed by a newline")
    low, high = int(parts[0]), int(parts[1])
    if low > high:
        raise ConfigError("HOST_API_RANGE min is greater than max")
    return low, high


def make_psql_query(runner: Runner, settings: Settings) -> Callable[[str], str]:
    """Returns a query function that runs psql from the pinned image with the DB URL taken from SSM.

    Why: the URL is fetched with the instance role and handed to docker through the environment, so it never appears
    in an argv list where another process could read it. The image is pinned by digest in host.conf.
    """

    def query(sql: str) -> str:
        fetched = runner.run(
            [
                "aws",
                "ssm",
                "get-parameter",
                "--region",
                settings.aws_region,
                "--name",
                settings.database_url_parameter,
                "--with-decryption",
                "--query",
                "Parameter.Value",
                "--output",
                "text",
            ]
        )
        if fetched.returncode != 0:
            raise ConfigError(f"reading the database parameter failed: {fetched.stderr.strip()}")
        url = fetched.stdout.strip()
        if not url.startswith(("postgres://", "postgresql://")) or any(c.isspace() for c in url):
            raise ConfigError("database URL parameter is empty or malformed")
        result = runner.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "-e",
                "DATABASE_URL",
                "--entrypoint",
                "/bin/sh",
                settings.psql_image,
                "-c",
                _PSQL_SCRIPT,
                "sh",
                sql,
            ],
            env={"DATABASE_URL": url},
        )
        if result.returncode != 0:
            raise ConfigError(f"psql failed: {result.stderr.strip()}")
        return result.stdout

    return query
