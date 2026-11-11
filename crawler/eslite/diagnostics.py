"""Diagnostic HTML files for Eslite pages that failed to parse (plan v12 §8).

The rules (file name, byte cap, retention, never-raises) are those of ``catalog_core.run_diagnostics``. This module
binds them to the ``eslite.diagnostics`` logger.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from catalog_core import run_diagnostics as _generic
from catalog_core.run_diagnostics import DIAGNOSTIC_RETAIN

__all__ = ["DIAGNOSTIC_RETAIN", "DiagnosticWriter", "log"]

log = logging.getLogger("eslite.diagnostics")


class DiagnosticWriter(_generic.DiagnosticWriter):
    """Saves Eslite diagnostic HTML into ``directory``. ``clock`` (UTC) is injected so tests control the names."""

    def __init__(
        self,
        directory: Path,
        *,
        max_bytes: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        retain: int = DIAGNOSTIC_RETAIN,
    ) -> None:
        super().__init__(directory, max_bytes=max_bytes, logger_name="eslite.diagnostics", clock=clock, retain=retain)
