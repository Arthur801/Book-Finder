"""Eslite run configuration: the environment keys of the Eslite mode, read and validated before any work.

The loader, the validation rules and the error texts are those of ``catalog_core.run_config``. This module supplies the
Eslite keys, defaults and error class, and keeps every name the CLI and the tests import from here:

- ``load_config(env) -> EsliteConfig`` is pure: it takes a mapping, reads no file and makes no request;
- ``EsliteConfig`` is the generic ``CategoryRunConfig`` (the same fields);
- ``EsliteConfigError`` is a ``CategoryConfigError`` (still a ``ValueError``): the caller maps it to exit code 2.

Defaults (provisional, user-approved until the page list exists, CB-08 §7): soft budget 7200 seconds, hard limit 9000
seconds (``CRAWLER_RUN_HARD_LIMIT_SECONDS``, shared with the other providers). ``ESLITE_WRITE_POLICY`` defaults to
``normal``. ``ESLITE_ARTIFACTS_DIR`` (default ``crawler/artifacts``) holds ``eslite/last-run.json``, ``eslite/history/`` and
``eslite/diagnostics/``. ``ESLITE_DIAGNOSTIC_MAX_BYTES`` (default 2 MiB) caps one saved diagnostic HTML file.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from catalog_core.models import WritePolicy
from catalog_core.run_config import (
    HARD_LIMIT_ENV,
    CategoryConfigError,
    CategoryConfigSpec,
    CategoryRunConfig,
    load_category_config,
)
from eslite import acquisition
from eslite.page_list import PAGES_FILE_ENV, resolve_pages_file

WRITE_POLICY_ENV = "ESLITE_WRITE_POLICY"
DEFAULT_WRITE_POLICY = WritePolicy.NORMAL
SOFT_BUDGET_ENV = "ESLITE_SOFT_RUN_BUDGET_SECONDS"
HTTP_TIMEOUT_ENV = "ESLITE_HTTP_TIMEOUT_SECONDS"
HTTP_MAX_ATTEMPTS_ENV = "ESLITE_HTTP_MAX_ATTEMPTS"
MAX_RESPONSE_BYTES_ENV = "ESLITE_MAX_RESPONSE_BYTES"
ARTIFACTS_DIR_ENV = "ESLITE_ARTIFACTS_DIR"
DIAGNOSTIC_MAX_BYTES_ENV = "ESLITE_DIAGNOSTIC_MAX_BYTES"

DEFAULT_SOFT_BUDGET_SECONDS = 7200  # provisional (user-approved, 2026-11-11): revisit once the page list exists
DEFAULT_HARD_LIMIT_SECONDS = 9000  # provisional; must stay above the soft budget
# crawler/artifacts, located relative to the package, not the working directory (same rule as the other providers).
DEFAULT_ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"
DEFAULT_DIAGNOSTIC_MAX_BYTES = 2 * 1024 * 1024

__all__ = [
    "ARTIFACTS_DIR_ENV",
    "DEFAULT_ARTIFACTS_DIR",
    "DEFAULT_DIAGNOSTIC_MAX_BYTES",
    "DEFAULT_HARD_LIMIT_SECONDS",
    "DEFAULT_SOFT_BUDGET_SECONDS",
    "DEFAULT_WRITE_POLICY",
    "DIAGNOSTIC_MAX_BYTES_ENV",
    "HARD_LIMIT_ENV",
    "HTTP_MAX_ATTEMPTS_ENV",
    "HTTP_TIMEOUT_ENV",
    "MAX_RESPONSE_BYTES_ENV",
    "SOFT_BUDGET_ENV",
    "WRITE_POLICY_ENV",
    "EsliteConfig",
    "EsliteConfigError",
    "load_config",
]


class EsliteConfigError(CategoryConfigError):
    """An Eslite setting is missing, malformed or out of range. The message names the key."""


EsliteConfig = CategoryRunConfig  # the same frozen dataclass: fields, equality and isinstance are the generic ones


def eslite_spec() -> CategoryConfigSpec:
    """The Eslite keys and defaults. Built per call, so the acquisition defaults are read at call time."""
    return CategoryConfigSpec(
        error_class=EsliteConfigError,
        pages_file_env=PAGES_FILE_ENV,
        resolve_pages_file=resolve_pages_file,
        write_policy_env=WRITE_POLICY_ENV,
        default_write_policy=DEFAULT_WRITE_POLICY,
        soft_budget_env=SOFT_BUDGET_ENV,
        default_soft_budget_seconds=DEFAULT_SOFT_BUDGET_SECONDS,
        default_hard_limit_seconds=DEFAULT_HARD_LIMIT_SECONDS,
        http_timeout_env=HTTP_TIMEOUT_ENV,
        default_http_timeout_seconds=acquisition.REQUEST_TIMEOUT_SECONDS,
        http_max_attempts_env=HTTP_MAX_ATTEMPTS_ENV,
        default_http_max_attempts=acquisition.MAX_ATTEMPTS,
        max_response_bytes_env=MAX_RESPONSE_BYTES_ENV,
        default_max_response_bytes=acquisition.MAX_RESPONSE_BYTES,
        artifacts_dir_env=ARTIFACTS_DIR_ENV,
        default_artifacts_dir=DEFAULT_ARTIFACTS_DIR,
        diagnostic_max_bytes_env=DIAGNOSTIC_MAX_BYTES_ENV,
        default_diagnostic_max_bytes=DEFAULT_DIAGNOSTIC_MAX_BYTES,
    )


def load_config(env: Mapping[str, str]) -> EsliteConfig:
    """The validated Eslite settings. Raises ``EsliteConfigError`` for any invalid value."""
    return load_category_config(env, eslite_spec())
