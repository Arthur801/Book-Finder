"""Accounting for pages mode (``ledger.PagesLedger``, crawler.md §15, pages mode). Pure: no database, no fetcher."""

import logging
from datetime import UTC, datetime
from uuid import uuid4

from books_crawler.ledger import EXIT_FAILED, EXIT_SUCCESS, PagesLedger
from books_crawler.models import (
    CatalogResolution,
    Failure,
    JobName,
    ResolvedRow,
    RunStatus,
    SkippedPage,
    SkippedRow,
    SkipReason,
    SourceRef,
)

NOW = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)
PAGE_1 = "https://www.books.com.tw/web/sys_saletopb/books/01/?attribute=7&loc=P_0002_002"
PAGE_2 = "https://www.books.com.tw/web/sys_saletopb/books/02/?attribute=7&loc=P_0002_003"


def resolved(rank: int, resolution: CatalogResolution = CatalogResolution.IMPORTED) -> ResolvedRow:
    return ResolvedRow(
        rank=rank, url=f"https://www.books.com.tw/products/{rank:010d}", source_ref=SourceRef(source_id=uuid4(), book_id=uuid4()), resolution=resolution
    )


def skipped(rank: int, reason: SkipReason = SkipReason.FETCH_ERROR, attempts: int = 3) -> SkippedRow:
    return SkippedRow(
        rank=rank,
        url=f"https://www.books.com.tw/products/{rank:010d}",
        failure=Failure(error_type=reason, error_message="simulated", attempts=attempts),
    )


def skipped_page(url: str = PAGE_1) -> SkippedPage:
    return SkippedPage(url=url, failure=Failure(error_type=SkipReason.FETCH_ERROR, error_message="HTTP 403", attempts=3))


def finish(ledger: PagesLedger, error: str | None = None):
    return ledger.report(run_id="run-1", job_name=JobName.CATEGORY_PAGES, started_at=NOW, finished_at=NOW, error=error)


def test_every_page_and_row_done_is_success_with_counters_and_no_skips():
    ledger = PagesLedger()
    ledger.record_page_ok()
    ledger.record(resolved(1, CatalogResolution.IMPORTED))
    ledger.record(resolved(2, CatalogResolution.EXISTING))
    ledger.record(resolved(3, CatalogResolution.ISBN_ATTACHED))
    ledger.record_page_ok()

    report = finish(ledger)

    assert report.status is RunStatus.SUCCESS
    assert report.exit_code == EXIT_SUCCESS
    assert report.pages_total == 2
    assert report.rows_seen == 3
    assert report.new_book_count == 1
    assert report.existing_book_count == 2  # the existing source and the ISBN-attached one
    assert report.attached_source_count == 1
    assert report.skipped == [] and report.skipped_pages == []
    assert report.error is None


def test_a_skipped_row_makes_the_run_partial_success_and_exit_zero():
    ledger = PagesLedger()
    ledger.record_page_ok()
    ledger.record(resolved(1))
    ledger.record(skipped(2))

    report = finish(ledger)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.exit_code == EXIT_SUCCESS
    assert report.skipped_count == 1
    assert report.error_count == 1
    assert report.restricted_book_count == 0


def test_a_restricted_row_is_partial_success_but_not_an_error():
    ledger = PagesLedger()
    ledger.record_page_ok()
    ledger.record(skipped(1, SkipReason.RESTRICTED_BOOK, attempts=1))

    report = finish(ledger)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.exit_code == EXIT_SUCCESS
    assert report.restricted_book_count == 1
    assert report.error_count == 0


def test_a_skipped_page_makes_the_run_partial_success_and_is_counted():
    ledger = PagesLedger()
    ledger.record_page_skipped(skipped_page(PAGE_1))
    ledger.record_page_ok()
    ledger.record(resolved(1))

    report = finish(ledger)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.exit_code == EXIT_SUCCESS
    assert report.pages_total == 2
    assert [page.url for page in report.skipped_pages] == [PAGE_1]
    assert report.skipped == []  # a page is not a row


def test_when_every_configured_page_failed_the_run_fails_with_exit_one():
    ledger = PagesLedger()
    ledger.record_page_skipped(skipped_page(PAGE_1))
    ledger.record_page_skipped(skipped_page(PAGE_2))

    report = finish(ledger)

    assert report.status is RunStatus.FAILED
    assert report.exit_code == EXIT_FAILED
    assert report.error == "all 2 category page(s) failed"


def test_row_failures_never_abort_however_many_come_in_a_row():
    ledger = PagesLedger()
    ledger.record_page_ok()
    for rank in range(1, 51):
        ledger.record(skipped(rank))
    ledger.record(resolved(51))

    report = finish(ledger)

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.exit_code == EXIT_SUCCESS
    assert report.aborted_at_rank is None
    assert report.skipped_count == 50
    assert report.new_book_count == 1


def test_an_external_error_fails_the_run_even_when_rows_were_recorded():
    ledger = PagesLedger()
    ledger.record_page_ok()
    ledger.record(resolved(1))

    report = finish(ledger, error="OperationalError: database is down")

    assert report.status is RunStatus.FAILED
    assert report.exit_code == EXIT_FAILED
    assert report.new_book_count == 1
    assert report.error == "OperationalError: database is down"


def test_an_empty_run_with_no_pages_is_success():
    report = finish(PagesLedger())

    assert report.status is RunStatus.SUCCESS
    assert report.pages_total == 0
    assert report.rows_seen == 0


def test_the_same_rank_on_two_pages_and_the_same_book_twice_are_not_errors():
    ledger = PagesLedger()
    book = SourceRef(source_id=uuid4(), book_id=uuid4())
    ledger.record_page_ok()
    ledger.record(ResolvedRow(rank=1, url=PAGE_1, source_ref=book, resolution=CatalogResolution.EXISTING))
    ledger.record_page_ok()
    ledger.record(ResolvedRow(rank=1, url=PAGE_1, source_ref=book, resolution=CatalogResolution.EXISTING))

    report = finish(ledger)

    assert report.status is RunStatus.SUCCESS
    assert report.rows_seen == 2


def test_a_skipped_row_is_logged_with_its_page_url_and_attempts(caplog):
    caplog.set_level(logging.INFO, logger="books_crawler")
    outcome = skipped(2)
    ledger = PagesLedger()

    ledger.record(outcome)

    assert caplog.messages == [f"page rank 2 ({outcome.url}) skipped after 3 attempt(s) (fetch_error): simulated"]


def test_catalog_counters_follow_the_catalog_axis_table_with_no_ranking_decision():
    ledger = PagesLedger()
    ledger.record_page_ok()
    ledger.record(resolved(1, CatalogResolution.EXISTING))
    ledger.record(resolved(2, CatalogResolution.IMPORTED))
    ledger.record(resolved(3, CatalogResolution.ISBN_ATTACHED))
    ledger.record(resolved(4, CatalogResolution.AMBIGUOUS_CREATED))
    ledger.record(skipped(5, SkipReason.RESTRICTED_BOOK, attempts=1))
    ledger.record(skipped(6))

    report = finish(ledger)

    assert report.items_seen == report.rows_seen == 6
    assert (report.existing_book_count, report.new_book_count, report.attached_source_count) == (2, 2, 1)
    assert (report.existing_source_count, report.new_source_count, report.ambiguous_isbn_count) == (1, 3, 1)
    assert (report.skipped_count, report.restricted_book_count, report.error_count) == (2, 1, 1)
    assert report.offer_updated_count == 0
    assert report.job_name is JobName.CATEGORY_PAGES
    assert report.provider_code == "BOOKS_COM_TW"
