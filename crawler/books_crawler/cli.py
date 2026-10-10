"""Command-line entry point: ``python -m books_crawler`` (run from the ``crawler`` directory).

Environment:
    DATABASE_URL     PostgreSQL connection URL of the shared database (required; never logged).
    CRAWLER_FETCHER  Page fetcher: ``browser`` (default, headless Chromium via Playwright, ADR-006)
                     or ``http`` (requests; debugging only, blocked by books.com.tw's challenge).

Exit codes: 0 = SUCCESS or PARTIAL_SUCCESS (bestsellers replaced), 1 = FAILED (bestsellers unchanged),
2 = configuration error.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping

from books_crawler import db
from books_crawler.fetcher import HttpFetcher, PlaywrightFetcher
from books_crawler.parsers import parse_detail_html, parse_ranking_html
from books_crawler.run import RunDependencies, run_once

EXIT_CONFIG_ERROR = 2
FETCHER_ENV = "CRAWLER_FETCHER"
FETCHER_BROWSER = "browser"
FETCHER_HTTP = "http"


def _configure_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger("books_crawler")
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    return root


def main(environ: Mapping[str, str] | None = None) -> int:
    _configure_logging()
    log = logging.getLogger("books_crawler.cli")
    env = os.environ if environ is None else environ

    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        log.error("DATABASE_URL is not set; nothing was crawled")
        return EXIT_CONFIG_ERROR

    fetcher_choice = env.get(FETCHER_ENV, "").strip().lower() or FETCHER_BROWSER
    fetcher: HttpFetcher | PlaywrightFetcher
    if fetcher_choice == FETCHER_BROWSER:
        fetcher = PlaywrightFetcher()
    elif fetcher_choice == FETCHER_HTTP:
        fetcher = HttpFetcher()
    else:
        log.error("%s must be '%s' or '%s', not %r", FETCHER_ENV, FETCHER_BROWSER, FETCHER_HTTP, fetcher_choice)
        return EXIT_CONFIG_ERROR
    log.info("using %s fetcher", fetcher_choice)

    deps = RunDependencies(
        fetcher=fetcher,
        parse_ranking=parse_ranking_html,
        parse_detail=parse_detail_html,
        connect=lambda: db.connect(database_url),
    )
    # The browser must be closed however the run ends: normal result, FAILED, or an exception.
    try:
        return run_once(deps).exit_code
    finally:
        fetcher.close()


if __name__ == "__main__":
    raise SystemExit(main())
