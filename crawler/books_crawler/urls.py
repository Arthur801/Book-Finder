"""Product URL canonicalization: the identity of a books.com.tw source.

ASSUMPTION (re-check against the real fixtures once captured):
    Product pages are addressed as ``https://www.books.com.tw/products/<id>`` where ``<id>``
    is alphanumeric (the documented examples are 10-digit numeric ids). Query strings
    (tracking parameters such as ``loc=``) and fragments carry no identity and are dropped.
    Relative paths and the ``books.com.tw`` host without ``www`` are accepted and normalized.

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
