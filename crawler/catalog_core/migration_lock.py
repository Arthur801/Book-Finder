"""The shared side of the Catalog migration lock (plan v12 §8, item 1).

A migration holds the exclusive side of ``CATALOG_MIGRATION_LOCK_KEY`` on its own session while it runs. Every crawler
database session takes the shared side on the connection it writes through, on the first connect and on every
reconnect (``catalog_core.session``). While a migration holds the exclusive lock, a shared attempt fails and the crawler
writes nothing. A session-level advisory lock is released when its session ends, so a holder that dies releases the lock.

The deploy side (``deploy/host/bookfinder_host/``) must use the same key value: it takes the exclusive side with
``pg_advisory_lock``. The two sides are linked only by this value; a cross-module consistency test lives with the
deploy side.
"""

from __future__ import annotations

from typing import Any

# Chosen for this migration lock (plan v12 §8). Changing it breaks the exclusion with the deploy side.
CATALOG_MIGRATION_LOCK_KEY = 2026102501


class MigrationLockBusy(Exception):
    """A database migration holds the Catalog lock; this session may not write.

    Deliberately not a ``psycopg.Error``: a retryable database failure is retried by the service, and retrying a
    migration lock would only wait on a migration that is still running. The run stops instead.
    """


def try_acquire_shared(conn: Any) -> bool:
    """Try to take the shared migration lock on ``conn``'s session. False when a migration holds it exclusively."""
    row = conn.execute("SELECT pg_try_advisory_lock_shared(%s::bigint)", (CATALOG_MIGRATION_LOCK_KEY,)).fetchone()
    return bool(row[0])
