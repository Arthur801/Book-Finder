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
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg

from books_crawler.models import (
    IDENTIFIER_ISBN_10,
    IDENTIFIER_ISBN_13,
    SOURCE_TYPE_BOOKS_COM_TW,
    BookDraft,
    Identifier,
    SnapshotRow,
    SourceRef,
)


class BookAlreadyRankedError(Exception):
    """A new product's ISBN resolves to a Book that another product already holds in this ranking.

    ``bestsellers.book_id`` is unique, so this run cannot place both products. Fails the run.
    """

    def __init__(self, book_id: UUID):
        super().__init__(f"matched Book {book_id} is already used by another product in this ranking")
        self.book_id = book_id


@dataclass(frozen=True)
class PersistedProduct:
    ref: SourceRef
    # Set when the product was attached to an existing Book by ISBN instead of creating a new Book.
    matched_identifier: Identifier | None = None


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


def _find_book_by_isbn(conn: psycopg.Connection, identifiers: Sequence[Identifier]) -> tuple[UUID, Identifier] | None:
    """Match an existing Book by ISBN: ISBN-13 first, then ISBN-10 (data-model §6)."""
    for identifier_type in (IDENTIFIER_ISBN_13, IDENTIFIER_ISBN_10):
        for identifier in identifiers:
            if identifier.identifier_type != identifier_type:
                continue
            row = conn.execute(
                "SELECT book_id FROM book_identifiers WHERE identifier_type = %s AND identifier_value = %s",
                (identifier.identifier_type, identifier.identifier_value),
            ).fetchone()
            if row is not None:
                return row[0], identifier
    return None


def _insert_source(conn: psycopg.Connection, source_id: UUID, book_id: UUID, source_url: str, now: datetime) -> None:
    conn.execute(
        """
        INSERT INTO book_sources (id, book_id, source_type, external_id, source_url, first_seen_at, last_seen_at)
        VALUES (%s, %s, %s, NULL, %s, %s, %s)
        """,
        (source_id, book_id, SOURCE_TYPE_BOOKS_COM_TW, source_url, now, now),
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


def persist_new_product(
    conn: psycopg.Connection,
    draft: BookDraft,
    now: datetime,
    reserved_book_ids: Collection[UUID] = (),
) -> PersistedProduct:
    """Persist a product whose source URL is not known yet, in one transaction.

    - If one of its ISBNs (ISBN-13 first, then ISBN-10) already belongs to a Book, only a new
      BOOKS_COM_TW ``book_sources`` row is inserted for that Book. The existing Book's metadata,
      identifiers, contributors and subjects are not modified (no canonical merge by the crawler).
    - Otherwise a new Book is created with its source, identifiers, contributors and subjects.
    - ``reserved_book_ids`` are Books already used by another product in this ranking. Matching one
      of them raises ``BookAlreadyRankedError`` before anything is written.
    """
    source_id = uuid.uuid4()
    identifiers = list(dict.fromkeys(draft.identifiers))
    subjects = list(dict.fromkeys(draft.subjects))

    with conn.transaction():
        match = _find_book_by_isbn(conn, identifiers)
        if match is not None:
            book_id, identifier = match
            if book_id in reserved_book_ids:
                raise BookAlreadyRankedError(book_id)
            _insert_source(conn, source_id, book_id, draft.source_url, now)
            return PersistedProduct(SourceRef(source_id=source_id, book_id=book_id), matched_identifier=identifier)

        book_id = uuid.uuid4()
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
                [(book_id, subject, SOURCE_TYPE_BOOKS_COM_TW) for subject in subjects],
            )
    return PersistedProduct(SourceRef(source_id=source_id, book_id=book_id))


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
