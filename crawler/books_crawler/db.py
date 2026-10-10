"""PostgreSQL access for the crawler (ADR-002).

Rules:
- Only ``books``, ``book_sources``, ``book_identifiers``, ``book_contributors``, ``book_subjects``
  and ``bestsellers`` are written (data-model §7). No DDL is ever executed here.
- Connections use autocommit mode; every write goes through an explicit ``conn.transaction()``
  block, so a failure always rolls back exactly that unit of work.
- The schema is owned by EF Core and has no DB defaults, so UUIDs and timestamps come from here.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

import psycopg

from books_crawler.models import SOURCE_TYPE_BOOKS_COM_TW, BookDraft, SnapshotRow, SourceRef


class BookConflictError(Exception):
    """A new Book's ISBN already belongs to another Book (data-model §10, invariant 4)."""


def connect(database_url: str) -> psycopg.Connection:
    """Open a connection in autocommit mode (transactions are explicit, see module docstring)."""
    return psycopg.connect(database_url, autocommit=True)


def find_source(conn: psycopg.Connection, source_url: str) -> SourceRef | None:
    """Look up the BOOKS_COM_TW source row for a canonical product URL."""
    row = conn.execute(
        "SELECT id, book_id FROM book_sources WHERE source_type = %s AND source_url = %s",
        (SOURCE_TYPE_BOOKS_COM_TW, source_url),
    ).fetchone()
    if row is None:
        return None
    return SourceRef(source_id=row[0], book_id=row[1])


def insert_new_book(conn: psycopg.Connection, draft: BookDraft, now: datetime) -> SourceRef:
    """Persist one new Book with its source, identifiers, contributors and subjects.

    Runs in a single transaction. Any failure rolls back the whole Book.
    """
    book_id = uuid.uuid4()
    source_id = uuid.uuid4()
    identifiers = list(dict.fromkeys((item.identifier_type, item.identifier_value) for item in draft.identifiers))
    subjects = list(dict.fromkeys(draft.subjects))

    with conn.transaction():
        for identifier_type, identifier_value in identifiers:
            owner = conn.execute(
                "SELECT book_id FROM book_identifiers WHERE identifier_type = %s AND identifier_value = %s",
                (identifier_type, identifier_value),
            ).fetchone()
            if owner is not None:
                raise BookConflictError(f"{identifier_type} {identifier_value} already belongs to another Book")

        conn.execute(
            """
            INSERT INTO books (
                id, title, subtitle, publisher, published_date, published_date_precision,
                language, description, table_of_contents, page_count, thumbnail_url,
                created_at, updated_at
            ) VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                book_id,
                draft.title,
                draft.publisher,
                draft.published_date,
                draft.published_date_precision,
                draft.language,
                draft.description,
                draft.table_of_contents,
                draft.page_count,
                draft.thumbnail_url,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO book_sources (id, book_id, source_type, external_id, source_url, first_seen_at, last_seen_at)
            VALUES (%s, %s, %s, NULL, %s, %s, %s)
            """,
            (source_id, book_id, SOURCE_TYPE_BOOKS_COM_TW, draft.source_url, now, now),
        )
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES (%s, %s, %s)",
                [(book_id, identifier_type, identifier_value) for identifier_type, identifier_value in identifiers],
            )
            cursor.executemany(
                "INSERT INTO book_contributors (book_id, contributor_order, name, role) VALUES (%s, %s, %s, %s)",
                [(book_id, item.order, item.name, item.role) for item in draft.contributors],
            )
            cursor.executemany(
                "INSERT INTO book_subjects (book_id, subject, source_type) VALUES (%s, %s, %s)",
                [(book_id, subject, SOURCE_TYPE_BOOKS_COM_TW) for subject in subjects],
            )

    return SourceRef(source_id=source_id, book_id=book_id)


def replace_bestsellers(conn: psycopg.Connection, rows: Sequence[SnapshotRow], captured_at: datetime) -> None:
    """Replace the whole bestseller list in one transaction (crawler.md §10).

    If any statement fails, the transaction rolls back and the previous list stays intact.
    """
    with conn.transaction():
        conn.execute("DELETE FROM bestsellers")
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO bestsellers (rank, book_id, source_id, captured_at) VALUES (%s, %s, %s, %s)",
                [(row.rank, row.book_id, row.source_id, captured_at) for row in rows],
            )
