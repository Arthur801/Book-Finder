"""Page retrieval seam (crawler.md §15).

``Fetcher`` is the only thing the orchestration uses to obtain HTML; ``create_fetcher`` builds one
from the ``CRAWLER_FETCHER`` kind. Two adapters sit at this seam:

- ``CurlCffiFetcher`` (here): production default, Chrome TLS/HTTP fingerprint.
- ``browser.PlaywrightFetcher``: optional headless browser for diagnostics. Its module is imported
  only when the browser kind is chosen, so the curl path does not need Playwright installed.

Both adapters share the request pacing (``RequestPacer``), the page classification
(``classify_page``) and the failure diagnostics (``save_failure_diagnostics``). Tests inject
fixture-backed fetchers into the run flow; only the browser tests start Chromium, and only against
local pages.

Deliberately absent: browser stealth, ``navigator.webdriver`` patching, CAPTCHA solving and proxy
rotation (AGENTS.md §1.3). A blocked page is a ``FetchError``, never a reason to escalate.
"""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from enum import Enum, StrEnum, auto
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from books_crawler.redact import redact

log = logging.getLogger("books_crawler.fetcher")


class FetcherKind(StrEnum):
    """Values of the ``CRAWLER_FETCHER`` setting."""

    CURL = "curl"
    BROWSER = "browser"


DEFAULT_NAVIGATION_TIMEOUT_MS = 30_000
MAX_NAVIGATION_TIMEOUT_MS = 300_000
MIN_PAGE_DELAY_SECONDS = 3.0
MAX_PAGE_DELAY_SECONDS = 30.0
# Failure diagnostics of both fetchers (the folder name predates the non-challenge failures saved there).
DEFAULT_DIAGNOSTIC_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "challenges"
_ACCEPT_LANGUAGE = "zh-TW,zh;q=0.9"

# Cloudflare sets this response header on challenge responses (value "challenge").
CHALLENGE_HEADER = "cf-mitigated"
CHALLENGE_TITLE = "歡迎光臨博客來"
# Present on the ranking page and on product pages; absent from the challenge interstitial.
PAGE_CONTENT_SELECTOR = ".main_column"
# The site's own error page, sometimes served with HTTP 200 and without page content.
CONNECTION_ERROR_PHRASES = ("您的連線暫時異常", "Connection is temporarily unavailable")
# The only response headers saved with failure diagnostics; never cookies or request headers.
DIAGNOSTIC_HEADERS = (CHALLENGE_HEADER, "cf-ray", "content-type")


class FetchError(Exception):
    """A page could not be retrieved (network error, timeout, non-200 response, browser crash, or a challenge)."""


class BrowserUnavailableError(RuntimeError):
    """Chromium could not be started for Playwright (usually: not installed, or missing libraries)."""


class Fetcher(Protocol):
    """What the run needs from a fetcher (crawler.md §6, §15).

    - ``get`` returns the page body as text, or raises:
      - ``FetchError``: this page could not be retrieved. The run retries and possibly skips it.
      - ``BrowserUnavailableError``: the environment cannot run a browser at all. Never retried and
        never skipped per book; it fails the whole run. It is deliberately not a ``FetchError``.
    - ``close`` releases the session or browser; the caller calls it however the run ends.
    """

    def get(self, url: str) -> str: ...

    def close(self) -> None: ...


def create_fetcher(kind: FetcherKind, *, navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS) -> Fetcher:
    """Build the fetcher for ``kind``. ``navigation_timeout_ms`` only applies to the browser."""
    if kind is FetcherKind.CURL:
        return CurlCffiFetcher()
    # Imported here on purpose: Playwright is only needed by the optional browser fetcher.
    from books_crawler.browser import PlaywrightFetcher

    return PlaywrightFetcher(navigation_timeout_ms=navigation_timeout_ms)


class PageProblem(Enum):
    """Why a fetched page is not usable, in the order ``classify_page`` checks it."""

    CHALLENGE = auto()
    CONNECTION_ERROR_PAGE = auto()
    HTTP_STATUS = auto()


def classify_page(status: int, headers: Mapping[str, str], html: str) -> PageProblem | None:
    """Classify one response; ``None`` means the page can be parsed.

    1. A Cloudflare challenge: the ``cf-mitigated: challenge`` header, or the challenge title on a
       page without the site's content. The title alone is not enough: a real page that happens to
       carry it is still served.
    2. The site's connection-error page without page content (even with HTTP 200).
    3. Any status other than 200 (redirects included; they are never followed).
    """
    soup = BeautifulSoup(html, "html.parser")
    has_content = soup.select_one(PAGE_CONTENT_SELECTOR) is not None
    challenge_header = headers.get(CHALLENGE_HEADER, "").strip().lower() == "challenge"
    if challenge_header or (CHALLENGE_TITLE in _title(soup) and not has_content):
        return PageProblem.CHALLENGE
    if not has_content and any(phrase in soup.get_text() for phrase in CONNECTION_ERROR_PHRASES):
        return PageProblem.CONNECTION_ERROR_PAGE
    if status != 200:
        return PageProblem.HTTP_STATUS
    return None


def page_error(url: str, problem: PageProblem, status: int) -> FetchError:
    """The ``FetchError`` for a classified page; every adapter reports the same text."""
    if problem is PageProblem.CHALLENGE:
        return FetchError(f"GET {url} is blocked by a Cloudflare challenge")
    if problem is PageProblem.CONNECTION_ERROR_PAGE:
        return FetchError(f"GET {url} returned a website connection-error page (HTTP {status})")
    return FetchError(f"GET {url} returned HTTP {status}")


def save_failure_diagnostics(
    directory: Path,
    *,
    url: str,
    status: int,
    headers: Mapping[str, str],
    html: str,
    extra: Mapping[str, Any] | None = None,
    screenshot: Callable[[Path], None] | None = None,
) -> None:
    """Save the failed page as HTML and JSON (plus a PNG when ``screenshot`` is given).

    Never raises: diagnostics must not replace the ``FetchError``. Each output is attempted on its
    own, and each failed attempt gets its own file stem. Only ``DIAGNOSTIC_HEADERS`` are kept,
    never cookies or request headers.
    """
    try:
        base = _new_diagnostic_base(directory)
    except Exception as exc:
        log.warning("cannot create the diagnostics directory: %s", redact(str(exc)))
        return

    def write_metadata(path: Path) -> None:
        # Built here, inside the per-output try below, so that even a failure while reading the
        # headers or the title only costs this one file.
        metadata = {
            "requested_url": redact(url),
            "status": status,
            "title": redact(_title(BeautifulSoup(html, "html.parser"))),
            "headers": {name: redact(headers[name]) for name in DIAGNOSTIC_HEADERS if name in headers},
            **(extra or {}),
        }
        path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    outputs: dict[str, Callable[[Path], Any]] = {
        ".html": lambda path: path.write_text(html, encoding="utf-8"),
        ".json": write_metadata,
    }
    if screenshot is not None:
        outputs[".png"] = screenshot
    for suffix, write in outputs.items():
        path = base.with_suffix(suffix)
        try:
            write(path)
            log.warning("failure diagnostics saved: %s", redact(str(path)))
        except Exception as exc:
            log.warning("cannot save failure diagnostics %s: %s", suffix, redact(str(exc)))


def _title(soup: BeautifulSoup) -> str:
    return soup.title.get_text(strip=True) if soup.title else ""


def _new_diagnostic_base(directory: Path) -> Path:
    """Create ``directory`` and return a unique file stem in it, so retries never overwrite each other."""
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8])


def _sample_page_delay() -> float:
    return random.uniform(MIN_PAGE_DELAY_SECONDS, MAX_PAGE_DELAY_SECONDS)


class RequestPacer:
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
        diagnostic_dir: Path = DEFAULT_DIAGNOSTIC_DIR,
    ) -> None:
        self._session = session if session is not None else curl_requests.Session(impersonate="chrome")
        self._timeout = timeout
        self._pacer = RequestPacer(fixed_delay=None, sleep=sleep, clock=clock, sample_delay=sample_delay)
        self._diagnostic_dir = Path(diagnostic_dir)

    def get(self, url: str) -> str:
        self._pacer.wait()
        try:
            try:
                response = self._session.get(
                    url,
                    timeout=self._timeout,
                    allow_redirects=False,
                    headers={"Accept-Language": _ACCEPT_LANGUAGE},
                )
            except curl_requests.RequestsError as exc:
                raise FetchError(f"GET {url} failed: {type(exc).__name__}: {redact(str(exc))}") from exc
            response.encoding = "utf-8"
            html = response.text
            log.info("GET %s status=%d bytes=%d", url, response.status_code, len(response.content))
            problem = classify_page(response.status_code, response.headers, html)
            if problem is not None:
                save_failure_diagnostics(
                    self._diagnostic_dir,
                    url=url,
                    status=response.status_code,
                    headers=response.headers,
                    html=html,
                    extra={"fetcher": "curl", "impersonate": "chrome"},
                )
                raise page_error(url, problem, response.status_code)
            return html
        finally:
            self._pacer.finished()

    def close(self) -> None:
        self._session.close()
