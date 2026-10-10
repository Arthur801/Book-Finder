"""Test doubles and helpers.

- Fake fetcher / parsers for flow tests (prepared objects, no HTML).
- Real saved pages from ``tests/fixtures`` plus helpers that derive negative pages from them.

Nothing in the test suite touches books.com.tw; the fetcher records every requested URL so
tests can assert that existing products never trigger a detail request.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path

from bs4 import BeautifulSoup

from books_crawler.fetcher import FetchError
from books_crawler.models import BookDraft, RankingRow

PRODUCT_URL_PREFIX = "https://www.books.com.tw/products/"
RANKING_HTML = "<ranking/>"

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RANKING_FIXTURE = "ranking_books_7d_top100.html"


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


# ---------------------------------------------------------------------------
# Real fixtures and derived negative pages
# ---------------------------------------------------------------------------

def fixture_html(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def detail_fixture_name(product_id: str) -> str:
    return f"detail_{product_id}.html"


def _ranking_items(soup: BeautifulSoup):
    return soup.select("ul.clearfix > li.item")


def ranking_without_last_item(html: str) -> str:
    """Ranking with 99 rows (the real page minus its last ranked row)."""
    soup = BeautifulSoup(html, "html.parser")
    _ranking_items(soup)[-1].decompose()
    return str(soup)


def ranking_with_duplicate_url(html: str) -> str:
    """Ranking where rank 2 links to the same product as rank 1."""
    soup = BeautifulSoup(html, "html.parser")
    items = _ranking_items(soup)
    first_href = items[0].find("a", href=re.compile(r"/products/"))["href"]
    for link in items[1].find_all("a", href=re.compile(r"/products/")):
        link["href"] = first_href
    return str(soup)


def ranking_with_product_at_rank(html: str, rank: int, url: str) -> str:
    """Ranking where the given rank links to another product URL (all its product links)."""
    soup = BeautifulSoup(html, "html.parser")
    for link in _ranking_items(soup)[rank - 1].find_all("a", href=re.compile(r"/products/")):
        link["href"] = url
    return str(soup)


def detail_without_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    soup.find("h1").decompose()
    return str(soup)


def detail_without_row(html: str, label: str) -> str:
    """Detail page with the labelled row (e.g. 出版日期) removed."""
    soup = BeautifulSoup(html, "html.parser")
    row = next(li for li in soup.find_all("li") if li.get_text(strip=True).startswith(label + "："))
    row.decompose()
    return str(soup)


def detail_with_isbn(html: str, old: str, new: str) -> str:
    return html.replace(old, new)
