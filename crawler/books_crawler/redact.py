"""Secret redaction for everything the crawler writes to the log (crawler.md §12).

The rules live in ``catalog_core.redact`` and are shared with the Kingstone adapter; this module keeps the
``books_crawler.redact`` import path the Books code and tests use.
"""

from __future__ import annotations

from catalog_core.redact import redact

__all__ = ["redact"]
