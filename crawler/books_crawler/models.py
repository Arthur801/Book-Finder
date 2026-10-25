"""Plain data types shared by parsers, the DB layer and the run orchestration.

Values are already normalized (see ``catalog_core/normalize.py`` and ``normalize.py``). The enums are ``StrEnum``
whose values are exactly the stored vocabulary of ``Docs/data/data-model.md``, so they can be passed to SQL and
compared with plain strings. The provider-neutral Catalog types live in ``catalog_core.models``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

# Re-exported from catalog_core.models: existing imports from books_crawler.models keep working.
from catalog_core.models import (  # noqa: F401
    RESOLVED_CATALOG_RESOLUTIONS,
    BookDraft,
    CatalogResolution,
    Contributor,
    ContributorRole,
    Identifier,
    IdentifierType,
    ProviderCode,
    PublishedDatePrecision,
    SourceRecord,
    SourceRef,
)


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
class SnapshotRow:
    """One row of the bestseller snapshot that replaces the current ``bestsellers`` table."""

    rank: int
    book_id: UUID
    source_id: UUID
