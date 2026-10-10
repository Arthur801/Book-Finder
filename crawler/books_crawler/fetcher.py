"""Page retrieval seam.

``Fetcher`` is the only thing the orchestration uses to obtain HTML.

Two implementations exist:

- ``PlaywrightFetcher`` (production default, ADR-006): headless Chromium through Playwright.
  books.com.tw answers plain HTTP clients with a Cloudflare challenge, so a real browser is used.
- ``HttpFetcher``: requests-based, kept for debugging (selected with ``CRAWLER_FETCHER=http``).

Tests inject fixture-backed fetchers into the run flow; only the browser tests start Chromium,
and only against local pages.

Deliberately absent: stealth / anti-detection patches, CAPTCHA solving and proxy rotation
(AGENTS.md §1.3, ADR-006). A Cloudflare challenge is reported as ``FetchError``, never bypassed.

Error contract for the run flow (crawler.md §6, §15):

- ``FetchError``: this page could not be retrieved. Retried and possibly skipped by the run.
- ``BrowserUnavailableError``: the environment cannot run a browser at all. Never retried and never
  skipped per book; it fails the whole run. It is deliberately not a ``FetchError``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any, Protocol

import requests
from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from books_crawler.redact import redact

log = logging.getLogger("books_crawler.fetcher")


class FetcherKind(StrEnum):
    """Values of the ``CRAWLER_FETCHER`` setting."""

    BROWSER = "browser"
    HTTP = "http"


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Normal desktop Chrome UA and zh-TW locale for the Playwright browser. Approved by the user on
# 2026-10-11 (ADR-006). The major version matches the Chromium that the pinned playwright release
# installs (see crawler/README.md); update both together.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)
BROWSER_LOCALE = "zh-TW"

DEFAULT_NAVIGATION_TIMEOUT_MS = 30_000
MAX_NAVIGATION_TIMEOUT_MS = 300_000
DEFAULT_PAGE_DELAY_SECONDS = 1.0

# Cloudflare sets this response header on challenge responses (value "challenge").
CHALLENGE_HEADER = "cf-mitigated"
CHALLENGE_TITLE = "歡迎光臨博客來"
# Present on the ranking page and on product pages; absent from the challenge interstitial.
PAGE_CONTENT_SELECTOR = ".main_column"


class FetchError(Exception):
    """A page could not be retrieved (network error, timeout, non-200 response, browser crash, or a challenge)."""


class BrowserUnavailableError(RuntimeError):
    """Chromium could not be started for Playwright (usually: not installed, or missing libraries)."""


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

    def close(self) -> None:
        self._session.close()


class PlaywrightFetcher:
    """Fetches pages with headless Chromium through Playwright's sync API (ADR-006).

    Lifecycle: one Playwright driver, one browser and one browser context serve every ``get`` of
    this instance. Chromium is started lazily on the first ``get``, so constructing the fetcher
    starts nothing. ``close()`` (also run when leaving a ``with`` block) closes the context, the
    browser and the driver. It is idempotent and safe to call without any prior ``get``.

    Each ``get`` opens a new page in the shared context and closes it again afterwards.

    Wait strategy: ``wait_until="load"``. The method returns only after the load event, so the
    page's scripts have run and images/stylesheets are done (the spec says "頁面載入完成後的
    HTML"). ``domcontentloaded`` would return earlier, before late-running page scripts such as
    a challenge script have finished.

    Failure rules:

    - ``FetchError``: navigation error or timeout, a browser crash or closed page during any step
      (every Playwright error is wrapped), a ``cf-mitigated: challenge`` header, a status other than
      200, or a challenge interstitial (see ``_is_challenge_page``). No retries here; retry and skip
      belong to the run (crawler.md §6).
    - ``BrowserUnavailableError``: Chromium or the Playwright driver cannot be started. Not retried.

    Pacing: requests are sequential. Before each ``get`` after the first, the fetcher sleeps until
    ``delay_seconds`` have elapsed since the previous ``get`` returned.
    """

    def __init__(
        self,
        *,
        navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
        delay_seconds: float = DEFAULT_PAGE_DELAY_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._navigation_timeout_ms = navigation_timeout_ms
        self._delay_seconds = delay_seconds
        self._sleep = sleep
        self._clock = clock
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._last_finished: float | None = None

    @property
    def browser(self) -> Browser | None:
        """The shared browser, or ``None`` before the first ``get`` and after ``close()``."""
        return self._browser

    @property
    def navigation_timeout_ms(self) -> int:
        return self._navigation_timeout_ms

    def __enter__(self) -> PlaywrightFetcher:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def get(self, url: str) -> str:
        self._wait_for_delay()
        try:
            return self._fetch(url)
        finally:
            self._last_finished = self._clock()

    def close(self) -> None:
        context, browser, playwright = self._context, self._browser, self._playwright
        self._context = None
        self._browser = None
        self._playwright = None
        try:
            if context is not None:
                _close_quietly(context.close, "browser context")
        finally:
            try:
                if browser is not None:
                    _close_quietly(browser.close, "browser")
            finally:
                if playwright is not None:
                    _close_quietly(playwright.stop, "Playwright driver")

    def _wait_for_delay(self) -> None:
        if self._last_finished is None or self._delay_seconds <= 0:
            return
        remaining = self._delay_seconds - (self._clock() - self._last_finished)
        if remaining > 0:
            self._sleep(remaining)

    def _fetch(self, url: str) -> str:
        context = self._ensure_context()
        page = None
        try:
            try:
                page = context.new_page()
                response = page.goto(url, wait_until="load", timeout=self._navigation_timeout_ms)
                if response is None:
                    raise FetchError(f"GET {url} returned no response")
                if response.headers.get(CHALLENGE_HEADER, "").strip().lower() == "challenge":
                    raise FetchError(f"GET {url} is blocked by a Cloudflare challenge ({CHALLENGE_HEADER})")
                if response.status != 200:
                    raise FetchError(f"GET {url} returned HTTP {response.status}")
                html = page.content()
                if _is_challenge_page(page.title(), page.query_selector(PAGE_CONTENT_SELECTOR) is not None):
                    raise FetchError(f"GET {url} is still a Cloudflare challenge page")
                return html
            except PlaywrightError as exc:
                # Covers timeouts, net errors, and crashes (TargetClosedError is a subclass).
                raise FetchError(f"GET {url} failed: {type(exc).__name__}") from exc
        finally:
            if page is not None:
                _close_quietly(page.close, "page")

    def _ensure_context(self) -> BrowserContext:
        if self._context is None:
            self._start()
        assert self._context is not None
        return self._context

    def _start(self) -> None:
        try:
            playwright = sync_playwright().start()
        except Exception as exc:  # the driver itself could not start
            raise _browser_unavailable(exc) from exc
        self._playwright = playwright
        try:
            self._browser = playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context(user_agent=BROWSER_USER_AGENT, locale=BROWSER_LOCALE)
        except Exception as exc:  # Chromium missing, missing libraries, or the launch crashed
            self.close()
            raise _browser_unavailable(exc) from exc


def _browser_unavailable(exc: Exception) -> BrowserUnavailableError:
    first_line = redact(str(exc).splitlines()[0]) if str(exc).strip() else type(exc).__name__
    return BrowserUnavailableError(
        "Chromium could not be launched for Playwright; install it with "
        f"'python -m playwright install chromium' (original error: {first_line})"
    )


def _close_quietly(action: Callable[[], None], what: str) -> None:
    """Close one browser resource. A failure here is logged and never replaces the original error."""
    try:
        action()
    except Exception as exc:
        log.warning("closing the %s failed: %s: %s", what, type(exc).__name__, redact(str(exc)))


def _is_challenge_page(title: str, has_page_content: bool) -> bool:
    """A challenge interstitial has the challenge title and none of the site's page content.

    The title alone is not enough: a real page that happens to carry the title is still served.
    """
    return CHALLENGE_TITLE in title and not has_page_content
