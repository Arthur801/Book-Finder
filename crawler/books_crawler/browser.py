"""Optional headless-browser fetcher for diagnostics (crawler.md §15.1).

Imported only when ``CRAWLER_FETCHER=browser`` or by ``inspect_page``, so the production curl path
does not need Playwright. It shares pacing, page classification and failure diagnostics with the
curl fetcher (``fetcher.py``).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from books_crawler.fetcher import (
    DEFAULT_DIAGNOSTIC_DIR,
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    BrowserUnavailableError,
    FetchError,
    RequestPacer,
    classify_page,
    page_error,
    save_failure_diagnostics,
)
from books_crawler.redact import redact

log = logging.getLogger("books_crawler.browser")

# Normal desktop Chrome UA and zh-TW locale for the Playwright browser. Approved by the user on
# 2026-10-11 (crawler.md §15.1). The major version matches the Chromium that the pinned playwright release
# installs (see crawler/README.md); update both together.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)
BROWSER_LOCALE = "zh-TW"

# What a launch hands over: the Playwright driver, the browser and the one shared context.
BrowserSession = tuple[Playwright, Browser, BrowserContext]


def launch_chromium() -> BrowserSession:
    """Start the Playwright driver, headless Chromium and one browser context.

    If anything after the driver fails, what was started is closed again before the error escapes.
    """
    playwright = sync_playwright().start()
    browser: Browser | None = None
    try:
        browser = playwright.chromium.launch(headless=True)
        return playwright, browser, browser.new_context(user_agent=BROWSER_USER_AGENT, locale=BROWSER_LOCALE)
    except Exception:
        if browser is not None:
            _close_quietly(browser.close, "browser")
        _close_quietly(playwright.stop, "Playwright driver")
        raise


class PlaywrightFetcher:
    """Fetches pages with headless Chromium through Playwright's sync API.

    Lifecycle: one Playwright driver, one browser and one browser context serve every ``get`` of
    this instance. Chromium is started lazily on the first ``get`` through ``launch``, so
    constructing the fetcher starts nothing. ``close()`` (also run when leaving a ``with`` block)
    closes the context, the browser and the driver. It is idempotent and safe to call without any
    prior ``get``. Tests pass their own ``launch`` that hands over a fake context.

    Each ``get`` opens a new page in the shared context and closes it again afterwards.

    Wait strategy: ``wait_until="load"``. The method returns only after the load event, so the
    page's scripts have run and images/stylesheets are done (the spec says "頁面載入完成後的
    HTML"). ``domcontentloaded`` would return earlier, before late-running page scripts such as
    a challenge script have finished.

    Failure rules:

    - ``FetchError``: navigation error or timeout, a browser crash or closed page during any step
      (every Playwright error is wrapped), or a page that ``classify_page`` rejects. A rejected
      page is saved first (HTML, JSON and a screenshot). No retries here; retry and skip belong
      to the run (crawler.md §6).
    - ``BrowserUnavailableError``: ``launch`` failed (Chromium or the Playwright driver cannot be
      started). Not retried.

    Pacing: production uses independent 3..30 second delay targets before every request.
    Explicit ``delay_seconds`` is available for local diagnostics/tests.
    """

    def __init__(
        self,
        *,
        navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
        delay_seconds: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        diagnostic_dir: Path = DEFAULT_DIAGNOSTIC_DIR,
        launch: Callable[[], BrowserSession] = launch_chromium,
    ) -> None:
        self._navigation_timeout_ms = navigation_timeout_ms
        self._pacer = RequestPacer(fixed_delay=delay_seconds, sleep=sleep, clock=clock)
        self._diagnostic_dir = Path(diagnostic_dir)
        self._launch = launch
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

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
        self._pacer.wait()
        try:
            return self._fetch(url)
        finally:
            self._pacer.finished()

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

    def _fetch(self, url: str) -> str:
        context = self._ensure_context()
        page = None
        try:
            try:
                page = context.new_page()
                response = page.goto(url, wait_until="load", timeout=self._navigation_timeout_ms)
                if response is None:
                    raise FetchError(f"GET {url} returned no response")
                html = self._content(page, response)
                problem = classify_page(response.status, response.headers, html)
                if problem is not None:
                    self._save(page, url, response, html)
                    raise page_error(url, problem, response.status)
                return html
            except PlaywrightError as exc:
                # Covers timeouts, net errors, and crashes (TargetClosedError is a subclass).
                raise FetchError(f"GET {url} failed: {type(exc).__name__}: {_first_line(exc)}") from exc
        finally:
            if page is not None:
                _close_quietly(page.close, "page")

    @staticmethod
    def _content(page: Any, response: Any) -> str:
        """The page DOM. A challenge or error page that cannot be read (e.g. it is navigating away
        again) is still classified from its status and headers, with an empty body."""
        try:
            return page.content()
        except PlaywrightError:
            if classify_page(response.status, response.headers, "") is None:
                raise
            return ""

    def _save(self, page: Any, url: str, response: Any, html: str) -> None:
        """Capture the page before it is closed: no additional navigation and no challenge solving."""
        save_failure_diagnostics(
            self._diagnostic_dir,
            url=url,
            status=response.status,
            headers=response.headers,
            html=html,
            extra={"fetcher": "browser", "page_url": redact(page.url or "")},
            screenshot=lambda path: page.screenshot(path=str(path), full_page=True, timeout=5000),
        )

    def _ensure_context(self) -> BrowserContext:
        if self._context is None:
            try:
                self._playwright, self._browser, self._context = self._launch()
            except Exception as exc:  # driver missing, Chromium missing, missing libraries, or a crash
                raise _browser_unavailable(exc) from exc
        return self._context


def _browser_unavailable(exc: Exception) -> BrowserUnavailableError:
    return BrowserUnavailableError(
        "Chromium could not be launched for Playwright; install it with "
        f"'python -m playwright install chromium' (original error: {_first_line(exc) or type(exc).__name__})"
    )


def _first_line(exc: Exception) -> str:
    """The first line of an error message, redacted; Playwright errors carry multi-line call logs."""
    return redact(str(exc).splitlines()[0]) if str(exc).strip() else ""


def _close_quietly(action: Callable[[], None], what: str) -> None:
    """Close one browser resource. A failure here is logged and never replaces the original error."""
    try:
        action()
    except Exception as exc:
        log.warning("closing the %s failed: %s: %s", what, type(exc).__name__, redact(str(exc)))
