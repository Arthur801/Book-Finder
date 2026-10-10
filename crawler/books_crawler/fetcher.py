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
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

import requests
from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Desktop Chrome UA for the Playwright browser. The major version matches the Chromium that the
# pinned playwright release installs (see crawler/README.md); update both together.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)
BROWSER_LOCALE = "zh-TW"

DEFAULT_NAVIGATION_TIMEOUT_MS = 30_000
DEFAULT_PAGE_DELAY_SECONDS = 1.0

# Cloudflare sets this response header on challenge responses (value "challenge").
CHALLENGE_HEADER = "cf-mitigated"
CHALLENGE_TITLE = "歡迎光臨博客來"
# Present on the ranking page and on product pages; absent from the challenge interstitial.
PAGE_CONTENT_SELECTOR = ".main_column"


class FetchError(Exception):
    """A page could not be retrieved (network error, timeout, non-200 response, or a challenge)."""


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

    Failure rules (all raise ``FetchError``): navigation error or timeout, a
    ``cf-mitigated: challenge`` header, a status other than 200, or a challenge interstitial
    (see ``_is_challenge_page``). No retries here; retry and skip belong to the run (crawler.md §6).

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
                context.close()
        finally:
            try:
                if browser is not None:
                    browser.close()
            finally:
                if playwright is not None:
                    playwright.stop()

    def _wait_for_delay(self) -> None:
        if self._last_finished is None or self._delay_seconds <= 0:
            return
        remaining = self._delay_seconds - (self._clock() - self._last_finished)
        if remaining > 0:
            self._sleep(remaining)

    def _fetch(self, url: str) -> str:
        context = self._ensure_context()
        page = context.new_page()
        try:
            try:
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
                raise FetchError(f"GET {url} failed: {type(exc).__name__}") from exc
        finally:
            page.close()

    def _ensure_context(self) -> BrowserContext:
        if self._context is None:
            self._start()
        assert self._context is not None
        return self._context

    def _start(self) -> None:
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context(user_agent=BROWSER_USER_AGENT, locale=BROWSER_LOCALE)
        except PlaywrightError as exc:
            self.close()
            raise BrowserUnavailableError(
                "Chromium could not be launched for Playwright; install it with "
                "'python -m playwright install chromium' "
                f"(original error: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__})"
            ) from exc


def _is_challenge_page(title: str, has_page_content: bool) -> bool:
    """A challenge interstitial has the challenge title and none of the site's page content.

    The title alone is not enough: a real page that happens to carry the title is still served.
    """
    return CHALLENGE_TITLE in title and not has_page_content
