"""Provider-neutral run configuration (catalog_core.run_config), offline: plain mappings, a non-Kingstone spec.

The spec is the ESLITE one (``ESLITE_`` keys, its own error class). The Kingstone keys must be ignored by it, and the
Kingstone loader must ignore the ESLITE keys.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from catalog_core.models import WritePolicy
from catalog_core.run_config import (
    HARD_LIMIT_ENV,
    CategoryConfigError,
    CategoryConfigSpec,
    CategoryRunConfig,
    load_category_config,
)
from kingstone.config import KingstoneConfigError
from kingstone.config import load_config as load_kingstone_config

DEFAULT_ARTIFACTS = Path("/defaults/artifacts")
PAGES_DEFAULT = Path("/defaults/pages.txt")


class EsliteConfigError(CategoryConfigError):
    """The error class of the ESLITE spec in these tests."""


def resolve_pages(raw: str) -> Path:
    value = raw.strip()
    return Path(value) if value else PAGES_DEFAULT


def eslite_spec() -> CategoryConfigSpec:
    return CategoryConfigSpec(
        error_class=EsliteConfigError,
        pages_file_env="ESLITE_PAGES_FILE",
        resolve_pages_file=resolve_pages,
        write_policy_env="ESLITE_WRITE_POLICY",
        default_write_policy=WritePolicy.NEW_BOOKS_ONLY,
        soft_budget_env="ESLITE_SOFT_RUN_BUDGET_SECONDS",
        default_soft_budget_seconds=1000,
        default_hard_limit_seconds=1200,
        http_timeout_env="ESLITE_HTTP_TIMEOUT_SECONDS",
        default_http_timeout_seconds=15,
        http_max_attempts_env="ESLITE_HTTP_MAX_ATTEMPTS",
        default_http_max_attempts=4,
        max_response_bytes_env="ESLITE_MAX_RESPONSE_BYTES",
        default_max_response_bytes=4096,
        artifacts_dir_env="ESLITE_ARTIFACTS_DIR",
        default_artifacts_dir=DEFAULT_ARTIFACTS,
        diagnostic_max_bytes_env="ESLITE_DIAGNOSTIC_MAX_BYTES",
        default_diagnostic_max_bytes=512,
    )


def load(env: dict[str, str]) -> CategoryRunConfig:
    return load_category_config(env, eslite_spec())


def test_defaults_come_from_the_spec_when_nothing_is_set():
    assert load({}) == CategoryRunConfig(
        pages_file=PAGES_DEFAULT,
        write_policy=WritePolicy.NEW_BOOKS_ONLY,
        soft_budget_seconds=1000.0,
        hard_limit_seconds=1200.0,
        http_timeout_seconds=15.0,
        http_max_attempts=4,
        max_response_bytes=4096,
        artifacts_dir=DEFAULT_ARTIFACTS,
        diagnostic_max_bytes=512,
    )


def test_values_are_read_with_the_spec_keys_and_stripped():
    config = load(
        {
            "ESLITE_SOFT_RUN_BUDGET_SECONDS": " 900 ",
            HARD_LIMIT_ENV: "1000",
            "ESLITE_PAGES_FILE": "  /data/p.txt  ",
            "ESLITE_WRITE_POLICY": " normal ",
            "ESLITE_HTTP_MAX_ATTEMPTS": "2",
            "ESLITE_ARTIFACTS_DIR": "/out",
        }
    )
    assert (config.soft_budget_seconds, config.hard_limit_seconds) == (900.0, 1000.0)
    assert config.pages_file == Path("/data/p.txt")
    assert config.write_policy is WritePolicy.NORMAL
    assert config.http_max_attempts == 2
    assert config.artifacts_dir == Path("/out")


def test_a_blank_value_counts_as_unset():
    assert load({"ESLITE_SOFT_RUN_BUDGET_SECONDS": "   ", "ESLITE_ARTIFACTS_DIR": ""}) == load({})


def test_soft_budget_must_be_below_the_shared_hard_limit():
    with pytest.raises(EsliteConfigError, match="ESLITE_SOFT_RUN_BUDGET_SECONDS must be less than CRAWLER_RUN_HARD_LIMIT_SECONDS"):
        load({"ESLITE_SOFT_RUN_BUDGET_SECONDS": "3600", HARD_LIMIT_ENV: "3600"})


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("ESLITE_SOFT_RUN_BUDGET_SECONDS", "soon", "ESLITE_SOFT_RUN_BUDGET_SECONDS must be a number of seconds"),
        ("ESLITE_SOFT_RUN_BUDGET_SECONDS", "nan", "ESLITE_SOFT_RUN_BUDGET_SECONDS must be a finite number of seconds"),
        ("ESLITE_SOFT_RUN_BUDGET_SECONDS", "0", "ESLITE_SOFT_RUN_BUDGET_SECONDS must be greater than 0, not 0"),
        (HARD_LIMIT_ENV, "-5", f"{HARD_LIMIT_ENV} must be greater than 0, not -5"),
        ("ESLITE_HTTP_MAX_ATTEMPTS", "1.5", "ESLITE_HTTP_MAX_ATTEMPTS must be a whole number"),
        ("ESLITE_MAX_RESPONSE_BYTES", "0", "ESLITE_MAX_RESPONSE_BYTES must be at least 1, not 0"),
        ("ESLITE_DIAGNOSTIC_MAX_BYTES", "-1", "ESLITE_DIAGNOSTIC_MAX_BYTES must be a whole number"),
    ],
)
def test_bad_numbers_raise_the_spec_error_with_the_key_name(key, value, message):
    with pytest.raises(EsliteConfigError) as info:
        load({key: value})
    assert str(info.value) == message


def test_an_unknown_write_policy_names_the_key_and_does_not_echo_the_value():
    with pytest.raises(EsliteConfigError) as info:
        load({"ESLITE_WRITE_POLICY": "delete-everything"})
    assert str(info.value) == "ESLITE_WRITE_POLICY must be one of: normal, new-books-only"
    assert "delete-everything" not in str(info.value)


def test_the_error_class_is_the_spec_class_and_still_a_value_error():
    with pytest.raises(ValueError) as info:
        load({"ESLITE_HTTP_MAX_ATTEMPTS": "0"})
    assert isinstance(info.value, EsliteConfigError)
    assert isinstance(info.value, CategoryConfigError)


def test_kingstone_keys_are_ignored_by_the_eslite_loader():
    config = load(
        {
            "KINGSTONE_SOFT_RUN_BUDGET_SECONDS": "1",
            "KINGSTONE_HTTP_MAX_ATTEMPTS": "9",
            "KINGSTONE_WRITE_POLICY": "delete-everything",
            "KINGSTONE_ARTIFACTS_DIR": "/kingstone-only",
        }
    )
    assert config == load({})


def test_eslite_keys_are_ignored_by_the_kingstone_loader():
    kingstone = load_kingstone_config({"ESLITE_SOFT_RUN_BUDGET_SECONDS": "1", "ESLITE_HTTP_MAX_ATTEMPTS": "9", "ESLITE_ARTIFACTS_DIR": "/eslite-only"})
    assert kingstone == load_kingstone_config({})


def test_the_kingstone_error_is_a_category_config_error_and_a_value_error():
    with pytest.raises(KingstoneConfigError) as info:
        load_kingstone_config({"KINGSTONE_HTTP_MAX_ATTEMPTS": "0"})
    assert isinstance(info.value, CategoryConfigError)
    assert isinstance(info.value, ValueError)


def test_the_config_is_frozen():
    config = load({})
    with pytest.raises(AttributeError):
        config.soft_budget_seconds = 1.0  # type: ignore[misc]
