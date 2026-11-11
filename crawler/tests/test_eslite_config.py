"""Eslite run configuration (eslite.config). Offline: plain mappings, no environment, no files."""

from pathlib import Path

import pytest

from catalog_core.models import WritePolicy
from eslite import acquisition
from eslite.config import (
    DEFAULT_ARTIFACTS_DIR,
    DEFAULT_DIAGNOSTIC_MAX_BYTES,
    DEFAULT_HARD_LIMIT_SECONDS,
    DEFAULT_SOFT_BUDGET_SECONDS,
    EsliteConfig,
    EsliteConfigError,
    load_config,
)
from eslite.page_list import DEFAULT_PAGES_FILE, PAGES_FILE_ENV


def test_defaults_when_nothing_is_set():
    config = load_config({})

    assert config == EsliteConfig(
        pages_file=DEFAULT_PAGES_FILE,
        write_policy=WritePolicy.NORMAL,
        soft_budget_seconds=72000.0,
        hard_limit_seconds=79200.0,
        http_timeout_seconds=30.0,
        http_max_attempts=3,
        max_response_bytes=5 * 1024 * 1024,
        artifacts_dir=DEFAULT_ARTIFACTS_DIR,
        diagnostic_max_bytes=2 * 1024 * 1024,
    )
    assert (DEFAULT_SOFT_BUDGET_SECONDS, DEFAULT_HARD_LIMIT_SECONDS) == (72000, 79200)
    assert DEFAULT_DIAGNOSTIC_MAX_BYTES == 2 * 1024 * 1024


def test_the_defaults_are_the_eslite_acquisition_defaults():
    config = load_config({})

    assert config.http_timeout_seconds == float(acquisition.REQUEST_TIMEOUT_SECONDS)
    assert config.http_max_attempts == acquisition.MAX_ATTEMPTS
    assert config.max_response_bytes == acquisition.MAX_RESPONSE_BYTES


def test_the_pages_file_default_is_the_crawler_eslite_pages_file():
    assert PAGES_FILE_ENV == "ESLITE_PAGES_FILE"
    assert DEFAULT_PAGES_FILE == Path(__file__).resolve().parent.parent / "eslite-pages.txt"


def test_the_artifacts_default_is_the_crawler_artifacts_folder():
    assert DEFAULT_ARTIFACTS_DIR == Path(__file__).resolve().parent.parent / "artifacts"


def test_every_key_can_be_set():
    config = load_config(
        {
            "ESLITE_PAGES_FILE": "/srv/eslite.txt",
            "ESLITE_WRITE_POLICY": "new-books-only",
            "ESLITE_SOFT_RUN_BUDGET_SECONDS": "600",
            "CRAWLER_RUN_HARD_LIMIT_SECONDS": "900",
            "ESLITE_HTTP_TIMEOUT_SECONDS": "12",
            "ESLITE_HTTP_MAX_ATTEMPTS": "2",
            "ESLITE_MAX_RESPONSE_BYTES": "1000",
            "ESLITE_ARTIFACTS_DIR": "/var/eslite-artifacts",
            "ESLITE_DIAGNOSTIC_MAX_BYTES": "4096",
        }
    )

    assert config.pages_file == Path("/srv/eslite.txt")
    assert config.write_policy is WritePolicy.NEW_BOOKS_ONLY
    assert (config.soft_budget_seconds, config.hard_limit_seconds) == (600.0, 900.0)
    assert (config.http_timeout_seconds, config.http_max_attempts, config.max_response_bytes) == (12.0, 2, 1000)
    assert config.artifacts_dir == Path("/var/eslite-artifacts")
    assert config.diagnostic_max_bytes == 4096


@pytest.mark.parametrize(("soft", "hard"), [("9000", "9000"), ("9001", "9000"), ("7200", "7200")])
def test_a_soft_budget_not_below_the_hard_limit_is_refused(soft, hard):
    with pytest.raises(EsliteConfigError) as info:
        load_config({"ESLITE_SOFT_RUN_BUDGET_SECONDS": soft, "CRAWLER_RUN_HARD_LIMIT_SECONDS": hard})

    assert "ESLITE_SOFT_RUN_BUDGET_SECONDS must be less than CRAWLER_RUN_HARD_LIMIT_SECONDS" in str(info.value)


def test_a_soft_budget_below_the_default_hard_limit_is_accepted():
    assert load_config({"ESLITE_SOFT_RUN_BUDGET_SECONDS": "8999"}).soft_budget_seconds == 8999.0


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ESLITE_SOFT_RUN_BUDGET_SECONDS", "abc"),
        ("ESLITE_WRITE_POLICY", "bogus"),
        ("ESLITE_HTTP_MAX_ATTEMPTS", "0"),
        ("ESLITE_HTTP_TIMEOUT_SECONDS", "-1"),
        ("ESLITE_MAX_RESPONSE_BYTES", "0"),
        ("ESLITE_DIAGNOSTIC_MAX_BYTES", "x"),
    ],
)
def test_an_invalid_eslite_value_raises_the_eslite_error_and_names_the_key(key, value):
    with pytest.raises(EsliteConfigError) as info:
        load_config({key: value})

    assert key in str(info.value)


def test_the_error_class_is_a_value_error_and_a_category_config_error():
    from catalog_core.run_config import CategoryConfigError

    assert issubclass(EsliteConfigError, CategoryConfigError)
    assert issubclass(EsliteConfigError, ValueError)


def test_kingstone_keys_are_ignored():
    config = load_config(
        {
            "KINGSTONE_SOFT_RUN_BUDGET_SECONDS": "abc",
            "KINGSTONE_WRITE_POLICY": "bogus",
            "KINGSTONE_PAGES_FILE": "/nope.txt",
            "KINGSTONE_HTTP_MAX_ATTEMPTS": "0",
            "KINGSTONE_ARTIFACTS_DIR": "/nope",
        }
    )

    assert config == load_config({})


def test_a_blank_value_counts_as_unset():
    config = load_config({"ESLITE_WRITE_POLICY": "   ", "ESLITE_PAGES_FILE": "", "ESLITE_SOFT_RUN_BUDGET_SECONDS": " "})

    assert config.write_policy is WritePolicy.NORMAL
    assert config.pages_file == DEFAULT_PAGES_FILE
    assert config.soft_budget_seconds == 72000.0


def test_the_write_policy_error_never_echoes_the_value():
    with pytest.raises(EsliteConfigError) as info:
        load_config({"ESLITE_WRITE_POLICY": "super-secret-value"})

    assert "super-secret-value" not in str(info.value)
