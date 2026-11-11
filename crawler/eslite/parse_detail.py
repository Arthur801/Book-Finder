"""Eslite product detail API parser (CB-08 詳細 API): one JSON response per New Source.

Reads the fields the contract needs from ``GET /api/v4/products/<guid>/description``. A body that is exactly the 404
shape is ``ProductNotFound``; any other body without the expected structure raises ``EsliteParseError`` (fail closed).
Optional fields that are absent or null become None. Nothing here touches the network.

Contributor rules (CB-08 decision, documented here because the contract leaves them to the parser):

- ``author`` splits on ``;`` into groups and each group on ``/`` into pieces. A piece that is exactly a role word
  sets the role of the name pieces before it in the same group that do not have a role yet (so ``甲/乙/編`` makes both
  editors). A role word with no such name before it is a parse error. Other names are AUTHOR.
- ``translator`` is TRANSLATOR, ``compiler`` EDITOR, ``painter`` ILLUSTRATOR; each splits on ``/``.
- A bare ``等`` piece is never a name (it is the "et al." marker), in any of these fields.
- An exact duplicate (name, role) is kept once; order is 1..n in the sequence above.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from catalog_core.html_text import text_with_line_breaks
from catalog_core.models import BookDraft, Contributor, ContributorRole, Identifier, PublishedDatePrecision
from catalog_core.normalize import clean_text, normalize_isbn
from eslite.models import EsliteParseError, ProductNotFound, RestrictedProduct
from eslite.urls import GUID_RE, product_url

log = logging.getLogger("eslite.parse_detail")

NOT_FOUND_MESSAGE = "Product not found"
_LANGUAGE_MAP = {"中文/繁體": "zh-TW", "中文/簡體": "zh-CN"}
_LANGUAGE_PREFIX = re.compile(r"[0-9]+:")
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T00:00:00\.000\+08:00")
_DIGITS = re.compile(r"[0-9]+")
_EAN13_ISBN = re.compile(r"97[89][0-9]{10}")
_ETC = "等"
_EDITOR_ROLE_WORDS = frozenset({"編", "主編", "編著", "編者"})
_OTHER_ROLE_WORDS = frozenset({"策劃", "策畫", "總策劃", "總策畫"})
_DESCRIPTION_NAME = "內容簡介"
_TOC_NAMES = ("產品目錄", "目錄")


def parse_detail_json(text: str, guid: str) -> BookDraft:
    """Parse one detail API response for product ``guid`` (a caller error when the guid is malformed)."""
    if not isinstance(guid, str) or GUID_RE.fullmatch(guid) is None:
        raise ValueError("an Eslite product guid is 16 to 23 ASCII digits")
    body = _json_object(text)
    if body.get("message") == NOT_FOUND_MESSAGE and "product_guid" not in body:
        raise ProductNotFound(guid)
    if body.get("product_guid") != guid:
        raise EsliteParseError(f"detail product_guid {body.get('product_guid')!r} does not match the requested guid")
    if "restricted" in body:
        restricted = body["restricted"]
        if not isinstance(restricted, bool):
            raise EsliteParseError("detail restricted is not a boolean")
        if restricted:
            raise RestrictedProduct(guid)

    title = _required_text(body, "product_name")
    publisher = _optional_text(body, "manufacturer")
    published = _published_date(_optional_text(body, "manufacturer_date"))
    short_description = _optional_text(body, "short_description")
    language = _language(_specifications(body))
    descriptions = _html_entries(body)

    description = _html_section(descriptions, (_DESCRIPTION_NAME,))
    if description is None:
        description = short_description

    return BookDraft(
        source_url=product_url(guid),
        title=title,
        external_id=guid,
        publisher=publisher,
        published_date=published,
        published_date_precision=PublishedDatePrecision.DAY if published is not None else None,
        language=language,
        description=description,
        table_of_contents=_html_section(descriptions, _TOC_NAMES),
        page_count=_page_count(_specifications(body)),
        thumbnail_url=_thumbnail(body),
        identifiers=_identifiers(body),
        contributors=_contributors(body),
        subjects=_subjects(body),
    )


def _json_object(text: str) -> dict[str, Any]:
    try:
        body = json.loads(text)
    except ValueError as exc:
        raise EsliteParseError("detail response is not valid JSON") from exc
    if not isinstance(body, dict):
        raise EsliteParseError("detail response is not a JSON object")
    return body


def _optional_text(body: dict[str, Any], key: str) -> str | None:
    """A cleaned text field; None when absent, null or blank; parse error when present but not a string."""
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise EsliteParseError(f"detail {key} is not a string")
    return clean_text(value)


def _required_text(body: dict[str, Any], key: str) -> str:
    value = _optional_text(body, key)
    if value is None:
        raise EsliteParseError(f"detail {key} is missing or blank")
    return value


def _list_field(body: dict[str, Any], key: str) -> list[Any]:
    """A list field; absent or null means no entries, any other non-list is a parse error."""
    value = body.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise EsliteParseError(f"detail {key} is not a list")
    return value


def _published_date(raw: str | None) -> date | None:
    """The calendar date of ``YYYY-MM-DDT00:00:00.000+08:00``; any other shape, or an invalid day, is None."""
    if raw is None:
        return None
    match = _DATE.fullmatch(raw)
    if match is None:
        log.warning("unrecognized Eslite manufacturer_date %r; storing NULL", raw)
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        log.warning("invalid Eslite manufacturer_date %r; storing NULL", raw)
        return None


def _identifiers(body: dict[str, Any]) -> tuple[Identifier, ...]:
    """ISBN identifiers: isbn13 (or ean when isbn13 is empty and ean is a 978/979 13-digit code), then isbn10."""
    isbn13 = _optional_text(body, "isbn13")
    ean = _optional_text(body, "ean")
    isbn10 = _optional_text(body, "isbn10")
    first = isbn13
    if first is None and ean is not None and _EAN13_ISBN.fullmatch(ean):
        first = ean
    identifiers: list[Identifier] = []
    for raw in (first, isbn10):
        identifier = normalize_isbn(raw)
        if identifier is not None and identifier not in identifiers:
            identifiers.append(identifier)
    return tuple(identifiers)


def _contributors(body: dict[str, Any]) -> tuple[Contributor, ...]:
    pairs = _author_pairs(_optional_text(body, "author"))
    pairs += _name_pairs(_optional_text(body, "translator"), ContributorRole.TRANSLATOR)
    pairs += _name_pairs(_optional_text(body, "compiler"), ContributorRole.EDITOR)
    pairs += _name_pairs(_optional_text(body, "painter"), ContributorRole.ILLUSTRATOR)
    contributors: list[Contributor] = []
    seen: set[tuple[str, ContributorRole]] = set()
    for role, name in pairs:
        if (name, role) in seen:
            continue
        seen.add((name, role))
        contributors.append(Contributor(order=len(contributors) + 1, name=name, role=role))
    return tuple(contributors)


def _name_pairs(text: str | None, role: ContributorRole) -> list[tuple[ContributorRole, str]]:
    if text is None:
        return []
    pairs: list[tuple[ContributorRole, str]] = []
    for piece in text.split("/"):
        name = clean_text(piece)
        if name is not None and name != _ETC:
            pairs.append((role, name))
    return pairs


def _author_pairs(text: str | None) -> list[tuple[ContributorRole, str]]:
    """Names of the author field. A role word sets the role of the unassigned names before it in its group."""
    if text is None:
        return []
    pairs: list[tuple[ContributorRole, str]] = []
    for group in text.split(";"):
        entries: list[list[Any]] = []  # [role or None, name]; None until a role word claims it
        for piece in group.split("/"):
            value = clean_text(piece)
            if value is None or value == _ETC:
                continue
            if value in _EDITOR_ROLE_WORDS or value in _OTHER_ROLE_WORDS:
                claimed = [entry for entry in entries if entry[0] is None]
                if not claimed:
                    raise EsliteParseError(f"author role word {value!r} has no name before it")
                role = ContributorRole.EDITOR if value in _EDITOR_ROLE_WORDS else ContributorRole.OTHER
                for entry in claimed:
                    entry[0] = role
            else:
                entries.append([None, value])
        for role, name in entries:
            pairs.append((ContributorRole.AUTHOR if role is None else role, name))
    return pairs


def _specifications(body: dict[str, Any]) -> dict[str, str]:
    """The 規格 tag → cleaned name map (first entry of a tag wins; blank names are absent)."""
    values: dict[str, str] = {}
    for spec in _list_field(body, "product_specifications"):
        if not isinstance(spec, dict):
            raise EsliteParseError("detail product_specifications entry is not an object")
        tag, name = spec.get("tag"), spec.get("name")
        if not isinstance(tag, str) or (name is not None and not isinstance(name, str)):
            raise EsliteParseError("detail product_specifications entry has a non-string tag or name")
        cleaned = clean_text(name)
        if cleaned is not None:
            values.setdefault(tag, cleaned)
    return values


def _language(specs: dict[str, str]) -> str | None:
    raw = specs.get("language")
    if raw is None:
        return None
    code = _LANGUAGE_MAP.get(_LANGUAGE_PREFIX.sub("", raw, count=1))
    if code is None:
        log.warning("unmapped Eslite language %r; storing NULL", raw)
    return code


def _page_count(specs: dict[str, str]) -> int | None:
    raw = specs.get("pages")
    if raw is None or _DIGITS.fullmatch(raw) is None:
        return None
    count = int(raw)
    return count if count > 0 else None


def _html_entries(body: dict[str, Any]) -> dict[str, str]:
    """descriptions entries as name → raw HTML (first entry of a name wins)."""
    entries: dict[str, str] = {}
    for entry in _list_field(body, "descriptions"):
        if not isinstance(entry, dict):
            raise EsliteParseError("detail descriptions entry is not an object")
        name = _optional_text(entry, "name")
        html = entry.get("description")
        if html is not None and not isinstance(html, str):
            raise EsliteParseError("detail descriptions entry description is not a string")
        if name is not None and html is not None:
            entries.setdefault(name, html)
    return entries


def _html_section(entries: dict[str, str], names: tuple[str, ...]) -> str | None:
    """The first of ``names`` whose HTML has text, as line-preserving plain text."""
    for name in names:
        html = entries.get(name)
        if html is None:
            continue
        text = text_with_line_breaks(BeautifulSoup(html, "html.parser"))
        if text is not None:
            return text
    return None


def _thumbnail(body: dict[str, Any]) -> str | None:
    photos = _list_field(body, "photos")
    if not photos:
        return None
    default_id = body.get("default_product_photo_id")
    if default_id is not None and (isinstance(default_id, bool) or not isinstance(default_id, int)):
        raise EsliteParseError("detail default_product_photo_id is not an integer")
    chosen: dict[str, Any] | None = None
    for photo in photos:
        if not isinstance(photo, dict):
            raise EsliteParseError("detail photos entry is not an object")
        photo_id = photo.get("id")
        if isinstance(photo_id, bool) or not isinstance(photo_id, int):
            raise EsliteParseError("detail photos entry id is not an integer")
        if chosen is None and photo_id == default_id:
            chosen = photo
    if chosen is None:
        chosen = photos[0]
    path = chosen.get("original_path")
    if path is None:
        return None
    if not isinstance(path, str):
        raise EsliteParseError("detail photos entry original_path is not a string")
    path = path.strip()
    return path if path.startswith("https://") else None


def _subjects(body: dict[str, Any]) -> tuple[str, ...]:
    """The third-level category name only; level-2 names carry promotional text and are not subjects."""
    name = _optional_text(body, "level3_name")
    return (name,) if name else ()
