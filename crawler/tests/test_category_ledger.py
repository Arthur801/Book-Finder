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
