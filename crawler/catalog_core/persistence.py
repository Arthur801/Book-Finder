"""PostgreSQL access for the provider-neutral Catalog (ADR-002).

Rules:
- Only ``books``, ``book_sources``, ``book_identifiers``, ``book_contributors`` and ``book_subjects``
  are written (data-model §7). No DDL is ever executed here.
- Every function that reads or writes a Book Source takes the ``provider`` explicitly and filters on
  ``source_code``: a provider never sees or changes another provider's Sources. Nothing here reads a
  module-global provider.
- Connections use autocommit mode; every write goes through an explicit ``conn.transaction()``
  block, so a failure always rolls back exactly that unit of work.
- The crawler writes and reads ``source_code`` only. Migration 011 removed the legacy ``source_type``
  column and its sync triggers, so SQL here never names them.
- The schema is owned by EF Core and has no DB defaults, so UUIDs and timestamps come from here.
- Decisions (which Book a new source belongs to, whether a Book may be ranked twice) are made by
  ``catalog_core.service`` and by ``identity``. This module only looks up and writes.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import psycopg

from catalog_core.identity import SourceIdentity, decide_source_identity
from catalog_core.models import (
    BookDraft,
    ContributorRole,
    IdentifierType,
    ProviderCode,
    SourceRecord,
    SourceRef,
)


class SourceTouchConflict(Exception):
    """A touch matched no row: the Source is not a Book Source of ``provider`` (or does not exist)."""


def connect(database_url: str) -> psycopg.Connection:
    """Open a connection in autocommit mode (transactions are explicit, see module docstring)."""
    return psycopg.connect(database_url, autocommit=True)


def provider_enabled(database_url: str, code: ProviderCode) -> bool | None:
    """``source_providers.enabled`` for ``code``; None when the provider row does not exist (crawler.md §3.1)."""
    with connect(database_url) as conn:
        row = conn.execute("SELECT enabled FROM source_providers WHERE code = %s", (code,)).fetchone()
    return None if row is None else bool(row[0])


def _lookup(conn: psycopg.Connection, provider: ProviderCode, where: str, value: object) -> SourceRecord | None:
    row = conn.execute(
        f"SELECT id, book_id, external_id FROM book_sources WHERE source_code = %s AND {where} = %s",
        (provider, value),
    ).fetchone()
    if row is None:
        return None
    return SourceRecord(source_id=row[0], book_id=row[1], external_id=row[2])


def resolve_source_identity(
    conn: psycopg.Connection,
    provider: ProviderCode,
    source_url: str,
    external_id: str | None = None,
) -> SourceIdentity:
    """Source identity of one item of ``provider`` (data-model §7.3): both keys are queried when ``external_id`` is given."""
    by_external_id = _lookup(conn, provider, "external_id", external_id) if external_id is not None else None
    by_url = _lookup(conn, provider, "source_url", source_url)
    return decide_source_identity(by_external_id, by_url, external_id=external_id)


def touch_source(conn: psycopg.Connection, provider: ProviderCode, source_id: UUID, observed_at: datetime) -> None:
    """Move ``last_seen_at`` of one existing Source of ``provider`` forward, in its own transaction (crawler.md §6.1).

    ``last_seen_at`` becomes ``GREATEST(last_seen_at, observed_at)``, so a clock that moved back never
    moves it backwards. A touch that matches no row (the Source is missing or belongs to another provider)
    raises ``SourceTouchConflict`` and changes nothing.
    """
    with conn.transaction():
        cursor = conn.execute(
            "UPDATE book_sources SET last_seen_at = GREATEST(last_seen_at, %s) WHERE id = %s AND source_code = %s",
            (observed_at, source_id, provider),
        )
        if cursor.rowcount != 1:
            raise SourceTouchConflict(f"Book Source {source_id} is not a {provider} Book Source; nothing was touched")


def find_books_by_isbn(conn: psycopg.Connection, values: Sequence[str]) -> list[UUID]:
    """Distinct Books owning any of the normalized ISBN values (data-model §7.2 step 2), sorted for stable logs.

    Only the ``ISBN`` identifier type matches: migration 011 converted the legacy ISBN_10 / ISBN_13 rows to ``ISBN``.
    """
    if not values:
        return []
    rows = conn.execute(
        """
        SELECT DISTINCT book_id FROM book_identifiers
        WHERE identifier_value = ANY(%s) AND identifier_type = %s
        """,
        (list(values), IdentifierType.ISBN),
    ).fetchall()
    return sorted(row[0] for row in rows)


def _insert_source(
    conn: psycopg.Connection,
    provider: ProviderCode,
    source_id: UUID,
    book_id: UUID,
    draft: BookDraft,
    now: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO book_sources (id, book_id, source_code, external_id, source_url, first_seen_at, last_seen_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (source_id, book_id, provider, draft.external_id, draft.source_url, now, now),
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


def _write_identifiers(conn: psycopg.Connection, book_id: UUID, draft: BookDraft) -> None:
    # Always stored as the ISBN type: the value is the §7.1 key (data-model §6.5, §7.2).
    values = list(dict.fromkeys(item.identifier_value for item in draft.identifiers))
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            [(book_id, IdentifierType.ISBN, value) for value in values],
        )


def _write_subjects(conn: psycopg.Connection, provider: ProviderCode, book_id: UUID, draft: BookDraft) -> None:
    subjects = list(dict.fromkeys(draft.subjects))
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO book_subjects (book_id, subject, source_code) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            [(book_id, subject, provider) for subject in subjects],
        )


def _fill_book_gaps(conn: psycopg.Connection, book_id: UUID, draft: BookDraft, now: datetime) -> None:
    """Fill only the NULL books columns from the draft (data-model §7.4); ``updated_at`` only when something was filled."""
    row = conn.execute(
        """
        SELECT publisher, published_date, published_date_precision, language, description,
               table_of_contents, page_count, thumbnail_url
        FROM books WHERE id = %s FOR UPDATE
        """,
        (book_id,),
    ).fetchone()
    publisher, published_date, precision, language, description, toc, page_count, thumbnail = row
    fills: dict[str, object] = {}
    if publisher is None and draft.publisher is not None:
        fills["publisher"] = draft.publisher
    if published_date is None and precision is None and draft.published_date is not None:
        fills["published_date"] = draft.published_date
        fills["published_date_precision"] = draft.published_date_precision
    if language is None and draft.language is not None:
        fills["language"] = draft.language
    if description is None and draft.description is not None:
        fills["description"] = draft.description
    if toc is None and draft.table_of_contents is not None:
        fills["table_of_contents"] = draft.table_of_contents
    if page_count is None and draft.page_count is not None:
        fills["page_count"] = draft.page_count
    if thumbnail is None and draft.thumbnail_url is not None:
        fills["thumbnail_url"] = draft.thumbnail_url
    if fills:
        fills["updated_at"] = now
        assignments = ", ".join(f"{column} = %s" for column in fills)
        conn.execute(f"UPDATE books SET {assignments} WHERE id = %s", (*fills.values(), book_id))


def _fill_author_if_missing(conn: psycopg.Connection, book_id: UUID, draft: BookDraft) -> None:
    """Add the draft's AUTHORs only when the Book has no AUTHOR, after its current maximum order (§7.4)."""
    has_author = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM book_contributors WHERE book_id = %s AND role = %s)",
        (book_id, ContributorRole.AUTHOR),
    ).fetchone()[0]
    authors = [item for item in draft.contributors if item.role is ContributorRole.AUTHOR]
    if has_author or not authors:
        return
    base = conn.execute("SELECT COALESCE(MAX(contributor_order), 0) FROM book_contributors WHERE book_id = %s", (book_id,)).fetchone()[0]
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO book_contributors (book_id, contributor_order, name, role) VALUES (%s, %s, %s, %s)",
            [(book_id, base + position, item.name, item.role) for position, item in enumerate(authors, start=1)],
        )


def persist_new_source(
    conn: psycopg.Connection,
    provider: ProviderCode,
    draft: BookDraft,
    now: datetime,
    attach_to_book_id: UUID | None = None,
) -> SourceRef:
    """Persist a new Book Source of ``provider`` in one transaction (data-model §7.2, §7.4).

    The Source stores ``draft.external_id`` (NULL when the draft has none).

    - ``attach_to_book_id`` set (exactly one Book matched the ISBN): the source is attached and the
      Book's NULL columns, a missing AUTHOR, its identifiers and this source's subjects are filled
      in the same transaction.
    - ``attach_to_book_id`` None: a new Book is created with its source, identifiers, contributors
      and subjects (no match, or an ambiguous match, in which case nothing of the existing Books changes).
    """
    source_id = uuid.uuid4()
    with conn.transaction():
        if attach_to_book_id is not None:
            _insert_source(conn, provider, source_id, attach_to_book_id, draft, now)
            _fill_book_gaps(conn, attach_to_book_id, draft, now)
            _fill_author_if_missing(conn, attach_to_book_id, draft)
            _write_identifiers(conn, attach_to_book_id, draft)
            _write_subjects(conn, provider, attach_to_book_id, draft)
            return SourceRef(source_id=source_id, book_id=attach_to_book_id)

        book_id = uuid.uuid4()
        _insert_book(conn, book_id, draft, now)
        _insert_source(conn, provider, source_id, book_id, draft, now)
        _write_identifiers(conn, book_id, draft)
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO book_contributors (book_id, contributor_order, name, role) VALUES (%s, %s, %s, %s)",
                [(book_id, item.order, item.name, item.role) for item in draft.contributors],
            )
        _write_subjects(conn, provider, book_id, draft)
    return SourceRef(source_id=source_id, book_id=book_id)
