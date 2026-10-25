"""Integration tests for ``catalog_core.persistence``: provider-explicit writes and the monotonic touch.

Runs against the throwaway PostgreSQL of ``conftest.py``. No network is used.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from books_crawler import db
from catalog_core import persistence
from catalog_core.identity import IdentityKind
from catalog_core.models import ProviderCode
from catalog_core.persistence import SourceTouchConflict
from tests.fakes import make_draft, product_url

NOW = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
EARLIER = NOW - timedelta(days=1)
BOOKS = ProviderCode.BOOKS_COM_TW
KINGSTONE = ProviderCode.KINGSTONE


def query(url: str, sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def seed_books_source(db_url: str, url: str, now: datetime = NOW) -> tuple[uuid.UUID, uuid.UUID]:
    """One BOOKS_COM_TW Book Source created through the persistence module: returns (source_id, book_id)."""
    with persistence.connect(db_url) as conn:
        ref = persistence.persist_new_source(conn, BOOKS, make_draft(url), now)
    return ref.source_id, ref.book_id


def last_seen_at(db_url: str, source_id: uuid.UUID) -> datetime:
    return query(db_url, "SELECT last_seen_at FROM book_sources WHERE id = %s", (source_id,))[0][0]


def test_touch_with_a_later_time_advances_last_seen_at(db_url):
    source_id, _ = seed_books_source(db_url, product_url(1))
    with persistence.connect(db_url) as conn:
        persistence.touch_source(conn, BOOKS, source_id, LATER)

    assert last_seen_at(db_url, source_id) == LATER


def test_touch_with_an_earlier_time_keeps_last_seen_at(db_url):
    # The clock moved back: last_seen_at is GREATEST(stored, observed), so it never goes backwards.
    source_id, _ = seed_books_source(db_url, product_url(1))
    with persistence.connect(db_url) as conn:
        persistence.touch_source(conn, BOOKS, source_id, EARLIER)

    assert last_seen_at(db_url, source_id) == NOW


def test_repeating_the_same_touch_is_idempotent(db_url):
    source_id, _ = seed_books_source(db_url, product_url(1))
    with persistence.connect(db_url) as conn:
        persistence.touch_source(conn, BOOKS, source_id, LATER)
        persistence.touch_source(conn, BOOKS, source_id, LATER)

    assert last_seen_at(db_url, source_id) == LATER


def test_touch_with_the_wrong_provider_raises_and_leaves_the_row_unchanged(db_url):
    source_id, _ = seed_books_source(db_url, product_url(1))
    with persistence.connect(db_url) as conn, pytest.raises(SourceTouchConflict) as raised:
        persistence.touch_source(conn, KINGSTONE, source_id, LATER)

    assert str(source_id) in str(raised.value) and "KINGSTONE" in str(raised.value)
    assert last_seen_at(db_url, source_id) == NOW


def test_touch_of_a_missing_source_raises_source_touch_conflict(db_url):
    with persistence.connect(db_url) as conn, pytest.raises(SourceTouchConflict) as raised:
        persistence.touch_source(conn, BOOKS, uuid.uuid4(), LATER)

    assert "BOOKS_COM_TW" in str(raised.value)


def test_persist_new_source_stores_the_kingstone_provider_and_external_id(db_url):
    draft = make_draft(product_url(7), external_id="K-7")
    with persistence.connect(db_url) as conn:
        ref = persistence.persist_new_source(conn, KINGSTONE, draft, NOW)

    rows = query(db_url, "SELECT source_code, external_id, source_url, book_id FROM book_sources WHERE id = %s", (ref.source_id,))
    assert rows == [("KINGSTONE", "K-7", product_url(7), ref.book_id)]


def test_provider_isolation_same_url_is_new_for_kingstone_and_existing_for_books(db_url):
    source_id, book_id = seed_books_source(db_url, product_url(3))
    with persistence.connect(db_url) as conn:
        for_kingstone = persistence.resolve_source_identity(conn, KINGSTONE, product_url(3))
        for_books = persistence.resolve_source_identity(conn, BOOKS, product_url(3))

    assert for_kingstone.kind is IdentityKind.NEW
    assert for_books.kind is IdentityKind.EXISTING
    assert for_books.ref.source_id == source_id and for_books.ref.book_id == book_id


def test_provider_isolation_external_id_lookup_only_sees_its_own_provider(db_url):
    with persistence.connect(db_url) as conn:
        persistence.persist_new_source(conn, KINGSTONE, make_draft(product_url(4), external_id="K-4"), NOW)
        identity = persistence.resolve_source_identity(conn, BOOKS, product_url(5), external_id="K-4")

    assert identity.kind is IdentityKind.NEW


def test_books_connect_and_provider_enabled_are_the_persistence_functions(db_url):
    # The Books package keeps only its own Bestseller code; the shared connection helpers live in persistence.
    assert db.SnapshotValidationError is not None
    assert not hasattr(db, "persist_new_source")
    assert persistence.provider_enabled(db_url, "BOOKS_COM_TW") is True
