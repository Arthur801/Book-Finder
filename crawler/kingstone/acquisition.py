"""Kingstone (金石堂) HTTP acquisition: URL guards, pacing, bounded retry, budget and response classification.

Two layers, so the policy can be tested with a fake transport:

- ``Transport`` (a port): one GET that returns a ``RawResponse`` or raises one of the transport exceptions.
  ``CurlTransport`` is the production adapter: curl_cffi with Chrome impersonation, no redirects, TLS verification on.
- ``KingstoneFetcher``: the policy. It accepts only the URLs in ``kingstone.urls``, paces every request, retries the
  transient failures and turns every outcome into either a page body or an ``AcquisitionError``.

Waiting rules. Before each request (retries included) the wait is the larger of two bounds, not their sum:

- pacing: the sampled delay, counted from the end of the previous request;
- retry floor: the backoff, or Retry-After when the server sent one, counted from the moment the failed response
  (or error) was received. It is not reduced by any time that passed afterwards.

The budget is checked before every request, including one that needs no wait. A remaining budget of zero or less, or a
wait larger than the remaining budget, fails with ``BUDGET_EXHAUSTED`` before anything sleeps or is sent.

Deliberately absent: challenge or CAPTCHA detection (a 200 page is returned and the parser fails closed), cookie
persistence, a browser and diagnostic files.
"""

from __future__ import annotations

import email.utils
import logging
import math
import random
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlsplit

from curl_cffi import requests as curl_requests
from curl_cffi.const import CurlECode, CurlOpt
from curl_cffi.requests import exceptions as curl_exceptions

from kingstone.urls import SITE_HOST, canonical_list_url, km_code_from_detail_url

log = logging.getLogger("kingstone.acquisition")

_ACCEPT_LANGUAGE = "zh-TW,zh;q=0.9"
_LIST_REJECTED = "not an accepted Kingstone category list page URL"
_DETAIL_REJECTED = "not an accepted Kingstone detail page URL"

MAX_ATTEMPTS = 3
REQUEST_TIMEOUT_SECONDS = 30
MAX_BACKOFF_SECONDS = 60
MAX_RETRY_AFTER_SECONDS = 120
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
_LIBCURL_SIZE_CAP = {CurlOpt.MAXFILESIZE_LARGE: MAX_RESPONSE_BYTES}
MIN_PAGE_DELAY_SECONDS = 3
MAX_PAGE_DELAY_SECONDS = 10
BACKOFF_BASE_SECONDS = 5
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRY_AFTER_STATUSES = frozenset({429, 503})


class TransportTimeout(Exception):
    """The request timed out. Retryable."""


class TransportConnectionError(Exception):
    """The connection failed or was reset. Retryable."""


class ResponseTooLarge(Exception):
    """The response body is larger than ``max_bytes``. Not retryable."""


class AcquisitionFailure(StrEnum):
    """Why a page could not be acquired. Every failure of this layer carries one of these."""

    REDIRECT = "REDIRECT"
    HTTP_STATUS = "HTTP_STATUS"
    OVERSIZE = "OVERSIZE"
    TRANSPORT = "TRANSPORT"
    DECODE_ERROR = "DECODE_ERROR"
    RETRY_AFTER_TOO_LONG = "RETRY_AFTER_TOO_LONG"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


class AcquisitionError(Exception):
    """A page could not be acquired. ``attempts`` counts the requests actually sent; ``status`` is the last HTTP status."""

    def __init__(self, kind: AcquisitionFailure, message: str, attempts: int, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.attempts = attempts
        self.status = status


@dataclass(frozen=True)
class RawResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    """One GET. ``max_bytes`` bounds the body; exceeding it raises ``ResponseTooLarge``."""

    def get(self, url: str, *, timeout: float, max_bytes: int) -> RawResponse: ...

    def close(self) -> None: ...


class CurlTransport:
    """The production transport: curl_cffi Chrome impersonation, redirects not followed, TLS verification on.

    Two bounds on the body. libcurl's ``MAXFILESIZE_LARGE`` is set on the session at construction to
    ``MAX_RESPONSE_BYTES``; when libcurl aborts with ``FILESIZE_EXCEEDED`` (63) that becomes ``ResponseTooLarge``. The
    body is also streamed and counted against the per-call ``max_bytes``, so a response is never buffered past it,
    whatever libcurl does. Timeouts and connection failures map to the retryable transport exceptions. TLS failures are
    not retried: a certificate problem does not go away on a second request, so they propagate unchanged and the
    fetcher reports them as ``TRANSPORT``.
    """

    def __init__(self, *, session: Any | None = None) -> None:
        self._session = session if session is not None else curl_requests.Session(impersonate="chrome", curl_options=_LIBCURL_SIZE_CAP)

    def get(self, url: str, *, timeout: float, max_bytes: int) -> RawResponse:
        try:
            return self._fetch(url, timeout=timeout, max_bytes=max_bytes)
        except curl_exceptions.Timeout as exc:
            raise TransportTimeout(type(exc).__name__) from exc
        except curl_exceptions.SSLError:
            raise
        except curl_exceptions.ConnectionError as exc:
            raise TransportConnectionError(type(exc).__name__) from exc
        except curl_exceptions.RequestException as exc:
            if exc.code == CurlECode.FILESIZE_EXCEEDED:
                raise ResponseTooLarge(f"libcurl stopped the body at {MAX_RESPONSE_BYTES} bytes") from exc
            raise

    def _fetch(self, url: str, *, timeout: float, max_bytes: int) -> RawResponse:
        response = self._session.get(
            url,
            timeout=timeout,
            allow_redirects=False,
            stream=True,
            headers={"Accept-Language": _ACCEPT_LANGUAGE},
        )
        try:
            declared = _declared_length(response.headers)
            if declared is not None and declared > max_bytes:
                raise ResponseTooLarge(f"Content-Length {declared} exceeds {max_bytes}")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content():
                total += len(chunk)
                if total > max_bytes:
                    raise ResponseTooLarge(f"body exceeds {max_bytes} bytes")
                chunks.append(chunk)
            return RawResponse(int(response.status_code), dict(response.headers), b"".join(chunks))
        finally:
            response.close()

    def close(self) -> None:
        self._session.close()


def backoff_seconds(attempt: int) -> float:
    """The backoff before ``attempt`` (2 or 3): 5 seconds, then 10, doubling and capped at ``MAX_BACKOFF_SECONDS``."""
    if attempt < 2:
        raise ValueError("backoff applies to retries only (attempt >= 2)")
    return float(min(MAX_BACKOFF_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (attempt - 2)))


def _sample_delay() -> float:
    return random.uniform(MIN_PAGE_DELAY_SECONDS, MAX_PAGE_DELAY_SECONDS)


def _unlimited_budget() -> float:
    return math.inf


class KingstoneFetcher:
    """Paced, bounded HTTP for Kingstone pages. Sequential: one request at a time, one pacing clock per instance.

    - Only the URL grammar in ``kingstone.urls`` is requested; anything else is ``ValueError`` before any request.
    - Each request (retries included) waits ``max(sample_delay() - seconds since the previous request ended, floor)``.
      The first request has no previous request, so its pacing term is the full sampled delay. The floor is 0 except
      on a retry.
    - Up to ``MAX_ATTEMPTS`` requests. Retried: timeouts, connection failures, and HTTP 429, 500, 502, 503, 504.
      The floor for retry N is ``backoff_seconds(N)``; it is counted from the moment the failed response or error
      was received. A 429 or 503 Retry-After (seconds or HTTP-date, read against ``wall_clock``) raises the floor to
      ``max(backoff, Retry-After)``, counted from the same moment. Retry-After above ``MAX_RETRY_AFTER_SECONDS`` fails
      at once. A Retry-After on the last attempt is not read: there is nothing to delay, so the request fails as plain
      retry exhaustion.
    - The budget is checked before every request. ``budget_remaining()`` at or below 0, or a wait above it, fails with
      ``BUDGET_EXHAUSTED`` before sleeping or sending.
    - Redirects are never followed: a 3xx is ``REDIRECT``. Other 4xx are ``HTTP_STATUS`` and are not retried.
    - A 200 body must be strict UTF-8, otherwise ``DECODE_ERROR``. Page content (challenges, CAPTCHA, restricted
      pages) is not judged here; the parser fails closed on it.
    """

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sample_delay: Callable[[], float] = _sample_delay,
        budget_remaining: Callable[[], float] = _unlimited_budget,
    ) -> None:
        self._transport = transport if transport is not None else CurlTransport()
        self._sleep = sleep
        self._clock = clock
        self._wall_clock = wall_clock
        self._sample_delay = sample_delay
        self._budget_remaining = budget_remaining
        self._last_finished: float | None = None

    def fetch_list_page(self, url: str) -> str:
        _require_list_url(url)
        return self._get(url)

    def fetch_detail_page(self, url: str) -> str:
        _require_detail_url(url)
        return self._get(url)

    def close(self) -> None:
        self._transport.close()

    def _get(self, url: str) -> str:
        retry_floor = 0.0
        attempt = 0
        while True:
            attempt += 1
            self._wait_before_request(retry_floor, url=url, sent=attempt - 1)
            try:
                response = self._send(url)
            except (TransportTimeout, TransportConnectionError) as exc:
                reason = type(exc).__name__
                log.info("GET %s error=%s attempt=%d", url, reason, attempt)
                if attempt == MAX_ATTEMPTS:
                    raise AcquisitionError(AcquisitionFailure.TRANSPORT, f"GET {url} failed after {attempt} attempts: {reason}", attempt) from exc
                log.warning("retrying GET %s attempt=%d after %s", url, attempt, reason)
                retry_floor = backoff_seconds(attempt + 1)
                continue
            except ResponseTooLarge as exc:
                log.info("GET %s error=ResponseTooLarge attempt=%d", url, attempt)
                raise _oversize(url, attempt) from exc
            except Exception as exc:
                log.info("GET %s error=%s attempt=%d", url, type(exc).__name__, attempt)
                raise AcquisitionError(AcquisitionFailure.TRANSPORT, f"GET {url} failed: {type(exc).__name__}", attempt) from exc

            status = response.status
            log.info("GET %s status=%d bytes=%d attempt=%d", url, status, len(response.body), attempt)
            if len(response.body) > MAX_RESPONSE_BYTES:
                raise _oversize(url, attempt, status)
            if status == 200:
                return _decode(url, response.body, attempt)
            if 300 <= status < 400:
                location = _location_path(response.headers)
                raise AcquisitionError(
                    AcquisitionFailure.REDIRECT,
                    f"GET {url} returned HTTP {status} (Location path: {location}); redirects are not followed",
                    attempt,
                    status,
                )
            if status in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS:
                retry_floor = backoff_seconds(attempt + 1)
                if status in RETRY_AFTER_STATUSES:
                    retry_after = self._retry_after_seconds(response.headers)
                    if retry_after is not None:
                        if retry_after > MAX_RETRY_AFTER_SECONDS:
                            raise AcquisitionError(
                                AcquisitionFailure.RETRY_AFTER_TOO_LONG,
                                f"GET {url} returned HTTP {status} with Retry-After above {MAX_RETRY_AFTER_SECONDS} seconds",
                                attempt,
                                status,
                            )
                        retry_floor = max(retry_floor, retry_after)
                log.warning("retrying GET %s attempt=%d after status=%d", url, attempt, status)
                continue
            if status in RETRYABLE_STATUSES:
                raise AcquisitionError(AcquisitionFailure.HTTP_STATUS, f"GET {url} returned HTTP {status} after {attempt} attempts", attempt, status)
            raise AcquisitionError(AcquisitionFailure.HTTP_STATUS, f"GET {url} returned HTTP {status}", attempt, status)

    def _send(self, url: str) -> RawResponse:
        try:
            return self._transport.get(url, timeout=REQUEST_TIMEOUT_SECONDS, max_bytes=MAX_RESPONSE_BYTES)
        finally:
            self._last_finished = self._clock()

    def _wait_before_request(self, floor: float, *, url: str, sent: int) -> None:
        elapsed = 0.0 if self._last_finished is None else self._clock() - self._last_finished
        wait = max(self._sample_delay() - elapsed, floor)
        remaining = self._budget_remaining()
        if remaining <= 0 or wait > remaining:
            raise AcquisitionError(AcquisitionFailure.BUDGET_EXHAUSTED, f"GET {url} needs a {wait:.1f}s wait, more than the remaining budget", sent)
        if wait <= 0:
            return
        self._sleep(wait)

    def _retry_after_seconds(self, headers: Mapping[str, str]) -> float | None:
        """Retry-After as seconds from now; None when absent or unparseable (then only the backoff applies)."""
        raw = _header(headers, "retry-after")
        if raw is None:
            return None
        value = raw.strip()
        if re.fullmatch(r"[0-9]+", value):
            return float(value)
        try:
            when = email.utils.parsedate_to_datetime(value)
        except TypeError, ValueError, IndexError:
            return None
        if when.tzinfo is None:
            return None
        return max(0.0, when.timestamp() - self._wall_clock())


def _require_list_url(url: str) -> None:
    _require_site_origin(url, _LIST_REJECTED)
    if canonical_list_url(url) != url:
        raise ValueError(_LIST_REJECTED)


def _require_detail_url(url: str) -> None:
    _require_site_origin(url, _DETAIL_REJECTED)
    if km_code_from_detail_url(url) is None:
        raise ValueError(_DETAIL_REJECTED)


def _require_site_origin(url: object, message: str) -> None:
    """HTTPS, host exactly ``SITE_HOST``, no userinfo, no port. Non-strings are rejected.

    The host is compared as an exact string, so an IP literal (which can never equal ``SITE_HOST``) is rejected too.
    """
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
        port = parts.port if parts is not None else None
    except ValueError as exc:
        raise ValueError(message) from exc
    if parts is None:
        raise ValueError(message)
    host = parts.hostname
    if parts.scheme != "https" or parts.username is not None or parts.password is not None or port is not None or host != SITE_HOST:
        raise ValueError(message)


def _oversize(url: str, attempt: int, status: int | None = None) -> AcquisitionError:
    return AcquisitionError(AcquisitionFailure.OVERSIZE, f"GET {url} response exceeds {MAX_RESPONSE_BYTES} bytes", attempt, status)


def _decode(url: str, body: bytes, attempt: int) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AcquisitionError(AcquisitionFailure.DECODE_ERROR, f"GET {url} returned a body that is not valid UTF-8", attempt, 200) from exc


def _location_path(headers: Mapping[str, str]) -> str:
    location = _header(headers, "location")
    if not location:
        return "none"
    try:
        return urlsplit(location).path or "/"
    except ValueError:
        return "unparseable"


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _declared_length(headers: Mapping[str, str]) -> int | None:
    raw = _header(headers, "content-length")
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None
