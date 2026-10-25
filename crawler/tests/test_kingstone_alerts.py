"""Kingstone alert reasons (kingstone.alerts), offline: pure functions, no files, no logging."""

from __future__ import annotations

import pytest

from kingstone.alerts import BUSY_REASON, SCHEMA_REASON, STREAK_LENGTH, alert_reasons, pages_not_reached_streak

NO_ALERT = {"status": "SUCCESS", "reason": None, "pages_completed": 2, "zero_card_pages": 0, "streak_reached": False}


def test_an_all_existing_successful_run_alerts_nothing():
    assert alert_reasons(**NO_ALERT) == []


def test_a_partial_success_alerts_nothing_by_itself():
    assert alert_reasons(**{**NO_ALERT, "status": "PARTIAL_SUCCESS"}) == []


def test_failed_status_alerts_failed():
    assert alert_reasons(**{**NO_ALERT, "status": "FAILED"}) == ["failed"]


def test_schema_prerequisite_missing_alerts_schema_and_failed():
    reasons = alert_reasons(**{**NO_ALERT, "status": "FAILED", "reason": SCHEMA_REASON, "pages_completed": 0})
    assert reasons == ["failed", "schema_prerequisite_missing"]


def test_maintenance_busy_alerts_busy_and_failed():
    reasons = alert_reasons(**{**NO_ALERT, "status": "FAILED", "reason": BUSY_REASON, "pages_completed": 0})
    assert reasons == ["failed", "maintenance_busy"]


def test_a_reason_other_than_schema_or_busy_does_not_alert_those_two():
    assert alert_reasons(**{**NO_ALERT, "reason": "SOMETHING_ELSE"}) == []


@pytest.mark.parametrize("completed, zero_cards, expected", [(1, 1, True), (3, 3, True), (3, 2, False), (0, 0, False)])
def test_zero_card_pages_alerts_only_when_every_completed_page_had_no_card(completed, zero_cards, expected):
    reasons = alert_reasons(**{**NO_ALERT, "pages_completed": completed, "zero_card_pages": zero_cards})
    assert ("zero_card_pages" in reasons) is expected


def test_the_streak_flag_alerts_pages_not_reached_streak():
    assert alert_reasons(**{**NO_ALERT, "streak_reached": True}) == ["pages_not_reached_streak"]


def test_reasons_come_in_a_fixed_order():
    reasons = alert_reasons(status="FAILED", reason=SCHEMA_REASON, pages_completed=1, zero_card_pages=1, streak_reached=True)
    assert reasons == ["failed", "schema_prerequisite_missing", "zero_card_pages", "pages_not_reached_streak"]


def test_the_streak_needs_three_entries_all_above_zero():
    history = [{"pages_not_reached": 4}, {"pages_not_reached": 7}]
    assert pages_not_reached_streak(3, history) is True
    assert pages_not_reached_streak(3, history[:1]) is False  # the 2nd run: only two entries in the window
    assert pages_not_reached_streak(3, []) is False
    assert STREAK_LENGTH == 3


def test_the_first_and_second_runs_above_zero_do_not_alert():
    assert pages_not_reached_streak(5, []) is False
    assert pages_not_reached_streak(5, [{"pages_not_reached": 5}]) is False


def test_a_later_run_above_zero_keeps_alerting():
    history = [{"pages_not_reached": 1}, {"pages_not_reached": 1}, {"pages_not_reached": 1}]
    assert pages_not_reached_streak(1, history) is True


def test_a_zero_in_the_window_resets_the_streak():
    assert pages_not_reached_streak(2, [{"pages_not_reached": 0}, {"pages_not_reached": 2}]) is False
    assert pages_not_reached_streak(2, [{"pages_not_reached": 2}, {"pages_not_reached": 0}]) is False


def test_the_current_run_at_zero_resets_the_streak():
    assert pages_not_reached_streak(0, [{"pages_not_reached": 3}, {"pages_not_reached": 3}]) is False


def test_an_unknown_count_is_not_part_of_the_streak():
    assert pages_not_reached_streak(None, [{"pages_not_reached": 3}, {"pages_not_reached": 3}]) is False
    assert pages_not_reached_streak(3, [{"pages_not_reached": None}, {"pages_not_reached": 3}]) is False


def test_a_parse_error_200_alerts_unclassified_200_even_when_partial():
    reasons = alert_reasons(**{**NO_ALERT, "status": "PARTIAL_SUCCESS", "parse_error_200_count": 1})
    assert reasons == ["unclassified_200"]


def test_no_parse_error_200_alerts_nothing_extra():
    assert alert_reasons(**{**NO_ALERT, "parse_error_200_count": 0}) == []


def test_unclassified_200_comes_before_zero_card_pages_in_the_fixed_order():
    reasons = alert_reasons(
        status="FAILED",
        reason=None,
        pages_completed=1,
        zero_card_pages=1,
        streak_reached=True,
        parse_error_200_count=2,
    )
    assert reasons == ["failed", "unclassified_200", "zero_card_pages", "pages_not_reached_streak"]
