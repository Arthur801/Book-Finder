"""Host configuration (/etc/book-finder/host.conf) and the production psql query.

Why: the forced command runs as root and must not execute configuration. The file is parsed as data with a fixed key
set; values are limited to a character set with no shell meaning, so the file cannot smuggle a second command.
"""

import math
import os
import re
import stat
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
    "PUBLIC_URL",
    "RDS_INSTANCE_ID",
    "SSM_DB_CONNECTION",
    "SSM_OPENAI_KEY",
    "SSM_JWT_KEY",
    "CRAWLER_IMAGE_REPOSITORY",
}
_OPTIONAL = {
    "COMPOSE_PROJECT": "book-finder",
    "LOCK_TIMEOUT_S": "10",
    # Covers the 30 min deploy-lock wait, the 45 min db-maintenance wait and the snapshot before the SSH side gives up.
    "FOLLOW_TIMEOUT_S": "6000",
    "CRAWLER_CONF": "/etc/book-finder/crawler.conf",
    "DB_MAINTENANCE_LOCK": "/var/lib/book-finder/db-maintenance.lock",
    "RELEASES_DIR": "/opt/book-finder/releases",
    "RUN_DIR": "/run/book-finder",
    "CRAWLER_RUNNER": "/opt/book-finder/run-crawler.sh",
    "CRON_FILE": "/etc/cron.d/book-finder-crawler",
    # Absolute path to the AWS CLI; in production it must be a root-owned file that others cannot write (checked below).
    "AWS_CLI": "/usr/local/bin/aws",
}
_PATH_KEYS = (
    "STATE_FILE",
    "HISTORY_FILE",
    "DEPLOY_LOCK_FILE",
    "CRAWLER_CONF",
    "DB_MAINTENANCE_LOCK",
    "RELEASES_DIR",
    "RUN_DIR",
    "CRAWLER_RUNNER",
    "CRON_FILE",
)
# The psql container runs one fixed command; the SQL is passed as a single argv element and never interpolated.
_PSQL_SCRIPT = 'psql -X -At -v ON_ERROR_STOP=1 "$DATABASE_URL" -c "$1"'
# Optional, with no default: absent means the bundle is not mounted anywhere (the behaviour before DB_CA_BUNDLE existed).
# SSM_MIGRATION_CONNECTION names a role that owns the schema objects; efbundle alone uses it (deploy/README.md §2.4).
_OPTIONAL_UNSET = {"DB_CA_BUNDLE", "SSM_MIGRATION_CONNECTION"}
# The path goes into a --mount option and a compose variable, so only characters with no separator meaning are allowed.
_CA_PATH_RE = re.compile(r"/[A-Za-z0-9._/-]{1,512}")
CA_BUNDLE_MAX_BYTES = 1 << 20


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
    follow_timeout_s: float
    public_url: str
    rds_instance_id: str
    ssm_db_connection: str
    ssm_openai_key: str
    ssm_jwt_key: str
    crawler_image_repository: str
    crawler_conf: str
    db_maintenance_lock: str
    releases_dir: str
    run_dir: str
    crawler_runner: str
    cron_file: str
    # The AWS CLI used for SSM and RDS. The default keeps the existing argv-based tests unchanged.
    aws_cli: str = "aws"
    # Public CA bundle for verify-full; mounted read-only at the same path in every container that connects to RDS.
    db_ca_bundle: str | None = None
    # SSM parameter name of the connection string that efbundle uses; None keeps the web connection for migrations.
    ssm_migration_connection: str | None = None


def _positive_finite_seconds(values: dict[str, str], key: str) -> float:
    """A duration in seconds that a bounded wait can use: a finite number greater than zero.

    Why: float() accepts "nan" and "inf", and a NaN deadline never expires, so a bounded wait would not be bounded.
    """
    try:
        seconds = float(values[key])
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise ConfigError(f"{key} must be a finite number greater than zero")
    return seconds


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
        if key not in _REQUIRED and key not in _OPTIONAL and key not in _OPTIONAL_UNSET:
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
    if not is_repository(values["CRAWLER_IMAGE_REPOSITORY"]):
        raise ConfigError("CRAWLER_IMAGE_REPOSITORY must be a repository without a tag or digest")
    if not _is_public_url(values["PUBLIC_URL"]):
        raise ConfigError("PUBLIC_URL must be an https:// URL (or http://127.0.0.1 for a local stand-in edge)")
    if not values["AWS_CLI"].startswith("/"):
        raise ConfigError("AWS_CLI must be an absolute path")
    for key in _PATH_KEYS:
        if not values[key].startswith("/"):
            raise ConfigError(f"{key} must be an absolute path")
    if "DB_CA_BUNDLE" in values and _CA_PATH_RE.fullmatch(values["DB_CA_BUNDLE"]) is None:
        raise ConfigError("DB_CA_BUNDLE must be an absolute path made of letters, digits, '.', '_', '-' and '/'")
    if not is_digest_ref(values["PSQL_IMAGE"]):
        raise ConfigError("PSQL_IMAGE must be pinned by digest (<repository>@sha256:<digest>)")
    timeout = _positive_finite_seconds(values, "LOCK_TIMEOUT_S")
    follow_timeout = _positive_finite_seconds(values, "FOLLOW_TIMEOUT_S")
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
        follow_timeout_s=follow_timeout,
        public_url=values["PUBLIC_URL"],
        rds_instance_id=values["RDS_INSTANCE_ID"],
        ssm_db_connection=values["SSM_DB_CONNECTION"],
        ssm_openai_key=values["SSM_OPENAI_KEY"],
        ssm_jwt_key=values["SSM_JWT_KEY"],
        crawler_image_repository=values["CRAWLER_IMAGE_REPOSITORY"],
        crawler_conf=values["CRAWLER_CONF"],
        db_maintenance_lock=values["DB_MAINTENANCE_LOCK"],
        releases_dir=values["RELEASES_DIR"],
        run_dir=values["RUN_DIR"],
        crawler_runner=values["CRAWLER_RUNNER"],
        cron_file=values["CRON_FILE"],
        aws_cli=values["AWS_CLI"],
        db_ca_bundle=values.get("DB_CA_BUNDLE"),
        ssm_migration_connection=values.get("SSM_MIGRATION_CONNECTION"),
    )


def _is_public_url(value: str) -> bool:
    # Plain HTTP is accepted only for loopback: the local integration run has no TLS edge, and a loopback address
    # never leaves the host.
    if value.startswith("https://") and len(value) > len("https://"):
        return True
    return _LOOPBACK_URL_RE.fullmatch(value) is not None


_LOOPBACK_URL_RE = re.compile(r"http://127\.0\.0\.1(:[0-9]{1,5})?(/.*)?")


def check_root_owned(path: str) -> None:
    """Production only: the AWS CLI runs as root, so a file another user could rewrite would be root code execution."""
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ConfigError(f"AWS_CLI is not a regular file: {path}")
    if info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ConfigError(f"AWS_CLI must be root-owned and not writable by group or others: {path}")


def check_ca_bundle(path: str) -> None:
    """Refuses a CA bundle the host must not mount: it must be a plain, public file of at most one mebibyte.

    Why lstat: a symlink is refused rather than followed, so the file that is mounted is the file that was checked.
    Why o+r: the containers run as a non-root user (uid 1654 for web, 10001 for the crawler) and must read the file.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError as exc:
        raise ConfigError(f"DB_CA_BUNDLE does not exist: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"DB_CA_BUNDLE cannot be inspected: {exc}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise ConfigError("DB_CA_BUNDLE must not be a symbolic link")
    if not stat.S_ISREG(info.st_mode):
        raise ConfigError("DB_CA_BUNDLE must be a regular file")
    if not info.st_mode & stat.S_IROTH:
        raise ConfigError("DB_CA_BUNDLE must be readable by others (mode 0644): the container user must read it")
    if info.st_size > CA_BUNDLE_MAX_BYTES:
        raise ConfigError(f"DB_CA_BUNDLE is larger than {CA_BUNDLE_MAX_BYTES} bytes")


def ca_bundle_mount_args(path: str | None) -> list[str]:
    """The docker --mount argument that places the bundle read-only at the same path; nothing when unset."""
    if path is None:
        return []
    return ["--mount", f"type=bind,src={path},dst={path},readonly"]


def load_settings(path: str | Path = DEFAULT_CONFIG_PATH) -> Settings:
    try:
        data = read_regular_file(path, 65536)
    except FileNotFoundError as exc:
        raise ConfigError(f"host configuration is missing: {path}") from exc
    except UnsafeFileError as exc:
        raise ConfigError(str(exc)) from exc
    settings = parse_settings(data.decode("utf-8"))
    if settings.db_ca_bundle is not None:
        check_ca_bundle(settings.db_ca_bundle)
    if os.geteuid() == 0:
        try:
            check_root_owned(settings.aws_cli)
        except OSError as exc:
            raise ConfigError(f"AWS_CLI cannot be inspected: {exc}") from exc
    return settings


# The host's own requests (health checks) identify themselves with this product name. Edge rules that block the default
# "Python-urllib" agent (the 2026-10-24 production 403) must let this one through; see deploy/README.md §7.2.
HOST_USER_AGENT_PRODUCT = "book-finder-deploy"


def host_user_agent(path: str | Path = HOST_API_RANGE_PATH) -> str:
    """The User-Agent the host sends: the product name and the highest HOST_API release_api this host supports."""
    _, high = read_host_api_range(path)
    return f"{HOST_USER_AGENT_PRODUCT}/{high}"


def read_host_api_range(path: str | Path = HOST_API_RANGE_PATH) -> tuple[int, int]:
    """The host supports release_api values from min through max inclusive (N4: a release outside the range is refused before anything changes)."""
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
                settings.aws_cli,
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
                *ca_bundle_mount_args(settings.db_ca_bundle),
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
