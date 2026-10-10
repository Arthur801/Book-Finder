"""Plain data types shared by parsers, the DB layer and the run orchestration.

Values are already normalized (see ``normalize.py``) and use the stored vocabulary of
``Docs/data/data-model.md`` (``BOOKS_COM_TW``, ``ISBN_13``, ``AUTHOR``, ``DAY`` ...).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

SOURCE_TYPE_BOOKS_COM_TW = "BOOKS_COM_TW"

PRECISION_YEAR = "YEAR"
PRECISION_MONTH = "MONTH"
PRECISION_DAY = "DAY"
VALID_PRECISIONS = frozenset({PRECISION_YEAR, PRECISION_MONTH, PRECISION_DAY})

IDENTIFIER_ISBN_10 = "ISBN_10"
IDENTIFIER_ISBN_13 = "ISBN_13"

ROLE_AUTHOR = "AUTHOR"
ROLE_ORIGINAL_AUTHOR = "ORIGINAL_AUTHOR"
ROLE_TRANSLATOR = "TRANSLATOR"
ROLE_EDITOR = "EDITOR"
ROLE_ILLUSTRATOR = "ILLUSTRATOR"
ROLE_OTHER = "OTHER"


@dataclass(frozen=True)
class RankingRow:
    """One row of the bestseller ranking page: the source rank and the product URL."""

    rank: int
    url: str


@dataclass(frozen=True)
class Identifier:
    identifier_type: str  # ISBN_10 / ISBN_13
    identifier_value: str  # normalized: no dashes or spaces, uppercase


@dataclass(frozen=True)
class Contributor:
    order: int  # 1-based position in the source listing
    name: str
    role: str  # one of the ROLE_* constants


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
    published_date_precision: str | None = None
    language: str | None = None
    description: str | None = None
    table_of_contents: str | None = None
    page_count: int | None = None
    thumbnail_url: str | None = None
    identifiers: tuple[Identifier, ...] = ()
    contributors: tuple[Contributor, ...] = ()
    subjects: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.title or not self.title.strip():
            raise ValueError("title is required")
        if (self.published_date is None) != (self.published_date_precision is None):
            raise ValueError("published_date and published_date_precision must be set together")
        if self.published_date_precision is not None and self.published_date_precision not in VALID_PRECISIONS:
            raise ValueError(f"invalid published_date_precision: {self.published_date_precision!r}")
        if self.page_count is not None and self.page_count <= 0:
            raise ValueError("page_count must be > 0 when present")


@dataclass(frozen=True)
class SourceRef:
    """A BOOKS_COM_TW ``book_sources`` row and the Book it belongs to."""

    source_id: UUID
    book_id: UUID


@dataclass(frozen=True)
class SnapshotRow:
    """One row of the bestseller snapshot that replaces the current ``bestsellers`` table."""

    rank: int
    book_id: UUID
    source_id: UUID
