"""Ranking validation (crawler.md §4).

The ranking page is all-or-nothing: any violation raises and the run fails without touching the
current bestsellers. Skipping applies only to new detail pages (run.py, crawler.md §6); it never
relaxes ``validate_ranking``.

Product URLs are canonicalized once, by the ranking parser (``parsers.parse_ranking_html``), so
the rows validated here already carry canonical URLs.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from books_crawler.models import RankingRow

EXPECTED_RANKING_COUNT = 100


class RankingValidationError(Exception):
    """The scraped ranking is incomplete or inconsistent."""


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
