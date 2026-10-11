"""Run accounting through the ``RunLedger`` interface: no database, no fetcher (crawler.md §6, §11).

Each test records row outcomes in rank order, the way the run does, and checks the resulting report.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import pytest

from books_crawler.ledger import RunLedger, RunReport
from books_crawler.models import Failure, Resolution, ResolvedRow, RunStatus, SkipReason, SkippedRow, SourceRef
from tests.fakes import product_url

NOW = datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)


def resolved(rank: int, resolution: Resolution = Resolution.NEW_BOOK, book_id: uuid.UUID | None = None) -> ResolvedRow:
    return ResolvedRow(rank=rank, source_ref=SourceRef(uuid.uuid4(), book_id or uuid.uuid4()), resolution=resolution)


def failed(rank: int, reason: SkipReason = SkipReason.FETCH_ERROR, attempts: int = 3) -> SkippedRow:
    return SkippedRow(rank=rank, url=product_url(rank), failure=Failure(reason, f"rank {rank} failed", attempts))


def restricted(rank: int) -> SkippedRow:
    return failed(rank, SkipReason.RESTRICTED_BOOK, attempts=1)


def record_until_abort(ledger: RunLedger, outcomes) -> RunLedger:
    """Record outcomes until the ledger aborts, like the run loop."""
    for outcome in outcomes:
        ledger.record(outcome)
        if ledger.aborted:
            break
    return ledger


def report_of(ledger: RunLedger, error: str | None = None) -> RunReport:
    return ledger.report(run_id="run", started_at=NOW, finished_at=NOW, ranking_count=100, error=error)


def test_all_rows_resolved_is_success_with_counters_and_snapshot():
    outcomes = [
        resolved(1, Resolution.EXISTING_SOURCE),
        resolved(2, Resolution.ISBN_ATTACHED),
        resolved(3, Resolution.NEW_BOOK),
        resolved(4, Resolution.NEW_BOOK),
    ]
    ledger = record_until_abort(RunLedger(), outcomes)
    report = report_of(ledger)

    assert report.status is RunStatus.SUCCESS
    assert report.exit_code == 0
    assert (report.existing_book_count, report.attached_source_count, report.new_book_count) == (2, 1, 2)
    assert report.skipped == [] and report.error is None and report.aborted_at_rank is None
    assert [row.rank for row in ledger.snapshot] == [1, 2, 3, 4]
    assert [(row.book_id, row.source_id) for row in ledger.snapshot] == [
        (item.source_ref.book_id, item.source_ref.source_id) for item in outcomes
    ]


@pytest.mark.parametrize(
    ("first_failing_rank", "failures", "expected_abort_rank"),
    [
        (1, 20, None),  # 20 consecutive errors keep going
        (1, 21, 21),  # the 21st stops the run at once
        (80, 21, 100),  # the 21st error is the last rank
    ],
)
def test_consecutive_error_limit(first_failing_rank, failures, expected_abort_rank):
    failing = set(range(first_failing_rank, first_failing_rank + failures))
    outcomes = [failed(rank) if rank in failing else resolved(rank) for rank in range(1, 101)]
    ledger = record_until_abort(RunLedger(), outcomes)
    report = report_of(ledger)

    assert report.aborted_at_rank == expected_abort_rank
    if expected_abort_rank is None:
        assert report.status is RunStatus.PARTIAL_SUCCESS
        assert report.error is None
        assert len(ledger.snapshot) == 100 - failures
    else:
        assert ledger.aborted
        assert report.status is RunStatus.FAILED
        assert report.exit_code == 1
        assert report.consecutive_error_count == 21
        assert report.error == (
            f"run aborted at rank {expected_abort_rank} after 21 consecutive error(s) (limit 20): "
            f"fetch_error: rank {expected_abort_rank} failed"
        )


@pytest.mark.parametrize(
    "reset",
    [
        lambda rank: resolved(rank, Resolution.NEW_BOOK),
        lambda rank: resolved(rank, Resolution.EXISTING_SOURCE),
        lambda rank: resolved(rank, Resolution.ISBN_ATTACHED),
        restricted,
    ],
    ids=["new-book", "existing-source", "isbn-attached", "restricted"],
)
def test_any_non_error_row_resets_the_streak(reset):
    outcomes = [failed(rank) for rank in range(1, 21)] + [reset(21)] + [failed(rank) for rank in range(22, 42)]
    report = report_of(record_until_abort(RunLedger(), outcomes))

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.aborted_at_rank is None
    assert report.error_count == 40
    assert report.consecutive_error_count == 20


@pytest.mark.parametrize(
    "reason",
    [SkipReason.FETCH_ERROR, SkipReason.PARSE_ERROR, SkipReason.DATABASE_ERROR, SkipReason.DUPLICATE_BOOK_IN_RANKING],
)
def test_every_general_error_type_counts_toward_the_streak(reason):
    report = report_of(record_until_abort(RunLedger(), [failed(rank, reason) for rank in range(1, 22)]))

    assert report.aborted_at_rank == 21
    assert f": {reason}: rank 21 failed" in report.error


def test_cumulative_errors_have_no_limit():
    outcomes = [failed(rank) if rank % 2 else resolved(rank) for rank in range(1, 101)]
    ledger = record_until_abort(RunLedger(), outcomes)
    report = report_of(ledger)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.error_count == 50
    assert [row.rank for row in ledger.snapshot] == list(range(2, 101, 2))  # original ranks, gaps kept


def test_restricted_rows_are_skipped_but_are_not_errors():
    outcomes = [restricted(rank) for rank in range(1, 31)] + [resolved(31)]
    ledger = record_until_abort(RunLedger(), outcomes)
    report = report_of(ledger)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert (report.skipped_count, report.restricted_book_count, report.error_count) == (30, 30, 0)
    assert report.consecutive_error_count == 0
    assert [item.rank for item in report.skipped if item.is_restricted] == list(range(1, 31))


@pytest.mark.parametrize(
    ("outcome", "status", "aborted_at_rank"),
    [
        (resolved(1), RunStatus.SUCCESS, None),
        (restricted(1), RunStatus.PARTIAL_SUCCESS, None),
        (failed(1, SkipReason.DATABASE_ERROR), RunStatus.FAILED, 1),
    ],
    ids=["imported", "restricted", "general-error"],
)
def test_limit_zero_is_the_single_book_policy(outcome, status, aborted_at_rank):
    report = report_of(record_until_abort(RunLedger(max_consecutive_errors=0), [outcome]))

    assert report.status is status
    assert report.aborted_at_rank == aborted_at_rank
    if aborted_at_rank is not None:
        assert report.error == "run aborted at rank 1 after 1 consecutive error(s) (limit 0): database_error: rank 1 failed"


def test_external_error_fails_the_run_even_without_rows():
    report = report_of(RunLedger(), error="FetchError: ranking page failed")

    assert report.status is RunStatus.FAILED
    assert report.error == "FetchError: ranking page failed"
    assert report.aborted_at_rank is None


def test_external_error_after_rows_keeps_the_counters():
    ledger = record_until_abort(RunLedger(), [resolved(1), failed(2)])
    report = report_of(ledger, error="OperationalError: replace failed")

    assert report.status is RunStatus.FAILED
    assert (report.new_book_count, report.error_count) == (1, 1)


def test_ranked_maps_each_book_to_its_rank_and_is_read_only():
    first = resolved(1)
    ledger = record_until_abort(RunLedger(), [first, failed(2), resolved(3)])

    assert ledger.ranked[first.source_ref.book_id] == 1
    assert len(ledger.ranked) == 2
    with pytest.raises(TypeError):
        ledger.ranked[uuid.uuid4()] = 4  # type: ignore[index]


def test_a_book_already_in_the_snapshot_is_a_programming_error():
    book_id = uuid.uuid4()
    ledger = record_until_abort(RunLedger(), [resolved(1, book_id=book_id)])

    with pytest.raises(ValueError, match="already used by rank 1"):
        ledger.record(resolved(2, book_id=book_id))


def test_outcomes_must_arrive_in_rank_order():
    ledger = record_until_abort(RunLedger(), [resolved(5)])

    with pytest.raises(ValueError, match="rank order"):
        ledger.record(resolved(5))


def test_nothing_can_be_recorded_after_an_abort():
    ledger = record_until_abort(RunLedger(max_consecutive_errors=0), [failed(1)])

    with pytest.raises(ValueError, match="aborted"):
        ledger.record(resolved(2))


def test_skips_are_logged_and_the_abort_is_left_to_the_caller(caplog):
    caplog.set_level(logging.INFO, logger="books_crawler")
    outcomes = [restricted(1), failed(2, attempts=3), failed(3, SkipReason.PARSE_ERROR)]
    record_until_abort(RunLedger(max_consecutive_errors=1), outcomes)

    by_message = {record.getMessage(): record.levelno for record in caplog.records}
    assert by_message["rank 1 skipped after 1 attempt(s) (restricted_book): rank 1 failed"] == logging.INFO
    assert by_message["rank 2 skipped after 3 attempt(s) (fetch_error): rank 2 failed"] == logging.WARNING
    # The run logs the single ERROR line for a failed run, abort included (crawler.md §11).
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
