"""Books.com.tw-specific PostgreSQL writes (ADR-002): the Bestseller snapshot only.

Rules:
- Only ``bestsellers`` is written here. The provider-neutral Catalog writes (Books, Sources, identifiers,
  contributors, subjects, the connection helpers and the provider registry lookup) live in
  ``catalog_core.persistence``, which takes the provider explicitly.
- Connections use autocommit mode; every write goes through an explicit ``conn.transaction()``
  block. No DDL is ever executed here.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import psycopg

from books_crawler.models import PROVIDER, SnapshotRow


class SnapshotValidationError(Exception):
    """A snapshot row's source is not a BOOKS_COM_TW Book Source of that row's Book (crawler.md §14.4)."""


def replace_bestsellers(conn: psycopg.Connection, rows: Sequence[SnapshotRow], captured_at: datetime) -> None:
    """Replace the whole bestseller list in one transaction (crawler.md §14.4).

    First, every row's ``source_id`` must be a BOOKS_COM_TW Book Source of that row's own Book, or
    ``SnapshotValidationError`` is raised before the current list is touched. The other snapshot
    rules are schema constraints (rank range and uniqueness, ``book_id`` uniqueness). This
    transaction does not touch ``last_seen_at``: that was set per item in its own transaction (§6.1).
    """
    source_ids = [row.source_id for row in rows]
    with conn.transaction():
        owners = dict(
            conn.execute(
                "SELECT id, book_id FROM book_sources WHERE source_code = %s AND id = ANY(%s)",
                (PROVIDER, source_ids),
            ).fetchall()
        )
        for row in rows:
            if owners.get(row.source_id) != row.book_id:
                raise SnapshotValidationError(f"rank {row.rank}: source {row.source_id} is not a BOOKS_COM_TW source of Book {row.book_id}")
        conn.execute("DELETE FROM bestsellers")
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO bestsellers (rank, book_id, source_id, captured_at) VALUES (%s, %s, %s, %s)",
                [(row.rank, row.book_id, row.source_id, captured_at) for row in rows],
            )
