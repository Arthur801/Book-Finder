"""Eslite run artifacts (eslite.artifacts): the restricted_skipped key of the terminal record. Offline."""

from __future__ import annotations

from datetime import UTC, datetime

from catalog_core.category_ledger import CategoryReport, RunStatus
from catalog_core.models import ProviderCode, WritePolicy
from eslite.artifacts import record_from_report, record_pre_run

START = datetime(2026, 11, 1, 1, 0, tzinfo=UTC)
END = datetime(2026, 11, 1, 1, 5, tzinfo=UTC)


def _report(**overrides) -> CategoryReport:
    values = {
        "run_id": "r-1",
        "status": RunStatus.SUCCESS,
        "started_at": START,
        "finished_at": END,
        "pages_listed": 1,
        "pages_completed": 1,
        "pages_skipped": (),
        "pages_interrupted": 0,
        "pages_not_reached": 0,
        "zero_card_pages": 0,
        "budget_exhausted": False,
        "items_seen": 1,
        "existing_source": 0,
        "imported": 1,
        "isbn_attached": 0,
        "ambiguous_created": 0,
        "policy_skipped_count": 0,
        "failed": 0,
        "recovered_commit_count": 0,
        "identity_warning_count": 0,
        "failed_items": (),
        "write_policy": WritePolicy.NORMAL,
        "provider_code": ProviderCode.ESLITE,
    }
    values.update(overrides)
    return CategoryReport(**values)


def test_the_run_record_carries_restricted_skipped_right_after_policy_skipped():
    record = record_from_report(_report(items_excluded=3))

    keys = list(record)
    assert record["restricted_skipped"] == 3
    assert keys.index("restricted_skipped") == keys.index("policy_skipped") + 1


def test_the_pre_run_record_carries_restricted_skipped_zero_right_after_policy_skipped():
    record = record_pre_run(run_id="r-0", status="FAILED", exit_code=1, reason="x", write_policy="normal", started_at=START, finished_at=END)

    keys = list(record)
    assert record["restricted_skipped"] == 0
    assert keys.index("restricted_skipped") == keys.index("policy_skipped") + 1
