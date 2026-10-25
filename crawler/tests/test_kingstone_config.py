"""Kingstone run configuration (kingstone.config). Offline: plain mappings, no environment, no files."""

from pathlib import Path

import pytest

from catalog_core.models import WritePolicy
from kingstone import acquisition
from kingstone.config import (
    DEFAULT_ARTIFACTS_DIR,
    DEFAULT_DIAGNOSTIC_MAX_BYTES,
    DEFAULT_HARD_LIMIT_SECONDS,
    DEFAULT_SOFT_BUDGET_SECONDS,
    KingstoneConfig,
    KingstoneConfigError,
    load_config,
)
from kingstone.page_list import DEFAULT_PAGES_FILE, PAGES_FILE_ENV

WRITE_POLICY_ENV = "KINGSTONE_WRITE_POLICY"

_ENV_KEYS = [
    PAGES_FILE_ENV,
    WRITE_POLICY_ENV,
    "KINGSTONE_SOFT_RUN_BUDGET_SECONDS",
    "CRAWLER_RUN_HARD_LIMIT_SECONDS",
    "KINGSTONE_HTTP_TIMEOUT_SECONDS",
    "KINGSTONE_HTTP_MAX_ATTEMPTS",
    "KINGSTONE_MAX_RESPONSE_BYTES",
    "KINGSTONE_ARTIFACTS_DIR",
    "KINGSTONE_DIAGNOSTIC_MAX_BYTES",
]


def test_defaults_when_nothing_is_set():
    config = load_config({})
    assert config == KingstoneConfig(
        pages_file=DEFAULT_PAGES_FILE,
        write_policy=WritePolicy.NEW_BOOKS_ONLY,
        soft_budget_seconds=7200.0,
        hard_limit_seconds=9000.0,
        http_timeout_seconds=float(acquisition.REQUEST_TIMEOUT_SECONDS),
        http_max_attempts=acquisition.MAX_ATTEMPTS,
        max_response_bytes=acquisition.MAX_RESPONSE_BYTES,
        artifacts_dir=DEFAULT_ARTIFACTS_DIR,
        diagnostic_max_bytes=2 * 1024 * 1024,
    )
    assert DEFAULT_SOFT_BUDGET_SECONDS == 7200
    assert DEFAULT_HARD_LIMIT_SECONDS == 9000


def test_the_config_is_frozen():
    config = load_config({})
    with pytest.raises(AttributeError):
        config.soft_budget_seconds = 1.0  # type: ignore[misc]


def test_every_key_can_be_set():
    config = load_config(
        {
            PAGES_FILE_ENV: "/data/pages.txt",
            WRITE_POLICY_ENV: "normal",
            "KINGSTONE_SOFT_RUN_BUDGET_SECONDS": "120.5",
            "CRAWLER_RUN_HARD_LIMIT_SECONDS": "600",
            "KINGSTONE_HTTP_TIMEOUT_SECONDS": "12",
            "KINGSTONE_HTTP_MAX_ATTEMPTS": "1",
            "KINGSTONE_MAX_RESPONSE_BYTES": "2048",
            "KINGSTONE_ARTIFACTS_DIR": "/var/kingstone-artifacts",
            "KINGSTONE_DIAGNOSTIC_MAX_BYTES": "4096",
        }
    )
    assert config == KingstoneConfig(
        pages_file=Path("/data/pages.txt"),
        write_policy=WritePolicy.NORMAL,
        soft_budget_seconds=120.5,
        hard_limit_seconds=600.0,
        http_timeout_seconds=12.0,
        http_max_attempts=1,
        max_response_bytes=2048,
        artifacts_dir=Path("/var/kingstone-artifacts"),
        diagnostic_max_bytes=4096,
    )


def test_the_default_artifacts_dir_is_crawler_artifacts_next_to_the_package():
    assert DEFAULT_ARTIFACTS_DIR == Path(__file__).resolve().parents[1] / "artifacts"
    assert DEFAULT_DIAGNOSTIC_MAX_BYTES == 2 * 1024 * 1024
    assert load_config({"KINGSTONE_ARTIFACTS_DIR": "   "}).artifacts_dir == DEFAULT_ARTIFACTS_DIR


@pytest.mark.parametrize("value", ["0", "-5", "1.5", "abc", "1e6"])
def test_a_diagnostic_cap_must_be_a_positive_whole_number(value):
    with pytest.raises(KingstoneConfigError, match="KINGSTONE_DIAGNOSTIC_MAX_BYTES"):
        load_config({"KINGSTONE_DIAGNOSTIC_MAX_BYTES": value})


def test_surrounding_whitespace_is_ignored_in_values():
    config = load_config({"KINGSTONE_SOFT_RUN_BUDGET_SECONDS": "  900 ", PAGES_FILE_ENV: "  /data/p.txt  "})
    assert config.soft_budget_seconds == 900.0
    assert config.pages_file == Path("/data/p.txt")


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_values_count_as_unset(blank):
    env = {key: blank for key in _ENV_KEYS}
    config = load_config(env)
    assert config == load_config({})


# --- seconds: finite and > 0 -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "KINGSTONE_SOFT_RUN_BUDGET_SECONDS",
        "CRAWLER_RUN_HARD_LIMIT_SECONDS",
        "KINGSTONE_HTTP_TIMEOUT_SECONDS",
    ],
)
@pytest.mark.parametrize("value", ["abc", "3 300s", "1,5"])
def test_seconds_must_be_numbers(key, value):
    with pytest.raises(KingstoneConfigError) as info:
        load_config({key: value})
    assert key in str(info.value)
    assert value not in str(info.value)


@pytest.mark.parametrize("key", ["KINGSTONE_HTTP_TIMEOUT_SECONDS", "KINGSTONE_SOFT_RUN_BUDGET_SECONDS", "CRAWLER_RUN_HARD_LIMIT_SECONDS"])
@pytest.mark.parametrize("value", ["0", "-1", "-0.5"])
def test_seconds_must_be_positive(key, value):
    with pytest.raises(KingstoneConfigError) as info:
        load_config({key: value})
    assert key in str(info.value)


@pytest.mark.parametrize("key", ["KINGSTONE_HTTP_TIMEOUT_SECONDS", "KINGSTONE_SOFT_RUN_BUDGET_SECONDS", "CRAWLER_RUN_HARD_LIMIT_SECONDS"])
@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "Infinity", "1e400"])
def test_seconds_must_be_finite(key, value):
    with pytest.raises(KingstoneConfigError) as info:
        load_config({key: value})
    assert key in str(info.value)


def test_soft_budget_must_be_below_the_hard_limit():
    with pytest.raises(KingstoneConfigError) as info:
        load_config({"KINGSTONE_SOFT_RUN_BUDGET_SECONDS": "3600", "CRAWLER_RUN_HARD_LIMIT_SECONDS": "3600"})
    assert "KINGSTONE_SOFT_RUN_BUDGET_SECONDS" in str(info.value)
    assert "CRAWLER_RUN_HARD_LIMIT_SECONDS" in str(info.value)


def test_soft_budget_above_the_default_hard_limit_is_rejected():
    with pytest.raises(KingstoneConfigError):
        load_config({"KINGSTONE_SOFT_RUN_BUDGET_SECONDS": "9001"})


def test_soft_budget_below_a_lowered_hard_limit_is_accepted():
    config = load_config({"KINGSTONE_SOFT_RUN_BUDGET_SECONDS": "100", "CRAWLER_RUN_HARD_LIMIT_SECONDS": "101"})
    assert (config.soft_budget_seconds, config.hard_limit_seconds) == (100.0, 101.0)


# --- counts: whole numbers, at least 1 --------------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["KINGSTONE_HTTP_MAX_ATTEMPTS", "KINGSTONE_MAX_RESPONSE_BYTES"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_counts_must_be_at_least_one(key, value):
    with pytest.raises(KingstoneConfigError) as info:
        load_config({key: value})
    assert key in str(info.value)


@pytest.mark.parametrize("key", ["KINGSTONE_HTTP_MAX_ATTEMPTS", "KINGSTONE_MAX_RESPONSE_BYTES"])
@pytest.mark.parametrize("value", ["abc", "2.5", "1e3", "nan", "inf", "+3", "3 4"])
def test_counts_must_be_whole_numbers(key, value):
    with pytest.raises(KingstoneConfigError) as info:
        load_config({key: value})
    assert key in str(info.value)
    assert value not in str(info.value)


def test_counts_accept_plain_whole_numbers():
    config = load_config({"KINGSTONE_HTTP_MAX_ATTEMPTS": "5", "KINGSTONE_MAX_RESPONSE_BYTES": "1"})
    assert config.http_max_attempts == 5
    assert config.max_response_bytes == 1


def test_error_messages_name_the_key_of_the_first_bad_value():
    with pytest.raises(KingstoneConfigError) as info:
        load_config({"KINGSTONE_HTTP_MAX_ATTEMPTS": "0", "KINGSTONE_MAX_RESPONSE_BYTES": "x"})
    assert "KINGSTONE_HTTP_MAX_ATTEMPTS" in str(info.value)


def test_config_error_is_a_value_error():
    assert issubclass(KingstoneConfigError, ValueError)


# --- write policy (CB-07 Phase 5): default new-books-only, two legal values -------------------------------------------


def test_write_policy_defaults_to_new_books_only():
    assert load_config({}).write_policy is WritePolicy.NEW_BOOKS_ONLY


@pytest.mark.parametrize(("raw", "policy"), [("normal", WritePolicy.NORMAL), ("new-books-only", WritePolicy.NEW_BOOKS_ONLY)])
def test_write_policy_accepts_the_two_legal_values(raw, policy):
    assert load_config({WRITE_POLICY_ENV: raw}).write_policy is policy


def test_write_policy_surrounding_whitespace_is_ignored():
    assert load_config({WRITE_POLICY_ENV: "  normal  "}).write_policy is WritePolicy.NORMAL


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_write_policy_counts_as_unset_and_takes_the_default(blank):
    assert load_config({WRITE_POLICY_ENV: blank}).write_policy is WritePolicy.NEW_BOOKS_ONLY


@pytest.mark.parametrize("value", ["Normal", "new_books_only", "all-books", "all", "0"])
def test_write_policy_rejects_any_other_value_and_names_the_key(value):
    with pytest.raises(KingstoneConfigError) as info:
        load_config({WRITE_POLICY_ENV: value})
    assert WRITE_POLICY_ENV in str(info.value)
    assert value not in str(info.value)
