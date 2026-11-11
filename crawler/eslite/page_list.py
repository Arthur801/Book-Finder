"""The Eslite category list page file: which list pages a future pages run reads (CB-08 source contract).

Format: one URL per line in the accepted grammar (see ``eslite.urls``); ``#`` comments and blank lines are ignored;
duplicates are kept once; at most ``MAX_PAGES`` distinct URLs. Each listed page is read once; pagination is not
followed. The file rules live in ``catalog_core.page_list``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from catalog_core.page_list import PageListError, load_url_list
from catalog_core.redact import redact
from eslite.urls import canonical_list_url

__all__ = ["DEFAULT_PAGES_FILE", "MAX_PAGES", "PAGES_FILE_ENV", "PageListError", "load_page_urls", "resolve_pages_file"]

PAGES_FILE_ENV = "ESLITE_PAGES_FILE"
# crawler/eslite-pages.txt, located relative to the package, not the working directory.
DEFAULT_PAGES_FILE = Path(__file__).resolve().parent.parent / "eslite-pages.txt"
MAX_PAGES = 400
log = logging.getLogger("eslite.page_list")


def resolve_pages_file(raw: str) -> Path:
    """The page list path: the env var value when non-blank, otherwise the default file."""
    value = raw.strip()
    return Path(value) if value else DEFAULT_PAGES_FILE


def load_page_urls(path: Path) -> list[str]:
    """The canonical list page URLs of ``path``. Raises PageListError for an unreadable, invalid, empty or oversized file."""
    return load_url_list(
        path,
        canonical_list_url,
        kind="Eslite category list page URL",
        file_label="Eslite category list pages",
        url_label="Eslite category list page URLs",
        max_entries=MAX_PAGES,
        redact_message=redact,
        logger=log,
    )
