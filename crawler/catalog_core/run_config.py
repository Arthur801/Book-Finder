"""Category-run configuration: the environment settings of one provider's run, read and validated before any work.

``load_category_config`` is pure: it takes a mapping and a ``CategoryConfigSpec``, reads no file and makes no request.
Every problem raises the spec's ``error_class`` (a ``CategoryConfigError``, a ``ValueError``; the caller maps it to
exit code 2). A value that is blank or whitespace counts as unset. Error messages name the key. A value is echoed only
when it is a finite number that was rejected for its range; anything that is not a number is never echoed.

The spec carries the env key names and the provider's defaults, so each provider reads its own keys. The one shared key
is ``CRAWLER_RUN_HARD_LIMIT_SECONDS`` (``HARD_LIMIT_ENV``): the local runner passes it into the container for every
provider. A write policy is validated against ``WritePolicy``; its error message never echoes the value.

An env value for a path is used as given (the pages file is resolved by the provider's resolver).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from catalog_core.models import WritePolicy

HARD_LIMIT_ENV = "CRAWLER_RUN_HARD_LIMIT_SECONDS"


class CategoryConfigError(ValueError):
    """A category-run setting is missing, malformed or out of range. The message names the key."""


@dataclass(frozen=True)
class CategoryRunConfig:
    pages_file: Path
    write_policy: WritePolicy
    soft_budget_seconds: float  # no new request starts once the run has less budget than its wait
    hard_limit_seconds: float  # the run limit the host enforces; the soft budget must stay below it
    http_timeout_seconds: float
    http_max_attempts: int
    max_response_bytes: int
    artifacts_dir: Path  # the root of the run artifacts; a provider's files live in its own folder under it
    diagnostic_max_bytes: int  # the size cap of one saved diagnostic HTML file, in bytes


@dataclass(frozen=True)
class CategoryConfigSpec:
    """The env keys, defaults and error class of one provider's category run. Pure data; no I/O."""

    error_class: type[CategoryConfigError]
    pages_file_env: str
    resolve_pages_file: Callable[[str], Path]
    write_policy_env: str
    default_write_policy: WritePolicy
    soft_budget_env: str
    default_soft_budget_seconds: float
    default_hard_limit_seconds: float
    http_timeout_env: str
    default_http_timeout_seconds: float
    http_max_attempts_env: str
    default_http_max_attempts: int
    max_response_bytes_env: str
    default_max_response_bytes: int
    artifacts_dir_env: str
    default_artifacts_dir: Path
    diagnostic_max_bytes_env: str
    default_diagnostic_max_bytes: int
    hard_limit_env: str = HARD_LIMIT_ENV


def load_category_config(env: Mapping[str, str], spec: CategoryConfigSpec) -> CategoryRunConfig:
    """The validated settings of one provider. Raises ``spec.error_class`` for any invalid value."""
    soft = _seconds(env, spec, spec.soft_budget_env, spec.default_soft_budget_seconds)
    hard = _seconds(env, spec, spec.hard_limit_env, spec.default_hard_limit_seconds)
    if soft >= hard:
        raise spec.error_class(f"{spec.soft_budget_env} must be less than {spec.hard_limit_env}")
    return CategoryRunConfig(
        pages_file=spec.resolve_pages_file(env.get(spec.pages_file_env) or ""),
        write_policy=_write_policy(env, spec),
        soft_budget_seconds=soft,
        hard_limit_seconds=hard,
        http_timeout_seconds=_seconds(env, spec, spec.http_timeout_env, spec.default_http_timeout_seconds),
        http_max_attempts=_count(env, spec, spec.http_max_attempts_env, spec.default_http_max_attempts),
        max_response_bytes=_count(env, spec, spec.max_response_bytes_env, spec.default_max_response_bytes),
        artifacts_dir=_artifacts_dir(env, spec),
        diagnostic_max_bytes=_count(env, spec, spec.diagnostic_max_bytes_env, spec.default_diagnostic_max_bytes),
    )


def _raw(env: Mapping[str, str], key: str) -> str | None:
    """The stripped value, or None when the key is absent or blank."""
    value = env.get(key)
    if value is None or not value.strip():
        return None
    return value.strip()


def _write_policy(env: Mapping[str, str], spec: CategoryConfigSpec) -> WritePolicy:
    raw = _raw(env, spec.write_policy_env)
    if raw is None:
        return spec.default_write_policy
    try:
        return WritePolicy(raw)
    except ValueError:
        legal = ", ".join(policy.value for policy in WritePolicy)
        raise spec.error_class(f"{spec.write_policy_env} must be one of: {legal}") from None


def _seconds(env: Mapping[str, str], spec: CategoryConfigSpec, key: str, default: float) -> float:
    raw = _raw(env, key)
    if raw is None:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        raise spec.error_class(f"{key} must be a number of seconds") from None
    if not math.isfinite(value):
        raise spec.error_class(f"{key} must be a finite number of seconds")
    if value <= 0:
        raise spec.error_class(f"{key} must be greater than 0, not {value:g}")
    return value


def _artifacts_dir(env: Mapping[str, str], spec: CategoryConfigSpec) -> Path:
    raw = _raw(env, spec.artifacts_dir_env)
    return spec.default_artifacts_dir if raw is None else Path(raw)


def _count(env: Mapping[str, str], spec: CategoryConfigSpec, key: str, default: int) -> int:
    raw = _raw(env, key)
    if raw is None:
        return default
    if re.fullmatch(r"[0-9]+", raw) is None:
        raise spec.error_class(f"{key} must be a whole number")
    value = int(raw)
    if value < 1:
        raise spec.error_class(f"{key} must be at least 1, not {value}")
    return value
