"""Command-line entry point: ``python -m books_crawler`` (run from the ``crawler`` directory).

Modes (one entry point each):
    python -m books_crawler              daily run: 7-day overall TOP 100 Bestseller (crawler.md §14)
    python -m books_crawler.first_book   first-book import: rank 1 only, no Bestseller write (crawler.md §16)
    python -m books_crawler.pages        pages import: category 7-day ranking pages, Catalog only (crawler.md §15)

Environment:
    DATABASE_URL            PostgreSQL connection URL of the shared database (required; secret, never logged).
    CRAWLER_FETCHER         Page fetcher: ``curl`` (default, Chrome fingerprint, crawler.md §12)
                            or ``browser`` (Playwright; diagnostics only).
    CRAWLER_NAV_TIMEOUT_MS  Browser navigation timeout in milliseconds (1..300000; default 30000).
                            Empty means the default. Only used by the browser fetcher.
    CRAWLER_PAGES_FILE      Pages mode only: the category page list (default ``crawler/category-pages.txt``,
                            crawler.md §15.3). Read and validated before any request; ignored by the other modes.

Exit codes:
    daily and first-book: 0 = SUCCESS or PARTIAL_SUCCESS (bestsellers replaced, or Catalog import done),
                          1 = FAILED (bestsellers unchanged), 2 = configuration error.
    pages:                0 = SUCCESS or PARTIAL_SUCCESS (skipped pages or rows included),
                          1 = FAILED (the run could not continue), 2 = configuration error
                          (including an invalid page list, detected before any request).
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Mapping
from enum import StrEnum

from books_crawler import db
from books_crawler.fetcher import (
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    MAX_NAVIGATION_TIMEOUT_MS,
    FetcherKind,
    create_fetcher,
)
from books_crawler.page_list import (
    PAGES_FILE_ENV,
    PageListError,
    load_page_urls,
    resolve_pages_file,
)
from books_crawler.parsers import parse_detail_html, parse_ranking_html
from books_crawler.redact import redact
from books_crawler.run import RunDependencies, run_first_book, run_once, run_pages

EXIT_CONFIG_ERROR = 2
FETCHER_ENV = "CRAWLER_FETCHER"
NAVIGATION_TIMEOUT_ENV = "CRAWLER_NAV_TIMEOUT_MS"


class CrawlerMode(StrEnum):
    """Which run ``main`` starts. The values are the names used in the run log."""

    DAILY = "daily"
    FIRST_BOOK = "first-book"
    PAGES = "pages"


def configure_logging() -> logging.Logger:
    """Send ``books_crawler`` logs to stdout at INFO; shared by every crawler entry point."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger("books_crawler")
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    return root


def parse_navigation_timeout(raw: str) -> int:
    """Return the navigation timeout in ms. Empty means the default; anything else must be a whole number in range."""
    value = raw.strip()
    if not value:
        return DEFAULT_NAVIGATION_TIMEOUT_MS
    if re.fullmatch(r"[0-9]+", value) is None:
        raise ValueError(f"must be a whole number of milliseconds, not {raw!r}")
    milliseconds = int(value)
    if not 1 <= milliseconds <= MAX_NAVIGATION_TIMEOUT_MS:
        raise ValueError(f"must be between 1 and {MAX_NAVIGATION_TIMEOUT_MS} milliseconds, not {milliseconds}")
    return milliseconds


def main(environ: Mapping[str, str] | None = None, *, mode: CrawlerMode = CrawlerMode.DAILY) -> int:
    configure_logging()
    log = logging.getLogger("books_crawler.cli")
    env = os.environ if environ is None else environ

    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        log.error("DATABASE_URL is not set; nothing was crawled")
        return EXIT_CONFIG_ERROR

    try:
        navigation_timeout_ms = parse_navigation_timeout(env.get(NAVIGATION_TIMEOUT_ENV, ""))
    except ValueError as exc:
        log.error("%s %s", NAVIGATION_TIMEOUT_ENV, exc)
        return EXIT_CONFIG_ERROR

    raw_kind = env.get(FETCHER_ENV, "")
    try:
        kind = FetcherKind(raw_kind.strip().lower() or FetcherKind.CURL)
    except ValueError:
        choices = " or ".join(f"'{item.value}'" for item in FetcherKind)
        log.error("%s must be %s, not %r", FETCHER_ENV, choices, raw_kind)
        return EXIT_CONFIG_ERROR

    # Validate the page list before the fetcher exists, so a bad list makes no request at all.
    page_urls: list[str] = []
    if mode is CrawlerMode.PAGES:
        try:
            page_urls = load_page_urls(resolve_pages_file(env.get(PAGES_FILE_ENV, "")))
        except PageListError as exc:
            log.error("%s", redact(str(exc)))
            return EXIT_CONFIG_ERROR

    # TODO(#116 phase B): a disabled provider is a configuration error (exit 2, crawler.md §3.1, §14.5, §15.7, §16).
    # The check reads source_providers.enabled, which does not exist before migration 010, so it is not faked here.
    # It belongs right before the fetcher is created: no request may be made for a disabled provider.
    fetcher = create_fetcher(kind, navigation_timeout_ms=navigation_timeout_ms)
    log.info("using %s fetcher", kind.value)

    deps = RunDependencies(
        fetcher=fetcher,
        parse_ranking=parse_ranking_html,
        parse_detail=parse_detail_html,
        connect=lambda: db.connect(database_url),
    )
    # The fetcher must be closed however the run ends: normal result, FAILED, or an exception.
    try:
        if mode is CrawlerMode.FIRST_BOOK:
            return run_first_book(deps).exit_code
        if mode is CrawlerMode.PAGES:
            return run_pages(deps, page_urls).exit_code
        return run_once(deps).exit_code
    finally:
        fetcher.close()


if __name__ == "__main__":
    raise SystemExit(main())
