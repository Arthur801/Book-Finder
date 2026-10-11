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
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"  # skipped rows, no streak above 20 non-restricted errors; snapshot replaced
    FAILED = "FAILED"  # bestsellers unchanged


class SkipReason(StrEnum):
    """Why a ranking row was skipped (crawler.md §6, §12). Stored and logged as these values."""

    FETCH_ERROR = "fetch_error"
    PARSE_ERROR = "parse_error"
    DATABASE_ERROR = "database_error"
    DUPLICATE_BOOK_IN_RANKING = "duplicate_book_in_ranking"
    RESTRICTED_BOOK = "restricted_book"


@dataclass(frozen=True)
class Failure:
    """The (error_type, error_message, attempts) triple describing one failed row.

    ``attempts`` is the number of detail-page attempts actually made for the row. It is 0 when the
    detail page was never fetched (a known URL that duplicates an earlier rank).
    """

    error_type: SkipReason
    error_message: str
    attempts: int


@dataclass(frozen=True)
class SkippedRow:
    """A ranking row left out of the snapshot (crawler.md §6)."""

    rank: int
    url: str
    failure: Failure

    @property
    def is_restricted(self) -> bool:
        """A restricted member-only page: skipped without retry and not counted as an error."""
        return self.failure.error_type == SkipReason.RESTRICTED_BOOK


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
