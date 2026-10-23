"""Category page list file for pages mode (crawler.md §16, pages mode). No network, no database."""

import logging
from pathlib import Path

import pytest

from books_crawler import page_list
from books_crawler.page_list import PageListError, load_page_urls

CATEGORY_1 = "https://www.books.com.tw/web/sys_saletopb/books/01/?attribute=7&loc=P_0002_002"
CATEGORY_2 = "https://www.books.com.tw/web/sys_saletopb/books/02/?attribute=7&loc=P_0002_003"
CATEGORY_3 = "https://www.books.com.tw/web/sys_saletopb/books/03/?attribute=7&loc=P_0002_004"


def write_list(tmp_path, text: str):
    path = tmp_path / "category-pages.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_comments_blank_lines_and_surrounding_whitespace_are_ignored_and_order_is_kept(tmp_path):
    path = write_list(
        tmp_path,
        f"# header comment\n\n   {CATEGORY_2}  \n# another comment\n\t{CATEGORY_1}\n   \n{CATEGORY_3}\n",
    )

    assert load_page_urls(path) == [CATEGORY_2, CATEGORY_1, CATEGORY_3]


def test_a_line_that_is_not_a_category_ranking_url_is_an_error_naming_the_file_and_line(tmp_path):
    path = write_list(tmp_path, f"# comment\n{CATEGORY_1}\nhttps://example.com/not-books\n{CATEGORY_2}\n")

    with pytest.raises(PageListError, match=rf"{path!s}.*line 3"):
        load_page_urls(path)


def test_a_file_without_any_url_is_an_error_naming_the_file(tmp_path):
    path = write_list(tmp_path, "# only comments\n\n   \n")

    with pytest.raises(PageListError, match=rf"{path!s}: no category page URLs"):
        load_page_urls(path)


def test_a_missing_file_is_an_error_naming_the_file(tmp_path):
    path = tmp_path / "no-such-list.txt"

    with pytest.raises(PageListError, match=rf"cannot read category pages file {path!s}"):
        load_page_urls(path)


def test_without_the_env_var_the_default_file_is_crawler_category_pages_txt_next_to_the_package(monkeypatch):
    import books_crawler

    package_parent = Path(books_crawler.__file__).resolve().parent.parent

    assert page_list.resolve_pages_file("") == package_parent / "category-pages.txt"
    assert page_list.resolve_pages_file("   ") == package_parent / "category-pages.txt"


def test_the_env_var_overrides_the_default_file_path(tmp_path):
    override = tmp_path / "other-list.txt"

    assert page_list.resolve_pages_file(f"  {override}  ") == override


def test_the_shipped_default_list_is_the_21_category_pages_that_were_hard_coded_before_in_their_order():
    expected = [
        f"https://www.books.com.tw/web/sys_saletopb/books/{category}/?attribute=7&loc=P_0002_{loc:03d}"
        for category, loc in [
            ("01", 2),
            ("02", 3),
            ("03", 4),
            ("04", 5),
            ("07", 6),
            ("12", 7),
            ("06", 8),
            ("08", 9),
            ("09", 10),
            ("10", 11),
            ("11", 12),
            ("14", 13),
            ("24", 14),
            ("13", 15),
            ("22", 16),
            ("15", 17),
            ("16", 18),
            ("17", 19),
            ("18", 20),
            ("19", 21),
            ("20", 22),
        ]
    ]

    assert load_page_urls(page_list.DEFAULT_PAGES_FILE) == expected


def test_duplicate_urls_are_kept_once_in_first_seen_order_and_each_dropped_one_is_logged(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="books_crawler")
    path = write_list(tmp_path, f"{CATEGORY_2}\n{CATEGORY_1}\n{CATEGORY_2}\n{CATEGORY_1}\n{CATEGORY_3}\n")

    assert load_page_urls(path) == [CATEGORY_2, CATEGORY_1, CATEGORY_3]
    dropped = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(dropped) == 2
    assert all(CATEGORY_2 in m or CATEGORY_1 in m for m in dropped)
