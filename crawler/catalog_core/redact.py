"""Secret redaction for provider-neutral crawler output (crawler.md §12).

The same rules as ``books_crawler/redact.py``, which predates this module and is left as it is for now (CB-07 backlog:
Books switches to this copy once its own change is allowed). Keep the two patterns identical until then.
"""

from __future__ import annotations

import re

_DSN = re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^\s'\"]+")
_PASSWORD = re.compile(r"(?i)\b(password|pwd)\s*=\s*(?:'[^']*'|\"[^\"]*\"|[^\s'\"&;,]+)")


def redact(text: str) -> str:
    """Replace database URLs and ``password=`` assignments with placeholders."""
    text = _DSN.sub("postgresql://<redacted>", text)
    return _PASSWORD.sub(lambda match: f"{match.group(1)}=<redacted>", text)
