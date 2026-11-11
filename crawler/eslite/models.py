"""Eslite adapter data: parse errors and the not-found signal. The list types are provider-neutral (catalog_core)."""

from __future__ import annotations

from catalog_core.models import ListedItem, ListPage

__all__ = ["EmptyCategory", "EsliteParseError", "ListPage", "ListedItem", "ProductNotFound"]


class EsliteParseError(ValueError):
    """An Eslite API response does not have the structure the contract requires (fail closed, never guess)."""


class EmptyCategory(EsliteParseError):
    """A list page whose ``total`` is 0: a missing category, an empty category or a level-2 category.

    Page 1 with ``total`` 0 is a failed page, not a legal zero-row page (CB-08 decision). A later page with
    ``total`` above 0 and no products is a legal empty page instead.
    """


class ProductNotFound(Exception):
    """The detail API answered with the 404 body: the product does not exist. Not a parse error."""
