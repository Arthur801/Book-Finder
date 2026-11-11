"""Eslite category list API parser (CB-08 列表 API): one JSON response per listed page.

Reads ``{total, page_no, page_size, products}``, the ``guid`` of each card and its ``is_age_restricted`` flag. A card flagged
``true`` is an age-restricted product: it is dropped from ``items`` and counted in ``excluded_count`` (no detail fetch, not
a failure). Other card fields are not read: the detail API is the source of truth. ``is_book`` is not used to filter
(CB-08 decision: non-book products are treated as books). Nothing here touches the network.
"""

from __future__ import annotations

import json
from typing import Any

from catalog_core.models import ListedItem, ListPage
from eslite.models import EmptyCategory, EsliteParseError
from eslite.urls import GUID_RE, canonical_list_url, category_and_page, product_url

_REQUIRED_KEYS = ("total", "page_no", "page_size", "products")


def parse_list_json(text: str, url: str) -> ListPage:
    """Parse one list API response for the canonical list page ``url`` (a caller error otherwise)."""
    if canonical_list_url(url) != url:
        raise ValueError("parse_list_json needs the canonical Eslite list page URL")
    _, requested_page = category_and_page(url)
    body = _json_object(text)
    for key in _REQUIRED_KEYS:
        if key not in body:
            raise EsliteParseError(f"list response has no {key}")
    total = _int_field(body, "total")
    listed_page = _int_field(body, "page_no")
    page_size = _int_field(body, "page_size")
    products = body["products"]
    if not isinstance(products, list):
        raise EsliteParseError("list response products is not a list")
    if total < 0:
        raise EsliteParseError("list response total is negative")
    if listed_page != requested_page:
        raise EsliteParseError(f"list response page_no {listed_page} does not match the requested page {requested_page}")
    if total == 0:
        raise EmptyCategory(f"list response total is 0 for {url}")

    total_pages = -(-total // page_size) if page_size > 0 else None
    if not products:
        return ListPage(url=url, items=(), total_pages=total_pages, total_count=total, empty=True)

    items: list[ListedItem] = []
    seen: set[str] = set()
    excluded = 0
    for index, card in enumerate(products, start=1):
        guid = _card_guid(card, index)
        if guid in seen:
            continue
        seen.add(guid)
        if _is_age_restricted(card, index):
            excluded += 1
            continue
        items.append(ListedItem(external_id=guid, source_url=product_url(guid), list_url=url))
    return ListPage(
        url=url,
        items=tuple(items),
        total_pages=total_pages,
        total_count=total,
        empty=False,
        excluded_count=excluded,
    )


def _json_object(text: str) -> dict[str, Any]:
    try:
        body = json.loads(text)
    except ValueError as exc:
        raise EsliteParseError("list response is not valid JSON") from exc
    if not isinstance(body, dict):
        raise EsliteParseError("list response is not a JSON object")
    return body


def _int_field(body: dict[str, Any], key: str) -> int:
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise EsliteParseError(f"list response {key} is not an integer")
    return value


def _card_guid(card: Any, index: int) -> str:
    if not isinstance(card, dict):
        raise EsliteParseError(f"product card {index} is not a JSON object")
    if "guid" not in card:
        raise EsliteParseError(f"product card {index} has no guid")
    guid = card["guid"]
    if not isinstance(guid, str) or GUID_RE.fullmatch(guid) is None:
        raise EsliteParseError(f"product card {index} has a guid that is not 16 to 23 digits")
    return guid


def _is_age_restricted(card: dict[str, Any], index: int) -> bool:
    """The card's ``is_age_restricted`` flag; a missing flag means not restricted. A non-bool flag is a parse error."""
    if "is_age_restricted" not in card:
        return False
    flag = card["is_age_restricted"]
    if not isinstance(flag, bool):
        raise EsliteParseError(f"product card {index} has an is_age_restricted that is not a boolean")
    return flag
