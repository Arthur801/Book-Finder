"""Kingstone run ledger and the one terminal status rule (kingstone.ledger). Offline: no database, no fetcher."""

import json
import logging
import uuid
from datetime import UTC, datetime

import pytest

from catalog_core.models import CatalogResolution, ProviderCode, SourceRef
from catalog_core.service import ItemFailed, ItemResolved
from kingstone.ledger import (
    EXIT_FAILED,
    EXIT_SUCCESS,
    FailedItem,
    KingstoneLedger,
    KingstoneReport,
    RunStatus,
    SkippedPage,
    decide_status,
    format_report,
)

BASE = "https://www.kingstone.com.tw/book/jdc/?dis=list&page="
P1, P2, P3 = BASE + "1", BASE + "2", BASE + "3"
DETAIL = "https://www.kingstone.com.tw/basic/9789570000001/"
START = datetime(2026, 10, 25, 1, 0, tzinfo=UTC)
FINISH = datetime(2026, 10, 25, 2, 0, tzinfo=UTC)


def resolved(resolution=CatalogResolution.IMPORTED, *, recovered=False, warning=None):
    return ItemResolved(
        SourceRef(source_id=uuid.UUID(int=1), book_id=uuid.UUID(int=2)),
        resolution,
        attempts=1,
        recovered_commit=recovered,
        identity_warning=warning,
    )


def failed(reason="parse_error", *, message="layout changed", attempts=2, warning=None):
    return ItemFailed(reason, message, attempts=attempts, identity_warning=warning)


def item(ledger, page, result, external_id="9789570000001"):
    ledger.record_item(page, result, source_url=DETAIL, external_id=external_id)


def skipped(url, reason="fetch_error", message="HTTP 503", attempts=3):
    return SkippedPage(url=url, reason=reason, message=message, attempts=attempts)


def build(ledger, *, error=None):
    return ledger.report(run_id="run-1", started_at=START, finished_at=FINISH, error=error)


def completed_page(ledger, page, *results):
    ledger.page_started(page)
    for result in results:
        item(ledger, page, result)
    ledger.page_completed(page)


# --- terminal status: the rule, row by row (crawler.md §7) ---------------------------------------------------------


def test_fatal_error_is_failed_even_after_useful_progress():
    ledger = KingstoneLedger([P1, P2])
    completed_page(ledger, P1, resolved())
    report = build(ledger, error="database unavailable")
    assert report.status is RunStatus.FAILED
    assert report.zero_progress_reason is None
    assert report.error == "database unavailable"
    assert report.exit_code == EXIT_FAILED


def test_every_page_skipped_is_failed_with_a_zero_progress_reason():
    ledger = KingstoneLedger([P1, P2])
    ledger.record_page_skipped(skipped(P1))
    ledger.record_page_skipped(skipped(P2, reason="redirect", message="HTTP 302", attempts=1))
    report = build(ledger)
    assert report.status is RunStatus.FAILED
    assert report.zero_progress_reason is not None
    assert "skipped" in report.zero_progress_reason
    assert report.exit_code == EXIT_FAILED


def test_budget_exhausted_before_the_first_page_completes_is_failed():
    ledger = KingstoneLedger([P1, P2])
    ledger.page_started(P1)
    item(ledger, P1, resolved())
    ledger.stop_for_budget()
    report = build(ledger)
    assert report.status is RunStatus.FAILED
    assert report.zero_progress_reason is not None
    assert "budget" in report.zero_progress_reason
    assert report.pages_interrupted == 1
    assert report.pages_not_reached == 1
    assert report.budget_exhausted is True


def test_budget_exhausted_before_any_page_starts_is_failed():
    ledger = KingstoneLedger([P1])
    ledger.stop_for_budget()
    report = build(ledger)
    assert report.status is RunStatus.FAILED
    assert "budget" in report.zero_progress_reason
    assert report.pages_not_reached == 1


def test_empty_page_list_is_failed_with_a_reason():
    report = build(KingstoneLedger([]))
    assert report.status is RunStatus.FAILED
    assert report.pages_listed == 0
    assert report.zero_progress_reason is not None


def test_a_skipped_page_next_to_a_completed_one_is_partial_success():
    ledger = KingstoneLedger([P1, P2])
    ledger.record_page_skipped(skipped(P1))
    completed_page(ledger, P2, resolved(CatalogResolution.EXISTING))
    report = build(ledger)
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.zero_progress_reason is None
    assert report.exit_code == EXIT_SUCCESS
    assert report.pages_skipped == (skipped(P1),)


def test_a_failed_book_is_partial_success():
    ledger = KingstoneLedger([P1])
    completed_page(ledger, P1, resolved(), failed())
    report = build(ledger)
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.failed == 1
    assert report.failed_items == (
        FailedItem(list_url=P1, source_url=DETAIL, external_id="9789570000001", reason="parse_error", message="layout changed", attempts=2),
    )


def test_an_interrupted_page_is_partial_success_when_another_page_completed():
    ledger = KingstoneLedger([P1, P2])
    completed_page(ledger, P1, resolved())
    ledger.page_started(P2)
    item(ledger, P2, resolved())
    ledger.stop_for_budget()
    report = build(ledger)
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.pages_completed == 1
    assert report.pages_interrupted == 1
    assert report.pages_not_reached == 0


def test_pages_not_reached_after_a_budget_stop_is_partial_success():
    ledger = KingstoneLedger([P1, P2, P3])
    completed_page(ledger, P1, resolved(CatalogResolution.EXISTING))
    ledger.stop_for_budget()
    report = build(ledger)
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.pages_not_reached == 2
    assert report.budget_exhausted is True
    assert report.zero_progress_reason is None


def test_all_existing_books_is_success():
    ledger = KingstoneLedger([P1, P2])
    completed_page(ledger, P1, resolved(CatalogResolution.EXISTING), resolved(CatalogResolution.EXISTING))
    completed_page(ledger, P2, resolved(CatalogResolution.EXISTING))
    report = build(ledger)
    assert report.status is RunStatus.SUCCESS
    assert report.exit_code == EXIT_SUCCESS
    assert report.existing_source == 3
    assert report.zero_card_pages == 0


def test_a_page_with_no_cards_is_success_and_counted_as_zero_card_page():
    ledger = KingstoneLedger([P1, P2])
    completed_page(ledger, P1)
    completed_page(ledger, P2, resolved())
    report = build(ledger)
    assert report.status is RunStatus.SUCCESS
    assert report.zero_card_pages == 1
    assert report.pages_completed == 2


def test_only_empty_pages_are_success_with_zero_progress_not_claimed():
    ledger = KingstoneLedger([P1])
    completed_page(ledger, P1)
    report = build(ledger)
    assert report.status is RunStatus.SUCCESS
    assert report.zero_progress_reason is None
    assert report.zero_card_pages == 1


# --- decide_status as one rule over plain counts ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"error": "x", "pages_completed": 1}, RunStatus.FAILED),
        ({"pages_listed": 2, "pages_skipped": 2}, RunStatus.FAILED),
        ({"pages_listed": 2, "pages_skipped": 1, "pages_not_reached": 1, "budget_exhausted": True}, RunStatus.FAILED),
        ({"pages_listed": 2, "pages_completed": 1, "pages_skipped": 1}, RunStatus.PARTIAL_SUCCESS),
        ({"pages_listed": 1, "pages_completed": 1, "failed_items": 1}, RunStatus.PARTIAL_SUCCESS),
        ({"pages_listed": 2, "pages_completed": 1, "pages_interrupted": 1}, RunStatus.PARTIAL_SUCCESS),
        ({"pages_listed": 2, "pages_completed": 1, "pages_not_reached": 1}, RunStatus.PARTIAL_SUCCESS),
        ({"pages_listed": 1, "pages_completed": 1}, RunStatus.SUCCESS),
    ],
)
def test_decide_status_table(kwargs, status):
    defaults = {
        "error": None,
        "pages_listed": 1,
        "pages_completed": 0,
        "pages_skipped": 0,
        "pages_interrupted": 0,
        "pages_not_reached": 0,
        "failed_items": 0,
        "budget_exhausted": False,
    }
    defaults.update(kwargs)
    result, reason = decide_status(**defaults)
    assert result is status
    if status is RunStatus.FAILED and kwargs.get("error") is None:
        assert reason is not None  # a zero-progress failure always says why
    else:
        assert reason is None


def test_decide_status_returns_no_reason_for_a_fatal_error():
    assert decide_status(
        error="boom",
        pages_listed=1,
        pages_completed=0,
        pages_skipped=0,
        pages_interrupted=0,
        pages_not_reached=0,
        failed_items=0,
        budget_exhausted=False,
    ) == (RunStatus.FAILED, None)


def test_exit_codes():
    ledger = KingstoneLedger([P1])
    assert build(ledger).exit_code == EXIT_FAILED
    completed_page(ledger, P1, failed())
    assert build(ledger).exit_code == EXIT_SUCCESS
    assert build(KingstoneLedger([P1]), error="x").exit_code == 1


# --- counters -------------------------------------------------------------------------------------------------------


def test_resolution_counters_and_warnings_are_counted_per_outcome():
    ledger = KingstoneLedger([P1, P2])
    completed_page(
        ledger,
        P1,
        resolved(CatalogResolution.EXISTING),
        resolved(CatalogResolution.IMPORTED),
        resolved(CatalogResolution.ISBN_ATTACHED, recovered=True, warning="identity drift"),
        resolved(CatalogResolution.AMBIGUOUS_CREATED),
        failed(warning="touch warning"),
    )
    completed_page(ledger, P2, resolved(CatalogResolution.EXISTING, recovered=True))
    report = build(ledger)
    assert report.items_seen == 6
    assert report.existing_source == 2
    assert report.imported == 1
    assert report.isbn_attached == 1
    assert report.ambiguous_created == 1
    assert report.failed == 1
    assert report.recovered_commit_count == 2
    assert report.identity_warning_count == 2
    assert report.pages_completed == 2
    assert report.zero_card_pages == 0


def test_skipped_pages_are_listed_in_order_and_not_counted_as_items():
    ledger = KingstoneLedger([P1, P2, P3])
    ledger.record_page_skipped(skipped(P1))
    ledger.record_page_skipped(skipped(P2, reason="parse_error", message="no product list", attempts=1))
    completed_page(ledger, P3, resolved())
    report = build(ledger)
    assert report.pages_skipped == (skipped(P1), skipped(P2, reason="parse_error", message="no product list", attempts=1))
    assert report.items_seen == 1
    assert report.pages_listed == 3


def test_pages_not_started_or_skipped_are_not_reached_when_the_run_ends_early():
    ledger = KingstoneLedger([P1, P2, P3])
    completed_page(ledger, P1, resolved())
    report = build(ledger)
    assert report.pages_not_reached == 2
    assert report.pages_interrupted == 0


def test_a_run_that_stops_inside_a_page_reports_that_page_as_interrupted():
    ledger = KingstoneLedger([P1, P2])
    ledger.page_started(P1)
    item(ledger, P1, resolved())
    report = build(ledger, error="crash")
    assert report.pages_interrupted == 1
    assert report.pages_not_reached == 1
    assert report.pages_completed == 0


# --- misuse is rejected ----------------------------------------------------------------------------------------------


def test_page_started_for_an_unlisted_url_is_rejected():
    with pytest.raises(ValueError):
        KingstoneLedger([P1]).page_started(P2)


def test_page_started_twice_is_rejected():
    ledger = KingstoneLedger([P1, P2])
    ledger.page_started(P1)
    with pytest.raises(ValueError):
        ledger.page_started(P1)


def test_a_second_page_cannot_start_while_one_is_open():
    ledger = KingstoneLedger([P1, P2])
    ledger.page_started(P1)
    with pytest.raises(ValueError):
        ledger.page_started(P2)


def test_items_must_belong_to_the_open_page():
    ledger = KingstoneLedger([P1, P2])
    with pytest.raises(ValueError):
        item(ledger, P1, resolved())
    ledger.page_started(P1)
    with pytest.raises(ValueError):
        item(ledger, P2, resolved())


def test_page_completed_without_an_open_page_is_rejected():
    with pytest.raises(ValueError):
        KingstoneLedger([P1]).page_completed(P1)


def test_skipping_a_started_or_unlisted_page_is_rejected():
    ledger = KingstoneLedger([P1, P2])
    ledger.page_started(P1)
    with pytest.raises(ValueError):
        ledger.record_page_skipped(skipped(P1))
    with pytest.raises(ValueError):
        ledger.record_page_skipped(skipped(P2 + "&x=1"))


def test_no_page_can_start_after_a_budget_stop():
    ledger = KingstoneLedger([P1, P2])
    ledger.stop_for_budget()
    with pytest.raises(ValueError):
        ledger.page_started(P1)


# --- logging --------------------------------------------------------------------------------------------------------


def test_skipped_pages_and_failed_books_are_logged_as_warnings_only(caplog):
    caplog.set_level(logging.INFO, logger="kingstone.ledger")
    ledger = KingstoneLedger([P1, P2])
    ledger.record_page_skipped(skipped(P1))
    completed_page(ledger, P2, resolved(CatalogResolution.EXISTING), failed())
    records = [record for record in caplog.records if record.name == "kingstone.ledger"]
    assert [record.levelno for record in records] == [logging.WARNING, logging.WARNING]
    assert P1 in records[0].getMessage()
    assert "layout changed" in records[1].getMessage()


def test_existing_and_imported_books_are_not_logged(caplog):
    caplog.set_level(logging.INFO, logger="kingstone.ledger")
    ledger = KingstoneLedger([P1])
    completed_page(ledger, P1, resolved(CatalogResolution.EXISTING), resolved(CatalogResolution.IMPORTED))
    assert [record for record in caplog.records if record.name == "kingstone.ledger"] == []


# --- format_report --------------------------------------------------------------------------------------------------

FIELD_ORDER = [
    "run_id",
    "provider_code",
    "started_at",
    "finished_at",
    "status",
    "pages_listed",
    "pages_completed",
    "pages_skipped",
    "pages_interrupted",
    "pages_not_reached",
    "zero_card_pages",
    "budget_exhausted",
    "items_seen",
    "existing_source",
    "imported",
    "isbn_attached",
    "ambiguous_created",
    "failed",
    "recovered_commit_count",
    "identity_warning_count",
    "zero_progress_reason",
    "error",
    "exit_code",
    "skipped_pages",
    "failed_items",
]


def parse_line(line):
    """Split the one-line report into (key, raw value) pairs. Lists and free texts are JSON and may hold spaces."""
    pairs = []
    rest = line
    while rest:
        key, _, rest = rest.partition("=")
        if rest[:1] in ("[", '"'):
            _, end = json.JSONDecoder().raw_decode(rest)
            value, rest = rest[:end], rest[end:].lstrip()
        else:
            value, _, rest = rest.partition(" ")
        pairs.append((key, value))
    return pairs


def test_format_report_fields_in_fixed_order_and_one_line():
    ledger = KingstoneLedger([P1, P2])
    ledger.record_page_skipped(skipped(P1, message="HTTP 503 at 停機"))
    completed_page(ledger, P2, resolved(CatalogResolution.IMPORTED), failed(message="layout changed"))
    line = format_report(build(ledger))
    assert "\n" not in line
    assert [key for key, _ in parse_line(line)] == FIELD_ORDER
    assert line.startswith("run_id=run-1 provider_code=KINGSTONE started_at=2026-10-25T01:00:00+00:00 ")


def test_format_report_lists_are_json_without_ascii_escapes():
    ledger = KingstoneLedger([P1, P2])
    ledger.record_page_skipped(skipped(P1, message="HTTP 503 停機"))
    completed_page(ledger, P2, resolved(), failed(message="版面改變"))
    line = format_report(build(ledger))
    values = dict(parse_line(line))
    assert json.loads(values["skipped_pages"]) == [{"url": P1, "reason": "fetch_error", "message": "HTTP 503 停機", "attempts": 3}]
    assert json.loads(values["failed_items"]) == [
        {"list_url": P2, "source_url": DETAIL, "external_id": "9789570000001", "reason": "parse_error", "message": "版面改變", "attempts": 2}
    ]
    assert "停機" in line
    assert "\\u" not in line


def test_format_report_counts_and_flags():
    ledger = KingstoneLedger([P1, P2])
    completed_page(ledger, P1)
    ledger.stop_for_budget()
    values = dict(parse_line(format_report(build(ledger))))
    assert values["status"] == "PARTIAL_SUCCESS"  # the second page was not reached
    assert values["exit_code"] == "0"
    assert values["pages_listed"] == "2"
    assert values["pages_completed"] == "1"
    assert values["pages_not_reached"] == "1"
    assert values["zero_card_pages"] == "1"
    assert values["budget_exhausted"] == "true"
    assert values["zero_progress_reason"] == "null"
    assert values["error"] == "null"
    assert values["skipped_pages"] == "[]"


def test_format_report_quotes_free_text_and_shows_failed_status():
    ledger = KingstoneLedger([P1])
    report = build(ledger, error="cannot write, retry later")
    values = dict(parse_line(format_report(report)))
    assert values["status"] == "FAILED"
    assert values["exit_code"] == "1"
    assert json.loads(values["error"]) == "cannot write, retry later"
    assert values["zero_progress_reason"] == "null"  # a fatal error carries no zero-progress reason


def test_report_is_a_frozen_value_with_its_exit_code():
    report = build(KingstoneLedger([P1]))
    assert isinstance(report, KingstoneReport)
    assert report.provider_code is ProviderCode.KINGSTONE
    with pytest.raises(AttributeError):
        report.status = RunStatus.SUCCESS  # type: ignore[misc]
