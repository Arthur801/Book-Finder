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
