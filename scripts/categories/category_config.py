"""Load and validate the TOML rule files into frozen dataclasses.

Pure: reads files under one config directory, never touches the database or the network. Any problem raises
ConfigError, which the CLI turns into exit code 2 with the message printed.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CATEGORIES_FILE = "canonical_categories.toml"
PROVIDER_ROOTS_FILE = "provider_roots.toml"
MANUAL_FILE = "subject_mappings.toml"

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SLUG_MAX = 100
DISPLAY_NAME_MAX = 100
SUBJECT_MAX = 255
SOURCE_CODE_MAX = 64
LEVEL2_ID_PATTERN = re.compile(r"^[1-9][0-9]*$")
ESLITE_SOURCE = "ESLITE"

_CATEGORY_KEYS = frozenset({"slug", "display_name", "sort_order", "is_active"})
_MANUAL_KEYS = frozenset({"source_code", "subject", "slug", "root", "note"})


class ConfigError(Exception):
    """A rule file, or the derived level-3 TSV, is malformed or inconsistent."""


@dataclass(frozen=True)
class CanonicalCategory:
    slug: str
    display_name: str
    sort_order: int
    is_active: bool = True


@dataclass(frozen=True)
class ProviderRoot:
    """A source's top-level subject (or ESLITE level-2 id) that maps to a canonical slug."""

    source_code: str
    root: str
    slug: str


@dataclass(frozen=True)
class ManualMapping:
    source_code: str
    subject: str
    slug: str
    root: str
    note: str = ""


@dataclass(frozen=True)
class Rules:
    categories: tuple[CanonicalCategory, ...]
    provider_roots: tuple[ProviderRoot, ...]
    manual_mappings: tuple[ManualMapping, ...]


def load_rules(config_dir: Path) -> Rules:
    """Read and validate the three TOML rule files in ``config_dir``."""
    categories = _parse_categories(_read_toml(config_dir / CATEGORIES_FILE))
    slugs = {c.slug for c in categories}
    provider_roots = _parse_provider_roots(_read_toml(config_dir / PROVIDER_ROOTS_FILE), slugs)
    manual = _parse_manual(_read_toml(config_dir / MANUAL_FILE), slugs)
    return Rules(categories=categories, provider_roots=provider_roots, manual_mappings=manual)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"{path.name}: cannot read rule file ({exc.strerror})") from exc
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path.name}: not valid TOML ({exc})") from exc


def _check_keys(item: dict[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(item) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)}")


def _get_str(item: dict[str, Any], key: str, where: str, *, allow_empty: bool = False) -> str:
    if key not in item:
        raise ConfigError(f"{where}: missing required key '{key}'")
    value = item[key]
    if not isinstance(value, str):
        raise ConfigError(f"{where}: {key} must be a string")
    if not allow_empty and value.strip() == "":
        raise ConfigError(f"{where}: {key} must not be empty")
    return value


def _check_max(value: str, key: str, where: str, max_len: int) -> None:
    if len(value) > max_len:
        raise ConfigError(f"{where}: {key} must be at most {max_len} characters")


def _parse_categories(data: dict[str, Any]) -> tuple[CanonicalCategory, ...]:
    entries = data.get("category")
    if not entries:
        raise ConfigError(f"{CATEGORIES_FILE}: no [[category]] entries")
    categories: list[CanonicalCategory] = []
    seen_slugs: set[str] = set()
    seen_orders: set[int] = set()
    for index, item in enumerate(entries, start=1):
        where = f"{CATEGORIES_FILE} [[category]] #{index}"
        _check_keys(item, _CATEGORY_KEYS, where)
        slug = _get_str(item, "slug", where)
        if len(slug) > SLUG_MAX or not SLUG_PATTERN.fullmatch(slug):
            raise ConfigError(f"{where}: invalid slug {slug!r} (lowercase letters, digits and single hyphens)")
        if slug in seen_slugs:
            raise ConfigError(f"{where}: duplicate slug {slug!r}")
        seen_slugs.add(slug)
        display_name = _get_str(item, "display_name", where)
        _check_max(display_name, "display_name", where, DISPLAY_NAME_MAX)
        sort_order = item.get("sort_order")
        if not isinstance(sort_order, int) or isinstance(sort_order, bool):
            raise ConfigError(f"{where}: sort_order must be an integer")
        if sort_order in seen_orders:
            raise ConfigError(f"{where}: duplicate sort_order {sort_order}")
        seen_orders.add(sort_order)
        is_active = item.get("is_active", True)
        if not isinstance(is_active, bool):
            raise ConfigError(f"{where}: is_active must be a boolean")
        categories.append(CanonicalCategory(slug, display_name, sort_order, is_active))
    return tuple(categories)


def _parse_provider_roots(data: dict[str, Any], slugs: set[str]) -> tuple[ProviderRoot, ...]:
    roots: list[ProviderRoot] = []
    for source_code, table in data.items():
        where = f"{PROVIDER_ROOTS_FILE} [{source_code}]"
        if not isinstance(table, dict):
            raise ConfigError(f"{where}: must be a table of root = slug pairs")
        if source_code.strip() == "" or len(source_code) > SOURCE_CODE_MAX:
            raise ConfigError(f"{where}: source_code must not be empty and at most {SOURCE_CODE_MAX} characters")
        for root, slug in table.items():
            if root.strip() == "":
                raise ConfigError(f"{where}: root key must not be empty")
            if len(root) > SUBJECT_MAX:
                raise ConfigError(f"{where}: root key {root!r} is longer than {SUBJECT_MAX} characters")
            if source_code == ESLITE_SOURCE and not LEVEL2_ID_PATTERN.fullmatch(root):
                raise ConfigError(f"{where}: ESLITE root key {root!r} must be a positive integer (level-2 id)")
            if not isinstance(slug, str):
                raise ConfigError(f"{where}: value for {root!r} must be a string slug")
            if slug not in slugs:
                raise ConfigError(f"{where}: {root!r} points to unknown slug {slug!r}")
            roots.append(ProviderRoot(source_code=source_code, root=root, slug=slug))
    return tuple(roots)


def _parse_manual(data: dict[str, Any], slugs: set[str]) -> tuple[ManualMapping, ...]:
    entries = data.get("mapping", [])
    mappings: list[ManualMapping] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(entries, start=1):
        where = f"{MANUAL_FILE} [[mapping]] #{index}"
        _check_keys(item, _MANUAL_KEYS, where)
        source_code = _get_str(item, "source_code", where)
        _check_max(source_code, "source_code", where, SOURCE_CODE_MAX)
        subject = _get_str(item, "subject", where)
        _check_max(subject, "subject", where, SUBJECT_MAX)
        slug = _get_str(item, "slug", where)
        root = _get_str(item, "root", where)
        _check_max(root, "root", where, SUBJECT_MAX)
        note = item.get("note", "")
        if not isinstance(note, str):
            raise ConfigError(f"{where}: note must be a string")
        if slug not in slugs:
            raise ConfigError(f"{where}: unknown slug {slug!r}")
        key = (source_code, subject)
        if key in seen:
            raise ConfigError(f"{where}: duplicate mapping for {source_code} / {subject!r}")
        seen.add(key)
        mappings.append(ManualMapping(source_code, subject, slug, root, note))
    return tuple(mappings)
