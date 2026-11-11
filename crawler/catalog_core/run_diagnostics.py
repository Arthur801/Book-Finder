"""Diagnostic HTML files for category pages that failed to parse (plan v12 §8). Provider neutral.

``DiagnosticWriter.save_html`` is the sink the category run calls for a parse error on a list or detail page. It stores
the response body only: no headers, no cookies. Rules:

- File name ``<UTC time>-<list|detail>-<code>.html``, where the time is ``%Y%m%dT%H%M%S%fZ`` and the code is the
  category code (list) or the provider's detail code. Two saves in the same microsecond take the next microsecond, so
  the names stay in time order.
- The file is at most ``max_bytes`` bytes (UTF-8). A longer body is cut at a character boundary and the cut is marked
  by a comment at the end of the file, which is counted in the limit.
- Only the newest ``retain`` files are kept (by name, which sorts by time).
- A write failure is logged at WARNING on ``logger_name`` and dropped. The writer never raises, so a run never depends
  on it.

The directory is a parameter (the provider's ``diagnostics`` folder); a provider's module binds it and its logger name.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from catalog_core.run_artifacts import atomic_write_bytes

DIAGNOSTIC_RETAIN = 20
_UNSAFE = re.compile(r"[^A-Za-z0-9]")


class DiagnosticWriter:
    """Saves diagnostic HTML into ``directory``. ``clock`` (UTC) is injected so tests control the names."""

    def __init__(
        self,
        directory: Path,
        *,
        max_bytes: int,
        logger_name: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        retain: int = DIAGNOSTIC_RETAIN,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        self._directory = directory
        self._max_bytes = max_bytes
        self._clock = clock
        self._retain = retain
        self._log = logging.getLogger(logger_name)

    def save_html(self, *, kind: str, code: str, html: str) -> Path | None:
        """Writes one file and prunes the folder. Returns the path, or None when the write failed (logged)."""
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            payload = self._capped(html.encode("utf-8"))
            path = self._new_path(kind, code)
            atomic_write_bytes(path, payload)
        except OSError as exc:
            self._log.warning("could not save the %s diagnostic for %s: %s", kind, code, type(exc).__name__)
            return None
        self._prune()
        return path

    def _new_path(self, kind: str, code: str) -> Path:
        safe_code = _UNSAFE.sub("", code) or "unknown"
        moment = self._clock()
        while True:
            name = f"{moment.strftime('%Y%m%dT%H%M%S%fZ')}-{kind}-{safe_code}.html"
            path = self._directory / name
            if not path.exists():
                return path
            moment += timedelta(microseconds=1)

    def _capped(self, data: bytes) -> bytes:
        if len(data) <= self._max_bytes:
            return data
        note = f"\n<!-- diagnostic truncated at {self._max_bytes} bytes; the original body had {len(data)} bytes -->\n".encode()
        keep = self._max_bytes - len(note)
        if keep <= 0:
            return _whole_characters(data[: self._max_bytes])
        return _whole_characters(data[:keep]) + note

    def _prune(self) -> None:
        try:
            files = sorted(path for path in self._directory.glob("*.html") if path.is_file())
        except OSError:
            return
        for path in files[: max(0, len(files) - self._retain)]:
            try:
                path.unlink()
            except OSError as exc:
                self._log.warning("could not delete the old diagnostic %s: %s", path.name, type(exc).__name__)


def _whole_characters(data: bytes) -> bytes:
    """``data`` without a trailing partial UTF-8 character, so the cut file stays valid UTF-8."""
    return data.decode("utf-8", errors="ignore").encode("utf-8")
