"""Product URL canonicalization: the identity of a books.com.tw Book Source.

Verified against the saved pages in ``crawler/tests/fixtures`` (2026-10-11): ranking rows and
detail pages link products as ``https://www.books.com.tw/products/<10 digits>`` with tracking
query strings such as ``?loc=P_0003_001`` or ``?loc=hot_003``. The query string carries no
identity and is dropped. The 100 ranking URLs of the saved chart are unique after canonicalization.

Accepted inputs: absolute ``http``/``https`` URLs on ``books.com.tw`` or ``www.books.com.tw``,
protocol-relative and root-relative paths. Anything else is not a product URL and is rejected.

Canonical form: ``https://www.books.com.tw/products/<id>`` (no trailing slash, no query).
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

SITE_ORIGIN = "https://www.books.com.tw"
_ACCEPTED_HOSTS = frozenset({"www.books.com.tw", "books.com.tw"})
_PRODUCT_PATH = re.compile(r"^/products/([0-9A-Za-z]+)/?$")
PAGE_URLS=[
    "https://www.books.com.tw/web/sys_saletopb/books/01/?attribute=7&loc=P_0002_002",
    "https://www.books.com.tw/web/sys_saletopb/books/02/?attribute=7&loc=P_0002_003",
    "https://www.books.com.tw/web/sys_saletopb/books/03/?attribute=7&loc=P_0002_004",
    "https://www.books.com.tw/web/sys_saletopb/books/04/?attribute=7&loc=P_0002_005",
    "https://www.books.com.tw/web/sys_saletopb/books/07/?attribute=7&loc=P_0002_006",
    "https://www.books.com.tw/web/sys_saletopb/books/12/?attribute=7&loc=P_0002_007",
    "https://www.books.com.tw/web/sys_saletopb/books/06/?attribute=7&loc=P_0002_008",
    "https://www.books.com.tw/web/sys_saletopb/books/08/?attribute=7&loc=P_0002_009",
    "https://www.books.com.tw/web/sys_saletopb/books/09/?attribute=7&loc=P_0002_010",
    "https://www.books.com.tw/web/sys_saletopb/books/10/?attribute=7&loc=P_0002_011",
    "https://www.books.com.tw/web/sys_saletopb/books/11/?attribute=7&loc=P_0002_012",
    "https://www.books.com.tw/web/sys_saletopb/books/14/?attribute=7&loc=P_0002_013",
    "https://www.books.com.tw/web/sys_saletopb/books/24/?attribute=7&loc=P_0002_014",
    "https://www.books.com.tw/web/sys_saletopb/books/13/?attribute=7&loc=P_0002_015",
    "https://www.books.com.tw/web/sys_saletopb/books/22/?attribute=7&loc=P_0002_016",
    "https://www.books.com.tw/web/sys_saletopb/books/15/?attribute=7&loc=P_0002_017",
    "https://www.books.com.tw/web/sys_saletopb/books/16/?attribute=7&loc=P_0002_018",
    "https://www.books.com.tw/web/sys_saletopb/books/17/?attribute=7&loc=P_0002_019",
    "https://www.books.com.tw/web/sys_saletopb/books/18/?attribute=7&loc=P_0002_020",
    "https://www.books.com.tw/web/sys_saletopb/books/19/?attribute=7&loc=P_0002_021",
    "https://www.books.com.tw/web/sys_saletopb/books/20/?attribute=7&loc=P_0002_022"
]

class InvalidProductUrl(ValueError):
    """The value cannot be identified as a books.com.tw product URL."""


def canonicalize_product_url(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        raise InvalidProductUrl("product URL is empty")
    absolute = urljoin(SITE_ORIGIN + "/", value)
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https") or parts.hostname not in _ACCEPTED_HOSTS:
        raise InvalidProductUrl(f"not a books.com.tw URL: {value!r}")
    match = _PRODUCT_PATH.match(parts.path)
    if match is None:
        raise InvalidProductUrl(f"not a product URL: {value!r}")
    return f"{SITE_ORIGIN}/products/{match.group(1)}"
