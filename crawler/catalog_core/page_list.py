"""Shared file rules for provider page lists (category or list pages to import in pages mode).

File format: one URL per line; lines starting with ``#`` are comments; blank lines are ignored; surrounding
whitespace is trimmed; a UTF-8 BOM at the start is allowed. Each line is canonicalized by the provider; duplicates
(compared on the canonical value) are kept once, in first-seen order. Provider-specific URL grammars live with the
provider, not here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("catalog_core.page_list")


class PageListError(ValueError):
    """The page list cannot be used. The message names the file and, where relevant, the line."""


def _identity(text: str) -> str:
    return text


def load_url_list(
    path: Path,
    canonicalize: Callable[[str], str | None],
    *,
    kind: str,
    file_label: str,
    url_label: str,
    max_entries: int | None = None,
    logger: logging.Logger = log,
    redact_message: Callable[[str], str] = _identity,
) -> list[str]:
    """Read a page list file and return its canonical URLs.

    ``canonicalize`` returns the canonical URL for a stripped, non-comment line, or None when the line is invalid.
    ``kind`` names the URL in the invalid-line message ("not a {kind}"). ``file_label`` names the file in the read
    error ("cannot read {file_label} file {path}") and ``url_label`` names the URLs in the empty-list and limit
    errors. Error messages never echo the line text: a line may carry credentials. ``redact_message`` is applied to
    read errors, which can echo library text.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise PageListError(redact_message(f"cannot read {file_label} file {path}: {exc}")) from exc
    urls: list[str] = []
    seen: set[str] = set()
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        canonical = canonicalize(line)
        if canonical is None:
            raise PageListError(f"{path} line {number}: not a {kind}")
        if canonical in seen:
            logger.info("dropped duplicate %s at %s line %d: %s", kind, path, number, canonical)
            continue
        seen.add(canonical)
        urls.append(canonical)
    if not urls:
        raise PageListError(f"{path}: no {url_label}")
    if max_entries is not None and len(urls) > max_entries:
        raise PageListError(f"{path}: more than {max_entries} distinct {url_label}")
    return urls
