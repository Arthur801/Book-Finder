"""Eslite (誠品) HTTP acquisition: the Eslite ``FetchPolicy`` over the provider-neutral engine.

The engine (the ``Transport`` port, ``CurlTransport``, retry, pacing, budget, Retry-After, decode and redirect rules, and
the error taxonomy) lives in ``catalog_core.http_acquisition``. This module holds only what is Eslite-specific:

- the requests go to the athena JSON API, not to the web pages: a canonical www list page URL is mapped to its list API
  URL, and a www product URL to its detail API URL (``eslite.urls``); the www URLs are never requested;
- the URL predicates (only the exact list and detail API shapes are requested);
- the page delay, 3 to 10 seconds, uniform (user decision, 2026-11-11);
- the ``Accept: application/json`` and ``Accept-Language: zh-TW,zh;q=0.9`` request headers;
- the ``eslite.acquisition`` logger.

``EsliteFetcher`` is a ``PacedFetcher`` with ``ESLITE_POLICY``. Its constructor and defaults are those of the engine
(``sample_delay`` defaults to a uniform 3 to 10 second draw). A URL outside the accepted web grammar is a ``ValueError``
before any request. A detail 404 is ``AcquisitionError(HTTP_STATUS, status=404)`` and keeps no body (the engine's rule).

Deliberately absent: challenge or queue detection, cookie persistence, a browser and diagnostic files.
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
from eslite.urls import (
    API_HOST,
    canonical_list_url,
    detail_api_url,
    guid_from_detail_api_url,
    guid_from_product_url,
    is_list_api_url,
    list_api_url,
)

__all__ = [
    "BACKOFF_BASE_SECONDS",
    "ESLITE_POLICY",
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
    "EsliteFetcher",
    "FetchPolicy",
    "RawResponse",
    "ResponseTooLarge",
    "Transport",
    "TransportConnectionError",
    "TransportTimeout",
    "backoff_seconds",
    "curl_requests",
]

log = logging.getLogger("eslite.acquisition")

curl_requests = _engine.curl_requests

_ACCEPT = "application/json"
_ACCEPT_LANGUAGE = "zh-TW,zh;q=0.9"
_LIST_REJECTED = "not an accepted Eslite category list page URL"
_DETAIL_REJECTED = "not an accepted Eslite product page URL"

MIN_PAGE_DELAY_SECONDS = 3
MAX_PAGE_DELAY_SECONDS = 10


def _is_list_url(url: str) -> bool:
    return is_list_api_url(url)


def _is_detail_url(url: str) -> bool:
    return guid_from_detail_api_url(url) is not None


ESLITE_POLICY = FetchPolicy(
    site_host=API_HOST,
    is_list_url=_is_list_url,
    is_detail_url=_is_detail_url,
    list_rejected=_LIST_REJECTED,
    detail_rejected=_DETAIL_REJECTED,
    min_delay_seconds=MIN_PAGE_DELAY_SECONDS,
    max_delay_seconds=MAX_PAGE_DELAY_SECONDS,
    request_headers=MappingProxyType({"Accept": _ACCEPT, "Accept-Language": _ACCEPT_LANGUAGE}),
    logger_name="eslite.acquisition",
)


def _list_api_for(url: object) -> str:
    """The list API URL of a canonical www list page URL. Anything else is refused before any request."""
    if not isinstance(url, str) or canonical_list_url(url) != url:
        raise ValueError(_LIST_REJECTED)
    return list_api_url(url)


def _detail_api_for(url: object) -> str:
    """The detail API URL of a www product page URL. Anything else is refused before any request."""
    guid = guid_from_product_url(url) if isinstance(url, str) else None
    if guid is None:
        raise ValueError(_DETAIL_REJECTED)
    return detail_api_url(guid)


class EsliteFetcher(_engine.PacedFetcher):
    """Paced, bounded HTTP for Eslite pages: ``PacedFetcher`` with ``ESLITE_POLICY``, mapping the www URLs to the API.

    ``fetch_list_page`` takes the canonical list page URL (``https://www.eslite.com/category/3/<id>[?page=<n>]``) and
    requests its list API URL. ``fetch_detail_page`` takes the card's product URL (``https://www.eslite.com/product/<guid>``)
    and requests its detail API URL. Sequential: one request at a time, one pacing clock per instance.
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
            ESLITE_POLICY,
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

    def fetch_list_page(self, url: str) -> str:
        return super().fetch_list_page(_list_api_for(url))

    def fetch_detail_page(self, url: str) -> str:
        return super().fetch_detail_page(_detail_api_for(url))


class CurlTransport(_engine.CurlTransport):
    """The shared curl transport, sending the Eslite request headers unless others are given."""

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
            request_headers=ESLITE_POLICY.request_headers if request_headers is None else request_headers,
        )
