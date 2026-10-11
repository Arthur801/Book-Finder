"""Stand-ins for Playwright objects, injected through ``PlaywrightFetcher(launch=...)``.

Kept apart from ``fakes.py`` so that only the browser tests depend on Playwright.
"""

from __future__ import annotations

from collections.abc import Mapping

from playwright.sync_api import Error as PlaywrightError


class FakeResponse:
    def __init__(self, status: int = 200, headers: Mapping[str, str] | None = None) -> None:
        self.status = status
        self.headers = dict(headers or {})


class FakePage:
    """Stands in for a Playwright page: serves ``pages[url]`` after a successful ``goto``."""

    def __init__(self, context: FakeBrowserContext) -> None:
        self._context = context
        self._url: str | None = None
        self.closed = False

    @property
    def url(self) -> str | None:
        return self._url

    def goto(self, url: str, wait_until: str | None = None, timeout: float | None = None) -> FakeResponse:
        self._context.goto_calls.append(url)
        remaining = self._context.goto_failures.get(url, 0)
        if remaining > 0:
            self._context.goto_failures[url] = remaining - 1
            raise PlaywrightError(f"Target page, context or browser has been closed (simulated crash for {url})")
        if url not in self._context.pages:
            raise PlaywrightError(f"net::ERR_NAME_NOT_RESOLVED at {url}")
        self._url = url
        return FakeResponse(200, self._context.response_headers)

    def content(self) -> str:
        return self._context.pages[self._url]

    def screenshot(self, *, path: str, full_page: bool, timeout: float) -> None:
        raise PlaywrightError("screenshots are not simulated by this fake")

    def close(self) -> None:
        self.closed = True
        self._context.open_pages -= 1


class FakeBrowserContext:
    """Stands in for a Playwright browser context. Records what was requested and what was closed.

    - ``pages``: URL -> HTML served after a successful navigation;
    - ``goto_failures``: URL -> number of navigations that crash first (a PlaywrightError, as after
      a browser or page crash), then succeed;
    - ``response_headers``: headers of every successful navigation response.
    """

    def __init__(
        self,
        pages: Mapping[str, str],
        goto_failures: Mapping[str, int] | None = None,
        response_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.pages = dict(pages)
        self.goto_failures = dict(goto_failures or {})
        self.response_headers = dict(response_headers or {})
        self.goto_calls: list[str] = []
        self.open_pages = 0
        self.closed = False

    def new_page(self) -> FakePage:
        self.open_pages += 1
        return FakePage(self)

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    """Stands in for the launched browser; records whether it was closed."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeDriver:
    """Stands in for the Playwright driver returned by a launch; records whether it was stopped."""

    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def launching(context: FakeBrowserContext, driver: FakeDriver | None = None):
    """A ``launch`` callable for ``PlaywrightFetcher`` that hands over the fake context; no browser starts."""
    return lambda: (driver or FakeDriver(), FakeBrowser(), context)
