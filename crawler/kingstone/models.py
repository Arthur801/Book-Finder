"""Kingstone adapter data: a parsed category list page and the items it lists (CB-07 source contract)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ListedItem:
    """One product card on a category list page.

    ``external_id`` is the 13-digit km_code (the Kingstone product number); ``source_url`` is the canonical detail
    page URL; ``list_url`` is the canonical list page the card was read from.
    """

    external_id: str
    source_url: str
    list_url: str


@dataclass(frozen=True)
class ListPage:
    """A parsed category list page. ``total_pages`` and ``total_count`` are None when the page does not show them."""

    url: str
    items: tuple[ListedItem, ...]
    total_pages: int | None
    total_count: int | None
    empty: bool


class KingstoneParseError(ValueError):
    """A Kingstone page does not have the structure the contract requires (for example a missing product list)."""


class ProductNotFound(Exception):
    """The detail page is a soft 404: HTTP 200 without a product. Not a parse error."""
