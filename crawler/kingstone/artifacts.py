"""Run artifacts of the Kingstone adapter (plan v12 §8): the terminal JSON, the bounded history and the alert order.

Layout under the artifacts root (``KINGSTONE_ARTIFACTS_DIR``, default ``crawler/artifacts``)::

    kingstone/last-run.json           the newest terminal record (atomic overwrite)
    kingstone/history/<run_id>.json   one summary per terminal record, at most HISTORY_RETAIN files (oldest deleted)
    kingstone/diagnostics/            saved parse-error HTML (kingstone.diagnostics)

The history is for observability only. It is not a progress file and is never read for replay.

One record for every output. ``KingstoneArtifacts.finalize`` turns a record (from the report or the pre-run facts) into the
final record: it adds ``alert_reasons`` and redacts every string. The CLI prints that same final record as one stdout
JSON line, and ``KingstoneArtifacts.write`` stores it as ``last-run.json`` and as the history summary. So stdout,
last-run and history never disagree.

Order. ``finalize`` reads the history as it was before this run (so this run is never counted twice) and computes the
alert reasons. ``write`` then writes ``last-run.json``, then this run's history entry, and prunes the history. A failed
write is logged at ERROR and never raises, so ``write`` cannot stop the caller from printing the record.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from catalog_core.redact import redact
from kingstone.alerts import alert_reasons, pages_not_reached_streak
from kingstone.ledger import KingstoneReport

log = logging.getLogger("kingstone.artifacts")

KINGSTONE_DIR_NAME = "kingstone"
LAST_RUN_NAME = "last-run.json"
HISTORY_DIR_NAME = "history"
DIAGNOSTICS_DIR_NAME = "diagnostics"
HISTORY_RETAIN = 20
PROVIDER = "KINGSTONE"

_EMPTY_COUNTS: dict[str, Any] = {
    "pages_listed": 0,
    "pages_completed": 0,
    "pages_skipped": [],
    "pages_interrupted": 0,
    "pages_not_reached": None,  # unknown for a run that never reached its pages: not counted in the streak
    "zero_card_pages": 0,
    "parse_error_200_count": 0,
    "budget_exhausted": False,
    "items_listed": 0,
    "details_fetched": 0,
    "items_seen": 0,
    "existing_source": 0,
    "imported": 0,
    "isbn_attached": 0,
    "ambiguous_created": 0,
    "policy_skipped": 0,
    "failed": 0,
    "recovered_commit_count": 0,
    "identity_warning_count": 0,
    "failed_items": [],
    "http_attempts": 0,
    "http_failures": 0,
    "zero_progress_reason": None,
}


def record_from_report(report: KingstoneReport) -> dict[str, Any]:
    """The terminal record of a run that went through ``run_pages``. ``alert_reasons`` is added by ``publish``."""
    return {
        "run_id": report.run_id,
        "provider": report.provider_code.value,
        "status": report.status.value,
        "exit_code": report.exit_code,
        "reason": None,
        "error": report.error,
        "write_policy": report.write_policy.value,
        "started_at": report.started_at.isoformat(),
        "finished_at": report.finished_at.isoformat(),
        "pages_listed": report.pages_listed,
        "pages_completed": report.pages_completed,
        "pages_skipped": [{"url": page.url, "reason": page.reason, "message": page.message, "attempts": page.attempts} for page in report.pages_skipped],
        "pages_interrupted": report.pages_interrupted,
        "pages_not_reached": report.pages_not_reached,
        "zero_card_pages": report.zero_card_pages,
        "parse_error_200_count": report.parse_error_200_count,
        "budget_exhausted": report.budget_exhausted,
        "items_listed": report.items_listed,
        "details_fetched": report.details_fetched,
        "items_seen": report.items_seen,
        "existing_source": report.existing_source,
        "imported": report.imported,
        "isbn_attached": report.isbn_attached,
        "ambiguous_created": report.ambiguous_created,
        "policy_skipped": report.policy_skipped_count,
        "failed": report.failed,
        "recovered_commit_count": report.recovered_commit_count,
        "identity_warning_count": report.identity_warning_count,
        "failed_items": [
            {
                "list_url": item.list_url,
                "source_url": item.source_url,
                "external_id": item.external_id,
                "reason": item.reason,
                "message": item.message,
                "attempts": item.attempts,
            }
            for item in report.failed_items
        ],
        "http_attempts": report.http_attempts,
        "http_failures": report.http_failures,
        "zero_progress_reason": report.zero_progress_reason,
    }


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
    return {
        **_EMPTY_COUNTS,
        "run_id": run_id,
        "provider": PROVIDER,
        "status": status,
        "exit_code": exit_code,
        "reason": reason,
        "error": error,
        "write_policy": write_policy,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }


def read_history(history_dir: Path) -> list[dict[str, Any]]:
    """The readable history entries, newest ``finished_at`` first. A missing directory is empty.

    An entry that is not a JSON object with a run_id, a tz-aware finished_at, a status and a count (or null) is skipped
    with a WARNING on ``kingstone.artifacts``. Never raises.
    """
    return _read_history(history_dir)[0]


def _read_history(history_dir: Path) -> tuple[list[dict[str, Any]], int]:
    """``read_history`` plus the number of unreadable entries (their place in time is unknown)."""
    entries: list[tuple[datetime, dict[str, Any]]] = []
    unreadable = 0
    for path in _history_files(history_dir):
        entry = _read_entry(path)
        if entry is None:
            unreadable += 1
        else:
            entries.append((_finished(entry), entry))
    entries.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in entries], unreadable


class KingstoneArtifacts:
    """Writes the Kingstone run artifacts under one artifacts root. Construction does no I/O."""

    def __init__(self, root: Path, *, history_retain: int = HISTORY_RETAIN) -> None:
        self.directory = root / KINGSTONE_DIR_NAME
        self.last_run_path = self.directory / LAST_RUN_NAME
        self.history_dir = self.directory / HISTORY_DIR_NAME
        self.diagnostics_dir = self.directory / DIAGNOSTICS_DIR_NAME
        self._history_retain = history_retain

    def finalize(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """The final record: the alert reasons (from the history before this run) added, every string redacted. Writes nothing."""
        history, unreadable = _read_history(self.history_dir)
        if unreadable:
            # An unreadable entry may be one of the last runs, and its count is unknown: skipping it could join two
            # older entries into a false streak. The streak is not evaluated at all (under-reporting over a false alarm).
            log.warning("pages_not_reached streak not evaluated: %d unreadable history entr%s", unreadable, "y" if unreadable == 1 else "ies")
            streak = False
        else:
            streak = pages_not_reached_streak(record["pages_not_reached"], history)
        reasons = alert_reasons(
            status=str(record["status"]),
            reason=record["reason"],
            pages_completed=int(record["pages_completed"]),
            zero_card_pages=int(record["zero_card_pages"]),
            streak_reached=streak,
            parse_error_200_count=int(record["parse_error_200_count"]),
        )
        return _redact_tree({**record, "alert_reasons": reasons})

    def write(self, final: Mapping[str, Any]) -> None:
        """Writes ``last-run.json`` and this run's history summary, then prunes the history. Never raises."""
        try:
            atomic_write_json(self.last_run_path, final)
        except Exception as exc:  # noqa: BLE001 - artifacts never change the run's result
            log.error("could not write %s: %s", self.last_run_path, _describe(exc))

        try:
            summary = {
                "run_id": final["run_id"],
                "finished_at": final["finished_at"],
                "status": final["status"],
                "exit_code": final["exit_code"],
                "reason": final["reason"],
                "pages_not_reached": final["pages_not_reached"],
                "alert_reasons": final["alert_reasons"],
            }
            atomic_write_json(self.history_dir / f"{final['run_id']}.json", summary)
            self._prune_history()
        except Exception as exc:  # noqa: BLE001 - artifacts never change the run's result
            log.error("could not write the kingstone history under %s: %s", self.history_dir, _describe(exc))

    def publish(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """``finalize`` then ``write``. Returns the final record."""
        final = self.finalize(record)
        self.write(final)
        return final

    def _prune_history(self) -> None:
        """Keeps the newest ``history_retain`` files by finished_at. Unreadable files count as the oldest."""
        files = _history_files(self.history_dir)
        ranked = sorted(files, key=lambda path: _finished_or_min(path))
        for path in ranked[: max(0, len(ranked) - self._history_retain)]:
            try:
                path.unlink()
            except OSError as exc:
                log.error("could not delete the old history entry %s: %s", path.name, _describe(exc))


def atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    """Writes ``data`` as UTF-8 JSON atomically: a temp file in the same folder, fsync, then ``os.replace``."""
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Replaces ``path`` with ``payload`` in one step: the temp file is removed if anything fails before the replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    """Best effort: makes the rename durable on POSIX. Platforms that cannot open a directory skip it."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _history_files(history_dir: Path) -> list[Path]:
    try:
        return sorted(path for path in history_dir.glob("*.json") if path.is_file())
    except OSError:
        return []


def _read_entry(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        log.warning("skipping unreadable history entry %s: %s", path.name, _describe(exc))
        return None
    if not _valid_entry(data):
        log.warning("skipping invalid history entry %s", path.name)
        return None
    return data


def _valid_entry(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    count = data.get("pages_not_reached")
    if not isinstance(data.get("run_id"), str) or not isinstance(data.get("status"), str):
        return False
    if count is not None and (not isinstance(count, int) or isinstance(count, bool)):
        return False
    return _parse_finished(data.get("finished_at")) is not None


def _finished(entry: Mapping[str, Any]) -> datetime:
    parsed = _parse_finished(entry.get("finished_at"))
    assert parsed is not None  # guaranteed by _valid_entry
    return parsed


def _finished_or_min(path: Path) -> datetime:
    entry = _read_entry_quiet(path)
    parsed = _parse_finished(entry.get("finished_at")) if entry is not None else None
    return parsed if parsed is not None else datetime.min.replace(tzinfo=UTC)


def _read_entry_quiet(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        return None
    return data if _valid_entry(data) else None


def _parse_finished(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _redact_tree(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, Mapping):
        return {key: _redact_tree(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_redact_tree(item) for item in value]
    return value


def _describe(exc: BaseException) -> str:
    return redact(f"{type(exc).__name__}: {exc}")
