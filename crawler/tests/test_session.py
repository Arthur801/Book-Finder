"""The run-owned database session (crawler.md §13.1): a broken connection is replaced, a healthy one is kept.

Pure: the connect factory is a fake, so no database is needed.
"""

from contextlib import nullcontext

import psycopg
import pytest

from books_crawler.session import DatabaseSession


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
    session = DatabaseSession(connect)

    first = session.conn
    second = session.conn

    assert first is second
    assert len(connect.made) == 1


def test_a_broken_connection_is_replaced_and_the_old_one_is_closed_without_raising():
    connect = FakeConnect()
    session = DatabaseSession(connect)
    old = session.conn
    old.broken = True

    new = session.conn

    assert new is not old
    assert [item.name for item in connect.exited] == ["conn-1"]  # the broken one was closed; its error was ignored
    assert len(connect.made) == 2


def test_a_closed_connection_is_replaced_too():
    connect = FakeConnect()
    session = DatabaseSession(connect)
    old = session.conn
    old.closed = True

    assert session.conn is not old


def test_a_failed_reconnect_propagates_and_the_next_use_tries_again():
    connect = FakeConnect()
    session = DatabaseSession(connect)
    session.conn.broken = True
    connect.fail_next = 1

    with pytest.raises(psycopg.OperationalError, match="connect refused"):
        _ = session.conn

    assert session.conn.name == "conn-2"  # the next access reconnects


def test_the_factory_may_return_a_plain_context_manager_for_tests():
    marker = object()
    session = DatabaseSession(lambda: nullcontext(marker))

    assert session.conn is marker


def test_close_is_idempotent_and_ignores_errors_from_the_old_connection():
    connect = FakeConnect()
    with DatabaseSession(connect) as session:
        session.conn.broken = True
        _ = session.conn  # reconnects, closes the broken one
    session.close()

    assert len(connect.exited) == 2
