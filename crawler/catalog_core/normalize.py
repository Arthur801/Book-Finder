"""ISBN normalization of ``Docs/data/data-model.md`` §7.1: the provider-neutral part of the Catalog normalization rules.

Every function returns ``None`` instead of guessing when a value cannot be interpreted reliably. Nothing here touches
the network or the database. The Books-specific text rules (``clean_text``, ``map_language``, ``parse_published_date``
and the role labels) stay in ``books_crawler.normalize``; ``clean_text`` and the contributor role rules are shared.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from catalog_core.models import ContributorRole, Identifier, IdentifierType
from catalog_core.unicode_15_1 import is_assigned

log = logging.getLogger("catalog_core.normalize")

# crawler.md §11.1: 博客來 contributor label → role. Unknown labels → OTHER.
ROLE_MAP: dict[str, ContributorRole] = {
    "作者": ContributorRole.AUTHOR,
    "原文作者": ContributorRole.ORIGINAL_AUTHOR,
    "譯者": ContributorRole.TRANSLATOR,
    "編者": ContributorRole.EDITOR,
    "繪者": ContributorRole.ILLUSTRATOR,
}

_WHITESPACE = re.compile(r"\s+")


# data-model 7.1: NFKC is pinned to Unicode 15.1. Code points not assigned in 15.1 pass through unchanged and split
# the input; NFKC runs only on each maximal run of assigned code points. Mirrors Application/Catalog/IsbnNormalizer.cs.
_NFKC_SAMPLE = "\U0001e030"  # MODIFIER LETTER CYRILLIC SMALL A, added in 15.0; <super> to U+0430
_NFKC_SAMPLE_RESULT = "\u0430"


def compose_compatibility(text: str) -> str:
    """NFKC of ``text`` applied per maximal run of Unicode 15.1-assigned code points (data-model 7.1)."""
    parts: list[str] = []
    run: list[str] = []
    for char in text:
        if is_assigned(ord(char)):
            run.append(char)
            continue
        if run:
            parts.append(unicodedata.normalize("NFKC", "".join(run)))
            run = []
        parts.append(char)
    if run:
        parts.append(unicodedata.normalize("NFKC", "".join(run)))
    return "".join(parts)


def ensure_runtime_unicode_supported() -> None:
    """Refuse to run on a runtime whose Unicode data is older than 15.0 (data-model 7.1). Called once at startup."""
    if unicodedata.normalize("NFKC", _NFKC_SAMPLE) != _NFKC_SAMPLE_RESULT:
        raise RuntimeError("The runtime's Unicode data is older than 15.0; ISBN normalization would be wrong.")


# data-model §7.1, step 2: every code point of the Unicode 15.1 White_Space property. Written out explicitly on
# purpose: str.isspace(), \s and char.IsWhiteSpace() disagree with this property (U+001C..U+001F, U+180E, U+200B).
WHITE_SPACE_CODE_POINTS = frozenset(
    {
        0x0009, 0x000A, 0x000B, 0x000C, 0x000D, 0x0020, 0x0085, 0x00A0, 0x1680,
        *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000,
    }
)  # fmt: skip
_REMOVED_CODE_POINTS = WHITE_SPACE_CODE_POINTS | {0x002D}  # plus HYPHEN-MINUS (data-model §7.1 step 2)


def normalize_isbn_value(raw: str) -> str:
    """The cross-language ISBN key of data-model §7.1 (may be empty).

    1. Unicode NFKC; 2. remove U+002D and the White_Space code points; 3. ASCII a-z to upper case only.
    No length or checksum validation. The result is what ``book_identifiers`` stores and matches on.
    """
    kept: list[str] = []
    for char in compose_compatibility(raw):
        if ord(char) in _REMOVED_CODE_POINTS:
            continue
        kept.append(char.upper() if "a" <= char <= "z" else char)
    return "".join(kept)


def normalize_isbn(raw: str | None) -> Identifier | None:
    """The ``ISBN`` identifier of a draft, or None when there is no value (data-model §7.1, §6.5).

    The value is not validated: a malformed or checksum-wrong ISBN is stored as it normalizes.
    """
    if raw is None:
        return None
    value = normalize_isbn_value(raw)
    if not value:
        return None
    return Identifier(IdentifierType.ISBN, value)


def clean_text(raw: str | None) -> str | None:
    """Collapse internal whitespace and strip. Empty → None."""
    if raw is None:
        return None
    value = _WHITESPACE.sub(" ", raw).strip()
    return value or None


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
