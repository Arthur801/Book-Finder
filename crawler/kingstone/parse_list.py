"""Kingstone category list page parser (CB-07 列表頁解析).

Reads only the product cards of ``section#allProducts #displayCSS > .productGrid``. Card fields other than the km_code
(title, author, publisher, date) are not read; the detail page is the source of truth. ``total_pages`` and
``total_count`` are report-only (CB-07): a malformed value is logged as a warning and read as None, never an error.
Nothing here touches the network.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, NavigableString, Tag

from catalog_core.normalize import clean_text
from kingstone.models import KingstoneParseError, ListedItem, ListPage
from kingstone.urls import canonical_list_url, detail_url, km_code_from_href

log = logging.getLogger("kingstone.parse_list")

MAX_CARDS_PER_PAGE = 48
EMPTY_CATEGORY_TEXT = "此分類沒有相關商品唷！"

_PRODUCT_CARD = "section#allProducts #displayCSS > .productGrid > .mod_prod_card[data-prodno]"
_PRODUCT_GRID = "section#allProducts #displayCSS > .productGrid"
_EMPTY_CATEGORY = "section#allProducts #displayCSS > .emptyCategory"
_KM_CODE = re.compile(r"[0-9]{13}")
_POSITIVE_INT = re.compile(r"[1-9][0-9]*")
_DIGITS = re.compile(r"[0-9]+")


def parse_list_html(html: str, url: str) -> ListPage:
    """Parse one category list page. ``url`` must be the canonical list page URL (a caller error otherwise)."""
    if canonical_list_url(url) != url:
        raise ValueError("parse_list_html needs the canonical Kingstone list page URL")

    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("section#allProducts") is None:
        raise KingstoneParseError("list page has no section#allProducts")
    if soup.select_one("section#allProducts #displayCSS") is None:
        raise KingstoneParseError("list page has no #displayCSS inside section#allProducts")

    total_pages = _total_pages(soup)
    total_count = _total_count(soup)

    cards = soup.select(_PRODUCT_CARD)
    if not soup.select(_PRODUCT_GRID):
        if _has_empty_category(soup):
            return ListPage(url=url, items=(), total_pages=total_pages, total_count=total_count, empty=True)
        raise KingstoneParseError("list page has neither a product grid nor the empty-category notice")
    if not cards:
        raise KingstoneParseError("list page has a product grid but no product cards")
    if len(cards) > MAX_CARDS_PER_PAGE:
        raise KingstoneParseError(f"list page has {len(cards)} product cards, more than the {MAX_CARDS_PER_PAGE} allowed")

    items: list[ListedItem] = []
    seen: set[str] = set()
    for index, card in enumerate(cards, start=1):
        km_code = _card_km_code(card, index)
        if km_code in seen:
            continue
        seen.add(km_code)
        items.append(ListedItem(external_id=km_code, source_url=detail_url(km_code), list_url=url))

    return ListPage(url=url, items=tuple(items), total_pages=total_pages, total_count=total_count, empty=False)


def _card_km_code(card: Tag, index: int) -> str:
    prodno = card.get("data-prodno")
    if not isinstance(prodno, str) or _KM_CODE.fullmatch(prodno) is None:
        raise KingstoneParseError(f"product card {index} has a data-prodno that is not 13 digits")
    link = card.select_one(".coverbox a")
    if link is None:
        raise KingstoneParseError(f"product card {index} has no .coverbox link")
    href = link.get("href")
    if not isinstance(href, str):
        raise KingstoneParseError(f"product card {index} has a .coverbox link without href")
    link_km_code = km_code_from_href(href)
    if link_km_code is None:
        raise KingstoneParseError(f"product card {index} has a link href outside the detail page grammar")
    if link_km_code != prodno:
        raise KingstoneParseError(f"product card {index} data-prodno does not match its link km_code")
    return prodno


def _has_empty_category(soup: BeautifulSoup) -> bool:
    notices = soup.select(_EMPTY_CATEGORY)
    return any(clean_text(notice.get_text()) == EMPTY_CATEGORY_TEXT for notice in notices)


def _total_pages(soup: BeautifulSoup) -> int | None:
    field = soup.select_one("input#totalPages")
    if field is None:
        return None
    value = field.get("value")
    if not isinstance(value, str) or _POSITIVE_INT.fullmatch(value) is None:
        log.warning("Kingstone list page input#totalPages is not a positive integer; reading it as None")
        return None
    return int(value)


def _total_count(soup: BeautifulSoup) -> int | None:
    """The n in「共計<span>n</span>筆」: the span whose preceding text ends with 共計."""
    title = soup.select_one("section#allProducts .searchResultTitle")
    if title is None:
        return None
    for span in title.find_all("span"):
        previous = span.previous_sibling
        if isinstance(previous, NavigableString) and previous.strip().endswith("共計"):
            text = clean_text(span.get_text())
            if text is None or _DIGITS.fullmatch(text) is None:
                log.warning("Kingstone list page 共計 count is not a plain number; reading it as None")
                return None
            return int(text)
    return None
