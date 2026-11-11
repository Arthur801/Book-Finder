"""Kingstone adapter data: parse errors and the soft-404 signal. The list types are provider-neutral (catalog_core)."""

from __future__ import annotations

from catalog_core.models import ListedItem, ListPage

__all__ = ["KingstoneParseError", "ListPage", "ListedItem", "ProductNotFound"]


class KingstoneParseError(ValueError):
    """A Kingstone page does not have the structure the contract requires (for example a missing product list)."""


class ProductNotFound(Exception):
    """The detail page is a soft 404: HTTP 200 without a product. Not a parse error."""
