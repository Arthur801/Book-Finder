"""Page retrieval seam.

``Fetcher`` is the only thing the orchestration uses to obtain HTML.

Implementations:
- ``CurlCffiFetcher``: production default, Chrome TLS/HTTP fingerprint (crawler.md §15).
- ``PlaywrightFetcher``: optional headless browser and screenshot diagnostics.
- ``HttpFetcher``: requests-based, kept for debugging (selected with ``CRAWLER_FETCHER=http``).

Tests inject fixture-backed fetchers into the run flow; only the browser tests start Chromium,
and only against local pages.


Error contract for the run flow (crawler.md §6, §15):

- ``FetchError``: this page could not be retrieved. Retried and possibly skipped by the run.
- ``BrowserUnavailableError``: the environment cannot run a browser at all. Never retried and never
  skipped per book; it fails the whole run. It is deliberately not a ``FetchError``.
"""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from books_crawler.redact import redact

log = logging.getLogger("books_crawler.fetcher")


class FetcherKind(StrEnum):
    """Values of the ``CRAWLER_FETCHER`` setting."""

    BROWSER = "browser"
    HTTP = "http"
    CURL = "curl"


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Normal desktop Chrome UA and zh-TW locale for the Playwright browser. Approved by the user on
# 2026-10-11 (crawler.md §15.1). The major version matches the Chromium that the pinned playwright release
# installs (see crawler/README.md); update both together.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)
BROWSER_LOCALE = "zh-TW"

DEFAULT_NAVIGATION_TIMEOUT_MS = 30_000
MAX_NAVIGATION_TIMEOUT_MS = 300_000
MIN_PAGE_DELAY_SECONDS = 3.0
MAX_PAGE_DELAY_SECONDS = 30.0
DEFAULT_CHALLENGE_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "challenges"

# Cloudflare sets this response header on challenge responses (value "challenge").
CHALLENGE_HEADER = "cf-mitigated"
CHALLENGE_TITLE = "歡迎光臨博客來"
# Present on the ranking page and on product pages; absent from the challenge interstitial.
PAGE_CONTENT_SELECTOR = ".main_column"
# The only response headers saved with failure diagnostics; never cookies or request headers.
DIAGNOSTIC_HEADERS = (CHALLENGE_HEADER, "cf-ray", "content-type")


class FetchError(Exception):
    """A page could not be retrieved (network error, timeout, non-200 response, browser crash, or a challenge)."""


class BrowserUnavailableError(RuntimeError):
    """Chromium could not be started for Playwright (usually: not installed, or missing libraries)."""


class Fetcher(Protocol):
    def get(self, url: str) -> str:
        """Return the page body as text, or raise ``FetchError``."""
        ...


def _sample_page_delay() -> float:
    return random.uniform(MIN_PAGE_DELAY_SECONDS, MAX_PAGE_DELAY_SECONDS)


class _RequestPacer:
    """Sequential request pacing shared by every fetcher (crawler.md §15).

    Each request waits until its delay target has passed since the previous request finished, so
    parsing, DB work and retry backoff in between count toward the target.

    - Default (``fixed_delay=None``): an independent 3..30 second target is sampled for every
      request, and the first request waits too.
    - ``fixed_delay``: the same target every time, and the first request does not wait. Only for
      local diagnostics and tests.
    """

    def __init__(
        self,
        *,
        fixed_delay: float | None,
        sleep: Callable[[float], None],
        clock: Callable[[], float],
        sample_delay: Callable[[], float] = _sample_page_delay,
    ) -> None:
        self._next_target = sample_delay if fixed_delay is None else (lambda: fixed_delay)
        self._wait_before_first = fixed_delay is None
        self._sleep = sleep
        self._clock = clock
        self._last_finished: float | None = None

    def wait(self) -> None:
        """Sleep until the next request may start."""
        if self._last_finished is None and not self._wait_before_first:
            return
        target = self._next_target()
        elapsed = 0.0 if self._last_finished is None else self._clock() - self._last_finished
        remaining = target - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def finished(self) -> None:
        """Record the end of a request, successful or not."""
        self._last_finished = self._clock()


class HttpFetcher:
    """requests-based fetcher with a browser User-Agent, a timeout and a polite delay.

    Production uses independent 3..30 second delay targets, including the first request.
    """

    def __init__(
        self,
        *,
        session: Any | None = None,
        timeout: tuple[float, float] = (5.0, 20.0),
        delay_seconds: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session = session if session is not None else requests.Session()
        self._session.headers.update(
            {"User-Agent": DEFAULT_USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9"}
        )
        self._timeout = timeout
        self._pacer = _RequestPacer(fixed_delay=delay_seconds, sleep=sleep, clock=clock)

    def get(self, url: str) -> str:
        self._pacer.wait()
        try:
            return self._fetch(url)
        finally:
            self._pacer.finished()

    def _fetch(self, url: str) -> str:
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


class CurlCffiFetcher:
    """Sequential Chrome requests, with a sampled 3..30 second gap after each request.

    One session per run. No automatic redirects, so every network request observes pacing.
    Failures are retried by the run, under the same delay. TLS verification stays enabled.
    """

    def __init__(
        self,
        *,
        session: Any | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        sample_delay: Callable[[], float] = _sample_page_delay,
        diagnostic_dir: Path = DEFAULT_CHALLENGE_DIR,
    ) -> None:
        self._session = session if session is not None else curl_requests.Session(impersonate="chrome")
        self._timeout = timeout
        self._pacer = _RequestPacer(fixed_delay=None, sleep=sleep, clock=clock, sample_delay=sample_delay)
        self._diagnostic_dir = Path(diagnostic_dir)

    def get(self, url: str) -> str:
        self._pacer.wait()
        try:
            try:
                response = self._session.get(
                    url,
                    timeout=self._timeout,
                    allow_redirects=False,
                    headers={"Accept-Language": "zh-TW,zh;q=0.9"},
                )
            except curl_requests.RequestsError as exc:
                raise FetchError(f"GET {url} failed: {type(exc).__name__}: {redact(str(exc))}") from exc
            response.encoding = "utf-8"
            html = response.text
            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.get_text(strip=True) if soup.title else ""
            has_content = soup.select_one(PAGE_CONTENT_SELECTOR) is not None
            challenge = response.headers.get(CHALLENGE_HEADER, "").strip().lower() == "challenge"
            challenge = challenge or _is_challenge_page(title, has_content)
            connection_error_page = not has_content and (
                "您的連線暫時異常" in soup.get_text() or "Connection is temporarily unavailable" in soup.get_text()
            )
            log.info("GET %s status=%d bytes=%d", url, response.status_code, len(response.content))
            if challenge or connection_error_page or response.status_code != 200:
                self._save_failure(url, response, html, title)
                if challenge:
                    raise FetchError(f"GET {url} is blocked by a Cloudflare challenge")
                if connection_error_page:
                    raise FetchError(f"GET {url} returned a website connection-error page (HTTP {response.status_code})")
                raise FetchError(f"GET {url} returned HTTP {response.status_code}")
            return html
        finally:
            self._pacer.finished()

    def _save_failure(self, url: str, response: Any, html: str, title: str) -> None:
        try:
            base = _new_diagnostic_base(self._diagnostic_dir)
            base.with_suffix(".html").write_text(html, encoding="utf-8")
            metadata = {
                "requested_url": redact(url),
                "status": response.status_code,
                "title": redact(title),
                "fetcher": "curl",
                "impersonate": "chrome",
                "headers": _diagnostic_headers(response.headers),
            }
            base.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            log.warning("curl failure artifacts saved: %s (.html/.json)", base)
        except Exception as exc:
            log.warning("cannot save curl failure artifacts: %s", redact(str(exc)))

    def close(self) -> None:
        self._session.close()


class PlaywrightFetcher:
    """Fetches pages with headless Chromium through Playwright's sync API.

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
        challenge_dir: Path = DEFAULT_CHALLENGE_DIR,
    ) -> None:
        self._navigation_timeout_ms = navigation_timeout_ms
        self._pacer = _RequestPacer(fixed_delay=delay_seconds, sleep=sleep, clock=clock)
        self._challenge_dir = Path(challenge_dir)
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
                if response.headers.get(CHALLENGE_HEADER, "").strip().lower() == "challenge":
                    self._save_challenge(page, response, url)
                    raise FetchError(f"GET {url} is blocked by a Cloudflare challenge ({CHALLENGE_HEADER})")
                if response.status != 200:
                    raise FetchError(f"GET {url} returned HTTP {response.status}")
                html = page.content()
                if _is_challenge_page(page.title(), page.query_selector(PAGE_CONTENT_SELECTOR) is not None):
                    self._save_challenge(page, response, url)
                    raise FetchError(f"GET {url} is still a Cloudflare challenge page")
                return html
            except PlaywrightError as exc:
                # Covers timeouts, net errors, and crashes (TargetClosedError is a subclass).
                detail = redact(str(exc).splitlines()[0]) if str(exc).strip() else ""
                raise FetchError(f"GET {url} failed: {type(exc).__name__}: {detail}") from exc
        finally:
            if page is not None:
                _close_quietly(page.close, "page")

    def _save_challenge(self, page: Any, response: Any, url: str) -> None:
        """Capture the current page before closing it; diagnostics never replace FetchError.

        Only selected response headers are saved, never cookies or request headers.
        Each failed attempt gets its own files. No additional navigation or challenge solving.
        """
        try:
            base = _new_diagnostic_base(self._challenge_dir)
        except Exception as exc:
            log.warning("cannot create challenge directory: %s", redact(str(exc)))
            return

        def write_metadata(path: Path) -> None:
            metadata = {
                "requested_url": redact(url),
                "page_url": redact(page.url),
                "title": redact(page.title()),
                "status": response.status,
                "headers": _diagnostic_headers(response.headers),
            }
            path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        captures = {
            ".html": lambda path: path.write_text(page.content(), encoding="utf-8"),
            ".png": lambda path: page.screenshot(path=str(path), full_page=True, timeout=5000),
            ".json": write_metadata,
        }
        for suffix, capture in captures.items():
            path = base.with_suffix(suffix)
            try:
                capture(path)
                log.warning("challenge artifact saved: %s", redact(str(path)))
            except Exception as exc:
                log.warning("cannot save challenge artifact %s: %s", suffix, redact(str(exc)))

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


def _new_diagnostic_base(directory: Path) -> Path:
    """Create ``directory`` and return a unique file stem in it, so retries never overwrite each other."""
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8])


def _diagnostic_headers(headers: Any) -> dict[str, str]:
    """The selected response headers (``DIAGNOSTIC_HEADERS``) that are present, redacted."""
    return {name: redact(headers[name]) for name in DIAGNOSTIC_HEADERS if name in headers}


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
