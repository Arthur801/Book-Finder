"""Secret redaction for everything the crawler writes to the log (crawler.md §12).

Error messages come from libraries (psycopg, Playwright, requests) and can echo a connection
string or a password. Every log line and every stored error message passes through ``redact``.
Both providers use this module; ``books_crawler.redact`` re-exports it.
"""

from __future__ import annotations

import re

_DSN = re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^\s'\"]+")
_PASSWORD = re.compile(r"(?i)\b(password|pwd)\s*=\s*(?:'[^']*'|\"[^\"]*\"|[^\s'\"&;,]+)")


def redact(text: str) -> str:
    """Replace database URLs and ``password=`` assignments with placeholders."""
    text = _DSN.sub("postgresql://<redacted>", text)
    return _PASSWORD.sub(lambda match: f"{match.group(1)}=<redacted>", text)
