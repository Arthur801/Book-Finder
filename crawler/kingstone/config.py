"""Kingstone run configuration: the environment keys of the Kingstone mode, read and validated before any work.

The loader, the validation rules and the error texts are those of ``catalog_core.run_config``. This module supplies the
Kingstone keys, defaults and error class, and keeps every name the CLI and the tests import from here:

- ``load_config(env) -> KingstoneConfig`` is pure: it takes a mapping, reads no file and makes no request;
- ``KingstoneConfig`` is the generic ``CategoryRunConfig`` (the same fields);
- ``KingstoneConfigError`` is a ``CategoryConfigError`` (still a ``ValueError``): the caller maps it to exit code 2.

``KINGSTONE_WRITE_POLICY`` (``normal`` or ``new-books-only``, default ``normal``). ``KINGSTONE_ARTIFACTS_DIR`` (default
``crawler/artifacts``, located relative to the package, not the working directory) is the root of the run artifacts:
``kingstone/last-run.json``, ``kingstone/history/`` and ``kingstone/diagnostics/``. ``KINGSTONE_DIAGNOSTIC_MAX_BYTES``
(default 2 MiB) caps one saved diagnostic HTML file. The alert command is not part of this module (no alert command:
plan v12 §8).
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
from kingstone import acquisition
from kingstone.page_list import PAGES_FILE_ENV, resolve_pages_file

WRITE_POLICY_ENV = "KINGSTONE_WRITE_POLICY"
DEFAULT_WRITE_POLICY = WritePolicy.NORMAL  # Phase 7 user decision: an ISBN match attaches, so the Book links to both stores
SOFT_BUDGET_ENV = "KINGSTONE_SOFT_RUN_BUDGET_SECONDS"
HTTP_TIMEOUT_ENV = "KINGSTONE_HTTP_TIMEOUT_SECONDS"
HTTP_MAX_ATTEMPTS_ENV = "KINGSTONE_HTTP_MAX_ATTEMPTS"
MAX_RESPONSE_BYTES_ENV = "KINGSTONE_MAX_RESPONSE_BYTES"
ARTIFACTS_DIR_ENV = "KINGSTONE_ARTIFACTS_DIR"
DIAGNOSTIC_MAX_BYTES_ENV = "KINGSTONE_DIAGNOSTIC_MAX_BYTES"

DEFAULT_SOFT_BUDGET_SECONDS = 72000
DEFAULT_HARD_LIMIT_SECONDS = 79200
# crawler/artifacts, located relative to the package, not the working directory (same rule as the Books artifacts).
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
    "KingstoneConfig",
    "KingstoneConfigError",
    "load_config",
]


class KingstoneConfigError(CategoryConfigError):
    """A Kingstone setting is missing, malformed or out of range. The message names the key."""


KingstoneConfig = CategoryRunConfig  # the same frozen dataclass: fields, equality and isinstance are the generic ones


def kingstone_spec() -> CategoryConfigSpec:
    """The Kingstone keys and defaults. Built per call, so the acquisition defaults are read at call time."""
    return CategoryConfigSpec(
        error_class=KingstoneConfigError,
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


def load_config(env: Mapping[str, str]) -> KingstoneConfig:
    """The validated Kingstone settings. Raises ``KingstoneConfigError`` for any invalid value."""
    return load_category_config(env, kingstone_spec())
