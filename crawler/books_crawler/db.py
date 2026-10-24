"""PostgreSQL access for the crawler (ADR-002).

Rules:
- Only ``books``, ``book_sources``, ``book_identifiers``, ``book_contributors``, ``book_subjects``
  and ``bestsellers`` are written (data-model §7). No DDL is ever executed here.
- Connections use autocommit mode; every write goes through an explicit ``conn.transaction()``
  block, so a failure always rolls back exactly that unit of work.
- The schema is owned by EF Core and has no DB defaults, so UUIDs and timestamps come from here.
- Decisions (which Book a new source belongs to, whether a Book may be ranked twice) are made by
  the caller (``run``). This module only looks up and writes, except for the one bestseller rule
  the schema does not enforce (a ranked source must be a BOOKS_COM_TW source of the same Book),
  which ``replace_bestsellers`` checks inside its own transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import psycopg

from books_crawler.models import (
    BookDraft,
    Identifier,
    IdentifierType,
    IsbnMatch,
    SnapshotRow,
    SourceRef,
    SourceType,
)


class SnapshotValidationError(Exception):
    """A snapshot row's source is not a BOOKS_COM_TW Book Source of that row's Book (crawler.md §14.4)."""


def connect(database_url: str) -> psycopg.Connection:
    """Open a connection in autocommit mode (transactions are explicit, see module docstring)."""
    return psycopg.connect(database_url, autocommit=True)


def find_source(conn: psycopg.Connection, source_url: str) -> SourceRef | None:
    """Look up the BOOKS_COM_TW Book Source for a canonical product URL."""
    row = conn.execute(
        "SELECT id, book_id FROM book_sources WHERE source_type = %s AND source_url = %s",
        (SourceType.BOOKS_COM_TW, source_url),
    ).fetchone()
    if row is None:
        return None
    return SourceRef(source_id=row[0], book_id=row[1])


def find_book_by_isbn(conn: psycopg.Connection, identifiers: Sequence[Identifier]) -> IsbnMatch | None:
    """Find the existing Book that owns one of the identifiers: ISBN-13 first, then ISBN-10 (data-model §6)."""
    for identifier_type in (IdentifierType.ISBN_13, IdentifierType.ISBN_10):
        for identifier in identifiers:
            if identifier.identifier_type != identifier_type:
                continue
            row = conn.execute(
                "SELECT book_id FROM book_identifiers WHERE identifier_type = %s AND identifier_value = %s",
                (identifier.identifier_type, identifier.identifier_value),
            ).fetchone()
            if row is not None:
                return IsbnMatch(book_id=row[0], identifier=identifier)
    return None


def _insert_source(conn: psycopg.Connection, source_id: UUID, book_id: UUID, source_url: str, now: datetime) -> None:
    conn.execute(
        """
        INSERT INTO book_sources (id, book_id, source_type, external_id, source_url, first_seen_at, last_seen_at)
        VALUES (%s, %s, %s, NULL, %s, %s, %s)
        """,
        (source_id, book_id, SourceType.BOOKS_COM_TW, source_url, now, now),
    )


def _insert_book(conn: psycopg.Connection, book_id: UUID, draft: BookDraft, now: datetime) -> None:
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


def persist_new_source(
    conn: psycopg.Connection,
    draft: BookDraft,
    now: datetime,
    attach_to_book_id: UUID | None = None,
) -> SourceRef:
    """Persist a new BOOKS_COM_TW Book Source in one transaction.

    - ``attach_to_book_id`` set (the caller found an ISBN match): only a ``book_sources`` row is
      inserted for that Book. The Book's metadata, identifiers, contributors and subjects are not
      modified (no canonical merge by the crawler).
    - ``attach_to_book_id`` is None: a new Book is created with its source, identifiers,
      contributors and subjects.
    """
    source_id = uuid.uuid4()
    with conn.transaction():
        if attach_to_book_id is not None:
            _insert_source(conn, source_id, attach_to_book_id, draft.source_url, now)
            return SourceRef(source_id=source_id, book_id=attach_to_book_id)

        book_id = uuid.uuid4()
        identifiers = list(dict.fromkeys(draft.identifiers))
        subjects = list(dict.fromkeys(draft.subjects))
        _insert_book(conn, book_id, draft, now)
        _insert_source(conn, source_id, book_id, draft.source_url, now)
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES (%s, %s, %s)",
                [(book_id, item.identifier_type, item.identifier_value) for item in identifiers],
            )
            cursor.executemany(
                "INSERT INTO book_contributors (book_id, contributor_order, name, role) VALUES (%s, %s, %s, %s)",
                [(book_id, item.order, item.name, item.role) for item in draft.contributors],
            )
            cursor.executemany(
                "INSERT INTO book_subjects (book_id, subject, source_type) VALUES (%s, %s, %s)",
                [(book_id, subject, SourceType.BOOKS_COM_TW) for subject in subjects],
            )
    return SourceRef(source_id=source_id, book_id=book_id)


def replace_bestsellers(conn: psycopg.Connection, rows: Sequence[SnapshotRow], captured_at: datetime) -> None:
    """Replace the whole bestseller list and mark its sources as seen, in one transaction (crawler.md §14.4).

    First, every row's ``source_id`` must be a BOOKS_COM_TW Book Source of that row's own Book, or
    ``SnapshotValidationError`` is raised before the current list is touched. The other snapshot
    rules are not repeated here: rank range and uniqueness and ``book_id`` uniqueness are schema
    constraints, and ``RunLedger`` only puts resolved rows at their original ranks into a snapshot.

    In the same transaction, ``last_seen_at`` of every Book Source in the snapshot is set to
    ``captured_at`` (source metadata only; Book metadata is never touched). If any check or
    statement fails, everything rolls back: the previous list and ``last_seen_at`` values stay intact.
    """
    source_ids = [row.source_id for row in rows]
    with conn.transaction():
        owners = dict(
            conn.execute(
                "SELECT id, book_id FROM book_sources WHERE source_type = %s AND id = ANY(%s)",
                (SourceType.BOOKS_COM_TW, source_ids),
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
        conn.execute(
            "UPDATE book_sources SET last_seen_at = %s WHERE id = ANY(%s)",
            (captured_at, source_ids),
        )
