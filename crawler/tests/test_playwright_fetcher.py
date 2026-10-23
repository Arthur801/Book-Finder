"""PlaywrightFetcher against LOCAL pages only.

The browser tests start headless Chromium and load pages from a throwaway HTTP server bound to
127.0.0.1. Nothing here connects to books.com.tw. If Chromium cannot be launched, the browser
tests are skipped with the command that installs it; the other tests always run.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from books_crawler.browser import BROWSER_USER_AGENT, PlaywrightFetcher
from books_crawler.fetcher import BrowserUnavailableError, FetchError
from tests.browser_fakes import FakeBrowserContext, FakeDriver, FakePage, FakeResponse, launching

NORMAL_HTML = (
    "<!doctype html><html><head><meta charset=\"utf-8\"><title>博客來 測試頁</title></head>"
    "<body><div class=\"main_column\"><h1>本機測試書</h1></div>"
    "<script>document.body.insertAdjacentHTML(\"beforeend\", "
    "'<p id=\"rendered-by-script\">script ran before load</p>');</script></body></html>"
)
NAVIGATOR_HTML = (
    "<!doctype html><html><head><meta charset=\"utf-8\"><title>probe</title></head><body>"
    "<script>document.title = navigator.language; document.body.dataset.ua = navigator.userAgent;"
    "</script></body></html>"
)
CHALLENGE_HTML = (
    "<!doctype html><html><head><meta charset=\"utf-8\"><title>歡迎光臨博客來</title></head>"
    "<body><p>正在進行安全性檢查</p></body></html>"
)
TITLE_WITH_CONTENT_HTML = (
    "<!doctype html><html><head><meta charset=\"utf-8\"><title>歡迎光臨博客來</title></head>"
    "<body><div class=\"main_column\"><h1>本機測試書</h1></div></body></html>"
)

# path -> (status, extra headers, body)
ROUTES = {
    "/normal": (200, {}, NORMAL_HTML),
    "/navigator": (200, {}, NAVIGATOR_HTML),
    "/missing": (404, {}, "<html><title>not found</title></html>"),
    "/unavailable": (503, {}, "<html><title>maintenance</title></html>"),
    "/challenge-title": (200, {}, CHALLENGE_HTML),
    "/challenge-header": (200, {"cf-mitigated": "challenge"}, NORMAL_HTML),
    "/challenge-header-403": (403, {"cf-mitigated": "challenge"}, CHALLENGE_HTML),
    "/title-with-content": (200, {}, TITLE_WITH_CONTENT_HTML),
}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # keep pytest output quiet
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/slow":
            # Hold the response until the fixture tears down, so the navigation timeout fires.
            self.server.release.wait(timeout=30)
            self._reply(200, {}, NORMAL_HTML)
            return
        status, headers, body = ROUTES.get(path, (404, {}, "<html><title>not found</title></html>"))
        self._reply(status, headers, body)

    def _reply(self, status, headers, body):
        data = body.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass  # the browser already gave up (e.g. after the timeout test)


class LocalSite:
    def __init__(self) -> None:
        self.release = threading.Event()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.release = self.release
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def url(self, path: str) -> str:
        return self.base_url + path

    def close(self) -> None:
        self.release.set()
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture(scope="module")
def local_site():
    site = LocalSite()
    yield site
    site.close()


@pytest.fixture(scope="session")
def chromium_ready() -> None:
    """Skip every browser test with an actionable message when Chromium cannot be launched."""
    try:
        with sync_playwright() as playwright:
            playwright.chromium.launch(headless=True).close()
    except Exception as exc:  # noqa: BLE001 - any launch failure means the browser tests cannot run here
        first_line = (str(exc).strip().splitlines() or [type(exc).__name__])[0]
        pytest.skip(
            f"Chromium cannot be launched for Playwright ({first_line}). Install it with "
            "'python -m playwright install chromium' from the crawler environment. If system "
            "libraries are missing, install them once with 'sudo python -m playwright install-deps chromium' "
            "(run it from the environment that has Playwright installed)."
        )


class FakeClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


# ---------------------------------------------------------------------------
# Browser behaviour (real Chromium, local pages)
# ---------------------------------------------------------------------------


def test_normal_page_returns_html_after_load(chromium_ready, local_site):
    with PlaywrightFetcher(delay_seconds=0) as fetcher:
        html = fetcher.get(local_site.url("/normal"))

    assert "本機測試書" in html
    assert 'class="main_column"' in html
    # The HTML is taken after load, so content written by a page script is present too.
    assert 'id="rendered-by-script"' in html


def test_browser_uses_desktop_user_agent_and_zh_tw_locale(chromium_ready, local_site):
    with PlaywrightFetcher(delay_seconds=0) as fetcher:
        html = fetcher.get(local_site.url("/navigator"))

    assert f'data-ua="{BROWSER_USER_AGENT}"' in html
    assert "<title>zh-TW</title>" in html


@pytest.mark.parametrize(("path", "message"), [("/missing", "HTTP 404"), ("/unavailable", "HTTP 503")])
def test_non_200_response_raises_fetch_error_and_saves_diagnostics(chromium_ready, local_site, path, message, tmp_path):
    with PlaywrightFetcher(delay_seconds=0, diagnostic_dir=tmp_path) as fetcher, pytest.raises(FetchError, match=message):
        fetcher.get(local_site.url(path))
    assert len(list(tmp_path.glob("*.html"))) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_navigation_timeout_raises_fetch_error(chromium_ready, local_site):
    with PlaywrightFetcher(navigation_timeout_ms=500, delay_seconds=0) as fetcher, pytest.raises(FetchError, match="TimeoutError"):
        fetcher.get(local_site.url("/slow"))


@pytest.mark.parametrize("path", ["/challenge-title", "/challenge-header", "/challenge-header-403"])
def test_cloudflare_challenge_raises_fetch_error(chromium_ready, local_site, path, tmp_path):
    with PlaywrightFetcher(delay_seconds=0, diagnostic_dir=tmp_path) as fetcher, pytest.raises(FetchError, match="challenge"):
        fetcher.get(local_site.url(path))
    assert len(list(tmp_path.glob("*.png"))) == 1
    assert len(list(tmp_path.glob("*.html"))) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_challenge_title_on_a_page_with_content_is_not_a_challenge(chromium_ready, local_site):
    with PlaywrightFetcher(delay_seconds=0) as fetcher:
        html = fetcher.get(local_site.url("/title-with-content"))

    assert "本機測試書" in html


def test_unreachable_server_raises_fetch_error(chromium_ready):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]  # nothing listens on this port once the socket is closed
    with PlaywrightFetcher(delay_seconds=0, navigation_timeout_ms=5000) as fetcher, pytest.raises(FetchError, match="failed"):
        fetcher.get(f"http://127.0.0.1:{port}/")


def test_browser_that_disappears_mid_run_raises_fetch_error_and_close_still_works(chromium_ready, local_site):
    fetcher = PlaywrightFetcher(delay_seconds=0)
    fetcher.get(local_site.url("/normal"))
    fetcher.browser.close()  # simulated crash: the browser goes away under the fetcher

    with pytest.raises(FetchError, match="failed"):
        fetcher.get(local_site.url("/normal"))
    fetcher.close()  # must not raise even though the browser is already gone
    assert fetcher.browser is None


def test_consecutive_gets_are_separated_by_the_delay_without_real_waiting(chromium_ready, local_site):
    clock = FakeClock()
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    with PlaywrightFetcher(delay_seconds=2.0, sleep=fake_sleep, clock=clock) as fetcher:
        fetcher.get(local_site.url("/normal"))
        assert sleeps == []  # the first request is not delayed

        fetcher.get(local_site.url("/normal"))
        assert sleeps == [2.0]

        clock.now += 0.5  # 0.5 s already passed since the previous get returned
        fetcher.get(local_site.url("/normal"))
        assert sleeps == [2.0, 1.5]


def test_one_browser_is_reused_across_gets(chromium_ready, local_site):
    with PlaywrightFetcher(delay_seconds=0) as fetcher:
        fetcher.get(local_site.url("/normal"))
        first = fetcher.browser
        fetcher.get(local_site.url("/normal"))

        assert first is not None
        assert fetcher.browser is first
        assert first.is_connected()


def test_browser_is_closed_when_a_get_raises(chromium_ready, local_site, tmp_path):
    fetcher = PlaywrightFetcher(delay_seconds=0, diagnostic_dir=tmp_path)
    with pytest.raises(FetchError), fetcher:
        fetcher.get(local_site.url("/normal"))
        browser = fetcher.browser
        assert browser is not None and browser.is_connected()
        fetcher.get(local_site.url("/missing"))

    assert fetcher.browser is None
    assert not browser.is_connected()


def test_browser_is_closed_when_an_unrelated_exception_escapes(chromium_ready, local_site):
    fetcher = PlaywrightFetcher(delay_seconds=0)
    with pytest.raises(RuntimeError, match="run failed"), fetcher:
        fetcher.get(local_site.url("/normal"))
        browser = fetcher.browser
        raise RuntimeError("run failed")

    assert not browser.is_connected()


# ---------------------------------------------------------------------------
# Lifecycle and challenge rules that need no browser
# ---------------------------------------------------------------------------


def test_close_without_any_get_is_a_safe_no_op():
    fetcher = PlaywrightFetcher()
    fetcher.close()
    fetcher.close()

    assert fetcher.browser is None


def test_missing_chromium_raises_browser_unavailable_with_install_hint(monkeypatch, tmp_path):
    # An empty browsers directory makes Playwright's launch fail the same way as a missing install.
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "no-browsers-here"))
    fetcher = PlaywrightFetcher(delay_seconds=0)

    with pytest.raises(BrowserUnavailableError, match="playwright install chromium"):
        fetcher.get("http://127.0.0.1:9/")
    assert fetcher.browser is None


class _FakeLaunchingDriver:
    """Stands in for ``sync_playwright()`` and its chromium launcher, for the default launch's cleanup."""

    def __init__(self, launch_error: Exception) -> None:
        self.stopped = False
        self._launch_error = launch_error
        self.chromium = self

    def start(self) -> _FakeLaunchingDriver:
        return self

    def launch(self, headless: bool):
        raise self._launch_error

    def stop(self) -> None:
        self.stopped = True


class _NewPageCrashes(FakeBrowserContext):
    def new_page(self):
        raise PlaywrightError("Target page, context or browser has been closed")


class _PageCloseFails(FakePage):
    def close(self) -> None:
        raise PlaywrightError("close failed after the page already crashed")


class _ContextWithFailingPageClose(FakeBrowserContext):
    def new_page(self):
        self.open_pages += 1
        return _PageCloseFails(self)


def _fetcher_over(context: FakeBrowserContext, driver: FakeDriver | None = None, **options) -> PlaywrightFetcher:
    """A fetcher whose launch hands over the given fake context; no browser is started."""
    return PlaywrightFetcher(delay_seconds=0, launch=launching(context, driver), **options)


class _CapturedChallengePage(FakePage):
    def goto(self, url, **kwargs):
        super().goto(url, **kwargs)
        headers = {"cf-ray": "fixture-ray", "set-cookie": "secret-cookie"}
        if self._context.header_challenge:
            headers["cf-mitigated"] = "challenge"
        return FakeResponse(200, headers)

    def screenshot(self, *, path, full_page, timeout):
        assert not self.closed
        assert full_page and timeout == 5000
        if self._context.screenshot_failure:
            raise PlaywrightError("screenshot failed")
        Path(path).write_bytes(b"fake screenshot")


class _CapturedChallengeContext(FakeBrowserContext):
    def __init__(self, url, *, header_challenge=True, screenshot_failure=False):
        super().__init__({url: CHALLENGE_HTML})
        self.header_challenge = header_challenge
        self.screenshot_failure = screenshot_failure

    def new_page(self):
        self.open_pages += 1
        return _CapturedChallengePage(self)


@pytest.mark.parametrize("header_challenge", [True, False])
def test_challenge_artifacts_are_saved_before_close_and_attempts_do_not_overwrite(tmp_path, header_challenge):
    url = "https://www.books.com.tw/products/0011063006"
    context = _CapturedChallengeContext(url, header_challenge=header_challenge)
    with _fetcher_over(context, diagnostic_dir=tmp_path) as fetcher:
        for _ in range(2):
            with pytest.raises(FetchError, match="challenge"):
                fetcher.get(url)
            assert context.open_pages == 0
    assert len(list(tmp_path.glob("*.png"))) == 2
    assert len(list(tmp_path.glob("*.html"))) == 2
    metadata = list(tmp_path.glob("*.json"))
    assert len(metadata) == 2
    data = json.loads(metadata[0].read_text())
    assert data["requested_url"] == url
    assert data["title"] == "歡迎光臨博客來"
    assert data["headers"]["cf-ray"] == "fixture-ray"
    assert "set-cookie" not in data["headers"]
    assert next(tmp_path.glob("*.html")).read_text() == CHALLENGE_HTML


@pytest.mark.parametrize("failure", ["directory", "screenshot"])
def test_capture_failure_preserves_challenge_error_and_closes_page(tmp_path, failure):
    url = "https://www.books.com.tw/products/0011063006"
    target = tmp_path / "capture"
    if failure == "directory":
        target.write_text("not a directory")
    context = _CapturedChallengeContext(url, screenshot_failure=failure == "screenshot")
    with _fetcher_over(context, diagnostic_dir=target) as fetcher:
        with pytest.raises(FetchError, match="blocked by a Cloudflare challenge"):
            fetcher.get(url)
        assert context.open_pages == 0
    if failure == "screenshot":
        assert len(list(target.glob("*.html"))) == 1
        assert len(list(target.glob("*.json"))) == 1


def test_connection_error_page_is_a_fetch_error_and_saves_diagnostics(tmp_path):
    url = "https://www.books.com.tw/products/0000000006"
    html = "<html><body><h2>您的連線暫時異常 請稍後再嘗試 謝謝！</h2></body></html>"
    fetcher = _fetcher_over(FakeBrowserContext(pages={url: html}), diagnostic_dir=tmp_path)

    with pytest.raises(FetchError, match="website connection-error page"):
        fetcher.get(url)
    assert next(tmp_path.glob("*.html")).read_text() == html


class _ContentFailsAfterHeaderChallenge(FakeBrowserContext):
    """A challenge response whose page is navigating away again, so reading its DOM fails."""

    def new_page(self):
        self.open_pages += 1
        page = FakePage(self)

        def content():
            raise PlaywrightError("Unable to retrieve content because the page is navigating")

        page.content = content
        return page


def test_header_challenge_is_reported_and_saved_even_when_the_page_content_cannot_be_read(tmp_path):
    url = "https://www.books.com.tw/products/0000000008"
    context = _ContentFailsAfterHeaderChallenge(pages={url: ""}, response_headers={"cf-mitigated": "challenge"})
    fetcher = _fetcher_over(context, diagnostic_dir=tmp_path)

    with pytest.raises(FetchError, match="blocked by a Cloudflare challenge"):
        fetcher.get(url)
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert context.open_pages == 0


def test_a_launched_fake_browser_is_exposed_until_close():
    fetcher = _fetcher_over(FakeBrowserContext(pages={"https://example.test/": "<html></html>"}))
    fetcher.get("https://example.test/")

    assert fetcher.browser is not None
    fetcher.close()
    assert fetcher.browser is None


def test_new_page_crash_is_wrapped_into_fetch_error():
    fetcher = _fetcher_over(_NewPageCrashes(pages={}))

    with pytest.raises(FetchError, match="failed: Error"):
        fetcher.get("https://www.books.com.tw/products/0000000001")


def test_navigation_crash_is_fetch_error_and_the_page_is_still_closed():
    url = "https://www.books.com.tw/products/0000000002"
    context = FakeBrowserContext(pages={url: "<html></html>"}, goto_failures={url: 1})
    fetcher = _fetcher_over(context)

    with pytest.raises(FetchError, match="failed: Error"):
        fetcher.get(url)
    assert context.open_pages == 0  # the page was closed in the finally block

    assert fetcher.get(url) == "<html></html>"  # the next request works on the same context


def test_failing_page_close_never_masks_the_original_fetch_error():
    context = _ContextWithFailingPageClose(pages={})
    fetcher = _fetcher_over(context)

    with pytest.raises(FetchError, match="GET .* failed: Error"):
        fetcher.get("https://www.books.com.tw/products/0000000003")  # goto fails: no such page


def test_browser_start_failure_is_browser_unavailable_and_not_a_fetch_error():
    def broken_launch():
        raise RuntimeError("driver process could not be started")

    fetcher = PlaywrightFetcher(delay_seconds=0, launch=broken_launch)

    with pytest.raises(BrowserUnavailableError, match="playwright install chromium") as info:
        fetcher.get("https://www.books.com.tw/products/0000000004")
    assert not isinstance(info.value, FetchError)


def test_chromium_launch_failure_stops_the_driver_and_is_browser_unavailable(monkeypatch):
    # The default launch cleans up after itself, so this replaces Playwright's own entry point.
    driver = _FakeLaunchingDriver(launch_error=PlaywrightError("Executable doesn't exist at /no/chromium"))
    monkeypatch.setattr("books_crawler.browser.sync_playwright", lambda: driver)
    fetcher = PlaywrightFetcher(delay_seconds=0)

    with pytest.raises(BrowserUnavailableError, match="playwright install chromium"):
        fetcher.get("https://www.books.com.tw/products/0000000005")
    assert driver.stopped
    assert fetcher.browser is None


def test_close_stops_the_driver_even_when_closing_the_context_fails():
    class _ContextCloseFails(FakeBrowserContext):
        def close(self) -> None:
            raise PlaywrightError("context already gone")

    driver = FakeDriver()
    fetcher = _fetcher_over(_ContextCloseFails(pages={}), driver)
    with pytest.raises(FetchError):
        fetcher.get("https://www.books.com.tw/products/0000000007")  # starts the (fake) browser

    fetcher.close()  # no exception: the failure is logged, the rest of the shutdown still runs

    assert driver.stopped
