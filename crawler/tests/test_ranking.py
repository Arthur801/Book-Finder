import pytest

from books_crawler.models import RankingRow
from books_crawler.ranking import RankingValidationError, validate_ranking
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
