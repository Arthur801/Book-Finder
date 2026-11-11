"""Run artifacts of the Kingstone adapter (plan v12 §8): the Kingstone names of ``catalog_core.run_artifacts``.

Layout under the artifacts root (``KINGSTONE_ARTIFACTS_DIR``, default ``crawler/artifacts``)::

    kingstone/last-run.json           the newest terminal record (atomic overwrite)
    kingstone/history/<run_id>.json   one summary per terminal record, at most HISTORY_RETAIN files (oldest deleted)
    kingstone/diagnostics/            saved parse-error HTML (kingstone.diagnostics)

The record shape, the order of writes, the redaction and the failure rules are those of ``catalog_core.run_artifacts``.
This module binds them to the ``kingstone`` directory, the ``KINGSTONE`` provider and the ``kingstone.artifacts``
logger, and keeps every name the CLI and the tests import from here.
"""

from __future__ import annotations

import logging
import os  # noqa: F401 - tests patch os.replace / os.fsync through this module attribute (the shared os module)
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
    "HISTORY_DIR_NAME",
    "HISTORY_RETAIN",
    "KINGSTONE_DIR_NAME",
    "LAST_RUN_NAME",
    "PROVIDER",
    "KingstoneArtifacts",
    "atomic_write_bytes",
    "atomic_write_json",
    "log",
    "read_history",
    "record_from_report",
    "record_pre_run",
]

log = logging.getLogger("kingstone.artifacts")

KINGSTONE_DIR_NAME = "kingstone"
PROVIDER = ProviderCode.KINGSTONE.value


class KingstoneArtifacts(_generic.CategoryArtifacts):
    """Writes the Kingstone run artifacts under one artifacts root. Construction does no I/O."""

    def __init__(self, root: Path, *, history_retain: int = HISTORY_RETAIN) -> None:
        super().__init__(root, directory_name=KINGSTONE_DIR_NAME, logger_name="kingstone.artifacts", history_retain=history_retain)


def record_from_report(report: CategoryReport) -> dict[str, Any]:
    """The terminal record of a run that went through ``run_pages``. ``alert_reasons`` is added by ``publish``."""
    return _generic.record_from_report(report)


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
    return _generic.record_pre_run(
        provider=PROVIDER,
        run_id=run_id,
        status=status,
        exit_code=exit_code,
        reason=reason,
        write_policy=write_policy,
        started_at=started_at,
        finished_at=finished_at,
        error=error,
    )


def read_history(history_dir: Path) -> list[dict[str, Any]]:
    """The readable history entries, newest ``finished_at`` first. A missing directory is empty. Never raises."""
    return _generic.read_history(history_dir, log)
