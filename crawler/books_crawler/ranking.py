"""Ranking validation (crawler.md §4) and snapshot validation (crawler.md §10).

A ranking is all-or-nothing: any violation raises and the run fails without touching the current
bestsellers. Skipping rules belong to issue #7, not here.

Product URLs are canonicalized once, by the ranking parser (``parsers.parse_ranking_html``), so
the rows validated here already carry canonical URLs.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from books_crawler.models import RankingRow, SnapshotRow

EXPECTED_RANKING_COUNT = 100


class RankingValidationError(Exception):
    """The scraped ranking is incomplete or inconsistent."""


class SnapshotValidationError(Exception):
    """The bestseller snapshot to be written is inconsistent."""


def _has_exact_ranks(ranks: Iterable[int]) -> bool:
    """True when the ranks are exactly 1..100, each once (crawler.md §4)."""
    return sorted(ranks) == list(range(1, EXPECTED_RANKING_COUNT + 1))


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


def validate_snapshot(rows: Sequence[SnapshotRow]) -> list[SnapshotRow]:
    """Check the rows that will replace ``bestsellers``.

    Requires exactly 100 rows (no skips exist before issue #7), ranks exactly 1..100 and a
    book_id that appears once (``bestsellers.book_id`` is UNIQUE).
    """
    if len(rows) != EXPECTED_RANKING_COUNT:
        raise SnapshotValidationError(f"snapshot must have {EXPECTED_RANKING_COUNT} rows, got {len(rows)}")
    if not _has_exact_ranks(row.rank for row in rows):
        raise SnapshotValidationError("snapshot ranks must be exactly 1..100, each once")
    if len({row.book_id for row in rows}) != len(rows):
        raise SnapshotValidationError("snapshot book_id must be unique")
    return sorted(rows, key=lambda item: item.rank)
