"""Provider-neutral HTTP acquisition: URL guards, pacing, bounded retry, budget and response classification.

Two layers, so the policy can be tested with a fake transport:

- ``Transport`` (a port): one GET that returns a ``RawResponse`` or raises one of the transport exceptions.
  ``CurlTransport`` is the production adapter: curl_cffi with Chrome impersonation, no redirects, TLS verification on.
- ``PacedFetcher``: the engine. It accepts only the URLs a ``FetchPolicy`` accepts, paces every request, retries the
  transient failures and turns every outcome into either a page body or an ``AcquisitionError``.

A provider supplies a ``FetchPolicy`` (its site host, its list and detail URL predicates, its rejection messages, its
pacing range, its request headers and its logger name). The engine knows nothing else about the provider.

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

MAX_ATTEMPTS = 3
REQUEST_TIMEOUT_SECONDS = 30
MAX_BACKOFF_SECONDS = 60
MAX_RETRY_AFTER_SECONDS = 120
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
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

    ``request_headers`` are sent with every GET (none by default). Two bounds on the body. libcurl's
    ``MAXFILESIZE_LARGE`` is set on the session at construction to ``max_response_bytes`` (default ``MAX_RESPONSE_BYTES``);
    when libcurl aborts with ``FILESIZE_EXCEEDED`` (63) that becomes ``ResponseTooLarge``. The body is also streamed and
    counted against the per-call ``max_bytes``, so a response is never buffered past it, whatever libcurl does. Timeouts
    and connection failures map to the retryable transport exceptions. TLS failures are not retried: a certificate
    problem does not go away on a second request, so they propagate unchanged and the fetcher reports them as
    ``TRANSPORT``.
    """

    def __init__(
        self,
        *,
        session: Any | None = None,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        request_headers: Mapping[str, str] | None = None,
    ) -> None:
        # ``max_response_bytes`` sets the libcurl cap of the session this transport creates; an injected session keeps its own.
        self._session = session if session is not None else curl_requests.Session(impersonate="chrome", curl_options={CurlOpt.MAXFILESIZE_LARGE: max_response_bytes})
        self._request_headers = dict(request_headers or {})

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
                raise ResponseTooLarge("libcurl stopped the body at the configured size limit") from exc
            raise

    def _fetch(self, url: str, *, timeout: float, max_bytes: int) -> RawResponse:
        response = self._session.get(
            url,
            timeout=timeout,
            allow_redirects=False,
            stream=True,
            headers=dict(self._request_headers),
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


def unlimited_budget() -> float:
    return math.inf


@dataclass(frozen=True)
class FetchPolicy:
    """What a provider allows the engine to fetch, and how politely.

    - ``site_host``: the only host accepted (exact string match; https, no userinfo, no port).
    - ``is_list_url`` / ``is_detail_url``: the provider's URL grammar. A URL must pass the site check and then its
      method's predicate; otherwise ``ValueError`` with ``list_rejected`` / ``detail_rejected`` is raised before any request.
    - ``min_delay_seconds`` / ``max_delay_seconds``: the pacing sample range (uniform).
    - ``request_headers``: sent by ``CurlTransport`` with every request.
    - ``logger_name``: the logger the engine writes its request lines to.
    """

    site_host: str
    is_list_url: Callable[[str], bool]
    is_detail_url: Callable[[str], bool]
    list_rejected: str
    detail_rejected: str
    min_delay_seconds: float
    max_delay_seconds: float
    request_headers: Mapping[str, str]
    logger_name: str

    def __post_init__(self) -> None:
        if self.min_delay_seconds < 0 or self.max_delay_seconds < self.min_delay_seconds:
            raise ValueError("the pacing range needs 0 <= min_delay_seconds <= max_delay_seconds")


class PacedFetcher:
    """Paced, bounded HTTP for one provider's pages. Sequential: one request at a time, one pacing clock per instance.

    - Only the URLs the ``policy`` accepts are requested; anything else is ``ValueError`` before any request.
    - Each request (retries included) waits ``max(sample_delay() - seconds since the previous request ended, floor)``.
      The first request has no previous request, so its pacing term is the full sampled delay. The floor is 0 except
      on a retry. The default ``sample_delay`` samples uniformly from the policy's range.
    - Up to ``max_attempts`` requests (default ``MAX_ATTEMPTS``). Retried: timeouts, connection failures, and HTTP 429, 500, 502, 503, 504.
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
    - Counts for the run report (plan v12 §8): ``http_attempts`` is the number of requests actually sent (retries
      included; a request refused by the budget is not sent and not counted). ``http_failures`` counts the sent requests
      that did not give a usable 200 body: a transport error, a non-200 status (redirects and retried statuses too),
      an oversize body or a body that is not UTF-8.
    """

    def __init__(
        self,
        policy: FetchPolicy,
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
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._policy = policy
        self._log = logging.getLogger(policy.logger_name)
        self._transport = transport if transport is not None else CurlTransport(max_response_bytes=max_response_bytes, request_headers=policy.request_headers)
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._max_response_bytes = max_response_bytes
        self._sleep = sleep
        self._clock = clock
        self._wall_clock = wall_clock
        self._sample_delay = sample_delay if sample_delay is not None else _uniform_sampler(policy)
        self._budget_remaining = budget_remaining
        self._last_finished: float | None = None
        self._sent = 0
        self._failed = 0

    @property
    def http_attempts(self) -> int:
        """Requests actually sent by this fetcher (retries included)."""
        return self._sent

    @property
    def http_failures(self) -> int:
        """Sent requests that did not give a usable 200 body."""
        return self._failed

    def fetch_list_page(self, url: str) -> str:
        _require_url(url, self._policy, self._policy.is_list_url, self._policy.list_rejected)
        return self._get(url)

    def fetch_detail_page(self, url: str) -> str:
        _require_url(url, self._policy, self._policy.is_detail_url, self._policy.detail_rejected)
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
                self._failed += 1
                reason = type(exc).__name__
                self._log.info("GET %s error=%s attempt=%d", url, reason, attempt)
                if attempt == self._max_attempts:
                    raise AcquisitionError(AcquisitionFailure.TRANSPORT, f"GET {url} failed after {attempt} attempts: {reason}", attempt) from exc
                self._log.warning("retrying GET %s attempt=%d after %s", url, attempt, reason)
                retry_floor = backoff_seconds(attempt + 1)
                continue
            except ResponseTooLarge as exc:
                self._failed += 1
                self._log.info("GET %s error=ResponseTooLarge attempt=%d", url, attempt)
                raise _oversize(url, attempt, self._max_response_bytes) from exc
            except Exception as exc:
                self._failed += 1
                self._log.info("GET %s error=%s attempt=%d", url, type(exc).__name__, attempt)
                raise AcquisitionError(AcquisitionFailure.TRANSPORT, f"GET {url} failed: {type(exc).__name__}", attempt) from exc

            status = response.status
            self._log.info("GET %s status=%d bytes=%d attempt=%d", url, status, len(response.body), attempt)
            if len(response.body) > self._max_response_bytes:
                self._failed += 1
                raise _oversize(url, attempt, self._max_response_bytes, status)
            if status == 200:
                try:
                    return _decode(url, response.body, attempt)
                except AcquisitionError:
                    self._failed += 1
                    raise
            self._failed += 1
            if 300 <= status < 400:
                location = _location_path(response.headers)
                raise AcquisitionError(
                    AcquisitionFailure.REDIRECT,
                    f"GET {url} returned HTTP {status} (Location path: {location}); redirects are not followed",
                    attempt,
                    status,
                )
            if status in RETRYABLE_STATUSES and attempt < self._max_attempts:
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
                self._log.warning("retrying GET %s attempt=%d after status=%d", url, attempt, status)
                continue
            if status in RETRYABLE_STATUSES:
                raise AcquisitionError(AcquisitionFailure.HTTP_STATUS, f"GET {url} returned HTTP {status} after {attempt} attempts", attempt, status)
            raise AcquisitionError(AcquisitionFailure.HTTP_STATUS, f"GET {url} returned HTTP {status}", attempt, status)

    def _send(self, url: str) -> RawResponse:
        self._sent += 1
        try:
            return self._transport.get(url, timeout=self._timeout, max_bytes=self._max_response_bytes)
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


def _uniform_sampler(policy: FetchPolicy) -> Callable[[], float]:
    def sample() -> float:
        return random.uniform(policy.min_delay_seconds, policy.max_delay_seconds)

    return sample


def _require_url(url: object, policy: FetchPolicy, accepts: Callable[[str], bool], message: str) -> None:
    _require_site_origin(url, policy.site_host, message)
    if not accepts(url):
        raise ValueError(message)


def _require_site_origin(url: object, site_host: str, message: str) -> None:
    """HTTPS, host exactly ``site_host``, no userinfo, no port. Non-strings are rejected.

    The host is compared as an exact string, so an IP literal (which can never equal ``site_host``) is rejected too.
    """
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
        port = parts.port if parts is not None else None
    except ValueError as exc:
        raise ValueError(message) from exc
    if parts is None:
        raise ValueError(message)
    host = parts.hostname
    if parts.scheme != "https" or parts.username is not None or parts.password is not None or port is not None or host != site_host:
        raise ValueError(message)


def _oversize(url: str, attempt: int, limit: int, status: int | None = None) -> AcquisitionError:
    return AcquisitionError(AcquisitionFailure.OVERSIZE, f"GET {url} response exceeds {limit} bytes", attempt, status)


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
