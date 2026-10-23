"""The fetcher module's own interface: building a fetcher and classifying a fetched page (crawler.md §15)."""

import subprocess
import sys
from pathlib import Path

import pytest

from books_crawler.fetcher import (
    CurlCffiFetcher,
    FetcherKind,
    PageProblem,
    classify_page,
    create_fetcher,
    page_error,
    save_failure_diagnostics,
)

CRAWLER_DIR = Path(__file__).resolve().parents[1]
CONTENT = '<html><head><title>博客來-中文書</title></head><body><div class="main_column"><h1>書</h1></div></body></html>'
CHALLENGE = "<html><head><title>歡迎光臨博客來</title></head><body><p>正在進行安全性檢查</p></body></html>"
CHALLENGE_TITLE_WITH_CONTENT = (
    '<html><head><title>歡迎光臨博客來</title></head><body><div class="main_column"><h1>書</h1></div></body></html>'
)
CONNECTION_ERROR = "<html><body><h2>您的連線暫時異常 請稍後再嘗試 謝謝！</h2></body></html>"
CONNECTION_ERROR_EN = "<html><body><p>Connection is temporarily unavailable</p></body></html>"
CONNECTION_PHRASE_IN_CONTENT = '<html><body><div class="main_column">Connection is temporarily unavailable</div></body></html>'


def test_fetcher_kinds_are_the_documented_values():
    assert [kind.value for kind in FetcherKind] == ["curl", "browser"]


def test_curl_kind_builds_the_production_fetcher():
    fetcher = create_fetcher(FetcherKind.CURL)
    try:
        assert isinstance(fetcher, CurlCffiFetcher)
    finally:
        fetcher.close()


def test_browser_kind_builds_the_playwright_fetcher_without_starting_it():
    fetcher = create_fetcher(FetcherKind.BROWSER, navigation_timeout_ms=1234)
    try:
        assert type(fetcher).__name__ == "PlaywrightFetcher"
        assert fetcher.navigation_timeout_ms == 1234
        assert fetcher.browser is None
    finally:
        fetcher.close()


def test_the_curl_path_does_not_import_playwright():
    # A fresh interpreter: other tests in this process import Playwright themselves.
    code = (
        "import sys\n"
        "from books_crawler.fetcher import FetcherKind, create_fetcher\n"
        "create_fetcher(FetcherKind.CURL).close()\n"
        "assert 'playwright' not in sys.modules, sorted(m for m in sys.modules if m.startswith('playwright'))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=CRAWLER_DIR, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("status", "headers", "html", "expected"),
    [
        (200, {}, CONTENT, None),
        (200, {"cf-mitigated": "challenge"}, CONTENT, PageProblem.CHALLENGE),
        (403, {"cf-mitigated": " Challenge "}, CHALLENGE, PageProblem.CHALLENGE),
        (200, {}, CHALLENGE, PageProblem.CHALLENGE),
        (404, {}, CHALLENGE, PageProblem.CHALLENGE),  # a challenge wins over the status code
        (200, {}, CHALLENGE_TITLE_WITH_CONTENT, None),  # the title alone is not a challenge
        (200, {}, CONNECTION_ERROR, PageProblem.CONNECTION_ERROR_PAGE),
        (200, {}, CONNECTION_ERROR_EN, PageProblem.CONNECTION_ERROR_PAGE),
        (200, {}, CONNECTION_PHRASE_IN_CONTENT, None),
        (404, {}, "<html><title>not found</title></html>", PageProblem.HTTP_STATUS),
        (302, {"location": "/elsewhere"}, "", PageProblem.HTTP_STATUS),
    ],
    ids=[
        "normal",
        "challenge-header",
        "challenge-header-403",
        "challenge-title",
        "challenge-title-404",
        "title-with-content",
        "connection-error-zh",
        "connection-error-en",
        "connection-phrase-in-content",
        "not-found",
        "redirect",
    ],
)
def test_classify_page(status, headers, html, expected):
    assert classify_page(status, headers, html) is expected


class FakeExplodingHeaders(dict):
    """Headers that fail when read, standing in for any unexpected error while building the metadata."""

    def __contains__(self, name):
        raise RuntimeError("headers cannot be read")


def test_diagnostics_never_raise_even_when_the_metadata_cannot_be_built(tmp_path):
    save_failure_diagnostics(tmp_path, url="https://example.test/p", status=403, headers=FakeExplodingHeaders(), html=CHALLENGE)

    assert next(tmp_path.glob("*.html")).read_text() == CHALLENGE  # the other outputs are still written


@pytest.mark.parametrize(
    ("problem", "message"),
    [
        (PageProblem.CHALLENGE, "GET https://example.test/p is blocked by a Cloudflare challenge"),
        (PageProblem.CONNECTION_ERROR_PAGE, "GET https://example.test/p returned a website connection-error page (HTTP 200)"),
        (PageProblem.HTTP_STATUS, "GET https://example.test/p returned HTTP 200"),
    ],
)
def test_page_error_messages(problem, message):
    assert str(page_error("https://example.test/p", problem, 200)) == message
