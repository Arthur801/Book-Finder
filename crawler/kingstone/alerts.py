"""Alert reasons for one Kingstone run (plan v12 §8): the one place that decides what is alerted.

An alert is a log line only (``ALERT`` on ``kingstone.cli``, WARNING); nothing is sent anywhere. The reasons:

- ``failed``: the run ended FAILED (includes the pre-run failures recorded by the CLI).
- ``schema_prerequisite_missing``: the post-011 schema preflight failed (``SCHEMA_PREREQUISITE_MISSING``).
- ``maintenance_busy``: the first connection found the Catalog lock held by a migration. A busy run that was orphaned
  mid-run is the runner's alert (plan v12 §8, Phase 6 M4), not this module's.
- ``unclassified_200``: at least one HTTP 200 page or detail body failed to parse (``parse_error``). Not a soft 404,
  not an acquisition failure. It is the conservative stand-in for ``challenge``: see below.
- ``zero_card_pages``: at least one page completed and every completed page listed zero cards.
- ``pages_not_reached_streak``: ``pages_not_reached`` was above 0 in the last ``STREAK_LENGTH`` runs (see below).

Not implemented: ``challenge``. Acquisition returns a 200 body and the parser fails closed on it, and no challenge
fixture exists yet, so a challenge cannot be told apart from another unparseable page (backlog CB-07). Until a fixture
exists, every 200 parse failure raises ``unclassified_200`` (any run status), so a challenge is never silently skipped.
Once a fixture exists, its recognisable part is split out as ``challenge`` and the rest stays ``unclassified_200``.

An all-Existing run that completed its pages triggers nothing.

Streak rule. The window is this run plus the two most recent readable history entries, newest first. Any entry whose
``pages_not_reached`` is 0 resets the streak. Entries that are missing, unreadable, or have no count (a pre-run
result) are not in the window: the streak is then not established, so no alert is raised (under-reporting is
preferred to a false alarm). When any history entry is unreadable, ``KingstoneArtifacts.publish`` does not evaluate
the streak at all: the unreadable entry could be one of the last runs, and skipping it could join older entries into a
false streak.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

FAILED_STATUS = "FAILED"
SCHEMA_REASON = "SCHEMA_PREREQUISITE_MISSING"
BUSY_REASON = "MAINTENANCE_BUSY"
STREAK_LENGTH = 3


def pages_not_reached_streak(current: int | None, history: Sequence[Mapping[str, Any]]) -> bool:
    """True when the current run and the two newest history entries all have ``pages_not_reached`` above 0.

    ``history`` is newest first and holds only the readable entries (``kingstone.artifacts.read_history``).
    """
    if not _is_count(current) or current <= 0:
        return False
    values = [current, *(entry.get("pages_not_reached") for entry in history[: STREAK_LENGTH - 1])]
    if len(values) < STREAK_LENGTH:
        return False
    return all(_is_count(value) and value > 0 for value in values)


def alert_reasons(
    *,
    status: str,
    reason: str | None,
    pages_completed: int,
    zero_card_pages: int,
    streak_reached: bool,
    parse_error_200_count: int = 0,
) -> list[str]:
    """The alert reasons of one run, in a fixed order. Empty when nothing is alerted.

    Order: failed, schema_prerequisite_missing, maintenance_busy, unclassified_200, zero_card_pages,
    pages_not_reached_streak. ``unclassified_200`` comes before ``zero_card_pages``: a parse failure means the page
    content is unknown, so it is reported before the weaker "parsed but empty" signal.
    """
    reasons: list[str] = []
    if status == FAILED_STATUS:
        reasons.append("failed")
    if reason == SCHEMA_REASON:
        reasons.append("schema_prerequisite_missing")
    if reason == BUSY_REASON:
        reasons.append("maintenance_busy")
    if parse_error_200_count > 0:
        reasons.append("unclassified_200")
    if pages_completed > 0 and zero_card_pages == pages_completed:
        reasons.append("zero_card_pages")
    if streak_reached:
        reasons.append("pages_not_reached_streak")
    return reasons


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
