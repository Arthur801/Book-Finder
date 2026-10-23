import logging
from datetime import date

import pytest

from books_crawler.models import Identifier
from books_crawler.normalize import (
    map_contributor_role,
    map_language,
    normalize_isbn,
    parse_published_date,
)

# ISBN normalization and checksum (data-model §5.3)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0306406152", Identifier("ISBN_10", "0306406152")),
        ("0-306-40615-2", Identifier("ISBN_10", "0306406152")),
        ("080442957X", Identifier("ISBN_10", "080442957X")),
        ("080442957x", Identifier("ISBN_10", "080442957X")),
        ("9780306406157", Identifier("ISBN_13", "9780306406157")),
        ("978-0-306-40615-7", Identifier("ISBN_13", "9780306406157")),
        (" 978 0 306 40615 7 ", Identifier("ISBN_13", "9780306406157")),
        ("979-10-90636-07-1", Identifier("ISBN_13", "9791090636071")),
    ],
)
def test_normalize_isbn_accepts_valid_values(raw, expected):
    assert normalize_isbn(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "abc",
        "0306406153",  # ISBN-10 wrong checksum
        "9780306406158",  # ISBN-13 wrong checksum
        "978030640615",  # 12 digits
        "08044X957X",  # X only allowed as the last character
        "9770306406158",  # valid checksum but not a 978/979 ISBN-13 prefix
        "97803064061570",  # 14 digits
    ],
)
def test_normalize_isbn_rejects_invalid_values(raw):
    assert normalize_isbn(raw) is None


# Language mapping (data-model §2.1)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("繁體中文", "zh-TW"),
        ("簡體中文", "zh-CN"),
        ("英文", "en"),
        ("日文", "ja"),
        ("韓文", "ko"),
        ("  繁體中文  ", "zh-TW"),
        ("德文", None),
        ("", None),
        (None, None),
    ],
)
def test_map_language(raw, expected):
    assert map_language(raw) == expected


def test_unmapped_language_label_is_logged_and_stored_as_null(caplog):
    caplog.set_level(logging.WARNING, logger="books_crawler.normalize")

    assert map_language("德文") is None

    assert "unmapped language label '德文'" in caplog.text


# Contributor role mapping (crawler.md §8)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("作者", "AUTHOR"),
        ("作者：", "AUTHOR"),
        ("原文作者", "ORIGINAL_AUTHOR"),
        ("譯者", "TRANSLATOR"),
        (" 譯者 : ", "TRANSLATOR"),
        ("編者", "EDITOR"),
        ("繪者", "ILLUSTRATOR"),
        ("策劃", "OTHER"),
        ("", "OTHER"),
    ],
)
def test_map_contributor_role(raw, expected):
    assert map_contributor_role(raw) == expected


# Published date precision (data-model §5.1; assumption: formats documented in normalize.py)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026/10/11", (date(2026, 10, 11), "DAY")),
        ("2026-3-5", (date(2026, 3, 5), "DAY")),
        ("2026/10", (date(2026, 10, 1), "MONTH")),
        ("2026", (date(2026, 1, 1), "YEAR")),
        ("2024/02/29", (date(2024, 2, 29), "DAY")),
    ],
)
def test_parse_published_date_keeps_precision(raw, expected):
    assert parse_published_date(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [None, "", "約2026年", "2026/13", "2026/02/30", "2026/10/11 (日)", "10/11/2026"],
)
def test_parse_published_date_never_guesses(raw):
    assert parse_published_date(raw) == (None, None)
