"""HTML parsers for the books.com.tw ranking page and product detail pages.

Every selector is based on the real pages saved in ``crawler/tests/fixtures/`` (captured by the
user on 2026-10-11, browser "HTML only"). If a field is not reliably present it is returned as
None (with a log line); nothing is guessed. Parsers raise ``ParseError`` only when the page is
not the expected kind (wrong ranking tab, no title), because that must fail the run loudly.

Ranking page (``ranking_books_7d_top100.html``):
- The current tab is ``li.here`` containing "7日暢銷榜" (the user confirmed the URL is 中文書 7日暢銷榜).
- The 100 ranked rows are the ``li.item`` elements that are direct children of ``ul.clearfix``
  and contain ``p.no_list strong.no`` (the rank). Menu and category items have no rank and are ignored.
- The product URL is the first ``a[href*="/products/"]`` inside the item (the cover link; the title
  link carries the same URL). The URL is canonicalized with ``urls.canonicalize_product_url``.

Product detail page:
- Title: the page ``h1`` (equal to ``og:title``).
- Labelled rows are ``li`` elements of the form ``<label>：<value>``. Some rows are malformed in the
  source (an unclosed translator ``li`` nests the following rows), so only each row's *direct*
  children are read; the nested trace-widget markup is never read.
- Contributors: a row's direct ``a[href*="adv_author"]`` links are the names; the row label gives
  the role. Only the ``div.type02_p003`` block is searched, because other products on the page use
  the same markup.
- Description / TOC: the ``.bd .content`` of the ``div.mod`` block whose ``h3`` is 內容簡介 / 目錄.
- Subjects: the direct ``a`` children of the ``ul.sort`` row labelled 本書分類 (one per category level).
- Thumbnail: the ``img.cover`` whose alt text equals the title.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from bs4 import BeautifulSoup, Tag

from books_crawler.models import BookDraft, Contributor, Identifier, RankingRow
from books_crawler.normalize import (
    clean_text,
    map_contributor_role,
    map_language,
    normalize_isbn,
    parse_published_date,
)
from books_crawler.urls import canonicalize_product_url

log = logging.getLogger("books_crawler.parsers")

# 中文書 7日暢銷榜. The user confirmed on 2026-10-11 that this URL is the 中文書 7日暢銷榜;
# the saved page also shows the 7日暢銷榜 tab as the current tab (``li.here``).
RANKING_PAGE_URL = "https://www.books.com.tw/web/sys_saletopb/books/?attribute=7"

RankingParser = Callable[[str], list[RankingRow]]
DetailParser = Callable[[str, str], BookDraft]

_LABEL_SEPARATOR = re.compile(r"[：:]")
_PAGE_COUNT = re.compile(r"(\d+)\s*頁")


class ParseError(ValueError):
    """The page is not the expected kind of page; the run must fail."""


# ---------------------------------------------------------------------------
# Ranking page
# ---------------------------------------------------------------------------

def parse_ranking_html(html: str) -> list[RankingRow]:
    soup = BeautifulSoup(html, "html.parser")

    # The page has several ``li.here`` (top-level tab, sub tab, category). The 7-day tab is the
    # selected item of the sub-tab list ``ul.sub_list``.
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
        link = item.find("a", href=re.compile(r"/products/"))
        if link is None:
            raise ParseError(f"rank {rank_text} has no product link")
        rows.append(RankingRow(rank=int(rank_text), url=canonicalize_product_url(link["href"])))
    return rows


# ---------------------------------------------------------------------------
# Product detail page
# ---------------------------------------------------------------------------

def _split_label(li: Tag) -> tuple[str | None, str]:
    """Split a row's own text into (label, value). The label is None if the row is not labelled.

    Only direct string children are read, so a nested row (malformed source HTML) is not included.
    """
    own_text = " ".join(s.strip() for s in li.find_all(string=True, recursive=False) if s.strip())
    parts = _LABEL_SEPARATOR.split(own_text, maxsplit=1)
    if len(parts) != 2:
        return None, ""
    return clean_text(parts[0]), clean_text(parts[1]) or ""


def _labelled_rows(scope: Tag) -> list[tuple[str, Tag]]:
    rows: list[tuple[str, Tag]] = []
    for li in scope.find_all("li"):
        label, _ = _split_label(li)
        if label:
            rows.append((label, li))
    return rows


def _first_value(rows: list[tuple[str, Tag]], label: str) -> str | None:
    for row_label, li in rows:
        if row_label == label:
            _, value = _split_label(li)
            return value or None
    return None


def _section_text(soup: BeautifulSoup, heading: str) -> str | None:
    """Text of a detail section (內容簡介 / 目錄). None when the section is absent or empty."""
    header = next((h3 for h3 in soup.find_all("h3") if clean_text(h3.get_text()) == heading), None)
    if header is None or header.parent is None:
        return None
    # Section block: <div class="mod_b ..."><a name=...></a><h3>heading</h3><div class="bd"><div class="content">
    body = header.parent.find("div", class_="bd", recursive=False)
    content = body.find("div", class_="content", recursive=False) if body is not None else None
    if content is None:
        return None
    for line_break in content.find_all("br"):
        line_break.replace_with("\n")
    lines = [clean_text(line) for line in content.get_text("\n").splitlines()]
    text = "\n".join(line for line in lines if line)
    return text or None


def _publisher(rows: list[tuple[str, Tag]]) -> str | None:
    for label, li in rows:
        if label != "出版社":
            continue
        link = next((a for a in li.find_all("a", recursive=False) if "puballb" in (a.get("href") or "")), None)
        if link is not None:
            return clean_text(link.get_text(" ", strip=True))
        return _split_label(li)[1] or None
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


def _subjects(soup: BeautifulSoup) -> tuple[str, ...]:
    for sort_list in soup.select("ul.sort"):
        for li in sort_list.find_all("li", recursive=False):
            label, _ = _split_label(li)
            if label == "本書分類":
                names = [clean_text(a.get_text(" ", strip=True)) for a in li.find_all("a", recursive=False)]
                return tuple(dict.fromkeys(name for name in names if name))
    return ()


def _thumbnail(soup: BeautifulSoup, title: str) -> str | None:
    for img in soup.select("img.cover"):
        if clean_text(img.get("alt")) == title and img.get("src"):
            return img["src"]
    return None


def parse_detail_html(html: str, url: str) -> BookDraft:
    soup = BeautifulSoup(html, "html.parser")
    canonical_url = canonicalize_product_url(url)

    heading = soup.find("h1")
    title = clean_text(heading.get_text(" ", strip=True)) if heading is not None else None
    if title is None:
        raise ParseError(f"title (h1) not found on {canonical_url}")

    main = soup.select_one(".main_column") or soup
    rows = _labelled_rows(main)

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

    # Contributors come only from the block holding the publisher row (see module docstring).
    publisher_row = next((li for label, li in rows if label == "出版社"), None)
    info_block = publisher_row.find_parent("div", class_="type02_p003") if publisher_row is not None else None
    contributors = _contributors(info_block) if info_block is not None else ()

    return BookDraft(
        source_url=canonical_url,
        title=title,
        publisher=_publisher(rows),
        published_date=published_date,
        published_date_precision=precision,
        language=map_language(_first_value(rows, "語言")),
        description=_section_text(soup, "內容簡介"),
        table_of_contents=_section_text(soup, "目錄"),
        page_count=page_count,
        thumbnail_url=_thumbnail(soup, title),
        identifiers=identifiers,
        contributors=contributors,
        subjects=_subjects(soup),
    )
