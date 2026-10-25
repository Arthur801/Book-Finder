"""Kingstone product detail page parser (CB-07 來源契約「詳細頁解析」).

The page's machine-readable identity comes from the ``Product`` JSON-LD block (sku, name, isbn/gtin13, publisher,
datePublished, image). Everything that JSON-LD does not carry reliably (language, page count, contributors, subjects,
description, table of contents) is read from the visible page structure, as the contract requires. Only the listed
sections are read; the activity, related-theme, author-introduction and gift blocks are never touched.

Failures follow the contract's error classes: a soft 404 raises ``ProductNotFound``; any other page without the
expected structure raises ``KingstoneParseError`` (fail closed, never guess). Optional fields that are absent or
unreadable become None.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup, Tag

from catalog_core.html_text import text_with_line_breaks
from catalog_core.models import BookDraft, Contributor, ContributorRole, PublishedDatePrecision
from catalog_core.normalize import clean_text, normalize_isbn
from kingstone.models import KingstoneParseError, ProductNotFound
from kingstone.urls import km_code_from_detail_url

log = logging.getLogger("kingstone.parse_detail")

# CB-07 錯誤分類：soft 404 的 <title> 只有站名。
SOFT_404_TITLE = "金石堂"
_ROOT_SUBJECT = "中文書"
_AUTHOR_LABEL = "作者："
_TRANSLATOR_LABEL = "譯者："
_ENUMERATION_SEPARATOR = "、"
_ROLE_SEPARATOR = "/"
_NOISE_LINKS = frozenset({"追蹤", "?"})
_LANGUAGE_MAP = {"中文繁體": "zh-TW", "中文簡體": "zh-CN"}

_SCRIPT = 'script[type="application/ld+json"]'
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DIGITS = re.compile(r"[0-9]+")
# A whole original-language name in one bracket pair, with no bracket inside (half- or full-width).
_BRACKETED = re.compile(r"\([^()（）]*\)|（[^()（）]*）")


def parse_detail_html(html: str, url: str) -> BookDraft:
    """Parse one Kingstone detail page. ``url`` must be the canonical ``/basic/<km_code>/`` URL of that page."""
    km_code = _km_code(url)
    soup = BeautifulSoup(html, "html.parser")

    product = _product_json_ld(soup)
    if product is None:
        page_title = soup.title.get_text() if soup.title is not None else None
        if clean_text(page_title) == SOFT_404_TITLE:
            raise ProductNotFound(url)
        raise KingstoneParseError(f"no Product JSON-LD and the page is not the 404 page: {url}")

    if product.get("sku") != km_code:
        raise KingstoneParseError(f"JSON-LD sku {product.get('sku')!r} does not match the URL km_code {km_code}")
    title = _text_value(product.get("name"), "name", url)
    if title is None:
        raise KingstoneParseError(f"JSON-LD name is missing: {url}")

    spec = _spec_table(soup)
    published = _published_date(product.get("datePublished"))
    isbn = normalize_isbn(_text_value(product.get("isbn"), "isbn", url) or _text_value(product.get("gtin13"), "gtin13", url))

    return BookDraft(
        source_url=url,
        title=title,
        external_id=km_code,
        publisher=_publisher(product, url),
        published_date=published,
        published_date_precision=PublishedDatePrecision.DAY if published is not None else None,
        language=_language(spec),
        description=_section_text(soup, ".pdintro .panelCon"),
        table_of_contents=_section_text(soup, ".catalog .panelCon"),
        page_count=_page_count(spec),
        thumbnail_url=_thumbnail(product),
        identifiers=(isbn,) if isbn is not None else (),
        contributors=_contributors(soup),
        subjects=_subjects(soup),
    )


def _km_code(url: str) -> str:
    km_code = km_code_from_detail_url(url)
    if km_code is None:
        raise ValueError(f"not a canonical Kingstone detail URL (/basic/<13 digits>/): {url!r}")
    return km_code


def _json_ld_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        graph = data.get("@graph")
        items = [data, *(graph if isinstance(graph, list) else [])]
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def _is_product(item: dict[str, Any]) -> bool:
    types = item.get("@type")
    return "Product" in (types if isinstance(types, list) else [types])


def _product_json_ld(soup: BeautifulSoup) -> dict[str, Any] | None:
    """The first ``Product`` JSON-LD object, or None when the page has none.

    A script that mentions ``Product`` but is not valid JSON is a parse error, so a broken product block is never
    mistaken for a soft 404.
    """
    for script in soup.select(_SCRIPT):
        text = script.string if script.string is not None else script.get_text()
        if "Product" not in text:
            continue
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise KingstoneParseError("JSON-LD block that mentions Product is not valid JSON") from exc
        for item in _json_ld_items(data):
            if _is_product(item):
                return item
    return None


def _text_value(value: Any, field: str, url: str) -> str | None:
    """A cleaned string JSON-LD value; None when absent or blank; parse error when present but not a string."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise KingstoneParseError(f"JSON-LD {field} is not a string: {url}")
    return clean_text(value)


def _publisher(product: dict[str, Any], url: str) -> str | None:
    publisher = product.get("publisher")
    if not isinstance(publisher, dict):
        return None
    return _text_value(publisher.get("name"), "publisher.name", url)


def _published_date(raw: Any) -> date | None:
    if not isinstance(raw, str) or _DATE.fullmatch(raw) is None:
        if raw not in (None, ""):
            log.warning("unparseable Kingstone datePublished %r; storing NULL", raw)
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        log.warning("invalid Kingstone datePublished %r; storing NULL", raw)
        return None


def _thumbnail(product: dict[str, Any]) -> str | None:
    image = product.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, str) and image.strip():
        return image.strip()
    return None


def _spec_table(soup: BeautifulSoup) -> dict[str, str]:
    """The 規格表 as label → value. A value is the ``li.table_td`` that directly follows its ``li.table_th``."""
    values: dict[str, str] = {}
    for header in soup.select("li.table_th"):
        label = clean_text(header.get_text(" ", strip=True))
        cell = header.find_next_sibling("li")
        if label is None or cell is None or "table_td" not in (cell.get("class") or []):
            continue
        values.setdefault(label, clean_text(cell.get_text(" ", strip=True)) or "")
    return values


def _language(spec: dict[str, str]) -> str | None:
    raw = spec.get("語言")
    if not raw:
        return None
    code = _LANGUAGE_MAP.get(raw)
    if code is None:
        log.warning("unmapped Kingstone language %r; storing NULL", raw)
    return code


def _page_count(spec: dict[str, str]) -> int | None:
    raw = spec.get("頁數", "")
    if _DIGITS.fullmatch(raw) is None:
        return None
    count = int(raw)
    return count if count > 0 else None


def _section_text(soup: BeautifulSoup, selector: str) -> str | None:
    node = soup.select_one(selector)
    return text_with_line_breaks(node) if node is not None else None


def _role_and_name(piece: str) -> tuple[ContributorRole, str] | None:
    """A single name, optionally with a ``角色/`` prefix. Unprefixed names are AUTHOR; prefixed names are OTHER.

    Kingstone's role-prefix vocabulary is its own, not the Books.com.tw one. The E0 fixtures show only ``審訂/``,
    which has no Catalog role, so no prefix maps to a specific role until a fixture shows one.
    """
    value = clean_text(piece)
    if value is None:
        return None
    if _ROLE_SEPARATOR not in value:
        return ContributorRole.AUTHOR, value
    _, _, name = value.partition(_ROLE_SEPARATOR)
    cleaned = clean_text(name)
    if cleaned is None:
        return None
    return ContributorRole.OTHER, cleaned


def _author_pairs(unit: Tag) -> list[tuple[ContributorRole, str]]:
    pairs: list[tuple[ContributorRole, str]] = []
    for link in unit.find_all("a"):
        text = clean_text(link.get_text(" ", strip=True))
        if text is None or text in _NOISE_LINKS or _BRACKETED.fullmatch(text):
            # A fully bracketed link such as "(Gao Junqing)" is the original-language name, not a contributor.
            continue
        for piece in text.split(_ENUMERATION_SEPARATOR):
            pair = _role_and_name(piece)
            if pair is not None:
                pairs.append(pair)
    return pairs


def _translator_pairs(unit: Tag, label_tag: Tag) -> list[tuple[ContributorRole, str]]:
    # The translator row is plain text after its label; the label itself is not a name, and neither are the
    # follow/question-mark noise nodes that the author column also drops.
    parts = [str(part) for part in unit.find_all(string=True) if part.parent is not label_tag and clean_text(str(part)) not in _NOISE_LINKS]
    text = " ".join(parts)
    pairs: list[tuple[ContributorRole, str]] = []
    for piece in text.split(_ENUMERATION_SEPARATOR):
        name = clean_text(piece)
        if name is not None:
            pairs.append((ContributorRole.TRANSLATOR, name))
    return pairs


def _contributors(soup: BeautifulSoup) -> tuple[Contributor, ...]:
    contributors: list[Contributor] = []
    for unit in soup.select("li.basicunit"):
        label_tag = unit.select_one(".title_basic")
        if label_tag is None:
            continue
        label = clean_text(label_tag.get_text(" ", strip=True))
        if label == _AUTHOR_LABEL:
            pairs = _author_pairs(unit)
        elif label == _TRANSLATOR_LABEL:
            pairs = _translator_pairs(unit, label_tag)
        else:
            continue
        for role, name in pairs:
            contributors.append(Contributor(order=len(contributors) + 1, name=name, role=role))
    return tuple(contributors)


def _subjects(soup: BeautifulSoup) -> tuple[str, ...]:
    """Breadcrumb names in page order, de-duplicated (the page lists them twice), without the root 中文書."""
    names: list[str] = []
    for link in soup.select(".basic-category-breadcrumb a"):
        name = clean_text(link.get_text(" ", strip=True))
        if name is not None and name != _ROOT_SUBJECT:
            names.append(name)
    return tuple(dict.fromkeys(names))
