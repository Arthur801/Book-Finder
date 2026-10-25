"""Pure normalization rules from ``Docs/data/data-model.md`` §2, §2.1, §5.4, §5.5. The ISBN rules (§7.1), ``clean_text`` and the contributor role rules live in ``catalog_core.normalize``.

Every function returns ``None`` (or the documented fallback) instead of guessing when a value
cannot be interpreted reliably. Nothing here touches the network or the database.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from books_crawler.models import PublishedDatePrecision
from catalog_core.normalize import clean_text

log = logging.getLogger("books_crawler.normalize")

# data-model §2.1: 博客來「語言」display text → BCP 47 code. Anything else becomes NULL.
LANGUAGE_MAP: dict[str, str] = {
    "繁體中文": "zh-TW",
    "簡體中文": "zh-CN",
    "英文": "en",
    "日文": "ja",
    "韓文": "ko",
}

# 2026, 2026/10, 2026/10/11 (also accepts - and . as separators). Anything else is not parsed.
_DATE = re.compile(r"^(\d{4})(?:[/.\-](\d{1,2})(?:[/.\-](\d{1,2}))?)?$")


def map_language(raw: str | None) -> str | None:
    """Map a 博客來 language label to a language code (data-model §2.1)."""
    value = clean_text(raw)
    if value is None:
        return None
    code = LANGUAGE_MAP.get(value)
    if code is None:
        log.warning("unmapped language label %r; storing NULL", value)
    return code


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
