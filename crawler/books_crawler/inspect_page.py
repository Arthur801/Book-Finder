"""Inspect one page with the Playwright browser fetcher (diagnostics only), without accessing the database."""

import argparse
import logging
from pathlib import Path

from books_crawler.cli import configure_logging
from books_crawler.fetcher import (
    DEFAULT_CHALLENGE_DIR,
    BrowserUnavailableError,
    FetchError,
    PlaywrightFetcher,
)
from books_crawler.redact import redact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Page URL to inspect (one request, no retry)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_CHALLENGE_DIR)
    args = parser.parse_args()
    configure_logging()
    log = logging.getLogger("books_crawler.inspect_page")
    try:
        with PlaywrightFetcher(challenge_dir=args.output_dir) as fetcher:
            fetcher.get(args.url)
    except (FetchError, BrowserUnavailableError) as exc:
        log.error("%s", redact(str(exc)))
        return 1
    log.info("Page retrieved successfully; no challenge detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
