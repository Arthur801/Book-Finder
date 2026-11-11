"""Alert reasons for one Kingstone run (plan v12 §8): the Kingstone names of ``catalog_core.run_alerts``.

The reasons, the order, the streak rule and the ``challenge`` backlog note are documented in
``catalog_core.run_alerts``. This module only re-exports them unchanged for the Kingstone CLI, artifacts and tests.
"""

from __future__ import annotations

from catalog_core.run_alerts import (
    BUSY_REASON,
    FAILED_STATUS,
    SCHEMA_REASON,
    STREAK_LENGTH,
    alert_reasons,
    pages_not_reached_streak,
)

__all__ = [
    "BUSY_REASON",
    "FAILED_STATUS",
    "SCHEMA_REASON",
    "STREAK_LENGTH",
    "alert_reasons",
    "pages_not_reached_streak",
]
