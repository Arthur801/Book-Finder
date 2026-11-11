"""Eslite URL grammar (CB-08 來源契約): list page canonicalization, list and detail API URLs, product URLs.

Only the accepted grammar is recognized; anything else returns None (or raises ValueError for the builders). Nothing
here touches the network.

The list file holds web category URLs ``https://www.eslite.com/category/3/<id>[?page=<n>]``; the crawler reads the
list API for them. Only level-3 categories (path segment ``3``) list products. ``page=1`` is the same page as no page,
so the canonical form omits it.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

SITE_HOST = "www.eslite.com"
API_HOST = "athena.eslite.com"
GUID_RE = re.compile(r"^[0-9]{16,23}$")
PAGE_SIZE = 40

_SITE_ORIGIN = f"https://{SITE_HOST}"
_API_ORIGIN = f"https://{API_HOST}"
_POSITIVE = r"[1-9][0-9]*"
_GUID = r"[0-9]{16,23}"
_CATEGORY_PATH = re.compile(rf"/category/3/({_POSITIVE})")
_PAGE_QUERY = re.compile(rf"page=({_POSITIVE})")
_LIST_API = re.compile(
    rf"{re.escape(_API_ORIGIN)}/api/v1/categories/({_POSITIVE})/products"
    rf"\?page_no=({_POSITIVE})&sort_type=date&sort_order=desc&page_size={PAGE_SIZE}&is_available=true"
)
_DETAIL_API = re.compile(rf"{re.escape(_API_ORIGIN)}/api/v4/products/({_GUID})/description")
_PRODUCT_URL = re.compile(rf"{re.escape(_SITE_ORIGIN)}/product/({_GUID})")


def _parse_list_url(url: str) -> tuple[str, int] | None:
    """(category id text, page) of a URL in the accepted grammar, or None. Does not check canonical form."""
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    # geturl() drops an empty query or fragment marker, so a raw URL that does not survive the round trip has one.
    if parts.geturl() != url or parts.scheme != "https" or parts.netloc != SITE_HOST or parts.fragment:
        return None
    path = _CATEGORY_PATH.fullmatch(parts.path)
    if path is None:
        return None
    if not parts.query:
        return path.group(1), 1
    page = _PAGE_QUERY.fullmatch(parts.query)
    if page is None:
        return None
    return path.group(1), int(page.group(1))


def canonical_list_url(url: str) -> str | None:
    """The canonical form of an Eslite category list page URL, or None when it is outside the accepted grammar.

    Accepted: ``https://www.eslite.com/category/3/<id>`` with an optional ``?page=<n>``; id and n are positive decimal
    integers without leading zeros. No other query key, no fragment, no userinfo or port, no trailing slash, and the
    host must be exactly ``www.eslite.com`` over https. The canonical form drops ``page=1``.
    """
    parsed = _parse_list_url(url)
    if parsed is None:
        return None
    category, page = parsed
    canonical = f"{_SITE_ORIGIN}/category/3/{category}"
    return canonical if page == 1 else f"{canonical}?page={page}"


def _canonical_parts(canonical: str) -> tuple[str, int]:
    if canonical_list_url(canonical) != canonical:
        raise ValueError("expected the canonical Eslite list page URL (https://www.eslite.com/category/3/<id>[?page=<n>])")
    parsed = _parse_list_url(canonical)
    assert parsed is not None  # canonical_list_url accepted it
    return parsed


def category_and_page(canonical: str) -> tuple[int, int]:
    """The category id and the page number of a canonical list page URL. Raises ValueError for anything else."""
    category, page = _canonical_parts(canonical)
    return int(category), page


def list_api_url(canonical: str) -> str:
    """The list API URL for a canonical list page URL (fixed parameter order, as the site's category page sends it)."""
    category, page = _canonical_parts(canonical)
    return f"{_API_ORIGIN}/api/v1/categories/{category}/products?page_no={page}&sort_type=date&sort_order=desc&page_size={PAGE_SIZE}&is_available=true"


def is_list_api_url(url: str) -> bool:
    """True only for the exact list API shape that ``list_api_url`` produces (any positive category id and page)."""
    return isinstance(url, str) and _LIST_API.fullmatch(url) is not None


def _require_guid(guid: str) -> str:
    if not isinstance(guid, str) or GUID_RE.fullmatch(guid) is None:
        raise ValueError("an Eslite product guid is 16 to 23 ASCII digits")
    return guid


def detail_api_url(guid: str) -> str:
    """The detail API URL of a product guid. Raises ValueError for a guid outside ``GUID_RE``."""
    return f"{_API_ORIGIN}/api/v4/products/{_require_guid(guid)}/description"


def guid_from_detail_api_url(url: str) -> str | None:
    """The guid of an exact detail API URL (``detail_api_url`` shape), otherwise None."""
    if not isinstance(url, str):
        return None
    match = _DETAIL_API.fullmatch(url)
    return None if match is None else match.group(1)


def product_url(guid: str) -> str:
    """The web product page of a guid: the Source's ``source_url``. Never requested by the crawler."""
    return f"{_SITE_ORIGIN}/product/{_require_guid(guid)}"


def guid_from_product_url(url: str) -> str | None:
    """The guid of an exact web product page URL (``product_url`` shape), otherwise None. The inverse of ``product_url``."""
    if not isinstance(url, str):
        return None
    match = _PRODUCT_URL.fullmatch(url)
    return None if match is None else match.group(1)
