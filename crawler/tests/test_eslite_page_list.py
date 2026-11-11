"""Eslite category list page file (eslite.page_list). Offline: temp files and the default file path only."""

import logging

import pytest

from eslite import page_list
from eslite.page_list import MAX_PAGES, PAGES_FILE_ENV, PageListError, load_page_urls, resolve_pages_file

BASE = "https://www.eslite.com/category/3/"


def write_list(tmp_path, data: bytes, name="eslite-pages.txt"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_the_env_var_name_and_the_default_file_are_the_eslite_ones():
    assert PAGES_FILE_ENV == "ESLITE_PAGES_FILE"
    assert page_list.DEFAULT_PAGES_FILE.name == "eslite-pages.txt"
    assert page_list.DEFAULT_PAGES_FILE.parent.name == "crawler"
    assert MAX_PAGES == 400


def test_resolve_pages_file_uses_the_default_for_a_blank_value_and_the_override_otherwise(tmp_path):
    override = tmp_path / "other.txt"

    assert resolve_pages_file("") == page_list.DEFAULT_PAGES_FILE
    assert resolve_pages_file("   ") == page_list.DEFAULT_PAGES_FILE
    assert resolve_pages_file(f"  {override}  ") == override


def test_a_utf8_bom_is_allowed(tmp_path):
    path = write_list(tmp_path, "﻿".encode() + f"{BASE}101\n".encode())

    assert load_page_urls(path) == [f"{BASE}101"]


def test_comments_blank_lines_and_surrounding_whitespace_are_ignored_and_order_is_kept(tmp_path):
    text = f"# comment\n\n   {BASE}101?page=2  \n# another\n\t{BASE}34\n   \n"
    path = write_list(tmp_path, text.encode())

    assert load_page_urls(path) == [f"{BASE}101?page=2", f"{BASE}34"]


def test_a_page_one_twin_is_a_duplicate_and_the_first_seen_form_is_kept(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="eslite.page_list")
    path = write_list(tmp_path, f"{BASE}101\n{BASE}101?page=1\n{BASE}101?page=2\n{BASE}101?page=2\n".encode())

    assert load_page_urls(path) == [f"{BASE}101", f"{BASE}101?page=2"]
    duplicates = [r for r in caplog.records if r.name == "eslite.page_list" and "duplicate" in r.getMessage()]
    assert len(duplicates) == 2
    assert f"{path} line 2" in duplicates[0].getMessage()


def test_the_limit_counts_canonical_pages_so_a_page_one_twin_does_not_add_one(tmp_path):
    lines = "".join(f"{BASE}101?page={n}\n" for n in range(2, MAX_PAGES + 1))
    lines = f"{BASE}101\n" + lines + f"{BASE}101?page=1\n"
    path = write_list(tmp_path, lines.encode())

    urls = load_page_urls(path)

    assert len(urls) == MAX_PAGES
    assert urls[0] == f"{BASE}101"


def test_max_plus_one_distinct_pages_is_an_error(tmp_path):
    lines = "".join(f"{BASE}101?page={n}\n" for n in range(1, MAX_PAGES + 2))
    path = write_list(tmp_path, lines.encode())

    with pytest.raises(PageListError, match=rf"{path!s}: more than {MAX_PAGES} distinct"):
        load_page_urls(path)


@pytest.mark.parametrize(
    "line",
    [
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1",  # another provider
        "https://www.eslite.com/category/2/28",  # level 2
        "https://www.eslite.com/category/3/101/",  # trailing slash
        "https://www.eslite.com/category/3/101?page=0",  # page zero
        "http://www.eslite.com/category/3/101",  # not https
    ],
)
def test_an_invalid_line_is_an_error_that_names_the_line_and_not_its_text(tmp_path, line):
    path = write_list(tmp_path, f"{BASE}101\n{line}\n".encode())

    with pytest.raises(PageListError) as excinfo:
        load_page_urls(path)

    assert f"{path} line 2: not a Eslite category list page URL" in str(excinfo.value)
    assert line not in str(excinfo.value)


def test_a_file_with_only_comments_is_an_error(tmp_path):
    path = write_list(tmp_path, b"# nothing here\n\n")

    with pytest.raises(PageListError, match="no Eslite category list page URLs"):
        load_page_urls(path)


def test_a_read_error_message_is_redacted(tmp_path):
    missing = tmp_path / "password=hunter2" / "eslite-pages.txt"

    with pytest.raises(PageListError) as excinfo:
        load_page_urls(missing)

    assert "hunter2" not in str(excinfo.value)
    assert "password=<redacted>" in str(excinfo.value)
