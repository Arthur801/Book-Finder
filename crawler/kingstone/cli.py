"""Command-line entry point for the Kingstone (金石堂) category run: ``python -m kingstone`` (run from ``crawler/``).

Composition only: it reads and validates the settings, builds the real fetcher and the database store, and runs
``kingstone.run.run_pages`` once. Parsing, the write policy and the terminal status are not decided here.

Environment:
    DATABASE_URL                    PostgreSQL URL of the shared database (required; secret, never logged).
    KINGSTONE_PAGES_FILE            Category list page file (default ``crawler/kingstone-pages.txt``).
    KINGSTONE_WRITE_POLICY          ``new-books-only`` (default) or ``normal``.
    KINGSTONE_SOFT_RUN_BUDGET_SECONDS  Soft run budget (default 7200); no request starts once it runs out.
    CRAWLER_RUN_HARD_LIMIT_SECONDS  The hard run limit (default 9000); the soft budget must be below it.
    KINGSTONE_HTTP_TIMEOUT_SECONDS, KINGSTONE_HTTP_MAX_ATTEMPTS, KINGSTONE_MAX_RESPONSE_BYTES
                                    HTTP settings (defaults in ``kingstone.acquisition``).

Exit codes:
    0 = SUCCESS or PARTIAL_SUCCESS,
    1 = FAILED (the run could not continue, or the provider registry could not be read),
    2 = configuration error: DATABASE_URL, a setting, the page list, or a disabled or unregistered provider.
        Each of these is checked before the fetcher is built, so a configuration error sends no request.

The hard limit (``CRAWLER_RUN_HARD_LIMIT_SECONDS``) is enforced by the runner's watchdog (Phase 6). This module only
validates the value and keeps the soft budget below it.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

import psycopg

from catalog_core import persistence
from catalog_core.models import ProviderCode
from catalog_core.normalize import ensure_runtime_unicode_supported
from catalog_core.redact import redact
from catalog_core.session import DatabaseSession
from catalog_core.store import SessionCatalogStore
from kingstone.acquisition import KingstoneFetcher
from kingstone.config import KingstoneConfig, KingstoneConfigError, load_config
from kingstone.page_list import PageListError, load_page_urls
from kingstone.run import KingstoneFetcherPort, KingstoneRunDependencies, SoftBudget, run_pages

EXIT_FAILED = 1
EXIT_CONFIG_ERROR = 2
PROVIDER = ProviderCode.KINGSTONE


def configure_logging() -> logging.Logger:
    """Send ``kingstone`` and ``catalog_core`` logs to stdout at INFO. Own handler: the Books entry point is not imported."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger("kingstone")
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    core = logging.getLogger("catalog_core")
    core.handlers[:] = [handler]
    core.setLevel(logging.INFO)
    return root


def _default_fetcher(config: KingstoneConfig, budget: SoftBudget) -> KingstoneFetcher:
    """The production fetcher. The budget is the same clock the run checks, so both guards read one budget."""
    return KingstoneFetcher(
        timeout=config.http_timeout_seconds,
        max_attempts=config.http_max_attempts,
        max_response_bytes=config.max_response_bytes,
        budget_remaining=budget.remaining,
    )


def main(
    environ: Mapping[str, str] | None = None,
    *,
    provider_enabled: Callable[[str, ProviderCode], bool | None] | None = None,
    fetcher_factory: Callable[[KingstoneConfig, SoftBudget], KingstoneFetcherPort] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    configure_logging()
    log = logging.getLogger("kingstone.cli")
    env = os.environ if environ is None else environ

    # Fail fast on a runtime whose Unicode data would give wrong ISBN keys (data-model 7.1).
    try:
        ensure_runtime_unicode_supported()
    except RuntimeError as exc:
        log.error("%s", exc)
        return EXIT_CONFIG_ERROR

    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        log.error("DATABASE_URL is not set; nothing was crawled")
        return EXIT_CONFIG_ERROR

    try:
        config = load_config(env)
    except KingstoneConfigError as exc:
        log.error("%s", redact(str(exc)))
        return EXIT_CONFIG_ERROR

    # The page list is read and validated before the fetcher exists, so an invalid list makes no request at all.
    try:
        page_urls = load_page_urls(config.pages_file)
    except PageListError as exc:
        log.error("%s", redact(str(exc)))
        return EXIT_CONFIG_ERROR

    # A disabled (or unregistered) provider is a configuration error: nothing is fetched (crawler.md §3.1, §14.5).
    try:
        check = provider_enabled or persistence.provider_enabled  # resolved per call so tests can replace it
        enabled = check(database_url, PROVIDER)
    except psycopg.Error as exc:
        log.error("could not read source_providers: %s", redact(str(exc)))
        return EXIT_FAILED
    if enabled is not True:
        log.error("source provider %s is disabled or not registered; nothing was crawled", PROVIDER)
        return EXIT_CONFIG_ERROR

    budget = SoftBudget(config.soft_budget_seconds, monotonic)
    fetcher = (fetcher_factory or _default_fetcher)(config, budget)
    log.info("using the kingstone HTTP fetcher; write policy %s", config.write_policy.value)

    # The fetcher must be closed however the run ends: normal result, FAILED, or an exception.
    try:
        with DatabaseSession(lambda: persistence.connect(database_url)) as session:
            deps = KingstoneRunDependencies(
                fetcher=fetcher,
                store=SessionCatalogStore(session),
                budget=budget,
                clock=lambda: datetime.now(UTC),
                sleep=time.sleep,
                write_policy=config.write_policy,
            )
            report = run_pages(deps, page_urls)
        return report.exit_code
    finally:
        fetcher.close()


if __name__ == "__main__":
    raise SystemExit(main())
