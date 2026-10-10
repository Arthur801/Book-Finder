"""Command-line entry point: ``python -m books_crawler`` (run from the ``crawler`` directory).

Environment:
    DATABASE_URL  PostgreSQL connection URL of the shared database (required; never logged).

Exit codes: 0 = SUCCESS, 1 = FAILED (bestsellers unchanged), 2 = configuration error.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping, Sequence

from books_crawler import db
from books_crawler.fetcher import HttpFetcher
from books_crawler.parsers import parse_detail_html, parse_ranking_html
from books_crawler.run import RunDependencies, run_once

EXIT_CONFIG_ERROR = 2


def _configure_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger("books_crawler")
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    root.propagate = False
    return root


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    del argv  # no options yet
    _configure_logging()
    log = logging.getLogger("books_crawler.cli")
    env = os.environ if environ is None else environ

    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        log.error("DATABASE_URL is not set; nothing was crawled")
        return EXIT_CONFIG_ERROR

    deps = RunDependencies(
        fetcher=HttpFetcher(),
        parse_ranking=parse_ranking_html,
        parse_detail=parse_detail_html,
        connect=lambda: db.connect(database_url),
    )
    return run_once(deps).exit_code


if __name__ == "__main__":
    raise SystemExit(main())
