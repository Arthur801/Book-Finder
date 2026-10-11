"""The category page list for pages mode: which 7-day category ranking pages to import (crawler.md §16, pages mode).

File format: one URL per line; lines starting with ``#`` are comments; blank lines are ignored;
surrounding whitespace is trimmed. Duplicate URLs are kept once, in first-seen order.
"""

from __future__ import annotations

import logging
from pathlib import Path

from books_crawler.redact import redact
from books_crawler.urls import is_category_ranking_url

log = logging.getLogger("books_crawler.page_list")

PAGES_FILE_ENV = "CRAWLER_PAGES_FILE"
# crawler/category-pages.txt, located relative to the package, not the working directory.
DEFAULT_PAGES_FILE = Path(__file__).resolve().parent.parent / "category-pages.txt"


def resolve_pages_file(raw: str) -> Path:
    """The page list path: the env var value when non-blank, otherwise the default file."""
    value = raw.strip()
    return Path(value) if value else DEFAULT_PAGES_FILE


class PageListError(ValueError):
    """The page list cannot be used. The message names the file and, where relevant, the line."""


def load_page_urls(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise PageListError(redact(f"cannot read category pages file {path}: {exc}")) from exc
    urls: list[str] = []
    seen: set[str] = set()
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not is_category_ranking_url(line):
            # The line itself is not echoed: it may carry credentials (crawler.md §12).
            raise PageListError(f"{path} line {number}: not a books.com.tw category 7-day ranking URL")
        if line in seen:
            log.info("dropped duplicate category page URL at %s line %d: %s", path, number, line)
            continue
        seen.add(line)
        urls.append(line)
    if not urls:
        raise PageListError(f"{path}: no category page URLs")
    return urls
