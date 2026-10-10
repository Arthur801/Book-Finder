"""Plain data types shared by parsers, the DB layer and the run orchestration.

Values are already normalized (see ``normalize.py``). The enums are ``StrEnum`` whose values are
exactly the stored vocabulary of ``Docs/data/data-model.md`` (``BOOKS_COM_TW``, ``ISBN_13``,
``AUTHOR``, ``DAY`` ...), so they can be passed to SQL and compared with plain strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID


class SourceType(StrEnum):
    BOOKS_COM_TW = "BOOKS_COM_TW"


class PublishedDatePrecision(StrEnum):
    YEAR = "YEAR"
    MONTH = "MONTH"
    DAY = "DAY"


class IdentifierType(StrEnum):
    ISBN_10 = "ISBN_10"
    ISBN_13 = "ISBN_13"


class ContributorRole(StrEnum):
    AUTHOR = "AUTHOR"
    ORIGINAL_AUTHOR = "ORIGINAL_AUTHOR"
    TRANSLATOR = "TRANSLATOR"
    EDITOR = "EDITOR"
    ILLUSTRATOR = "ILLUSTRATOR"
    OTHER = "OTHER"


class RunStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"  # 1..10 skipped rows; bestsellers replaced (crawler.md §11)
    FAILED = "FAILED"  # bestsellers unchanged


@dataclass(frozen=True)
class SkippedRow:
    """A ranking row left out of the snapshot after its retries were exhausted (crawler.md §6)."""

    rank: int
    url: str
    error_type: str
    error_message: str
    attempts: int


@dataclass(frozen=True)
class RankingRow:
    """One row of the bestseller ranking: the source rank and the canonical product URL."""

    rank: int
    url: str


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
    """A BOOKS_COM_TW Book Source (``book_sources`` row) and the Book it belongs to."""

    source_id: UUID
    book_id: UUID


@dataclass(frozen=True)
class IsbnMatch:
    """An existing Book whose identifier equals one of a new source's identifiers."""

    book_id: UUID
    identifier: Identifier


@dataclass(frozen=True)
class SnapshotRow:
    """One row of the bestseller snapshot that replaces the current ``bestsellers`` table."""

    rank: int
    book_id: UUID
    source_id: UUID
