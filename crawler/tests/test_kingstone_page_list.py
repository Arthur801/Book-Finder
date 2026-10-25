"""Kingstone category list page file (kingstone.page_list). Offline: temp files and the shipped default file."""

import logging

import pytest

from kingstone import page_list
from kingstone.page_list import MAX_PAGES, PAGES_FILE_ENV, PageListError, load_page_urls, resolve_pages_file

BASE = "https://www.kingstone.com.tw/book/"


def write_list(tmp_path, data: bytes, name="kingstone-pages.txt"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_the_env_var_name_and_the_default_file_are_the_kingstone_ones():
    assert PAGES_FILE_ENV == "KINGSTONE_PAGES_FILE"
    assert page_list.DEFAULT_PAGES_FILE.name == "kingstone-pages.txt"
    assert page_list.DEFAULT_PAGES_FILE.parent.name == "crawler"
    assert MAX_PAGES == 200


def test_resolve_pages_file_uses_the_default_for_a_blank_value_and_the_override_otherwise(tmp_path):
    override = tmp_path / "other.txt"

    assert resolve_pages_file("") == page_list.DEFAULT_PAGES_FILE
    assert resolve_pages_file("   ") == page_list.DEFAULT_PAGES_FILE
    assert resolve_pages_file(f"  {override}  ") == override


def test_a_utf8_bom_is_allowed(tmp_path):
    path = write_list(tmp_path, "﻿".encode() + f"{BASE}jdc/?dis=list&page=1\n".encode())

    assert load_page_urls(path) == [f"{BASE}jdc/?dis=list&page=1"]


def test_comments_blank_lines_and_surrounding_whitespace_are_ignored_and_order_is_kept(tmp_path):
    text = f"# comment\n\n   {BASE}sj/?dis=list&page=1  \n# another\n\t{BASE}jdc/?dis=list&page=2\n   \n"
    path = write_list(tmp_path, text.encode())

    assert load_page_urls(path) == [f"{BASE}sj/?dis=list&page=1", f"{BASE}jdc/?dis=list&page=2"]


def test_a_code_differing_only_in_case_is_a_duplicate_and_the_first_seen_form_is_kept(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="kingstone.page_list")
    text = f"{BASE}JDC/?dis=list&page=1\n{BASE}jdc/?dis=list&page=1&sort=pu_desc\n{BASE}jdc/?page=1&dis=list\n"
    path = write_list(tmp_path, text.encode())

    assert load_page_urls(path) == [f"{BASE}jdc/?dis=list&page=1", f"{BASE}jdc/?dis=list&page=1&sort=pu_desc"]
    assert sum("duplicate" in r.getMessage() for r in caplog.records) == 1
    assert all(r.name == "kingstone.page_list" for r in caplog.records)


def test_an_invalid_line_error_names_the_file_and_the_line_but_not_the_url_text(tmp_path):
    secret = "https://user:hunter2@www.kingstone.com.tw/book/jdc/?dis=list&page=1&token=ZZZ"
    path = write_list(tmp_path, f"{BASE}jdc/?dis=list&page=1\n{secret}\n".encode())

    with pytest.raises(PageListError) as info:
        load_page_urls(path)

    message = str(info.value)
    assert str(path) in message
    assert "line 2" in message
    assert "hunter2" not in message
    assert "ZZZ" not in message
    assert "user:" not in message
    assert "not a Kingstone category list page URL" in message


def test_a_file_with_only_comments_is_an_error_naming_the_file(tmp_path):
    path = write_list(tmp_path, b"# nothing here\n\n")

    with pytest.raises(PageListError, match=rf"{path!s}: no Kingstone category list page URLs"):
        load_page_urls(path)


def test_exactly_200_distinct_urls_are_accepted(tmp_path):
    lines = "".join(f"{BASE}jdc/?dis=list&page={n}\n" for n in range(1, MAX_PAGES + 1))
    path = write_list(tmp_path, lines.encode())

    assert len(load_page_urls(path)) == 200


def test_201_distinct_urls_are_an_error(tmp_path):
    lines = "".join(f"{BASE}jdc/?dis=list&page={n}\n" for n in range(1, MAX_PAGES + 2))
    path = write_list(tmp_path, lines.encode())

    with pytest.raises(PageListError, match=rf"{path!s}: more than 200 distinct Kingstone category list page URLs"):
        load_page_urls(path)


def test_201_lines_that_are_only_200_distinct_urls_after_dedupe_are_accepted(tmp_path):
    lines = "".join(f"{BASE}jdc/?dis=list&page={n}\n" for n in range(1, MAX_PAGES + 1))
    path = write_list(tmp_path, (lines + f"{BASE}JDC/?dis=list&page=1\n").encode())

    assert len(load_page_urls(path)) == 200


def test_the_shipped_default_file_has_no_urls_yet_so_loading_it_is_an_error():
    with pytest.raises(PageListError, match=r"no Kingstone category list page URLs"):
        load_page_urls(page_list.DEFAULT_PAGES_FILE)


def test_a_missing_file_is_an_error_naming_the_file(tmp_path):
    path = tmp_path / "missing.txt"

    with pytest.raises(PageListError, match=rf"cannot read Kingstone category list pages file {path!s}"):
        load_page_urls(path)


def test_sa_desc_and_the_omitted_sort_are_one_page_so_the_list_keeps_one_row(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="kingstone.page_list")
    text = f"{BASE}jdc/?dis=list&page=1\n{BASE}jdc/?dis=list&page=1&sort=sa_desc\n"
    path = write_list(tmp_path, text.encode())

    assert load_page_urls(path) == [f"{BASE}jdc/?dis=list&page=1"]
    assert sum("duplicate" in r.getMessage() for r in caplog.records) == 1


def test_the_200_limit_counts_canonical_pages_so_an_sa_desc_twin_does_not_add_one(tmp_path):
    lines = "".join(f"{BASE}jdc/?dis=list&page={n}\n" for n in range(1, MAX_PAGES + 1))
    lines += f"{BASE}jdc/?dis=list&page=1&sort=sa_desc\n"
    path = write_list(tmp_path, lines.encode())

    urls = load_page_urls(path)

    assert len(urls) == 200
    assert f"{BASE}jdc/?dis=list&page=1" in urls


def test_201_distinct_pages_are_an_error_even_when_one_of_them_has_an_sa_desc_twin(tmp_path):
    lines = "".join(f"{BASE}jdc/?dis=list&page={n}\n" for n in range(1, MAX_PAGES + 2))
    lines += f"{BASE}jdc/?dis=list&page=1&sort=sa_desc\n"
    path = write_list(tmp_path, lines.encode())

    with pytest.raises(PageListError, match=rf"{path!s}: more than 200 distinct"):
        load_page_urls(path)


def test_a_read_error_message_is_redacted(tmp_path):
    missing = tmp_path / "password=hunter2" / "kingstone-pages.txt"

    with pytest.raises(PageListError) as excinfo:
        load_page_urls(missing)

    assert "hunter2" not in str(excinfo.value)
    assert "password=<redacted>" in str(excinfo.value)
