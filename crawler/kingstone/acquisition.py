"""Kingstone (金石堂) HTTP acquisition: the Kingstone ``FetchPolicy`` over the provider-neutral engine.

The engine (the ``Transport`` port, ``CurlTransport``, retry, pacing, budget, Retry-After, decode and redirect rules, and
the error taxonomy) lives in ``catalog_core.http_acquisition``. This module holds only what is Kingstone-specific:

- the URL predicates from ``kingstone.urls`` (only the accepted list and detail grammar is requested);
- the page delay, 3 to 10 seconds, uniform;
- the ``Accept-Language: zh-TW,zh;q=0.9`` request header;
- the ``kingstone.acquisition`` logger.

``KingstoneFetcher`` is the Kingstone policy with the same constructor and defaults as before the split. Its behaviour
(URL guards, pacing, retry, budget, counters, log lines) is documented in ``catalog_core.http_acquisition.PacedFetcher``.
The names re-exported below keep ``kingstone.acquisition`` importable for its existing callers and tests.

Deliberately absent: challenge or CAPTCHA detection, cookie persistence, a browser and diagnostic files.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from catalog_core import http_acquisition as _engine
from catalog_core.http_acquisition import (
    BACKOFF_BASE_SECONDS,
    MAX_ATTEMPTS,
    MAX_BACKOFF_SECONDS,
    MAX_RESPONSE_BYTES,
    MAX_RETRY_AFTER_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_AFTER_STATUSES,
    RETRYABLE_STATUSES,
    AcquisitionError,
    AcquisitionFailure,
    FetchPolicy,
    RawResponse,
    ResponseTooLarge,
    Transport,
    TransportConnectionError,
    TransportTimeout,
    backoff_seconds,
    unlimited_budget,
)
from kingstone.urls import SITE_HOST, canonical_list_url, km_code_from_detail_url

__all__ = [
    "BACKOFF_BASE_SECONDS",
    "KINGSTONE_POLICY",
    "MAX_ATTEMPTS",
    "MAX_BACKOFF_SECONDS",
    "MAX_PAGE_DELAY_SECONDS",
    "MAX_RESPONSE_BYTES",
    "MAX_RETRY_AFTER_SECONDS",
    "MIN_PAGE_DELAY_SECONDS",
    "REQUEST_TIMEOUT_SECONDS",
    "RETRYABLE_STATUSES",
    "RETRY_AFTER_STATUSES",
    "AcquisitionError",
    "AcquisitionFailure",
    "CurlTransport",
    "FetchPolicy",
    "KingstoneFetcher",
    "RawResponse",
    "ResponseTooLarge",
    "Transport",
    "TransportConnectionError",
    "TransportTimeout",
    "backoff_seconds",
    "curl_requests",
]

log = logging.getLogger("kingstone.acquisition")

curl_requests = _engine.curl_requests

_ACCEPT_LANGUAGE = "zh-TW,zh;q=0.9"
_LIST_REJECTED = "not an accepted Kingstone category list page URL"
_DETAIL_REJECTED = "not an accepted Kingstone detail page URL"

MIN_PAGE_DELAY_SECONDS = 3
MAX_PAGE_DELAY_SECONDS = 10


def _is_list_url(url: str) -> bool:
    return canonical_list_url(url) == url


def _is_detail_url(url: str) -> bool:
    return km_code_from_detail_url(url) is not None


KINGSTONE_POLICY = FetchPolicy(
    site_host=SITE_HOST,
    is_list_url=_is_list_url,
    is_detail_url=_is_detail_url,
    list_rejected=_LIST_REJECTED,
    detail_rejected=_DETAIL_REJECTED,
    min_delay_seconds=MIN_PAGE_DELAY_SECONDS,
    max_delay_seconds=MAX_PAGE_DELAY_SECONDS,
    request_headers=MappingProxyType({"Accept-Language": _ACCEPT_LANGUAGE}),
    logger_name="kingstone.acquisition",
)


class CurlTransport(_engine.CurlTransport):
    """The shared curl transport, sending the Kingstone request headers unless others are given."""

    def __init__(
        self,
        *,
        session: Any | None = None,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        request_headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            session=session,
            max_response_bytes=max_response_bytes,
            request_headers=KINGSTONE_POLICY.request_headers if request_headers is None else request_headers,
        )


class KingstoneFetcher(_engine.PacedFetcher):
    """Paced, bounded HTTP for Kingstone pages: ``PacedFetcher`` with ``KINGSTONE_POLICY``.

    Sequential: one request at a time, one pacing clock per instance. Only the URL grammar in ``kingstone.urls`` is
    requested. Constructor arguments and defaults are those of ``PacedFetcher`` (``sample_delay`` defaults to a uniform
    3 to 10 second draw).
    """

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sample_delay: Callable[[], float] | None = None,
        budget_remaining: Callable[[], float] = unlimited_budget,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        super().__init__(
            KINGSTONE_POLICY,
            transport=transport,
            sleep=sleep,
            clock=clock,
            wall_clock=wall_clock,
            sample_delay=sample_delay,
            budget_remaining=budget_remaining,
            timeout=timeout,
            max_attempts=max_attempts,
            max_response_bytes=max_response_bytes,
        )
