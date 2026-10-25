"""Provider-neutral Catalog types shared by every crawler provider.

Values are already normalized (see ``normalize.py``). The enums are ``StrEnum`` whose values are
exactly the stored vocabulary of ``Docs/data/data-model.md`` (``BOOKS_COM_TW``, ``KINGSTONE``, ``ISBN``,
``AUTHOR``, ``DAY`` ...), so they can be passed to SQL and compared with plain strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID


class ProviderCode(StrEnum):
    """``source_providers.code`` values the crawlers write (data-model §7, crawler.md §3.1)."""

    BOOKS_COM_TW = "BOOKS_COM_TW"
    KINGSTONE = "KINGSTONE"


class PublishedDatePrecision(StrEnum):
    YEAR = "YEAR"
    MONTH = "MONTH"
    DAY = "DAY"


class IdentifierType(StrEnum):
    ISBN = "ISBN"  # data-model §6.5: the normalized value of §7.1; the only ISBN type since migration 011


class ContributorRole(StrEnum):
    AUTHOR = "AUTHOR"
    ORIGINAL_AUTHOR = "ORIGINAL_AUTHOR"
    TRANSLATOR = "TRANSLATOR"
    EDITOR = "EDITOR"
    ILLUSTRATOR = "ILLUSTRATOR"
    OTHER = "OTHER"


class CatalogResolution(StrEnum):
    """Catalog-side outcome of one discovery item (crawler.md §3.5, §6.5). In-process only: never stored.

    The first four are resolved rows (they reach ``ResolvedRow``); ``RESTRICTED`` and ``FAILED`` are
    skipped rows (``SkippedRow``). Only the Catalog counters (§10.2) depend on this value.
    """

    EXISTING = "EXISTING"  # Source already known, touched and reused; no detail request
    IMPORTED = "IMPORTED"  # new Book and new Source
    ISBN_ATTACHED = "ISBN_ATTACHED"  # new Source attached to exactly one existing Book by ISBN, gaps filled
    AMBIGUOUS_CREATED = "AMBIGUOUS_CREATED"  # new Book and new Source, ISBN matched two or more Books
    RESTRICTED = "RESTRICTED"  # restricted member-only page (crawler.md §13.2)
    FAILED = "FAILED"  # retries exhausted, touch failed, or source identity conflict


RESOLVED_CATALOG_RESOLUTIONS = frozenset(
    {
        CatalogResolution.EXISTING,
        CatalogResolution.IMPORTED,
        CatalogResolution.ISBN_ATTACHED,
        CatalogResolution.AMBIGUOUS_CREATED,
    }
)


@dataclass(frozen=True)
class Identifier:
    identifier_type: IdentifierType
    identifier_value: str  # normalized: no dashes or spaces, uppercase


@dataclass(frozen=True)
class Contributor:
    order: int  # 1-based position in the source listing
    name: str
    role: ContributorRole


@dataclass(frozen=True)
class BookDraft:
    """A normalized, not yet persisted Book parsed from one product detail page.

    ``subtitle`` is deliberately absent: books.com.tw has no reliable subtitle field, so it
    is always stored as NULL.
    """

    source_url: str
    title: str
    publisher: str | None = None
    published_date: date | None = None
    published_date_precision: PublishedDatePrecision | None = None
    language: str | None = None
    description: str | None = None
    table_of_contents: str | None = None
    page_count: int | None = None
    thumbnail_url: str | None = None
    identifiers: tuple[Identifier, ...] = ()
    contributors: tuple[Contributor, ...] = ()
    subjects: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.title or not self.title.strip():
            raise ValueError("title is required")
        if (self.published_date is None) != (self.published_date_precision is None):
            raise ValueError("published_date and published_date_precision must be set together")
        if self.page_count is not None and self.page_count <= 0:
            raise ValueError("page_count must be > 0 when present")


@dataclass(frozen=True)
class SourceRef:
    """A Book Source (``book_sources`` row) and the Book it belongs to."""

    source_id: UUID
    book_id: UUID


@dataclass(frozen=True)
class SourceRecord:
    """A ``book_sources`` row as the identity lookup sees it (data-model §7.3)."""

    source_id: UUID
    book_id: UUID
    external_id: str | None
