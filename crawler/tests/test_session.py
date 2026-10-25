"""The run-owned database session (crawler.md §13.1): a broken connection is replaced, a healthy one is kept.

Pure: the connect factory is a fake, so no database is needed.
"""

from contextlib import nullcontext

import psycopg
import pytest

from catalog_core.migration_lock import MigrationLockBusy
from catalog_core.session import DatabaseSession


def granted(conn) -> bool:
    """Stands in for the shared migration lock in these pure tests: every attempt is granted."""
    return True


class FakeConnection:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False
        self.broken = False


class FakeConnect:
    """Hands out a new FakeConnection per call; each context's exit is recorded."""

    def __init__(self) -> None:
        self.made: list[FakeConnection] = []
        self.exited: list[FakeConnection] = []
        self.fail_next = 0

    def __call__(self):
        if self.fail_next:
            self.fail_next -= 1
            raise psycopg.OperationalError("connect refused")
        connection = FakeConnection(f"conn-{len(self.made) + 1}")
        self.made.append(connection)
        return _Context(connection, self.exited)


class _Context:
    def __init__(self, connection, exited):
        self._connection = connection
        self._exited = exited

    def __enter__(self):
        return self._connection

    def __exit__(self, *exc):
        self._exited.append(self._connection)
        if self._connection.broken:
            raise psycopg.OperationalError("cannot close a broken connection")  # closing must be ignored by the session
        return False


def test_a_healthy_connection_is_reused():
    connect = FakeConnect()
    session = DatabaseSession(connect, acquire_lock=granted)

    first = session.conn
    second = session.conn

    assert first is second
    assert len(connect.made) == 1


def test_a_broken_connection_is_replaced_and_the_old_one_is_closed_without_raising():
    connect = FakeConnect()
    session = DatabaseSession(connect, acquire_lock=granted)
    old = session.conn
    old.broken = True

    new = session.conn

    assert new is not old
    assert [item.name for item in connect.exited] == ["conn-1"]  # the broken one was closed; its error was ignored
    assert len(connect.made) == 2


def test_a_closed_connection_is_replaced_too():
    connect = FakeConnect()
    session = DatabaseSession(connect, acquire_lock=granted)
    old = session.conn
    old.closed = True

    assert session.conn is not old


def test_a_failed_reconnect_propagates_and_the_next_use_tries_again():
    connect = FakeConnect()
    session = DatabaseSession(connect, acquire_lock=granted)
    session.conn.broken = True
    connect.fail_next = 1

    with pytest.raises(psycopg.OperationalError, match="connect refused"):
        _ = session.conn

    assert session.conn.name == "conn-2"  # the next access reconnects


def test_the_factory_may_return_a_plain_context_manager_for_tests():
    marker = object()
    session = DatabaseSession(lambda: nullcontext(marker), acquire_lock=granted)

    assert session.conn is marker


def test_close_is_idempotent_and_ignores_errors_from_the_old_connection():
    connect = FakeConnect()
    with DatabaseSession(connect, acquire_lock=granted) as session:
        session.conn.broken = True
        _ = session.conn  # reconnects, closes the broken one
    session.close()

    assert len(connect.exited) == 2


class RecordingLock:
    """Records each shared-lock attempt and answers with the scripted outcomes (True, False, or an exception)."""

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.attempts: list[str] = []

    def __call__(self, conn) -> bool:
        self.attempts.append(conn.name)
        outcome = self.outcomes.pop(0) if self.outcomes else True
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_every_new_connection_takes_the_shared_migration_lock_before_it_is_handed_out():
    connect = FakeConnect()
    lock = RecordingLock()
    session = DatabaseSession(connect, acquire_lock=lock)

    _ = session.conn
    _ = session.conn  # a healthy connection is reused: no second attempt

    assert lock.attempts == ["conn-1"]


def test_a_reconnect_takes_the_shared_migration_lock_again():
    connect = FakeConnect()
    lock = RecordingLock()
    session = DatabaseSession(connect, acquire_lock=lock)
    session.conn.broken = True

    _ = session.conn

    assert lock.attempts == ["conn-1", "conn-2"]


def test_a_busy_lock_closes_the_new_connection_and_raises_migration_lock_busy():
    connect = FakeConnect()
    session = DatabaseSession(connect, acquire_lock=RecordingLock(False))

    with pytest.raises(MigrationLockBusy, match="migration lock busy"):
        _ = session.conn

    assert [item.name for item in connect.exited] == ["conn-1"]  # the connection that may not write is closed
    assert not isinstance(MigrationLockBusy(), psycopg.Error)


def test_a_busy_reconnect_writes_nothing_and_the_old_connection_is_closed():
    connect = FakeConnect()
    session = DatabaseSession(connect, acquire_lock=RecordingLock(True, False))
    old = session.conn
    old.broken = True

    with pytest.raises(MigrationLockBusy):
        _ = session.conn

    assert [item.name for item in connect.exited] == ["conn-1", "conn-2"]  # the broken one, then the new one that may not write
    assert [item.name for item in connect.made] == ["conn-1", "conn-2"]


def test_a_database_error_while_taking_the_lock_propagates_as_a_retryable_error_and_closes_the_connection():
    connect = FakeConnect()
    session = DatabaseSession(connect, acquire_lock=RecordingLock(psycopg.OperationalError("server closed")))

    with pytest.raises(psycopg.OperationalError, match="server closed"):
        _ = session.conn

    assert [item.name for item in connect.exited] == ["conn-1"]
