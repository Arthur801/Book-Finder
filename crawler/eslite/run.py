"""One Eslite run, page by page (CB-08 Phase 4): the Eslite binding of ``catalog_core.category_run``.

The run logic (list page, cards, detail, catalog write, budget, retries, failure scope, counts, identity warnings and
diagnostics) lives in ``catalog_core.category_run``. This module supplies the Eslite adapter only:

- ``ESLITE_ADAPTER``: the provider, the ``eslite.run`` / ``eslite.ledger`` logger names, the mode ``eslite``, the list and
  detail parsers, the exception types (``RestrictedProduct`` is the excluded type: age-restricted products are skipped and
  counted, not failed), the diagnostic file code of a list page, and the skip reason of a list parse error
  (``empty_category`` for a first page whose ``total`` is 0, ``parse_error`` for the rest);
- ``run_pages(deps, page_urls, run_id=None) -> CategoryReport``: ``run_category_pages`` with that adapter.

A card's detail parse error is ``EsliteParseError``; a detail 404 never reaches the parser (the fetcher raises
``AcquisitionError(HTTP_STATUS, status=404)``, which the run records as the card's ``http_status`` failure).

Not here: composing the real fetcher and the database store, the CLI and the exit code wiring.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from catalog_core.category_ledger import PARSE_ERROR_REASON, CategoryReport
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
from catalog_core.models import ListedItem, ProviderCode
from eslite.models import EmptyCategory, EsliteParseError, ProductNotFound, RestrictedProduct
from eslite.parse_detail import parse_detail_json
from eslite.parse_list import parse_list_json
from eslite.urls import category_and_page

__all__ = [
    "BACKOFF_BASE_SECONDS",
    "ESLITE_ADAPTER",
    "MAX_ITEM_ATTEMPTS",
    "DiagnosticSink",
    "EsliteFetcherPort",
    "EsliteRunDependencies",
    "SoftBudget",
    "backoff_seconds",
    "log",
    "run_pages",
]

# The Eslite page source is the provider-neutral port. ``eslite.acquisition.EsliteFetcher`` is the production one.
EsliteFetcherPort = CategoryFetcherPort

log = logging.getLogger("eslite.run")

EMPTY_CATEGORY_REASON = "empty_category"


@dataclass
class EsliteRunDependencies(CategoryRunDependencies):
    """The run's dependencies for Eslite: the provider-neutral fields, the same constructor and defaults."""


def _list_skip_reason(exc: Exception) -> str:
    return EMPTY_CATEGORY_REASON if isinstance(exc, EmptyCategory) else PARSE_ERROR_REASON


def _parse_detail(text: str, item: ListedItem):
    return parse_detail_json(text, item.external_id)


def _list_page_code(url: str) -> str:
    category, _ = category_and_page(url)
    return str(category)


ESLITE_ADAPTER = CategoryAdapter(
    provider=ProviderCode.ESLITE,
    mode="eslite",
    run_logger_name="eslite.run",
    ledger_logger_name="eslite.ledger",
    parse_list=parse_list_json,
    parse_detail=_parse_detail,
    parse_error=EsliteParseError,
    not_found=ProductNotFound,
    list_page_code=_list_page_code,
    list_skip_reason=_list_skip_reason,
    report_class=CategoryReport,
    excluded=RestrictedProduct,
)


def run_pages(deps: EsliteRunDependencies, page_urls: Sequence[str], run_id: str | None = None) -> CategoryReport:
    """Run the listed Eslite category pages once, in order. Never raises: fatal errors are reported through ``report.error``.

    A URL listed twice is run once (the page list file already drops duplicates; this keeps the ledger's rule).
    """
    return run_category_pages(ESLITE_ADAPTER, deps, page_urls, run_id=run_id)
