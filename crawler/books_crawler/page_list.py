"""The category page list for pages mode: which 7-day category ranking pages to import (crawler.md §15, pages mode).

File format: one URL per line; lines starting with ``#`` are comments; blank lines are ignored;
surrounding whitespace is trimmed. Duplicate URLs are kept once, in first-seen order. The file rules live in
``catalog_core.page_list``; this module supplies the books.com.tw URL rule and the environment/default path.
"""

from __future__ import annotations

import logging
from pathlib import Path

from books_crawler.redact import redact
from books_crawler.urls import is_category_ranking_url
from catalog_core.page_list import PageListError, load_url_list

log = logging.getLogger("books_crawler.page_list")

PAGES_FILE_ENV = "CRAWLER_PAGES_FILE"
# crawler/category-pages.txt, located relative to the package, not the working directory.
DEFAULT_PAGES_FILE = Path(__file__).resolve().parent.parent / "category-pages.txt"

__all__ = ["DEFAULT_PAGES_FILE", "PAGES_FILE_ENV", "PageListError", "load_page_urls", "resolve_pages_file"]


def resolve_pages_file(raw: str) -> Path:
    """The page list path: the env var value when non-blank, otherwise the default file."""
    value = raw.strip()
    return Path(value) if value else DEFAULT_PAGES_FILE


def _books_category_url(line: str) -> str | None:
    # The line is kept as written: the Books URL is already canonical for the duplicate check.
    return line if is_category_ranking_url(line) else None


def load_page_urls(path: Path) -> list[str]:
    return load_url_list(
        path,
        _books_category_url,
        kind="books.com.tw category 7-day ranking URL",
        file_label="category pages",
        url_label="category page URLs",
        logger=log,
        redact_message=redact,
    )
