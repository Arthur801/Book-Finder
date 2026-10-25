"""Kingstone URL grammar (CB-07 source contract): list page canonicalization, detail URLs and card href parsing.

Only the accepted grammar is recognized; anything else returns None (or raises for ``detail_url``). Nothing here
touches the network.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

SITE_ORIGIN = "https://www.kingstone.com.tw"
SORT_KEYS = frozenset({"sa_desc", "pu_desc", "pu_asc", "pr_desc", "pr_asc"})
# The site default (by sales). A page with this sort and a page with no sort are the same page.
DEFAULT_SORT = "sa_desc"

_SITE_HOST = "www.kingstone.com.tw"
_LIST_PATH = re.compile(r"/book/([A-Za-z]{2,4})/")
_PAGE = re.compile(r"[1-9][0-9]*")
_KM_CODE = re.compile(r"[0-9]{13}")
_RELATIVE_DETAIL = re.compile(r"/basic/([0-9]{13})/(?:\?[A-Za-z0-9_=&.%\-]*)?")
_ABSOLUTE_DETAIL_PATH = re.compile(r"/basic/([0-9]{13})/")
_LIST_QUERY_KEYS = frozenset({"dis", "page", "sort"})


def canonical_list_url(raw: str) -> str | None:
    """The canonical form of a category list page URL, or None when it is outside the accepted grammar.

    Accepted: ``https://www.kingstone.com.tw/book/<code>/?dis=list&page=<n>[&sort=<key>]`` where code is 2–4 ASCII
    letters (lowercased in the result), n is a positive integer without leading zeros, and the query has no other or
    repeated keys. Query keys in any order give the same canonical form.

    ``sa_desc`` is the site's default sort, so it is the same page as an omitted sort: the canonical form drops it
    (``&sort=sa_desc`` and no sort give one URL). The other keys are kept as written.
    """
    if not isinstance(raw, str) or not raw.startswith("https://") or "#" in raw:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme != "https" or parts.netloc != _SITE_HOST:
        return None
    path = _LIST_PATH.fullmatch(parts.path)
    if path is None:
        return None
    values = _parse_list_query(parts.query)
    if values is None:
        return None
    if values.get("dis") != "list" or "page" not in values:
        return None
    page = values["page"]
    if _PAGE.fullmatch(page) is None:
        return None
    canonical = f"{SITE_ORIGIN}/book/{path.group(1).lower()}/?dis=list&page={page}"
    sort = values.get("sort")
    if sort is not None:
        if sort not in SORT_KEYS:
            return None
        if sort != DEFAULT_SORT:
            canonical += f"&sort={sort}"
    return canonical


def _parse_list_query(query: str) -> dict[str, str] | None:
    """The key/value pairs of a list query, or None when a pair is malformed, unknown or repeated."""
    if not query:
        return None
    values: dict[str, str] = {}
    for piece in query.split("&"):
        key, separator, value = piece.partition("=")
        if not separator or key not in _LIST_QUERY_KEYS or key in values:
            return None
        values[key] = value
    return values


def detail_url(km_code: str) -> str:
    """The canonical detail page URL for a 13-digit km_code. Raises ValueError for anything else."""
    if not isinstance(km_code, str) or _KM_CODE.fullmatch(km_code) is None:
        raise ValueError("a Kingstone km_code is exactly 13 ASCII digits")
    return f"{SITE_ORIGIN}/basic/{km_code}/"


def km_code_from_href(href: str) -> str | None:
    """The km_code of a product card link: a relative ``/basic/<km_code>/[?query]`` or the same URL on the site origin.

    Anything else (other hosts, schemes, ports, fragments, other paths) returns None.
    """
    if not isinstance(href, str) or "#" in href:
        return None
    relative = _RELATIVE_DETAIL.fullmatch(href)
    if relative is not None:
        return relative.group(1)
    if not href.startswith("https://"):
        return None
    try:
        parts = urlsplit(href)
    except ValueError:
        return None
    if parts.scheme != "https" or parts.netloc != _SITE_HOST:
        return None
    path = _ABSOLUTE_DETAIL_PATH.fullmatch(parts.path)
    if path is None:
        return None
    if parts.query and not re.fullmatch(r"[A-Za-z0-9_=&.%\-]*", parts.query):
        return None
    return path.group(1)
