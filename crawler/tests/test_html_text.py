"""Behaviour of the shared ``catalog_core.html_text.text_with_line_breaks`` helper."""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from catalog_core.html_text import text_with_line_breaks


def _node(fragment: str):
    soup = BeautifulSoup(f'<div class="section">{fragment}</div>', "html.parser")
    return soup.select_one(".section")


@pytest.mark.parametrize(
    ("fragment", "expected"),
    [
        ("甲<br>乙", "甲\n乙"),
        ("甲<br/><br/>乙", "甲\n\n乙"),
        # Block boundaries add a line break on each side, so two adjacent blocks are separated by a blank line.
        ("<div>第一</div><div>第二</div>", "第一\n\n第二"),
        ("<p>甲</p><p>乙</p>", "甲\n\n乙"),
        ("<ul><li>一</li><li>二</li></ul>", "一\n\n二"),
        ("<h3>標題</h3>內文", "標題\n內文"),
    ],
)
def test_breaks_come_from_br_and_block_boundaries(fragment, expected):
    assert text_with_line_breaks(_node(fragment)) == expected


@pytest.mark.parametrize(
    "fragment",
    [
        "<strong>2026</strong><strong>國際布克獎得主</strong>",
        "甲<a href='#'>乙</a>丙",
        "<span>甲</span><em>乙</em>",
    ],
)
def test_inline_elements_never_split_a_line(fragment):
    assert "\n" not in (text_with_line_breaks(_node(fragment)) or "")


def test_inline_elements_keep_their_text_joined():
    assert text_with_line_breaks(_node("<strong>2026</strong><strong>國際布克獎得主</strong>")) == "2026國際布克獎得主"


def test_runs_of_blank_lines_collapse_to_one_blank_line():
    assert text_with_line_breaks(_node("<p>甲</p><p></p><p></p><p>乙</p>")) == "甲\n\n乙"
    assert text_with_line_breaks(_node("甲<br><br><br><br>乙")) == "甲\n\n乙"


def test_leading_and_trailing_blank_lines_are_removed():
    assert text_with_line_breaks(_node("<br>甲<br><br>")) == "甲"


def test_internal_whitespace_collapses_and_line_edges_are_stripped():
    assert text_with_line_breaks(_node("   甲     乙   ")) == "甲 乙"


def test_source_file_newlines_are_not_line_breaks():
    assert text_with_line_breaks(_node("甲\r\n    乙")) == "甲 乙"


def test_whitespace_only_section_returns_none():
    assert text_with_line_breaks(_node("<div>   </div><br>")) is None
