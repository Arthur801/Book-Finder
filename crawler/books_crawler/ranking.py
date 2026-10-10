"""Ranking validation (crawler.md §4) and snapshot validation (crawler.md §10).

The ranking page is all-or-nothing: any violation raises and the run fails without touching the
current bestsellers. Skipping applies only to new detail pages (run.py, crawler.md §6); it never
relaxes ``validate_ranking``.

Product URLs are canonicalized once, by the ranking parser (``parsers.parse_ranking_html``), so
the rows validated here already carry canonical URLs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from uuid import UUID

from books_crawler.models import RankingRow, SnapshotRow

EXPECTED_RANKING_COUNT = 100
MAX_SKIPPED_ROWS = 10  # crawler.md §6: more skipped rows than this fails the run
MIN_SNAPSHOT_ROWS = EXPECTED_RANKING_COUNT - MAX_SKIPPED_ROWS  # crawler.md §10


class RankingValidationError(Exception):
    """The scraped ranking is incomplete or inconsistent."""


class SnapshotValidationError(Exception):
    """The bestseller snapshot to be written is inconsistent."""


def _has_exact_ranks(ranks: Iterable[int]) -> bool:
    """True when the ranks are exactly 1..100, each once (crawler.md §4)."""
    return sorted(ranks) == list(range(1, EXPECTED_RANKING_COUNT + 1))


def _has_unique_ranks_in_range(ranks: Sequence[int]) -> bool:
    """True when every rank is within 1..100 and no rank appears twice (snapshot may have gaps)."""
    return all(1 <= rank <= EXPECTED_RANKING_COUNT for rank in ranks) and len(set(ranks)) == len(ranks)


def validate_ranking(rows: Sequence[RankingRow]) -> list[RankingRow]:
    """Validate the 100-row ranking and return it sorted by rank.

    Requires exactly 100 rows, ranks exactly 1..100 (each once), non-empty product URLs and no
    product URL at two ranks.
    """
    if len(rows) != EXPECTED_RANKING_COUNT:
        raise RankingValidationError(f"expected {EXPECTED_RANKING_COUNT} ranking rows, got {len(rows)}")
    if not _has_exact_ranks(row.rank for row in rows):
        raise RankingValidationError("ranks must be exactly 1..100, each appearing once")
    for row in rows:
        if not row.url:
            raise RankingValidationError(f"rank {row.rank}: product URL is empty")

    ordered = sorted(rows, key=lambda item: item.rank)
    first_rank_by_url: dict[str, int] = {}
    for row in ordered:
        first = first_rank_by_url.setdefault(row.url, row.rank)
        if first != row.rank:
            raise RankingValidationError(f"duplicate product URL at ranks {first} and {row.rank}: {row.url}")
    return ordered


def validate_snapshot(rows: Sequence[SnapshotRow], source_books: Mapping[UUID, UUID]) -> list[SnapshotRow]:
    """Check the rows that will replace ``bestsellers`` (crawler.md §10).

    - 90..100 rows (at most ``MAX_SKIPPED_ROWS`` ranks missing);
    - ranks within 1..100 and unique (gaps are allowed, renumbering is not);
    - ``book_id`` unique (``bestsellers.book_id`` is UNIQUE);
    - every ``source_id`` is a BOOKS_COM_TW Book Source of that row's own Book.

    ``source_books`` maps the ``source_id`` of each BOOKS_COM_TW Book Source to its ``book_id``, as
    read from the database by the caller. A source missing from the mapping is not valid.
    """
    if not MIN_SNAPSHOT_ROWS <= len(rows) <= EXPECTED_RANKING_COUNT:
        raise SnapshotValidationError(
            f"snapshot must have {MIN_SNAPSHOT_ROWS}..{EXPECTED_RANKING_COUNT} rows, got {len(rows)}"
        )
    if not _has_unique_ranks_in_range([row.rank for row in rows]):
        raise SnapshotValidationError("snapshot ranks must be within 1..100 and unique")
    if len({row.book_id for row in rows}) != len(rows):
        raise SnapshotValidationError("snapshot book_id must be unique")
    for row in rows:
        if source_books.get(row.source_id) != row.book_id:
            raise SnapshotValidationError(
                f"rank {row.rank}: source {row.source_id} is not a BOOKS_COM_TW source of Book {row.book_id}"
            )
    return sorted(rows, key=lambda item: item.rank)
