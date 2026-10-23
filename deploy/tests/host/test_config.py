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


@pytest.mark.parametrize(
    "mutation",
    [
        lambda text: text + "EXTRA=1\n",  # unknown key
        lambda text: text.replace("AWS_REGION=ap-northeast-1\n", ""),  # missing required key
        lambda text: text.replace("AWS_REGION=ap-northeast-1", "AWS_REGION=$(id)"),  # shell syntax in a value
        lambda text: text.replace("AWS_REGION=ap-northeast-1", "AWS_REGION=ap;reboot"),  # command separator
        lambda text: text.replace("AWS_REGION=ap-northeast-1", 'AWS_REGION="ap-northeast-1"'),  # quotes are not KEY=VALUE here
        lambda text: text + "STATE_FILE=/other\n",  # duplicate key
    ],
)
def test_rejects_bad_configuration(tmp_path, mutation):
    with pytest.raises(cfg.ConfigError):
        cfg.load_settings(write(tmp_path, mutation(VALID)))


def test_make_psql_query_passes_the_url_only_in_the_environment(tmp_path):
    url = "postgres://user:secret@db.internal/book_finder"
    runner = ScriptedRunner(
        [
            (("aws",), lambda argv: ok(url + "\n")),
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
    runner = ScriptedRunner([(("aws",), lambda argv: ok("postgres://x\nrm\n"))])
    query = cfg.make_psql_query(runner, cfg.load_settings(write(tmp_path, VALID)))
    with pytest.raises(cfg.ConfigError):
        query("SELECT 1;")


def test_make_psql_query_reports_psql_failure(tmp_path):
    runner = ScriptedRunner(
        [
            (("aws",), lambda argv: ok("postgres://db/x\n")),
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
