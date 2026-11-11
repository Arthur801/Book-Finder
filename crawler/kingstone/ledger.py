"""Run accounting for the Kingstone adapter (CB-07 Phase 4): the Kingstone names of the provider-neutral ledger.

The ledger, the report, the terminal status rule and ``format_report`` live in ``catalog_core.category_ledger`` (CB-08
Phase 3 M2). This module keeps the names the Kingstone run, CLI, artifacts and tests import, and binds them to
``ProviderCode.KINGSTONE`` and the ``kingstone.ledger`` logger:

- ``KingstoneLedger(page_urls, write_policy)``: a ``CategoryLedger`` for Kingstone;
- ``KingstoneReport``: a ``CategoryReport`` whose ``provider_code`` defaults to KINGSTONE, so a direct construction
  without a provider still reports Kingstone (same field order as before the split).

Behaviour, log lines and report text are those documented in ``catalog_core.category_ledger``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from catalog_core.category_ledger import (
    EXIT_CONFIG_ERROR,
    EXIT_FAILED,
    EXIT_SUCCESS,
    PARSE_ERROR_REASON,
    CategoryLedger,
    CategoryReport,
    FailedItem,
    RunStatus,
    SkippedPage,
    decide_status,
    format_report,
)
from catalog_core.models import ProviderCode, WritePolicy

__all__ = [
    "EXIT_CONFIG_ERROR",
    "EXIT_FAILED",
    "EXIT_SUCCESS",
    "PARSE_ERROR_REASON",
    "FailedItem",
    "KingstoneLedger",
    "KingstoneReport",
    "RunStatus",
    "SkippedPage",
    "decide_status",
    "format_report",
]

log = logging.getLogger("kingstone.ledger")


@dataclass(frozen=True)
class KingstoneReport(CategoryReport):
    """The outcome of one Kingstone run: a ``CategoryReport`` whose provider defaults to KINGSTONE."""

    provider_code: ProviderCode = ProviderCode.KINGSTONE


class KingstoneLedger(CategoryLedger):
    """Accounts for one Kingstone run over the listed pages, in list order."""

    def __init__(self, page_urls: Sequence[str], write_policy: WritePolicy) -> None:
        super().__init__(
            page_urls,
            write_policy,
            provider_code=ProviderCode.KINGSTONE,
            logger=log,
            report_class=KingstoneReport,
        )
