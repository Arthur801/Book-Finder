"""Provider-neutral diagnostic files (catalog_core.run_diagnostics), offline: a temporary folder and a fixed clock.

The folder is ``eslite/diagnostics`` and the logger ``fake.diagnostics``: no Kingstone name is involved.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from catalog_core.run_diagnostics import DIAGNOSTIC_RETAIN, DiagnosticWriter

MOMENT = datetime(2026, 11, 1, 3, 4, 5, 6, tzinfo=UTC)


def writer(folder, *, max_bytes: int = 1000, retain: int = DIAGNOSTIC_RETAIN, clock=None) -> DiagnosticWriter:
    return DiagnosticWriter(folder, max_bytes=max_bytes, logger_name="fake.diagnostics", clock=clock or (lambda: MOMENT), retain=retain)


def test_the_file_is_named_by_utc_time_kind_and_code_under_the_given_folder(tmp_path):
    folder = tmp_path / "eslite" / "diagnostics"
    path = writer(folder).save_html(kind="list", code="cat-1", html="<html>x</html>")

    assert path == folder / "20261101T030405000006Z-list-cat1.html"
    assert path.read_text(encoding="utf-8") == "<html>x</html>"


def test_an_unsafe_code_is_reduced_to_letters_and_digits(tmp_path):
    path = writer(tmp_path).save_html(kind="detail", code="../../", html="x")

    assert path is not None and path.name.endswith("-detail-unknown.html")


def test_a_body_over_the_cap_is_cut_and_marked_within_the_limit(tmp_path):
    body = "甲" * 400  # 1200 bytes in UTF-8
    path = writer(tmp_path, max_bytes=300).save_html(kind="list", code="c", html=body)

    assert path is not None
    data = path.read_bytes()
    assert len(data) <= 300
    assert b"diagnostic truncated at 300 bytes" in data
    data.decode("utf-8")  # still valid UTF-8


def test_only_the_newest_files_are_kept(tmp_path):
    ticks = [MOMENT + timedelta(seconds=n) for n in range(5)]
    clock = iter(ticks).__next__
    saver = writer(tmp_path, retain=2, clock=clock)
    for _ in range(5):
        saver.save_html(kind="list", code="c", html="x")

    names = sorted(path.name for path in tmp_path.glob("*.html"))
    assert names == [
        "20261101T030408000006Z-list-c.html",
        "20261101T030409000006Z-list-c.html",
    ]


def test_a_write_failure_is_logged_on_the_given_logger_and_returns_none(tmp_path, caplog):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="fake.diagnostics"):
        assert writer(blocker).save_html(kind="list", code="c", html="x") is None

    assert any(record.name == "fake.diagnostics" and "could not save the list diagnostic for c" in record.getMessage() for record in caplog.records)


def test_a_cap_below_one_byte_is_refused(tmp_path):
    with pytest.raises(ValueError, match="max_bytes must be at least 1"):
        writer(tmp_path, max_bytes=0)
