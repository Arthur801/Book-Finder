"""Ranking validation (crawler.md §4) and snapshot validation (crawler.md §10).

A ranking is all-or-nothing: any violation raises ``RankingValidationError`` and the run fails
without touching the current bestsellers. Skipping rules belong to issue #7, not here.
"""

from __future__ import annotations

from collections.abc import Sequence

from books_crawler.models import RankingRow, SnapshotRow
from books_crawler.urls import InvalidProductUrl, canonicalize_product_url

EXPECTED_RANKING_COUNT = 100


class RankingValidationError(Exception):
    """The scraped ranking is incomplete or inconsistent."""


class SnapshotValidationError(Exception):
    """The bestseller snapshot to be written is inconsistent."""


def validate_ranking(rows: Sequence[RankingRow]) -> list[RankingRow]:
    """Canonicalize product URLs and validate the 100-row ranking.

    Requires exactly 100 rows, ranks exactly 1..100 (each once), non-empty product URLs
    that are unique after canonicalization. Returns the rows sorted by rank with canonical URLs.
    """
    if len(rows) != EXPECTED_RANKING_COUNT:
        raise RankingValidationError(f"expected {EXPECTED_RANKING_COUNT} ranking rows, got {len(rows)}")

    canonical: list[RankingRow] = []
    for row in rows:
        try:
            url = canonicalize_product_url(row.url)
        except InvalidProductUrl as exc:
            raise RankingValidationError(f"rank {row.rank}: {exc}") from exc
        canonical.append(RankingRow(rank=row.rank, url=url))

    ranks = sorted(row.rank for row in canonical)
    if ranks != list(range(1, EXPECTED_RANKING_COUNT + 1)):
        raise RankingValidationError("ranks must be exactly 1..100, each appearing once")

    first_rank_by_url: dict[str, int] = {}
    for row in sorted(canonical, key=lambda item: item.rank):
        first = first_rank_by_url.setdefault(row.url, row.rank)
        if first != row.rank:
            raise RankingValidationError(f"duplicate product URL at ranks {first} and {row.rank}: {row.url}")

    return sorted(canonical, key=lambda item: item.rank)


def validate_snapshot(rows: Sequence[SnapshotRow]) -> list[SnapshotRow]:
    """Check the rows that will replace ``bestsellers``.

    Requires exactly 100 rows (no skips exist before issue #7), rank 1..100 unique, book_id unique.
    """
    if len(rows) != EXPECTED_RANKING_COUNT:
        raise SnapshotValidationError(f"snapshot must have {EXPECTED_RANKING_COUNT} rows, got {len(rows)}")
    ranks = sorted(row.rank for row in rows)
    if ranks != list(range(1, EXPECTED_RANKING_COUNT + 1)):
        raise SnapshotValidationError("snapshot ranks must be exactly 1..100, each once")
    if len({row.book_id for row in rows}) != len(rows):
        raise SnapshotValidationError("snapshot book_id must be unique")
    return sorted(rows, key=lambda item: item.rank)
