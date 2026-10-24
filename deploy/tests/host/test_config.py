"""Tests for bookfinder_host.config: the strict KEY=VALUE host configuration and the psql query closure.

Why: /etc/book-finder/host.conf is read by a root-run forced command. It is parsed as data (never sourced) and every
value is restricted to characters that cannot start a second command even if someone later pastes it into a shell.
"""

import pytest
from bookfinder_host import config as cfg
from bookfinder_host.ports import CommandResult
from bookfinder_host.testing import ScriptedRunner, ok

VALID = (
    """# comment lines are allowed
STATE_FILE=/var/lib/book-finder/state.json
HISTORY_FILE=/var/lib/book-finder/history.jsonl
DEPLOY_LOCK_FILE=/var/lib/book-finder/deploy.lock
WEB_IMAGE_REPOSITORY=ghcr.io/example/book-finder-web
PSQL_IMAGE=docker.io/library/postgres@sha256:"""
    + "f" * 64
    + """
DATABASE_URL_PARAMETER=/book-finder/prod/database-url
AWS_REGION=ap-northeast-1
SYSTEMD_UNIT=book-finder.service
PUBLIC_URL=https://book-finder.example
RDS_INSTANCE_ID=book-finder-prod
SSM_DB_CONNECTION=/book-finder/prod/db-connection
SSM_OPENAI_KEY=/book-finder/prod/openai-key
SSM_JWT_KEY=/book-finder/prod/jwt-key
CRAWLER_IMAGE_REPOSITORY=ghcr.io/example/book-finder-crawler
"""
)


def write(tmp_path, text):
    path = tmp_path / "host.conf"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_valid_configuration(tmp_path):
    settings = cfg.load_settings(write(tmp_path, VALID))
    assert settings.state_file == "/var/lib/book-finder/state.json"
    assert settings.aws_region == "ap-northeast-1"
    assert settings.compose_project == "book-finder"
    assert settings.follow_timeout_s == 6000.0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda text: text + "EXTRA=1\n",  # unknown key
        lambda text: text.replace("AWS_REGION=ap-northeast-1\n", ""),  # missing required key
        lambda text: text.replace("AWS_REGION=ap-northeast-1", "AWS_REGION=$(id)"),  # shell syntax in a value
        lambda text: text.replace("AWS_REGION=ap-northeast-1", "AWS_REGION=ap;reboot"),  # command separator
        lambda text: text.replace("AWS_REGION=ap-northeast-1", 'AWS_REGION="ap-northeast-1"'),  # quotes are not KEY=VALUE here
        lambda text: text + "STATE_FILE=/other\n",  # duplicate key
        lambda text: text.replace("postgres@sha256:" + "f" * 64, "postgres:17"),  # psql image must be digest-pinned
        lambda text: text.replace(
            "WEB_IMAGE_REPOSITORY=ghcr.io/example/book-finder-web\n", "WEB_IMAGE_REPOSITORY=ghcr.io/example/book-finder-web:v1\n"
        ),  # no tag in repository
        lambda text: text.replace("PUBLIC_URL=https://book-finder.example", "PUBLIC_URL=http://book-finder.example"),  # TLS only
        lambda text: text.replace("CRAWLER_IMAGE_REPOSITORY=ghcr.io/example/book-finder-crawler", "CRAWLER_IMAGE_REPOSITORY=ghcr.io/x:1"),
        lambda text: text + "CRON_FILE=relative/cron\n",  # paths must be absolute
        lambda text: text + "FOLLOW_TIMEOUT_S=0\n",  # must be positive
        lambda text: text + "FOLLOW_TIMEOUT_S=soon\n",  # must be a number
    ],
)
def test_rejects_bad_configuration(tmp_path, mutation):
    with pytest.raises(cfg.ConfigError):
        cfg.load_settings(write(tmp_path, mutation(VALID)))


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "Infinity", "0", "-1", "soon"])
def test_rejects_lock_timeout_that_is_not_a_finite_positive_number(tmp_path, value):
    with pytest.raises(cfg.ConfigError, match="LOCK_TIMEOUT_S"):
        cfg.load_settings(write(tmp_path, VALID + f"LOCK_TIMEOUT_S={value}\n"))


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "Infinity", "0", "-1", "soon"])
def test_rejects_follow_timeout_that_is_not_a_finite_positive_number(tmp_path, value):
    with pytest.raises(cfg.ConfigError, match="FOLLOW_TIMEOUT_S"):
        cfg.load_settings(write(tmp_path, VALID + f"FOLLOW_TIMEOUT_S={value}\n"))


@pytest.mark.parametrize(("value", "expected"), [("0.5", 0.5), ("10", 10.0)])
def test_accepts_lock_timeout_that_is_a_finite_positive_number(tmp_path, value, expected):
    settings = cfg.load_settings(write(tmp_path, VALID + f"LOCK_TIMEOUT_S={value}\n"))
    assert settings.lock_timeout_s == expected


def test_make_psql_query_passes_the_url_only_in_the_environment(tmp_path):
    url = "postgres://user:secret@db.internal/book_finder"
    runner = ScriptedRunner(
        [
            (("/usr/local/bin/aws",), lambda argv: ok(url + "\n")),
            (
                ("docker", "run"),
                lambda argv: ok("20261010174616_EnablePgvector\n20261010174654_Catalog\n"),
            ),
        ]
    )
    settings = cfg.load_settings(write(tmp_path, VALID))
    query = cfg.make_psql_query(runner, settings)
    assert query("SELECT 1;") == "20261010174616_EnablePgvector\n20261010174654_Catalog\n"

    docker_call = next(call for call in runner.calls if call[0][:2] == ["docker", "run"])
    argv, env = docker_call
    assert env == {"DATABASE_URL": url}
    assert all(url not in part for part in argv)
    assert "--pull=never" in argv
    assert "-e" in argv and argv[argv.index("-e") + 1] == "DATABASE_URL"


def test_make_psql_query_refuses_a_url_with_a_newline(tmp_path):
    runner = ScriptedRunner([(("/usr/local/bin/aws",), lambda argv: ok("postgres://x\nrm\n"))])
    query = cfg.make_psql_query(runner, cfg.load_settings(write(tmp_path, VALID)))
    with pytest.raises(cfg.ConfigError):
        query("SELECT 1;")


def test_make_psql_query_reports_psql_failure(tmp_path):
    runner = ScriptedRunner(
        [
            (("/usr/local/bin/aws",), lambda argv: ok("postgres://db/x\n")),
            (("docker", "run"), lambda argv: CommandResult(1, "", "connection refused")),
        ]
    )
    query = cfg.make_psql_query(runner, cfg.load_settings(write(tmp_path, VALID)))
    with pytest.raises(cfg.ConfigError, match="connection refused"):
        query("SELECT 1;")


def test_host_api_range_reads_min_and_max(tmp_path):
    path = tmp_path / "HOST_API_RANGE"
    path.write_text("1 1\n")
    assert cfg.read_host_api_range(path) == (1, 1)


@pytest.mark.parametrize("content", ["1\n", "2 1\n", "a b\n", "1 1 1\n", "-1 2\n"])
def test_host_api_range_rejects_malformed_content(tmp_path, content):
    path = tmp_path / "HOST_API_RANGE"
    path.write_text(content)
    with pytest.raises(cfg.ConfigError):
        cfg.read_host_api_range(path)


def test_aws_cli_defaults_to_the_absolute_path_and_must_be_absolute():
    settings = cfg.parse_settings(VALID)
    assert settings.aws_cli == "/usr/local/bin/aws"
    with pytest.raises(cfg.ConfigError):
        cfg.parse_settings(VALID + "AWS_CLI=aws\n")
    assert cfg.parse_settings(VALID + "AWS_CLI=/opt/aws/bin/aws\n").aws_cli == "/opt/aws/bin/aws"


def test_public_url_allows_plain_http_only_on_loopback():
    assert cfg.parse_settings(VALID.replace("https://book-finder.example", "http://127.0.0.1:5123")).public_url == "http://127.0.0.1:5123"
    for url in ("http://localhost:5000", "http://10.0.0.5", "http://127.0.0.1.evil.example"):
        with pytest.raises(cfg.ConfigError):
            cfg.parse_settings(VALID.replace("https://book-finder.example", url))


def test_root_ownership_check_refuses_a_file_the_operator_owns(tmp_path):
    config = cfg

    cli = tmp_path / "aws"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    with pytest.raises(cfg.ConfigError):
        config.check_root_owned(str(cli))


CA_PATH = "/etc/book-finder/global-bundle.pem"


def test_db_ca_bundle_is_unset_by_default_and_taken_when_absolute():
    assert cfg.parse_settings(VALID).db_ca_bundle is None
    assert cfg.parse_settings(VALID + f"DB_CA_BUNDLE={CA_PATH}\n").db_ca_bundle == CA_PATH


@pytest.mark.parametrize(
    "value",
    [
        "relative/bundle.pem",  # must be absolute
        "/etc/book-finder/a,readonly.pem",  # a comma would split the --mount option list
        "/etc/book-finder/a=b.pem",
        "/etc/book finder/x.pem",
        "/etc/book-finder/$(id).pem",
        "/etc/book-finder/x.pem;reboot",
    ],
)
def test_db_ca_bundle_path_must_be_absolute_and_plain(value):
    with pytest.raises(cfg.ConfigError, match="DB_CA_BUNDLE"):
        cfg.parse_settings(VALID + f"DB_CA_BUNDLE={value}\n")


def test_db_ca_bundle_duplicate_key_is_refused():
    with pytest.raises(cfg.ConfigError, match="duplicate"):
        cfg.parse_settings(VALID + f"DB_CA_BUNDLE={CA_PATH}\nDB_CA_BUNDLE={CA_PATH}\n")


def _bundle(tmp_path, *, mode=0o644, size=1024, name="global-bundle.pem"):
    path = tmp_path / name
    path.write_bytes(b"x" * size)
    path.chmod(mode)
    return path


def test_check_ca_bundle_accepts_a_public_regular_file_up_to_one_mebibyte(tmp_path):
    cfg.check_ca_bundle(str(_bundle(tmp_path)))
    cfg.check_ca_bundle(str(_bundle(tmp_path, size=1 << 20, name="exact.pem")))


def test_check_ca_bundle_refuses_a_missing_file(tmp_path):
    with pytest.raises(cfg.ConfigError, match="does not exist"):
        cfg.check_ca_bundle(str(tmp_path / "absent.pem"))


def test_check_ca_bundle_refuses_a_symlink_without_following_it(tmp_path):
    target = _bundle(tmp_path)
    link = tmp_path / "link.pem"
    link.symlink_to(target)
    with pytest.raises(cfg.ConfigError, match="symbolic link"):
        cfg.check_ca_bundle(str(link))


def test_check_ca_bundle_refuses_a_directory(tmp_path):
    with pytest.raises(cfg.ConfigError, match="regular file"):
        cfg.check_ca_bundle(str(tmp_path))


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o620])
def test_check_ca_bundle_refuses_a_file_that_others_cannot_read(tmp_path, mode):
    with pytest.raises(cfg.ConfigError, match="readable by others"):
        cfg.check_ca_bundle(str(_bundle(tmp_path, mode=mode)))


def test_check_ca_bundle_refuses_a_file_over_one_mebibyte(tmp_path):
    with pytest.raises(cfg.ConfigError, match="larger than"):
        cfg.check_ca_bundle(str(_bundle(tmp_path, size=(1 << 20) + 1)))


def test_load_settings_checks_the_configured_bundle_and_nothing_when_unset(tmp_path):
    bad = write(tmp_path, VALID + f"DB_CA_BUNDLE={tmp_path / 'missing.pem'}\n")
    with pytest.raises(cfg.ConfigError, match="does not exist"):
        cfg.load_settings(bad)
    good_bundle = _bundle(tmp_path)
    assert cfg.load_settings(write(tmp_path, VALID + f"DB_CA_BUNDLE={good_bundle}\n")).db_ca_bundle == str(good_bundle)
    assert cfg.load_settings(write(tmp_path, VALID)).db_ca_bundle is None


def test_ca_bundle_mount_argument_is_read_only_at_the_same_path():
    assert cfg.ca_bundle_mount_args(None) == []
    assert cfg.ca_bundle_mount_args(CA_PATH) == ["--mount", f"type=bind,src={CA_PATH},dst={CA_PATH},readonly"]


def test_make_psql_query_mounts_the_bundle_only_when_configured(tmp_path):
    url = "postgres://user:secret@db.internal/book_finder"

    def psql_argv(extra: str) -> list[str]:
        runner = ScriptedRunner(
            [
                (("/usr/local/bin/aws",), lambda argv: ok(url + "\n")),
                (("docker", "run"), lambda argv: ok("")),
            ]
        )
        cfg.make_psql_query(runner, cfg.load_settings(write(tmp_path, VALID + extra)))("SELECT 1;")
        return next(call for call in runner.calls if call[0][:2] == ["docker", "run"])[0]

    unset = psql_argv("")
    assert "--mount" not in unset
    bundle = _bundle(tmp_path)
    configured = psql_argv(f"DB_CA_BUNDLE={bundle}\n")
    assert configured[configured.index("--mount") + 1] == f"type=bind,src={bundle},dst={bundle},readonly"
    assert configured[: configured.index("--mount")] == unset[: configured.index("--mount")]


MIGRATION_PARAMETER = "/book-finder/prod/migration-connection"


def test_ssm_migration_connection_is_unset_by_default_and_taken_when_given():
    assert cfg.parse_settings(VALID).ssm_migration_connection is None
    assert cfg.parse_settings(VALID + f"SSM_MIGRATION_CONNECTION={MIGRATION_PARAMETER}\n").ssm_migration_connection == MIGRATION_PARAMETER


@pytest.mark.parametrize("value", ["", "/book-finder/prod/migration connection", "/book-finder/$(id)"])
def test_ssm_migration_connection_empty_or_unsafe_value_is_refused(value):
    with pytest.raises(cfg.ConfigError, match="SSM_MIGRATION_CONNECTION"):
        cfg.parse_settings(VALID + f"SSM_MIGRATION_CONNECTION={value}\n")


def test_ssm_migration_connection_duplicate_key_is_refused():
    with pytest.raises(cfg.ConfigError, match="duplicate"):
        cfg.parse_settings(VALID + f"SSM_MIGRATION_CONNECTION={MIGRATION_PARAMETER}\nSSM_MIGRATION_CONNECTION={MIGRATION_PARAMETER}\n")


def test_unknown_key_is_still_refused_next_to_the_migration_key():
    with pytest.raises(cfg.ConfigError, match="unknown key"):
        cfg.parse_settings(VALID + f"SSM_MIGRATION_CONNECTIONS={MIGRATION_PARAMETER}\n")
