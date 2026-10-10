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


def _owners(rows: list[SnapshotRow]) -> dict[uuid.UUID, uuid.UUID]:
    """source_id -> book_id as the database would report it: every row's source belongs to its Book."""
    return {row.source_id: row.book_id for row in rows}


def test_valid_snapshot_passes():
    rows = _snapshot()
    assert len(validate_snapshot(rows, _owners(rows))) == 100


def test_snapshot_with_gaps_from_skipped_ranks_passes():
    rows = [row for row in _snapshot() if row.rank not in {3, 50, 99}]

    result = validate_snapshot(rows, _owners(rows))

    assert len(result) == 97
    assert [row.rank for row in result][:4] == [1, 2, 4, 5]  # original ranks kept, not renumbered


def test_snapshot_must_have_between_90_and_100_rows():
    with pytest.raises(SnapshotValidationError, match="90..100 rows"):
        validate_snapshot(_snapshot(89), {})

    rows = _snapshot(90)
    assert len(validate_snapshot(rows, _owners(rows))) == 90


def test_snapshot_ranks_must_be_within_range_and_unique():
    rows = _snapshot()
    rows[1] = SnapshotRow(rank=1, book_id=rows[1].book_id, source_id=rows[1].source_id)

    with pytest.raises(SnapshotValidationError, match="within 1..100 and unique"):
        validate_snapshot(rows, _owners(rows))


def test_snapshot_rank_out_of_range_fails():
    rows = _snapshot(90)
    rows[-1] = SnapshotRow(rank=101, book_id=rows[-1].book_id, source_id=rows[-1].source_id)

    with pytest.raises(SnapshotValidationError, match="within 1..100 and unique"):
        validate_snapshot(rows, _owners(rows))


def test_snapshot_book_ids_must_be_unique():
    rows = _snapshot()
    rows[1] = SnapshotRow(rank=2, book_id=rows[0].book_id, source_id=rows[1].source_id)

    with pytest.raises(SnapshotValidationError, match="book_id must be unique"):
        validate_snapshot(rows, _owners(rows))


def test_source_must_be_a_booksdotcom_source_of_the_same_book():
    rows = _snapshot()
    owners = _owners(rows)
    owners[rows[4].source_id] = uuid.uuid4()  # the source now belongs to some other Book

    with pytest.raises(SnapshotValidationError, match="rank 5: source .* is not a BOOKS_COM_TW source"):
        validate_snapshot(rows, owners)


def test_source_missing_from_the_database_is_rejected():
    rows = _snapshot()
    owners = _owners(rows)
    del owners[rows[0].source_id]  # e.g. not a BOOKS_COM_TW source, so the lookup did not return it

    with pytest.raises(SnapshotValidationError, match="rank 1: source"):
        validate_snapshot(rows, owners)
