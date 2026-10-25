"""The database connection of one run, replaced when it breaks (crawler.md §13.1).

A run holds one connection for a long time. When the server closes it, or the network drops, every later use fails
on the dead connection, so a retry would only fail again. ``DatabaseSession`` owns the connection: it checks
``closed``/``broken`` on each access and opens a new one through the injected factory when the old one is gone.
Retries go through the same session, so they run on a live connection. The session is created by the run and
passed down; there is no module-level state.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Self

log = logging.getLogger("catalog_core.session")


class DatabaseSession:
    """Owns the run's connection. ``conn`` returns a usable connection, reconnecting first if needed.

    ``connect`` returns a context manager whose value is the connection (``db.connect`` does; tests may
    return ``nullcontext(fake)``). A failed connect raises from ``conn``; the next access tries again.
    """

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect
        self._context: Any = None
        self._conn: Any = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def conn(self) -> Any:
        if self._conn is None:
            self._open()
        elif _is_gone(self._conn):
            log.warning("database connection was lost; reconnecting")
            self._open()
        return self._conn

    def close(self) -> None:
        """Close the current connection. Errors are ignored: the connection may already be broken."""
        if self._context is not None:
            try:
                self._context.__exit__(None, None, None)
            except Exception:
                log.debug("ignored an error while closing the previous connection", exc_info=True)
        self._context = None
        self._conn = None

    def _open(self) -> None:
        self.close()
        context = self._connect()
        self._conn = context.__enter__()
        self._context = context


def _is_gone(conn: Any) -> bool:
    """True when the connection is closed or broken (psycopg sets ``broken`` after a fatal error)."""
    return bool(getattr(conn, "closed", False) or getattr(conn, "broken", False))
