"""The shared migration lock's key and acquisition helper (catalog_core.migration_lock), pure: no database.

The deploy side (``deploy/host/bookfinder_host/``) must use the same key value; its consistency test lives with the deploy
side (plan v12 §8, M3). The database behavior is in ``test_migration_lock_integration.py``.
"""

import psycopg

from catalog_core.migration_lock import CATALOG_MIGRATION_LOCK_KEY, MigrationLockBusy, try_acquire_shared


class ScriptedConnection:
    """Records the one statement sent and answers with the scripted lock result."""

    def __init__(self, granted: bool) -> None:
        self.granted = granted
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        return self

    def fetchone(self):
        return (self.granted,)


def test_the_key_is_the_documented_plan_value():
    assert CATALOG_MIGRATION_LOCK_KEY == 2026102501
    assert -(2**63) <= CATALOG_MIGRATION_LOCK_KEY < 2**63  # a bigint key


def test_try_acquire_shared_asks_for_the_shared_lock_on_the_key_and_returns_the_answer():
    granted = ScriptedConnection(granted=True)
    refused = ScriptedConnection(granted=False)

    assert try_acquire_shared(granted) is True
    assert try_acquire_shared(refused) is False
    sql, params = granted.statements[0]
    assert "pg_try_advisory_lock_shared" in sql
    assert params == (2026102501,)


def test_migration_lock_busy_is_a_plain_exception_not_a_database_error():
    assert issubclass(MigrationLockBusy, Exception)
    assert not issubclass(MigrationLockBusy, psycopg.Error)
