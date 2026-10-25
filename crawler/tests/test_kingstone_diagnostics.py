"""Kingstone diagnostic HTML files (kingstone.diagnostics), offline: a temporary folder and a fixed clock."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from kingstone.diagnostics import DIAGNOSTIC_RETAIN, DiagnosticWriter

MOMENT = datetime(2026, 10, 25, 3, 4, 5, 678901, tzinfo=UTC)


def fixed_clock(moment=MOMENT):
    return lambda: moment


def stepping_clock(start=MOMENT, step=timedelta(seconds=1)):
    state = {"now": start}

    def clock():
        current = state["now"]
        state["now"] = current + step
        return current

    return clock


def test_the_file_name_is_the_utc_time_kind_and_code(tmp_path):
    writer = DiagnosticWriter(tmp_path, max_bytes=1000, clock=fixed_clock())

    path = writer.save_html(kind="detail", code="2018630959191", html="<html>x</html>")

    assert path is not None
    assert path.name == "20261025T030405678901Z-detail-2018630959191.html"
    assert path.read_text(encoding="utf-8") == "<html>x</html>"


def test_the_list_file_name_uses_the_category_code(tmp_path):
    writer = DiagnosticWriter(tmp_path, max_bytes=1000, clock=fixed_clock())

    path = writer.save_html(kind="list", code="jdc", html="<html></html>")

    assert path is not None and path.name.endswith("-list-jdc.html")


def test_an_unsafe_code_is_reduced_to_letters_and_digits(tmp_path):
    writer = DiagnosticWriter(tmp_path, max_bytes=1000, clock=fixed_clock())

    path = writer.save_html(kind="list", code="../../x", html="<html></html>")

    assert path is not None and path.parent == tmp_path and path.name.endswith("-list-x.html")


def test_a_body_within_the_cap_is_saved_unchanged(tmp_path):
    body = "<html>" + "中" * 100 + "</html>"
    writer = DiagnosticWriter(tmp_path, max_bytes=len(body.encode("utf-8")), clock=fixed_clock())

    path = writer.save_html(kind="list", code="jdc", html=body)

    assert path is not None and path.read_bytes() == body.encode("utf-8")


def test_a_longer_body_is_cut_to_the_cap_with_a_note_and_stays_valid_utf8(tmp_path):
    body = "<html>" + "中" * 2000 + "</html>"  # 6000+ bytes of three-byte characters
    cap = 1000
    writer = DiagnosticWriter(tmp_path, max_bytes=cap, clock=fixed_clock())

    path = writer.save_html(kind="detail", code="2018630959191", html=body)

    assert path is not None
    data = path.read_bytes()
    assert len(data) <= cap
    text = data.decode("utf-8")  # must not end inside a character
    assert text.startswith("<html>中")
    assert text.rstrip().endswith("-->")
    assert "truncated at 1000 bytes" in text
    assert str(len(body.encode("utf-8"))) in text


def test_a_cap_smaller_than_the_note_keeps_only_whole_characters(tmp_path):
    writer = DiagnosticWriter(tmp_path, max_bytes=5, clock=fixed_clock())

    path = writer.save_html(kind="list", code="jdc", html="中中中中")

    assert path is not None
    data = path.read_bytes()
    assert len(data) <= 5
    assert data.decode("utf-8") == "中"


def test_only_the_newest_twenty_files_are_kept(tmp_path):
    writer = DiagnosticWriter(tmp_path, max_bytes=1000, clock=stepping_clock())

    paths = [writer.save_html(kind="list", code="jdc", html=f"<p>{n}</p>") for n in range(DIAGNOSTIC_RETAIN + 5)]

    remaining = sorted(p.name for p in tmp_path.glob("*.html"))
    assert len(remaining) == DIAGNOSTIC_RETAIN
    assert [p.name for p in paths[-DIAGNOSTIC_RETAIN:]] == remaining
    assert not paths[0].exists()  # the oldest is gone


def test_saves_in_the_same_microsecond_get_distinct_names_in_time_order(tmp_path):
    writer = DiagnosticWriter(tmp_path, max_bytes=1000, clock=fixed_clock())

    paths = [writer.save_html(kind="list", code="jdc", html=f"<p>{n}</p>") for n in range(3)]

    assert len({p.name for p in paths}) == 3
    assert [p.read_text(encoding="utf-8") for p in paths] == ["<p>0</p>", "<p>1</p>", "<p>2</p>"]
    assert sorted(p.name for p in paths) == [p.name for p in paths]


def test_a_write_failure_is_logged_and_returns_none(tmp_path, caplog):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    writer = DiagnosticWriter(blocker, max_bytes=1000, clock=fixed_clock())

    with caplog.at_level(logging.WARNING, logger="kingstone.diagnostics"):
        assert writer.save_html(kind="list", code="jdc", html="<html></html>") is None

    assert any("could not save the list diagnostic" in record.getMessage() for record in caplog.records)


def test_the_cap_must_be_positive(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        DiagnosticWriter(tmp_path, max_bytes=0)
