"""Command-line entry point: ``python -m books_crawler`` (run from the ``crawler`` directory).

Environment:
    DATABASE_URL            PostgreSQL connection URL of the shared database (required; secret, never logged).
    CRAWLER_FETCHER         Page fetcher: ``curl`` (default, Chrome fingerprint, crawler.md §15)
                            or ``browser`` (Playwright; diagnostics only).
    CRAWLER_NAV_TIMEOUT_MS  Browser navigation timeout in milliseconds (1..300000; default 30000).
                            Empty means the default. Only used by the browser fetcher.

Exit codes: 0 = SUCCESS or PARTIAL_SUCCESS (bestsellers replaced), 1 = FAILED (bestsellers unchanged),
2 = configuration error.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Mapping

from books_crawler import db
from books_crawler.fetcher import (
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    MAX_NAVIGATION_TIMEOUT_MS,
    FetcherKind,
    create_fetcher,
)
from books_crawler.parsers import parse_detail_html, parse_ranking_html
from books_crawler.run import RunDependencies, run_first_book, run_once, run_pages

EXIT_CONFIG_ERROR = 2
FETCHER_ENV = "CRAWLER_FETCHER"
NAVIGATION_TIMEOUT_ENV = "CRAWLER_NAV_TIMEOUT_MS"


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


def main(environ: Mapping[str, str] | None = None, *, first_book: bool = False, pages: bool = False) -> int:
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
        if first_book:
            return run_first_book(deps).exit_code

        if pages:
            return run_pages(deps).exit_code
        
        return run_once(deps).exit_code


    finally:
        fetcher.close()


if __name__ == "__main__":
    raise SystemExit(main())
