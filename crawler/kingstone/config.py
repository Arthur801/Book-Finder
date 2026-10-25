"""Kingstone run configuration: the environment keys of the Kingstone mode, read and validated before any work.

``load_config`` is pure: it takes a mapping, reads no file and makes no request. Every problem raises
``KingstoneConfigError`` (the caller maps it to exit code 2). A value that is blank or whitespace counts as unset.
Error messages name the key. A value is echoed only when it is a finite number that was rejected for its range;
anything that is not a number is never echoed.

Write policy, diagnostic size and the alert command are not part of this module (Phase 5 and 6).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from kingstone import acquisition
from kingstone.page_list import PAGES_FILE_ENV, resolve_pages_file

SOFT_BUDGET_ENV = "KINGSTONE_SOFT_RUN_BUDGET_SECONDS"
HARD_LIMIT_ENV = "CRAWLER_RUN_HARD_LIMIT_SECONDS"
HTTP_TIMEOUT_ENV = "KINGSTONE_HTTP_TIMEOUT_SECONDS"
HTTP_MAX_ATTEMPTS_ENV = "KINGSTONE_HTTP_MAX_ATTEMPTS"
MAX_RESPONSE_BYTES_ENV = "KINGSTONE_MAX_RESPONSE_BYTES"

DEFAULT_SOFT_BUDGET_SECONDS = 3300
DEFAULT_HARD_LIMIT_SECONDS = 3600


class KingstoneConfigError(ValueError):
    """A Kingstone setting is missing, malformed or out of range. The message names the key."""


@dataclass(frozen=True)
class KingstoneConfig:
    pages_file: Path
    soft_budget_seconds: float  # no new request starts once the run has less budget than its wait
    hard_limit_seconds: float  # the run limit the host enforces; the soft budget must stay below it
    http_timeout_seconds: float
    http_max_attempts: int
    max_response_bytes: int


def load_config(env: Mapping[str, str]) -> KingstoneConfig:
    """The validated Kingstone settings. Raises ``KingstoneConfigError`` for any invalid value."""
    soft = _seconds(env, SOFT_BUDGET_ENV, DEFAULT_SOFT_BUDGET_SECONDS)
    hard = _seconds(env, HARD_LIMIT_ENV, DEFAULT_HARD_LIMIT_SECONDS)
    if soft >= hard:
        raise KingstoneConfigError(f"{SOFT_BUDGET_ENV} must be less than {HARD_LIMIT_ENV}")
    return KingstoneConfig(
        pages_file=resolve_pages_file(env.get(PAGES_FILE_ENV) or ""),
        soft_budget_seconds=soft,
        hard_limit_seconds=hard,
        http_timeout_seconds=_seconds(env, HTTP_TIMEOUT_ENV, acquisition.REQUEST_TIMEOUT_SECONDS),
        http_max_attempts=_count(env, HTTP_MAX_ATTEMPTS_ENV, acquisition.MAX_ATTEMPTS),
        max_response_bytes=_count(env, MAX_RESPONSE_BYTES_ENV, acquisition.MAX_RESPONSE_BYTES),
    )


def _raw(env: Mapping[str, str], key: str) -> str | None:
    """The stripped value, or None when the key is absent or blank."""
    value = env.get(key)
    if value is None or not value.strip():
        return None
    return value.strip()


def _seconds(env: Mapping[str, str], key: str, default: float) -> float:
    raw = _raw(env, key)
    if raw is None:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        raise KingstoneConfigError(f"{key} must be a number of seconds") from None
    if not math.isfinite(value):
        raise KingstoneConfigError(f"{key} must be a finite number of seconds")
    if value <= 0:
        raise KingstoneConfigError(f"{key} must be greater than 0, not {value:g}")
    return value


def _count(env: Mapping[str, str], key: str, default: int) -> int:
    raw = _raw(env, key)
    if raw is None:
        return default
    if re.fullmatch(r"[0-9]+", raw) is None:
        raise KingstoneConfigError(f"{key} must be a whole number")
    value = int(raw)
    if value < 1:
        raise KingstoneConfigError(f"{key} must be at least 1, not {value}")
    return value
