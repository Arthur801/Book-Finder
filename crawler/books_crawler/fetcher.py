"""Page retrieval seam.

``Fetcher`` is the only thing the orchestration uses to obtain HTML. Production access to
books.com.tw is undecided (a Cloudflare challenge was observed on plain HTTP requests), so
``HttpFetcher`` is a simple, untuned implementation. Tests inject a fixture-backed fetcher.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

import requests

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class FetchError(Exception):
    """A page could not be retrieved (network error, timeout, or non-200 response)."""


class Fetcher(Protocol):
    def get(self, url: str) -> str:
        """Return the page body as text, or raise ``FetchError``."""
        ...


class HttpFetcher:
    """requests-based fetcher with a browser User-Agent, a timeout and a polite delay.

    The delay is applied before every request except the first one of this instance.
    """

    def __init__(
        self,
        *,
        session: Any | None = None,
        timeout: tuple[float, float] = (5.0, 20.0),
        delay_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session = session if session is not None else requests.Session()
        self._session.headers.update(
            {"User-Agent": DEFAULT_USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9"}
        )
        self._timeout = timeout
        self._delay_seconds = delay_seconds
        self._sleep = sleep
        self._requested_before = False

    def get(self, url: str) -> str:
        if self._requested_before and self._delay_seconds > 0:
            self._sleep(self._delay_seconds)
        self._requested_before = True
        try:
            response = self._session.get(url, timeout=self._timeout)
        except requests.RequestException as exc:
            raise FetchError(f"GET {url} failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise FetchError(f"GET {url} returned HTTP {response.status_code}")
        # books.com.tw pages declare UTF-8; do not trust the header-less default.
        response.encoding = "utf-8"
        return response.text
