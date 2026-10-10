"""Pure normalization rules from ``Docs/data/data-model.md`` §2, §2.1, §5.3, §5.4, §5.5.

Every function returns ``None`` (or the documented fallback) instead of guessing when a value
cannot be interpreted reliably. Nothing here touches the network or the database.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from books_crawler.models import ContributorRole, Identifier, IdentifierType, PublishedDatePrecision

log = logging.getLogger("books_crawler.normalize")

# data-model §2.1: 博客來「語言」display text → BCP 47 code. Anything else becomes NULL.
LANGUAGE_MAP: dict[str, str] = {
    "繁體中文": "zh-TW",
    "簡體中文": "zh-CN",
    "英文": "en",
    "日文": "ja",
    "韓文": "ko",
}

# crawler.md §8: 博客來 contributor label → role. Unknown labels → OTHER.
ROLE_MAP: dict[str, ContributorRole] = {
    "作者": ContributorRole.AUTHOR,
    "原文作者": ContributorRole.ORIGINAL_AUTHOR,
    "譯者": ContributorRole.TRANSLATOR,
    "編者": ContributorRole.EDITOR,
    "繪者": ContributorRole.ILLUSTRATOR,
}

_WHITESPACE = re.compile(r"\s+")
_ISBN_SEPARATORS = re.compile(r"[\s\-‐-―]")
_ISBN_10 = re.compile(r"^\d{9}[\dX]$")
_ISBN_13 = re.compile(r"^97[89]\d{10}$")
# 2026, 2026/10, 2026/10/11 (also accepts - and . as separators). Anything else is not parsed.
_DATE = re.compile(r"^(\d{4})(?:[/.\-](\d{1,2})(?:[/.\-](\d{1,2}))?)?$")


def clean_text(raw: str | None) -> str | None:
    """Collapse internal whitespace and strip. Empty → None."""
    if raw is None:
        return None
    value = _WHITESPACE.sub(" ", raw).strip()
    return value or None


def map_language(raw: str | None) -> str | None:
    """Map a 博客來 language label to a language code (data-model §2.1)."""
    value = clean_text(raw)
    if value is None:
        return None
    code = LANGUAGE_MAP.get(value)
    if code is None:
        log.warning("unmapped language label %r; storing NULL", value)
    return code


def normalize_role_label(raw: str) -> str:
    """Strip whitespace and a trailing full-width or ASCII colon from a contributor label."""
    value = clean_text(raw) or ""
    return value.rstrip("：:").strip()


def map_contributor_role(raw: str) -> ContributorRole:
    """Map a 博客來 contributor label (作者 / 譯者 / ...) to a contributor role."""
    label = normalize_role_label(raw)
    role = ROLE_MAP.get(label)
    if role is None:
        log.debug("contributor label %r has no role mapping; using OTHER", label)
        return ContributorRole.OTHER
    return role


def _isbn10_valid(digits: str) -> bool:
    total = 0
    for position, char in enumerate(digits):
        value = 10 if char == "X" else int(char)
        total += (10 - position) * value
    return total % 11 == 0


def _isbn13_valid(digits: str) -> bool:
    total = sum(int(char) * (1 if index % 2 == 0 else 3) for index, char in enumerate(digits))
    return total % 10 == 0


def normalize_isbn(raw: str | None) -> Identifier | None:
    """Normalize and validate an ISBN-10 or ISBN-13 (data-model §5.3).

    Removes dashes and whitespace, uppercases, validates the format, and validates the
    checksum. ISBN-13 must start with 978 or 979. Invalid values return ``None``.
    """
    if raw is None:
        return None
    cleaned = _ISBN_SEPARATORS.sub("", raw).upper()
    if len(cleaned) == 10 and _ISBN_10.match(cleaned) and _isbn10_valid(cleaned):
        return Identifier(IdentifierType.ISBN_10, cleaned)
    if len(cleaned) == 13 and _ISBN_13.match(cleaned) and _isbn13_valid(cleaned):
        return Identifier(IdentifierType.ISBN_13, cleaned)
    log.warning("ignoring invalid ISBN %r", raw.strip())
    return None


def parse_published_date(raw: str | None) -> tuple[date | None, PublishedDatePrecision | None]:
    """Parse 出版日期 keeping its real precision (never fabricates missing parts).

    ``2026/10/11`` → (2026-10-11, DAY); ``2026/10`` → (2026-10-01, MONTH); ``2026`` →
    (2026-01-01, YEAR). The stored ``date`` for MONTH/YEAR is only a storage anchor; the
    precision column says which parts are real. Unparseable input → (None, None).
    """
    value = clean_text(raw)
    if value is None:
        return None, None
    match = _DATE.match(value)
    if match is None:
        log.warning("unparseable published date %r; storing NULL", value)
        return None, None
    year_text, month_text, day_text = match.groups()
    try:
        if day_text is not None:
            return date(int(year_text), int(month_text), int(day_text)), PublishedDatePrecision.DAY
        if month_text is not None:
            return date(int(year_text), int(month_text), 1), PublishedDatePrecision.MONTH
        return date(int(year_text), 1, 1), PublishedDatePrecision.YEAR
    except ValueError:
        log.warning("invalid calendar date %r; storing NULL", value)
        return None, None
