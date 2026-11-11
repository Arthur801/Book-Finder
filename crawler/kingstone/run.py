"""One Kingstone run, page by page (CB-07 Phase 4, plan §5 and §7): the Kingstone binding of ``catalog_core.category_run``.

The run logic (list page, cards, detail, catalog write, budget, retries, failure scope, counts, identity warnings and
diagnostics) lives in ``catalog_core.category_run`` (CB-08 Phase 3 M2). This module supplies the Kingstone adapter and
keeps the names the CLI, the artifacts and the tests import from here:

- ``KINGSTONE_ADAPTER``: the provider, the ``kingstone.run`` / ``kingstone.ledger`` logger names, the mode ``kingstone``,
  the list and detail parsers, the exception types and the diagnostic file code of a list page;
- ``run_pages(deps, page_urls, run_id=None) -> KingstoneReport``: ``run_category_pages`` with that adapter;
- the generic budget, retry and dependency names, re-exported unchanged (``SoftBudget``, ``MAX_ITEM_ATTEMPTS``,
  ``BACKOFF_BASE_SECONDS``, ``backoff_seconds``) or as Kingstone-named subclasses (``KingstoneRunDependencies``,
  ``KingstoneFetcherPort``, ``DiagnosticSink``).

Every behaviour, log line and message is the one documented in ``catalog_core.category_run``: the Kingstone adapter only
binds names. A list or detail parse error of Kingstone (``KingstoneParseError``) is the adapter's ``parse_error``; a soft
404 (``ProductNotFound``) is its ``not_found``.

Not here: composing the real fetcher and the database store (Phase 5/6), the CLI and the exit code wiring.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from catalog_core.category_run import (
    BACKOFF_BASE_SECONDS,
    MAX_ITEM_ATTEMPTS,
    CategoryAdapter,
    CategoryFetcherPort,
    CategoryRunDependencies,
    DiagnosticSink,
    SoftBudget,
    backoff_seconds,
    run_category_pages,
)
from catalog_core.models import ProviderCode
from kingstone.ledger import KingstoneReport
from kingstone.models import KingstoneParseError, ProductNotFound
from kingstone.parse_detail import parse_detail_html
from kingstone.parse_list import parse_list_html
from kingstone.urls import category_code_from_list_url

__all__ = [
    "BACKOFF_BASE_SECONDS",
    "KINGSTONE_ADAPTER",
    "MAX_ITEM_ATTEMPTS",
    "DiagnosticSink",
    "KingstoneFetcherPort",
    "KingstoneRunDependencies",
    "SoftBudget",
    "backoff_seconds",
    "log",
    "run_pages",
]

# The Kingstone page source is the provider-neutral port. ``kingstone.acquisition.KingstoneFetcher`` is the production one.
KingstoneFetcherPort = CategoryFetcherPort

log = logging.getLogger("kingstone.run")


@dataclass
class KingstoneRunDependencies(CategoryRunDependencies):
    """The run's dependencies for Kingstone: the provider-neutral fields, the same constructor and defaults."""


KINGSTONE_ADAPTER = CategoryAdapter(
    provider=ProviderCode.KINGSTONE,
    mode="kingstone",
    run_logger_name="kingstone.run",
    ledger_logger_name="kingstone.ledger",
    parse_list=parse_list_html,
    parse_detail=lambda text, item: parse_detail_html(text, item.source_url),
    parse_error=KingstoneParseError,
    not_found=ProductNotFound,
    list_page_code=lambda url: category_code_from_list_url(url) or "unknown",
    report_class=KingstoneReport,
)


def run_pages(deps: KingstoneRunDependencies, page_urls: Sequence[str], run_id: str | None = None) -> KingstoneReport:
    """Run the listed Kingstone category pages once, in order. Never raises: fatal errors are reported through ``report.error``.

    A URL listed twice is run once (the page list file already drops duplicates; this keeps the ledger's rule).
    """
    return cast(KingstoneReport, run_category_pages(KINGSTONE_ADAPTER, deps, page_urls, run_id=run_id))
