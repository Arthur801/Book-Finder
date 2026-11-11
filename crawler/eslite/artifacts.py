"""Run artifacts of the Eslite adapter (plan v12 §8): the Eslite names of ``catalog_core.run_artifacts``.

Layout under the artifacts root (``ESLITE_ARTIFACTS_DIR``, default ``crawler/artifacts``)::

    eslite/last-run.json           the newest terminal record (atomic overwrite)
    eslite/history/<run_id>.json   one summary per terminal record, at most HISTORY_RETAIN files (oldest deleted)
    eslite/diagnostics/            saved parse-error HTML (eslite.diagnostics)
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from catalog_core import run_artifacts as _generic
from catalog_core.category_ledger import CategoryReport
from catalog_core.models import ProviderCode
from catalog_core.run_artifacts import (
    DIAGNOSTICS_DIR_NAME,
    HISTORY_DIR_NAME,
    HISTORY_RETAIN,
    LAST_RUN_NAME,
    atomic_write_bytes,
    atomic_write_json,
)

__all__ = [
    "DIAGNOSTICS_DIR_NAME",
    "ESLITE_DIR_NAME",
    "HISTORY_DIR_NAME",
    "HISTORY_RETAIN",
    "LAST_RUN_NAME",
    "PROVIDER",
    "EsliteArtifacts",
    "atomic_write_bytes",
    "atomic_write_json",
    "read_history",
    "record_from_report",
    "record_pre_run",
]

log = logging.getLogger("eslite.artifacts")

ESLITE_DIR_NAME = "eslite"
PROVIDER = ProviderCode.ESLITE.value


class EsliteArtifacts(_generic.CategoryArtifacts):
    """Writes the Eslite run artifacts under one artifacts root. Construction does no I/O."""

    def __init__(self, root: Path, *, history_retain: int = HISTORY_RETAIN) -> None:
        super().__init__(root, directory_name=ESLITE_DIR_NAME, logger_name="eslite.artifacts", history_retain=history_retain)


def record_from_report(report: CategoryReport) -> dict[str, Any]:
    """The terminal record of a run that went through ``run_pages``. ``alert_reasons`` is added by ``finalize``.

    ``restricted_skipped`` is the age-restricted cards skipped at the list and detail stages (not failures).
    """
    return _with_restricted_skipped(_generic.record_from_report(report), report.items_excluded)


def record_pre_run(
    *,
    run_id: str,
    status: str,
    exit_code: int,
    reason: str | None,
    write_policy: str,
    started_at: datetime,
    finished_at: datetime,
    error: str | None = None,
) -> dict[str, Any]:
    """The minimal terminal record of a result before or instead of the run: every count is 0, the page count is unknown."""
    return _with_restricted_skipped(
        _generic.record_pre_run(
            provider=PROVIDER,
            run_id=run_id,
            status=status,
            exit_code=exit_code,
            reason=reason,
            write_policy=write_policy,
            started_at=started_at,
            finished_at=finished_at,
            error=error,
        ),
        0,
    )


def _with_restricted_skipped(record: dict[str, Any], restricted_skipped: int) -> dict[str, Any]:
    """The record with ``restricted_skipped`` placed right after ``policy_skipped`` (the key order is part of the record)."""
    ordered: dict[str, Any] = {}
    for key, value in record.items():
        ordered[key] = value
        if key == "policy_skipped":
            ordered["restricted_skipped"] = restricted_skipped
    return ordered


def read_history(history_dir: Path) -> list[dict[str, Any]]:
    """The readable history entries, newest ``finished_at`` first. A missing directory is empty. Never raises."""
    return _generic.read_history(history_dir, log)
