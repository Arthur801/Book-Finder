"""Generic page-list file loader (catalog_core.page_list): file rules shared by every provider. No network, no database."""

import logging

import pytest

from catalog_core.page_list import PageListError, load_url_list

KIND = "test list URL"
FILE_LABEL = "test list"
URL_LABEL = "test list URLs"


def lower_or_none(line: str) -> str | None:
    """A toy canonicalizer: accepts every line that starts with https://example.test/, lowercases it."""
    if not line.startswith("https://example.test/"):
        return None
    return line.lower()


def keep_or_none(line: str) -> str | None:
    return line if line.startswith("https://example.test/") else None


def load(path, canonicalize=keep_or_none, **kwargs):
    return load_url_list(path, canonicalize, kind=KIND, file_label=FILE_LABEL, url_label=URL_LABEL, **kwargs)


def write_bytes(tmp_path, data: bytes, name="list.txt"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_a_utf8_bom_at_the_start_of_the_file_is_allowed(tmp_path):
    path = write_bytes(tmp_path, b"\xef\xbb\xbfhttps://example.test/a\nhttps://example.test/b\n")

    assert load(path) == ["https://example.test/a", "https://example.test/b"]


def test_comments_blank_lines_and_surrounding_whitespace_are_ignored(tmp_path):
    path = write_bytes(
        tmp_path,
        b"# header\n\n   https://example.test/a  \n  \n\thttps://example.test/b\n# tail\n",
    )

    assert load(path) == ["https://example.test/a", "https://example.test/b"]


def test_an_invalid_line_is_an_error_naming_the_file_and_line_number(tmp_path):
    path = write_bytes(tmp_path, b"# c\nhttps://example.test/a\nhttps://example.test/b\nnot a url\n")

    with pytest.raises(PageListError, match=rf"{path!s} line 4: not a test list URL"):
        load(path)


def test_an_invalid_line_message_never_echoes_the_line_text(tmp_path):
    secret = "https://user:hunter2@example.org/?password=s3cret"
    path = write_bytes(tmp_path, f"https://example.test/a\n{secret}\n".encode())

    with pytest.raises(PageListError) as info:
        load(path)

    message = str(info.value)
    assert f"{path} line 2" in message
    assert "hunter2" not in message
    assert "s3cret" not in message
    assert "example.org" not in message


def test_duplicates_are_compared_on_the_canonical_value_and_the_first_seen_form_is_kept(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="catalog_core.page_list")
    path = write_bytes(
        tmp_path,
        b"https://example.test/JDC\nhttps://example.test/x\nhttps://example.test/jdc\n",
    )

    assert load(path, lower_or_none) == ["https://example.test/jdc", "https://example.test/x"]
    assert sum("duplicate" in r.getMessage() for r in caplog.records) == 1


def test_a_custom_logger_receives_the_duplicate_log_line(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="books_crawler.page_list")
    path = write_bytes(tmp_path, b"https://example.test/a\nhttps://example.test/a\n")

    load(path, logger=logging.getLogger("books_crawler.page_list"))

    assert any(r.name == "books_crawler.page_list" and r.levelno == logging.INFO for r in caplog.records)


def test_a_file_without_any_url_is_an_error_naming_the_file(tmp_path):
    path = write_bytes(tmp_path, b"# only comments\n\n   \n")

    with pytest.raises(PageListError, match=rf"{path!s}: no test list URLs$"):
        load(path)


def test_a_missing_file_is_an_error_naming_the_file_with_the_file_label(tmp_path):
    path = tmp_path / "no-such-list.txt"

    with pytest.raises(PageListError, match=rf"cannot read test list file {path!s}"):
        load(path)


def test_the_read_error_message_passes_through_the_redact_hook(tmp_path):
    path = tmp_path / "no-such-list.txt"

    with pytest.raises(PageListError, match=r"REDACTED-MARK"):
        load(path, redact_message=lambda text: text + " REDACTED-MARK")


def test_max_entries_accepts_exactly_the_limit_and_rejects_one_more(tmp_path):
    lines = "".join(f"https://example.test/{i}\n" for i in range(3))
    path = write_bytes(tmp_path, lines.encode())

    assert len(load(path, max_entries=3)) == 3
    with pytest.raises(PageListError, match=rf"{path!s}: more than 2 distinct test list URLs"):
        load(path, max_entries=2)


def test_max_entries_counts_distinct_canonical_values_not_raw_lines(tmp_path):
    path = write_bytes(tmp_path, b"https://example.test/A\nhttps://example.test/a\nhttps://example.test/A\n")

    assert load(path, lower_or_none, max_entries=1) == ["https://example.test/a"]


def test_the_default_has_no_entry_limit(tmp_path):
    lines = "".join(f"https://example.test/{i}\n" for i in range(500))
    path = write_bytes(tmp_path, lines.encode())

    assert len(load(path)) == 500


def test_page_list_error_is_a_value_error():
    assert issubclass(PageListError, ValueError)
