"""Rule-file loading and validation (category_config.py). No database, no network."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from category_config import ConfigError, load_rules

VALID_CATEGORIES = """
[[category]]
slug = "literature"
display_name = "文學小說"
sort_order = 1

[[category]]
slug = "comics-light-novels"
display_name = "漫畫與輕小說"
sort_order = 2
is_active = false
"""

VALID_ROOTS = """
[BOOKS_COM_TW]
"文學小說" = "literature"

[KINGSTONE]
"文學" = "literature"

[ESLITE]
"28" = "literature"  # 📌文學館79折起
"""

VALID_MANUAL = """
[[mapping]]
source_code = "BOOKS_COM_TW"
subject = "童書"
slug = "literature"
root = "文學小說"
note = "例外"
"""


def write_config(directory: Path, categories: str = VALID_CATEGORIES, roots: str = VALID_ROOTS, manual: str = VALID_MANUAL) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "canonical_categories.toml").write_text(categories, encoding="utf-8")
    (directory / "provider_roots.toml").write_text(roots, encoding="utf-8")
    (directory / "subject_mappings.toml").write_text(manual, encoding="utf-8")
    return directory


def test_loads_valid_rules(tmp_path: Path) -> None:
    rules = load_rules(write_config(tmp_path))

    assert [c.slug for c in rules.categories] == ["literature", "comics-light-novels"]
    assert rules.categories[0].display_name == "文學小說"
    assert rules.categories[0].sort_order == 1
    assert rules.categories[0].is_active is True
    assert rules.categories[1].is_active is False
    assert {(r.source_code, r.root, r.slug) for r in rules.provider_roots} == {
        ("BOOKS_COM_TW", "文學小說", "literature"),
        ("KINGSTONE", "文學", "literature"),
        ("ESLITE", "28", "literature"),
    }
    assert len(rules.manual_mappings) == 1
    manual = rules.manual_mappings[0]
    assert (manual.source_code, manual.subject, manual.slug, manual.root, manual.note) == (
        "BOOKS_COM_TW",
        "童書",
        "literature",
        "文學小說",
        "例外",
    )


def test_manual_note_is_optional(tmp_path: Path) -> None:
    manual = VALID_MANUAL.replace('note = "例外"\n', "")
    rules = load_rules(write_config(tmp_path, manual=manual))

    assert rules.manual_mappings[0].note == ""


def test_empty_manual_file_is_valid(tmp_path: Path) -> None:
    rules = load_rules(write_config(tmp_path, manual="# only a comment\n"))

    assert rules.manual_mappings == ()


@pytest.mark.parametrize(
    ("categories", "message"),
    [
        (
            VALID_CATEGORIES + '\n[[category]]\nslug = "literature"\ndisplay_name = "重複"\nsort_order = 9\n',
            "duplicate slug",
        ),
        (VALID_CATEGORIES.replace('slug = "literature"', 'slug = "Literature"', 1), "invalid slug"),
        (VALID_CATEGORIES.replace('slug = "literature"', 'slug = "lit--erature"', 1), "invalid slug"),
        (VALID_CATEGORIES.replace('slug = "literature"', 'slug = "' + "a" * 101 + '"', 1), "invalid slug"),
        (VALID_CATEGORIES.replace('display_name = "文學小說"', 'display_name = "   "', 1), "display_name"),
        (VALID_CATEGORIES.replace('display_name = "文學小說"', 'display_name = "' + "字" * 101 + '"', 1), "display_name"),
        (VALID_CATEGORIES.replace("sort_order = 2", "sort_order = 1"), "duplicate sort_order"),
        (VALID_CATEGORIES.replace("is_active = false", 'is_active = "no"'), "is_active"),
        (VALID_CATEGORIES.replace("sort_order = 2", 'sort_order = "2"'), "sort_order"),
        (VALID_CATEGORIES.replace("sort_order = 2", "sort_ordr = 2"), "unknown key"),
        ("# no categories at all\n", "no [[category]]"),
    ],
)
def test_rejects_invalid_categories(tmp_path: Path, categories: str, message: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(message)):
        load_rules(write_config(tmp_path, categories=categories))


@pytest.mark.parametrize(
    ("roots", "message"),
    [
        ('[BOOKS_COM_TW]\n"文學小說" = "no-such-slug"\n', "unknown slug"),
        ('[BOOKS_COM_TW]\n"" = "literature"\n', "empty"),
        ('[BOOKS_COM_TW]\n"   " = "literature"\n', "empty"),
        ('[BOOKS_COM_TW]\n"' + "x" * 256 + '" = "literature"\n', "255"),
        ('[BOOKS_COM_TW]\n"文學" = 3\n', "must be a string"),
        ('[ESLITE]\n"abc" = "literature"\n', "positive integer"),
        ('[ESLITE]\n"0" = "literature"\n', "positive integer"),
        ('[ESLITE]\n"-5" = "literature"\n', "positive integer"),
        ('[ESLITE]\n"01" = "literature"\n', "positive integer"),
        ('[ESLITE]\n"" = "literature"\n', "must not be empty"),
        ('[ESLITE]\n"28" = "nope"\n', "unknown slug"),
        ('[BOOKS_COM_TW]\n"文學" = "literature"\n[BOOKS_COM_TW.bad]\n', "must be a string"),
        ("root = 1\n", "must be a table"),
        ("[BOOKS_COM_TW\n", "valid TOML"),
    ],
)
def test_rejects_invalid_provider_roots(tmp_path: Path, roots: str, message: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(message)):
        load_rules(write_config(tmp_path, roots=roots))


def test_rejects_provider_root_source_code_that_is_too_long(tmp_path: Path) -> None:
    roots = "[" + "S" * 65 + ']\n"文學" = "literature"\n'
    with pytest.raises(ConfigError, match="source_code"):
        load_rules(write_config(tmp_path, roots=roots))


@pytest.mark.parametrize(
    ("manual", "message"),
    [
        (VALID_MANUAL + VALID_MANUAL, "duplicate"),
        (VALID_MANUAL.replace('slug = "literature"', 'slug = "nope"'), "unknown slug"),
        (VALID_MANUAL.replace('source_code = "BOOKS_COM_TW"', 'source_code = ""'), "empty"),
        (VALID_MANUAL.replace('subject = "童書"', 'subject = ""'), "empty"),
        (VALID_MANUAL.replace('root = "文學小說"', 'root = ""'), "empty"),
        (VALID_MANUAL.replace('subject = "童書"', 'subject = "' + "書" * 256 + '"'), "255"),
        (VALID_MANUAL.replace('note = "例外"', "note = 1"), "note"),
        (VALID_MANUAL.replace('root = "文學小說"', 'rooot = "文學小說"'), "unknown key"),
        ('[[mapping]]\nsource_code = "BOOKS_COM_TW"\n', "missing required key"),
    ],
)
def test_rejects_invalid_manual_mappings(tmp_path: Path, manual: str, message: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(message)):
        load_rules(write_config(tmp_path, manual=manual))


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    (config / "provider_roots.toml").unlink()

    with pytest.raises(ConfigError, match=re.escape("provider_roots.toml")):
        load_rules(config)


def test_config_error_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="canonical_categories.toml"):
        load_rules(write_config(tmp_path, categories="[[category]]\nslug = 1\n"))
