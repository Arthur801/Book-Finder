"""The rule files and the TSV that ship in the repository must load, validate and cover every Eslite level-2."""

from __future__ import annotations

from pathlib import Path

from category_config import load_rules
from category_mapper import build_plan, can_apply, derive_desired
from eslite_tree import DEFAULT_TSV, read_level3_tsv

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
SHIPPED_AMBIGUOUS = {"繪本／插畫／漫畫", "語言考用"}


def test_shipped_rules_load_with_expected_counts() -> None:
    rules = load_rules(CONFIG_DIR)

    assert len(rules.categories) == 18
    assert [c.sort_order for c in rules.categories] == list(range(1, 19))
    assert rules.categories[-1].slug == "simplified-chinese"
    counts: dict[str, int] = {}
    for root in rules.provider_roots:
        counts[root.source_code] = counts.get(root.source_code, 0) + 1
    assert counts == {"BOOKS_COM_TW": 21, "KINGSTONE": 22, "ESLITE": 21}
    assert rules.manual_mappings == ()


def test_shipped_tsv_has_254_rows_and_every_level2_has_a_rule() -> None:
    rows = read_level3_tsv(DEFAULT_TSV)
    rules = load_rules(CONFIG_DIR)

    assert len(rows) == 254
    desired = derive_desired(rules, rows)
    assert desired.unruled == []


def test_shipped_tsv_ambiguous_names_are_exactly_the_reviewed_pair() -> None:
    rules = load_rules(CONFIG_DIR)
    rows = read_level3_tsv(DEFAULT_TSV)

    desired = derive_desired(rules, rows)

    assert {a.subject for a in desired.ambiguous} == SHIPPED_AMBIGUOUS
    plan = build_plan(rules, rows, db_categories=[], db_mappings=[])
    assert not can_apply(plan)
