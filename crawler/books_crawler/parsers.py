"""HTML parsers for the books.com.tw ranking page and product detail pages.

Every selector is based on the real pages saved in ``crawler/tests/fixtures/`` (captured by the
user on 2026-10-11, browser "HTML only"). If a field is not reliably present it is returned as
None (with a log line); nothing is guessed. Parsers raise ``ParseError`` when the page is not the
expected kind: wrong ranking tab, missing product container, missing title, unreadable rank.
A ranking-page parse error fails the run. A product-page parse error is retried and then the row is
skipped (crawler.md §13.2, §14.1), so it never produces a partially wrong Book.

Ranking page (``ranking_books_7d_top100.html``):
- The 7-day chart is the selected item of ``ul.sub_list`` (the page also has other ``li.here``).
- The 100 ranked rows are ``ul.clearfix > li.item`` elements containing ``p.no_list strong.no``.
  Menu and category items have no rank and are ignored.
- The product URL is the first ``a[href*="/products/"]`` of the item, canonicalized here.

Product detail page (scoped to the single ``.main_column`` product container; the parser never
reads the rest of the page, which contains other products' lists):
- Title: the container's ``h1`` (equal to ``og:title``).
- Labelled rows are ``li`` elements of the form ``<label>：<value>``. Some rows are malformed in the
  source (an unclosed translator ``li`` nests the following rows), so only each row's *direct*
  children are read; the nested trace-widget markup is never read.
- Contributors: a row's direct ``a[href*="adv_author"]`` links are the names; the row label gives
  the role. Only the ``div.type02_p003`` block is searched.
- Description / TOC: the ``.bd > .content`` of the ``div.mod_b`` block whose ``h3`` is 內容簡介 / 目錄.
- Subjects: the direct ``a`` children of every ``ul.sort`` row labelled 本書分類; every level is kept.
- Thumbnail: the ``img.cover`` whose alt text equals the title.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import NamedTuple

from bs4 import BeautifulSoup, Tag

from books_crawler.models import BookDraft, Contributor, Identifier, RankingRow
from books_crawler.normalize import (
    map_language,
    parse_published_date,
)
from books_crawler.urls import InvalidProductUrl, canonicalize_product_url
from catalog_core.html_text import text_with_line_breaks
from catalog_core.normalize import clean_text, map_contributor_role, normalize_isbn

log = logging.getLogger("books_crawler.parsers")

# 中文書 7日暢銷榜. The user confirmed on 2026-10-11 that this URL is the 中文書 7日暢銷榜;
# the saved page also shows the 7日暢銷榜 tab as the selected sub tab.
RANKING_PAGE_URL = "https://www.books.com.tw/web/sys_saletopb/books/?attribute=7"

RankingParser = Callable[[str], list[RankingRow]]
DetailParser = Callable[[str, str], BookDraft]

_PRODUCT_CONTAINER = ".main_column"
_PRODUCT_LINK = re.compile(r"/products/")
_LABEL_SEPARATOR = re.compile(r"[：:]")
_PAGE_COUNT = re.compile(r"(\d+)\s*頁")


class ParseError(ValueError):
    """The page is not the expected kind of page.

    On the ranking page the run fails. On a product detail page the row is retried and then skipped
    (crawler.md §13.2, §14.1).
    """


class RestrictedBookError(Exception):
    """The source explicitly requires an adult member login to view this product.

    Not a ``ParseError``: a restricted page is skipped without retry and is not an error (crawler.md §13.2).
    """


class _Row(NamedTuple):
    label: str
    value: str
    li: Tag


def _canonical(href: str | None, where: str) -> str:
    try:
        return canonicalize_product_url(href)
    except InvalidProductUrl as exc:
        raise ParseError(f"{where}: {exc}") from exc


# ---------------------------------------------------------------------------
# Ranking page
# ---------------------------------------------------------------------------


def parse_ranking_html(html: str) -> list[RankingRow]:
    soup = BeautifulSoup(html, "html.parser")

    current_tab = soup.select_one("ul.sub_list li.here > a")
    if current_tab is None or clean_text(current_tab.get_text()) != "7日暢銷榜":
        raise ParseError("ranking page is not the 7日暢銷榜 (selected sub tab is not 7日暢銷榜)")

    rows: list[RankingRow] = []
    for item in soup.select("ul.clearfix > li.item"):
        rank_tag = item.select_one("p.no_list strong.no")
        if rank_tag is None:
            continue  # menu / category item, not a ranking row
        rank_text = clean_text(rank_tag.get_text())
        if rank_text is None or not rank_text.isdigit():
            raise ParseError(f"unreadable rank value {rank_text!r}")
        link = item.find("a", href=_PRODUCT_LINK)
        if link is None:
            raise ParseError(f"rank {rank_text} has no product link")
        rows.append(RankingRow(rank=int(rank_text), url=_canonical(link["href"], f"rank {rank_text}")))
    return rows


# ---------------------------------------------------------------------------
# Product detail page
# ---------------------------------------------------------------------------


def _product_container(soup: BeautifulSoup) -> Tag:
    container = soup.select_one(_PRODUCT_CONTAINER)
    if container is None:
        raise ParseError(f"product container {_PRODUCT_CONTAINER} not found; refusing to read the whole page")
    return container


def _split_label(li: Tag) -> tuple[str | None, str]:
    """Split a row's own text into (label, value). The label is None if the row is not labelled.

    Only direct string children are read, so a nested row (malformed source HTML) is not included.
    """
    own_text = " ".join(s.strip() for s in li.find_all(string=True, recursive=False) if s.strip())
    parts = _LABEL_SEPARATOR.split(own_text, maxsplit=1)
    if len(parts) != 2:
        return None, ""
    return clean_text(parts[0]), clean_text(parts[1]) or ""


def _labelled_rows(container: Tag) -> list[_Row]:
    rows: list[_Row] = []
    for li in container.find_all("li"):
        label, value = _split_label(li)
        if label:
            rows.append(_Row(label, value, li))
    return rows


def _first_value(rows: list[_Row], label: str) -> str | None:
    for row in rows:
        if row.label == label:
            return row.value or None
    return None


def _section_text(container: Tag, heading: str) -> str | None:
    """Text of a detail section (內容簡介 / 目錄). None when the section is absent or empty."""
    header = next((h3 for h3 in container.find_all("h3") if clean_text(h3.get_text()) == heading), None)
    if header is None or header.parent is None:
        return None
    # Section block: <div class="mod_b ..."><a name=...></a><h3>heading</h3><div class="bd"><div class="content">
    body = header.parent.find("div", class_="bd", recursive=False)
    content = body.find("div", class_="content", recursive=False) if body is not None else None
    if content is None:
        return None
    return text_with_line_breaks(content)


def _publisher(rows: list[_Row]) -> str | None:
    for row in rows:
        if row.label != "出版社":
            continue
        link = next((a for a in row.li.find_all("a", recursive=False) if "puballb" in (a.get("href") or "")), None)
        if link is not None:
            return clean_text(link.get_text(" ", strip=True))
        return row.value or None
    return None


def _contributors(block: Tag) -> tuple[Contributor, ...]:
    contributors: list[Contributor] = []
    for li in block.find_all("li"):
        name_links = [a for a in li.find_all("a", recursive=False) if "adv_author" in (a.get("href") or "")]
        if not name_links:
            continue
        label, _ = _split_label(li)
        if label is None:
            log.warning("contributor row without a label skipped")
            continue
        role = map_contributor_role(label)
        for name_link in name_links:
            name = clean_text(name_link.get_text(" ", strip=True))
            if name:
                contributors.append(Contributor(order=len(contributors) + 1, name=name, role=role))
    return tuple(contributors)


def _subjects(container: Tag) -> tuple[str, ...]:
    """Every 本書分類 level from every group, de-duplicated in page order."""
    names: list[str] = []
    for sort_list in container.select("ul.sort"):
        for li in sort_list.find_all("li", recursive=False):
            label, _ = _split_label(li)
            if label != "本書分類":
                continue
            for link in li.find_all("a", recursive=False):
                name = clean_text(link.get_text(" ", strip=True))
                if name:
                    names.append(name)
    return tuple(dict.fromkeys(names))


def _thumbnail(container: Tag, title: str) -> str | None:
    for img in container.select("img.cover"):
        if clean_text(img.get("alt")) == title and img.get("src"):
            return img["src"]
    return None


def parse_detail_html(html: str, url: str) -> BookDraft:
    soup = BeautifulSoup(html, "html.parser")
    canonical_url = canonicalize_product_url(url)
    if soup.select_one(_PRODUCT_CONTAINER) is None:
        page_text = str(soup)
        if "限制級商品" in page_text and "登入會員" in page_text:
            raise RestrictedBookError(f"restricted product requires member login: {canonical_url}")
    container = _product_container(soup)

    heading = container.find("h1")
    title = clean_text(heading.get_text(" ", strip=True)) if heading is not None else None
    if title is None:
        raise ParseError(f"title (h1) not found in the product container of {canonical_url}")

    rows = _labelled_rows(container)

    published_date, precision = parse_published_date(_first_value(rows, "出版日期"))

    page_count: int | None = None
    spec = _first_value(rows, "規格")
    if spec is not None:
        match = _PAGE_COUNT.search(spec)
        if match is not None and int(match.group(1)) > 0:
            page_count = int(match.group(1))

    identifiers: tuple[Identifier, ...] = ()
    isbn = normalize_isbn(_first_value(rows, "ISBN"))
    if isbn is not None:
        identifiers = (isbn,)

    contributors: tuple[Contributor, ...] = ()
    publisher_row = next((row for row in rows if row.label == "出版社"), None)
    info_block = publisher_row.li.find_parent("div", class_="type02_p003") if publisher_row is not None else None
    if info_block is None:
        log.warning("contributor block not found; no contributors stored for %s", canonical_url)
    else:
        contributors = _contributors(info_block)

    return BookDraft(
        source_url=canonical_url,
        title=title,
        publisher=_publisher(rows),
        published_date=published_date,
        published_date_precision=precision,
        language=map_language(_first_value(rows, "語言")),
        description=_section_text(container, "內容簡介"),
        table_of_contents=_section_text(container, "目錄"),
        page_count=page_count,
        thumbnail_url=_thumbnail(container, title),
        identifiers=identifiers,
        contributors=contributors,
        subjects=_subjects(container),
    )
