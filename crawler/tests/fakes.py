"""Test doubles: a fixture-backed fetcher and parsers that return prepared objects.

Nothing in the test suite touches books.com.tw; the fetcher records every requested URL so
tests can assert that existing products never trigger a detail request.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from books_crawler.fetcher import FetchError
from books_crawler.models import BookDraft, RankingRow

PRODUCT_URL_PREFIX = "https://www.books.com.tw/products/"
RANKING_HTML = "<ranking/>"


def product_url(number: int) -> str:
    return f"{PRODUCT_URL_PREFIX}{number:010d}"


def ranking_rows(count: int = 100, *, offset: int = 0) -> list[RankingRow]:
    """Rows with ranks 1..count and URLs for product numbers offset+1..offset+count."""
    return [RankingRow(rank=rank, url=product_url(offset + rank)) for rank in range(1, count + 1)]


class FakeFetcher:
    def __init__(self, pages: Mapping[str, str] | None = None, failures: Mapping[str, Exception] | None = None):
        self.pages = dict(pages or {})
        self.failures = dict(failures or {})
        self.calls: list[str] = []

    def get(self, url: str) -> str:
        self.calls.append(url)
        if url in self.failures:
            raise self.failures[url]
        if url not in self.pages:
            raise FetchError(f"no fake page registered for {url}")
        return self.pages[url]

    def detail_calls(self) -> list[str]:
        return [url for url in self.calls if url.startswith(PRODUCT_URL_PREFIX)]


def fake_ranking_parser(rows: list[RankingRow]) -> Callable[[str], list[RankingRow]]:
    def parse(html: str) -> list[RankingRow]:
        assert html == RANKING_HTML
        return list(rows)

    return parse


def fake_detail_parser(drafts: Mapping[str, BookDraft]) -> Callable[[str, str], BookDraft]:
    def parse(html: str, url: str) -> BookDraft:
        if url not in drafts:
            raise ValueError(f"no prepared draft for {url}")
        return drafts[url]

    return parse


def make_draft(url: str, title: str | None = None, **overrides) -> BookDraft:
    """A minimal valid draft (title only). Keyword overrides set any other BookDraft field."""
    return BookDraft(source_url=url, title=title or f"Book {url.rsplit('/', 1)[-1]}", **overrides)
