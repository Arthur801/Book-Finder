"""HTML parser seams for the books.com.tw ranking page and product detail pages.

STATUS: stubs. The real selectors are NOT implemented because no real page fixtures exist yet
(the site answered with a Cloudflare challenge; see Docs/Implementation-Report/issue-6-crawler-success-path.md).
Do not guess selectors. Once the user saves real pages into ``crawler/tests/fixtures/``
(see ``crawler/tests/fixtures/README.md``), implement these functions against those fixtures
and add fixture-backed unit tests.

The orchestration depends only on the callable signatures below, so tests inject fake parsers.
"""

from __future__ import annotations

from collections.abc import Callable

from books_crawler.models import BookDraft, RankingRow

# UNVERIFIED: the 中文書 7日暢銷榜 URL has not been confirmed against page content yet.
RANKING_PAGE_URL = "https://www.books.com.tw/web/sys_saletopb/books/?attribute=7"

RankingParser = Callable[[str], list[RankingRow]]
DetailParser = Callable[[str, str], BookDraft]

_PENDING = (
    "books.com.tw {0} parser is not implemented yet: waiting for real HTML fixtures "
    "(TODO: see crawler/tests/fixtures/README.md)"
)


def parse_ranking_html(html: str) -> list[RankingRow]:
    """TODO(fixtures): extract exactly the 100 (rank, product URL) rows from the ranking page."""
    raise NotImplementedError(_PENDING.format("ranking"))


def parse_detail_html(html: str, url: str) -> BookDraft:
    """TODO(fixtures): build a normalized BookDraft (title required) from a product detail page.

    Must use the helpers in ``books_crawler.normalize`` for ISBN, language, role and date parsing.
    """
    raise NotImplementedError(_PENDING.format("detail"))
