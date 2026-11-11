"""The provider-neutral run report and ledger (catalog_core.category_ledger): the provider rule and the Kingstone binding.

Offline: no database, no fetcher.
"""

from __future__ import annotations

import logging
from dataclasses import fields
from datetime import UTC, datetime

import pytest

from catalog_core.category_ledger import CategoryLedger, CategoryReport, RunStatus, SkippedPage, format_report
from catalog_core.models import ProviderCode, WritePolicy
from kingstone.ledger import KingstoneLedger, KingstoneReport

START = datetime(2026, 11, 1, 1, 0, tzinfo=UTC)
END = datetime(2026, 11, 1, 1, 5, tzinfo=UTC)
P1 = "https://fake.test/list/1"


def report_kwargs() -> dict:
    """Every required CategoryReport field (no provider): a successful, empty run."""
    return {
        "run_id": "r-1",
        "status": RunStatus.SUCCESS,
        "started_at": START,
        "finished_at": END,
        "pages_listed": 0,
        "pages_completed": 0,
        "pages_skipped": (),
        "pages_interrupted": 0,
        "pages_not_reached": 0,
        "zero_card_pages": 0,
        "budget_exhausted": False,
        "items_seen": 0,
        "existing_source": 0,
        "imported": 0,
        "isbn_attached": 0,
        "ambiguous_created": 0,
        "policy_skipped_count": 0,
        "failed": 0,
        "recovered_commit_count": 0,
        "identity_warning_count": 0,
        "failed_items": (),
        "write_policy": WritePolicy.NORMAL,
    }


def test_a_base_report_cannot_be_built_without_a_provider():
    with pytest.raises(ValueError, match="needs a provider_code"):
        CategoryReport(**report_kwargs())


def test_a_base_report_carries_the_provider_it_is_given():
    report = CategoryReport(**report_kwargs(), provider_code=ProviderCode.ESLITE)

    assert report.provider_code is ProviderCode.ESLITE
    assert format_report(report).startswith("run_id=r-1 provider_code=ESLITE write_policy=normal ")


def test_the_ledger_builds_its_report_with_the_provider_and_logs_to_its_logger(caplog):
    caplog.set_level(logging.WARNING)
    ledger = CategoryLedger((P1,), WritePolicy.NORMAL, provider_code=ProviderCode.ESLITE, logger=logging.getLogger("fake.ledger"))
    ledger.record_page_skipped(SkippedPage(url=P1, reason="empty_category", message="none", attempts=1))

    report = ledger.report(run_id="r-2", started_at=START, finished_at=END)

    assert report.provider_code is ProviderCode.ESLITE
    assert type(report) is CategoryReport
    assert report.status is RunStatus.FAILED
    assert [(record.name, record.levelname) for record in caplog.records] == [("fake.ledger", "WARNING")]


def test_kingstone_report_keeps_the_field_order_and_defaults_to_kingstone():
    base_names = [field.name for field in fields(CategoryReport)]
    kingstone_names = [field.name for field in fields(KingstoneReport)]

    assert kingstone_names == base_names
    assert KingstoneReport(**report_kwargs()).provider_code is ProviderCode.KINGSTONE
    assert isinstance(KingstoneReport(**report_kwargs()), CategoryReport)


def test_the_kingstone_ledger_builds_kingstone_reports():
    report = KingstoneLedger((P1,), WritePolicy.NORMAL).report(run_id="r-3", started_at=START, finished_at=END)

    assert isinstance(report, KingstoneReport)
    assert report.provider_code is ProviderCode.KINGSTONE


# ---------------------------------------------------------------------------
# Excluded cards (a provider rule): counted in items_excluded, never a failure, never a zero-card page
# ---------------------------------------------------------------------------


def _ledger(*urls: str) -> CategoryLedger:
    return CategoryLedger(urls or (P1,), WritePolicy.NORMAL, provider_code=ProviderCode.ESLITE, logger=logging.getLogger("fake.ledger"))


def test_report_counts_items_excluded_from_page_started_and_record_excluded():
    ledger = _ledger()
    ledger.page_started(P1, items_listed=1, items_excluded=1)  # one card dropped at the list stage
    ledger.record_excluded(P1, source_url="https://fake.test/item/R1", external_id="R1")  # one at the detail stage
    ledger.page_completed(P1)

    report = ledger.report(run_id="r", started_at=START, finished_at=END)

    assert report.items_excluded == 2
    assert report.items_seen == 0
    assert report.failed == 0
    assert report.failed_items == ()
    assert report.parse_error_200_count == 0
    assert report.status is RunStatus.SUCCESS


def test_a_page_whose_every_card_is_excluded_is_completed_and_not_a_zero_card_page():
    ledger = _ledger()
    ledger.page_started(P1, items_listed=0, items_excluded=3)
    ledger.page_completed(P1)

    report = ledger.report(run_id="r", started_at=START, finished_at=END)

    assert report.pages_completed == 1
    assert report.zero_card_pages == 0
    assert report.items_excluded == 3
    assert report.status is RunStatus.SUCCESS


def test_a_page_with_no_cards_and_no_exclusions_is_still_a_zero_card_page():
    ledger = _ledger()
    ledger.page_started(P1, items_listed=0, items_excluded=0)
    ledger.page_completed(P1)

    report = ledger.report(run_id="r", started_at=START, finished_at=END)

    assert report.zero_card_pages == 1
    assert report.items_excluded == 0


def test_a_detail_level_exclusion_counts_once_and_the_page_is_not_a_zero_card_page():
    ledger = _ledger()
    ledger.page_started(P1, items_listed=1)
    ledger.record_excluded(P1, source_url="https://fake.test/item/R1", external_id="R1")
    ledger.page_completed(P1)

    report = ledger.report(run_id="r", started_at=START, finished_at=END)

    assert report.items_excluded == 1
    assert report.zero_card_pages == 0


def test_record_excluded_needs_the_open_page():
    ledger = _ledger()
    with pytest.raises(ValueError, match="open page"):
        ledger.record_excluded(P1, source_url="https://fake.test/item/R1", external_id="R1")

    ledger.page_started(P1)
    with pytest.raises(ValueError, match="open page"):
        ledger.record_excluded("https://fake.test/list/other", source_url="https://fake.test/item/R1", external_id="R1")


def test_record_excluded_logs_one_info_line_with_the_source_url(caplog):
    caplog.set_level(logging.INFO, logger="fake.ledger")
    ledger = _ledger()
    ledger.page_started(P1)
    ledger.record_excluded(P1, source_url="https://fake.test/item/R1", external_id="R1")

    lines = [record for record in caplog.records if record.name == "fake.ledger" and record.levelno == logging.INFO]
    assert len(lines) == 1
    assert "https://fake.test/item/R1" in lines[0].getMessage()
    assert [record for record in caplog.records if record.levelno >= logging.WARNING] == []


def test_the_kingstone_report_defaults_items_excluded_to_zero():
    report = KingstoneReport(**report_kwargs())

    assert report.items_excluded == 0
