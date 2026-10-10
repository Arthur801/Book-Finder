import uuid

import pytest

from books_crawler.models import RankingRow, SnapshotRow
from books_crawler.ranking import (
    RankingValidationError,
    SnapshotValidationError,
    validate_ranking,
    validate_snapshot,
)
from tests.fakes import product_url, ranking_rows


def test_valid_ranking_is_returned_sorted_by_rank():
    rows = list(reversed(ranking_rows(100)))

    result = validate_ranking(rows)

    assert [row.rank for row in result] == list(range(1, 101))
    assert result[0].url == product_url(1)


def test_ranking_with_fewer_than_100_rows_fails():
    with pytest.raises(RankingValidationError, match="expected 100"):
        validate_ranking(ranking_rows(99))


def test_ranking_with_more_than_100_rows_fails():
    with pytest.raises(RankingValidationError, match="expected 100"):
        validate_ranking(ranking_rows(100) + [RankingRow(rank=101, url=product_url(999))])


def test_duplicate_product_url_fails():
    rows = ranking_rows(100)
    rows[1] = RankingRow(rank=2, url=product_url(1))  # rank 2 now points at rank 1's product

    with pytest.raises(RankingValidationError, match="duplicate product URL at ranks 1 and 2"):
        validate_ranking(rows)


def test_duplicate_rank_fails():
    rows = ranking_rows(100)
    rows[1] = RankingRow(rank=1, url=product_url(500))

    with pytest.raises(RankingValidationError, match="ranks must be exactly 1..100"):
        validate_ranking(rows)


def test_rank_out_of_range_fails():
    rows = ranking_rows(100)
    rows[-1] = RankingRow(rank=101, url=product_url(500))

    with pytest.raises(RankingValidationError, match="ranks must be exactly 1..100"):
        validate_ranking(rows)


def test_empty_product_url_fails():
    rows = ranking_rows(100)
    rows[0] = RankingRow(rank=1, url="")

    with pytest.raises(RankingValidationError, match="rank 1: product URL is empty"):
        validate_ranking(rows)


def _snapshot(count: int = 100) -> list[SnapshotRow]:
    return [SnapshotRow(rank=rank, book_id=uuid.uuid4(), source_id=uuid.uuid4()) for rank in range(1, count + 1)]


def test_valid_snapshot_passes():
    assert len(validate_snapshot(_snapshot())) == 100


def test_snapshot_must_have_100_rows():
    with pytest.raises(SnapshotValidationError, match="100 rows"):
        validate_snapshot(_snapshot(99))


def test_snapshot_ranks_must_be_exact():
    rows = _snapshot()
    rows[1] = SnapshotRow(rank=1, book_id=rows[1].book_id, source_id=rows[1].source_id)

    with pytest.raises(SnapshotValidationError, match="ranks must be exactly 1..100"):
        validate_snapshot(rows)


def test_snapshot_book_ids_must_be_unique():
    rows = _snapshot()
    rows[1] = SnapshotRow(rank=2, book_id=rows[0].book_id, source_id=rows[1].source_id)

    with pytest.raises(SnapshotValidationError, match="book_id must be unique"):
        validate_snapshot(rows)
