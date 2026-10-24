"""Plain data types shared by parsers, the DB layer and the run orchestration.

Values are already normalized (see ``normalize.py``). The enums are ``StrEnum`` whose values are
exactly the stored vocabulary of ``Docs/data/data-model.md`` (``BOOKS_COM_TW``, ``ISBN``,
``AUTHOR``, ``DAY`` ...), so they can be passed to SQL and compared with plain strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID


class ProviderCode(StrEnum):
    """``source_providers.code`` values this crawler writes (data-model §7, crawler.md §3.1)."""

    BOOKS_COM_TW = "BOOKS_COM_TW"


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


class RunStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"  # skipped rows, no streak above 20 non-restricted errors; snapshot replaced
    FAILED = "FAILED"  # bestsellers unchanged


class SkipReason(StrEnum):
    """Why a row was skipped (crawler.md §13, §14.2). Stored and logged as these values."""

    FETCH_ERROR = "fetch_error"
    PARSE_ERROR = "parse_error"
    DATABASE_ERROR = "database_error"
    DUPLICATE_BOOK_IN_RANKING = "duplicate_book_in_ranking"
    RESTRICTED_BOOK = "restricted_book"
    SOURCE_IDENTITY_CONFLICT = "source_identity_conflict"  # data-model §7.3: not retried, not written


class JobName(StrEnum):
    """The discovery job of a run, as logged in ``job_name`` (crawler.md §19.2, §15.8)."""

    DAILY_BESTSELLER = "daily-bestseller"
    FIRST_BOOK = "first-book"
    CATEGORY_PAGES = "category-pages"


PROVIDER = ProviderCode.BOOKS_COM_TW  # the single provider this crawler writes (crawler.md §3.1); logged as provider_code


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


class RankingDecision(StrEnum):
    """Ranking-side decision for one row of a ranking job (crawler.md §3.5, §14.2). Decided by ``RunLedger`` only."""

    ADMITTED = "ADMITTED"  # kept in the snapshot at its rank
    DUPLICATE_BOOK = "DUPLICATE_BOOK"  # the Book is already used by an earlier rank
    RESTRICTED_SKIP = "RESTRICTED_SKIP"  # restricted page: skipped, not an error
    ERROR_SKIP = "ERROR_SKIP"  # general error: skipped, counts toward the streak


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
    """A discovery item left out of the snapshot (crawler.md §14.2)."""

    rank: int
    url: str
    failure: Failure

    @property
    def is_restricted(self) -> bool:
        """A restricted member-only page: skipped without retry and not counted as an error."""
        return self.failure.error_type == SkipReason.RESTRICTED_BOOK

    @property
    def resolution(self) -> CatalogResolution:
        """The Catalog-side outcome of a skipped row: RESTRICTED or FAILED (crawler.md §6.5)."""
        return CatalogResolution.RESTRICTED if self.is_restricted else CatalogResolution.FAILED


@dataclass(frozen=True)
class SkippedPage:
    """A category ranking page skipped in pages mode because it could not be fetched or parsed (crawler.md §15.4)."""

    url: str
    failure: Failure


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
class ResolvedRow:
    """A discovery item that resolved to a Book (a resolved ``CatalogResolution``).

    ``attempts`` is the number of attempts that produced the resolution: 0 for an existing Source (no
    detail request), otherwise the attempt that wrote the Source. It is only used if the ledger later
    decides ``DUPLICATE_BOOK`` for this row.
    """

    rank: int
    url: str
    source_ref: SourceRef
    resolution: CatalogResolution
    attempts: int = 0

    def __post_init__(self) -> None:
        if self.resolution not in RESOLVED_CATALOG_RESOLUTIONS:
            raise ValueError(f"{self.resolution} is not a resolved outcome; use SkippedRow")


@dataclass(frozen=True)
class SourceRecord:
    """A ``book_sources`` row as the identity lookup sees it (data-model §7.3)."""

    source_id: UUID
    book_id: UUID
    external_id: str | None


@dataclass(frozen=True)
class SnapshotRow:
    """One row of the bestseller snapshot that replaces the current ``bestsellers`` table."""

    rank: int
    book_id: UUID
    source_id: UUID
