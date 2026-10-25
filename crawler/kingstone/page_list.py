"""The Kingstone category list page file: which list pages a future pages run reads (CB-07 source contract).

Format: one URL per line in the accepted grammar (see ``kingstone.urls``); ``#`` comments and blank lines are
ignored; duplicates are kept once; at most ``MAX_PAGES`` distinct URLs. Each listed page is read once; pagination
is not followed. The file rules live in ``catalog_core.page_list``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from catalog_core.page_list import PageListError, load_url_list
from kingstone.urls import canonical_list_url

__all__ = ["DEFAULT_PAGES_FILE", "MAX_PAGES", "PAGES_FILE_ENV", "PageListError", "load_page_urls", "resolve_pages_file"]

PAGES_FILE_ENV = "KINGSTONE_PAGES_FILE"
# crawler/kingstone-pages.txt, located relative to the package, not the working directory.
DEFAULT_PAGES_FILE = Path(__file__).resolve().parent.parent / "kingstone-pages.txt"
MAX_PAGES = 200
log = logging.getLogger("kingstone.page_list")


def resolve_pages_file(raw: str) -> Path:
    """The page list path: the env var value when non-blank, otherwise the default file."""
    value = raw.strip()
    return Path(value) if value else DEFAULT_PAGES_FILE


def load_page_urls(path: Path) -> list[str]:
    """The canonical list page URLs of ``path``. Raises PageListError for an unreadable, invalid, empty or oversized file."""
    return load_url_list(
        path,
        canonical_list_url,
        kind="Kingstone category list page URL",
        file_label="Kingstone category list pages",
        url_label="Kingstone category list page URLs",
        max_entries=MAX_PAGES,
        logger=log,
    )
