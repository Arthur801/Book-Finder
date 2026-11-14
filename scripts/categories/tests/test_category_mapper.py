"""Pure mapping rules and plan (category_mapper.py). No database, no network."""

from __future__ import annotations

from category_config import CanonicalCategory, ManualMapping, ProviderRoot, Rules
from category_mapper import (
    METHOD_MANUAL,
    METHOD_RULE,
    DbCategory,
    DbMapping,
    DesiredMapping,
    build_plan,
    can_apply,
    derive_desired,
    diff_categories,
    diff_mappings,
    has_drift,
    summarize_unmapped,
)
from eslite_tree import Level3Row


def rules(
    roots: list[ProviderRoot] | None = None,
    manual: list[ManualMapping] | None = None,
    categories: tuple[CanonicalCategory, ...] | None = None,
) -> Rules:
    return Rules(
        categories=categories
        or (
            CanonicalCategory("literature", "文學小說", 1),
            CanonicalCategory("comics-light-novels", "漫畫與輕小說", 2),
            CanonicalCategory("children-teens", "童書與青少年", 3),
            CanonicalCategory("simplified-chinese", "簡體書", 4, is_active=False),
        ),
        provider_roots=tuple(roots or ()),
        manual_mappings=tuple(manual or ()),
    )


def level3(level2_id: int, level3_id: int, level3_name: str, level2_name: str = "二") -> Level3Row:
    return Level3Row(level2_id, level2_name, level3_id, level3_name)


def mapping_for(desired: dict, source: str, subject: str) -> DesiredMapping:
    return desired.mappings[(source, subject)]


def test_same_subject_name_under_different_sources_maps_independently() -> None:
    r = rules(
        roots=[
            ProviderRoot("BOOKS_COM_TW", "童書", "children-teens"),
            ProviderRoot("KINGSTONE", "童書", "literature"),
        ]
    )

    desired = derive_desired(r, [])

    assert mapping_for(desired, "BOOKS_COM_TW", "童書").slug == "children-teens"
    assert mapping_for(desired, "KINGSTONE", "童書").slug == "literature"
    assert desired.ambiguous == []


def test_several_roots_can_map_to_the_same_slug() -> None:
    r = rules(
        roots=[
            ProviderRoot("BOOKS_COM_TW", "漫畫/圖文書", "comics-light-novels"),
            ProviderRoot("BOOKS_COM_TW", "輕小說", "comics-light-novels"),
        ]
    )

    desired = derive_desired(r, [])

    assert mapping_for(desired, "BOOKS_COM_TW", "漫畫/圖文書") == DesiredMapping("BOOKS_COM_TW", "漫畫/圖文書", "comics-light-novels", "漫畫/圖文書", METHOD_RULE)
    assert mapping_for(desired, "BOOKS_COM_TW", "輕小說").slug == "comics-light-novels"
    assert mapping_for(desired, "BOOKS_COM_TW", "輕小說").provider_root_subject == "輕小說"


def test_root_mapping_has_method_rule_and_root_as_provider_root_subject() -> None:
    desired = derive_desired(rules(roots=[ProviderRoot("KINGSTONE", "財經企管", "business")]), [])

    assert mapping_for(desired, "KINGSTONE", "財經企管") == DesiredMapping("KINGSTONE", "財經企管", "business", "財經企管", METHOD_RULE)


def test_eslite_names_derive_from_level2_roots() -> None:
    r = rules(roots=[ProviderRoot("ESLITE", "28", "literature"), ProviderRoot("ESLITE", "334", "children-teens")])
    rows = [level3(28, 1001, "小說"), level3(334, 2001, "繪本")]

    desired = derive_desired(r, rows)

    assert mapping_for(desired, "ESLITE", "小說") == DesiredMapping("ESLITE", "小說", "literature", "eslite-l2:28", METHOD_RULE)
    assert mapping_for(desired, "ESLITE", "繪本").provider_root_subject == "eslite-l2:334"


def test_eslite_same_name_under_two_level2_with_same_slug_is_one_mapping() -> None:
    r = rules(roots=[ProviderRoot("ESLITE", "28", "literature"), ProviderRoot("ESLITE", "61", "literature")])
    rows = [level3(28, 1001, "小說"), level3(61, 3002, "小說")]

    desired = derive_desired(r, rows)

    eslite = [m for m in desired.mappings.values() if m.source_code == "ESLITE"]
    assert len(eslite) == 1
    assert eslite[0].provider_root_subject == "eslite-l2:28"
    assert desired.ambiguous == []


def test_eslite_same_name_under_two_level2_with_different_slugs_is_ambiguous() -> None:
    r = rules(roots=[ProviderRoot("ESLITE", "28", "literature"), ProviderRoot("ESLITE", "162", "children-teens")])
    rows = [level3(28, 1001, "繪本"), level3(162, 4001, "繪本")]

    desired = derive_desired(r, rows)

    assert ("ESLITE", "繪本") not in desired.mappings
    assert len(desired.ambiguous) == 1
    ambiguous = desired.ambiguous[0]
    assert (ambiguous.source_code, ambiguous.subject) == ("ESLITE", "繪本")
    assert ambiguous.candidates == (("literature", 28), ("children-teens", 162))


def test_manual_mapping_overrides_derived_and_resolves_ambiguity() -> None:
    r = rules(
        roots=[ProviderRoot("ESLITE", "28", "literature"), ProviderRoot("ESLITE", "162", "children-teens")],
        manual=[ManualMapping("ESLITE", "繪本", "children-teens", "人工確認", "note")],
    )
    rows = [level3(28, 1001, "繪本"), level3(162, 4001, "繪本")]

    desired = derive_desired(r, rows)

    assert desired.ambiguous == []
    assert mapping_for(desired, "ESLITE", "繪本") == DesiredMapping("ESLITE", "繪本", "children-teens", "人工確認", METHOD_MANUAL)


def test_manual_mapping_overrides_a_root_mapping_for_the_same_key() -> None:
    r = rules(
        roots=[ProviderRoot("BOOKS_COM_TW", "童書", "children-teens")],
        manual=[ManualMapping("BOOKS_COM_TW", "童書", "literature", "童書", "")],
    )

    desired = derive_desired(r, [])

    assert mapping_for(desired, "BOOKS_COM_TW", "童書") == DesiredMapping("BOOKS_COM_TW", "童書", "literature", "童書", METHOD_MANUAL)


def test_unruled_eslite_level2_is_reported_and_not_mapped() -> None:
    r = rules(roots=[ProviderRoot("ESLITE", "28", "literature")])
    rows = [level3(28, 1001, "小說"), level3(999, 5001, "新分類", "新二"), level3(999, 5002, "另一個", "新二")]

    desired = derive_desired(r, rows)

    assert [(u.level2_id, u.level2_name, u.level3_count) for u in desired.unruled] == [(999, "新二", 2)]
    assert ("ESLITE", "新分類") not in desired.mappings


def test_plan_is_blocked_by_unruled_and_ambiguous() -> None:
    r = rules(roots=[ProviderRoot("ESLITE", "28", "literature"), ProviderRoot("ESLITE", "162", "children-teens")])
    rows = [level3(28, 1001, "繪本"), level3(162, 4001, "繪本"), level3(999, 5001, "新")]

    plan = build_plan(r, rows, db_categories=[], db_mappings=[])

    assert not can_apply(plan)
    assert has_drift(plan)


def test_diff_categories_inserts_updates_unchanged_orphans() -> None:
    desired = (
        CanonicalCategory("literature", "文學小說", 1),
        CanonicalCategory("business", "商業理財", 2),
        CanonicalCategory("psychology", "心理勵志", 3),
    )
    existing = [
        DbCategory("literature", "文學小說", 1, True),  # unchanged
        DbCategory("business", "商業", 2, True),  # display_name differs
        DbCategory("old-slug", "舊分類", 9, True),  # orphan
    ]

    inserts, updates, unchanged, orphans = diff_categories(desired, existing)

    assert [c.slug for c in inserts] == ["psychology"]
    assert [(old.slug, new.display_name) for old, new in updates] == [("business", "商業理財")]
    assert unchanged == ("literature",)
    assert [o.slug for o in orphans] == ["old-slug"]


def test_diff_categories_detects_sort_order_and_is_active_changes() -> None:
    desired = (CanonicalCategory("literature", "文學小說", 1, is_active=False),)
    existing = [DbCategory("literature", "文學小說", 5, True)]

    _, updates, unchanged, _ = diff_categories(desired, existing)

    assert len(updates) == 1
    assert unchanged == ()


def test_diff_mappings_inserts_updates_unchanged_orphans() -> None:
    desired = {
        ("BOOKS_COM_TW", "文學小說"): DesiredMapping("BOOKS_COM_TW", "文學小說", "literature", "文學小說", METHOD_RULE),
        ("BOOKS_COM_TW", "商業理財"): DesiredMapping("BOOKS_COM_TW", "商業理財", "business", "商業理財", METHOD_RULE),
        ("BOOKS_COM_TW", "童書"): DesiredMapping("BOOKS_COM_TW", "童書", "children-teens", "童書", METHOD_RULE),
        ("KINGSTONE", "文學"): DesiredMapping("KINGSTONE", "文學", "literature", "文學", METHOD_MANUAL),
    }
    existing = [
        DbMapping("BOOKS_COM_TW", "文學小說", "文學小說", "literature", METHOD_RULE),  # unchanged
        DbMapping("BOOKS_COM_TW", "商業理財", "商業理財", "literature", METHOD_RULE),  # slug differs
        DbMapping("KINGSTONE", "文學", "文學", "literature", METHOD_RULE),  # method differs
        DbMapping("ESLITE", "舊名稱", "eslite-l2:28", "literature", METHOD_RULE),  # orphan
    ]

    inserts, updates, unchanged, orphans = diff_mappings(desired, existing)

    assert [m.subject for m in inserts] == ["童書"]
    assert sorted(old.subject for old, _ in updates) == ["商業理財", "文學"]
    assert unchanged == (("BOOKS_COM_TW", "文學小說"),)
    assert [(o.source_code, o.subject) for o in orphans] == [("ESLITE", "舊名稱")]


def test_diff_mappings_detects_provider_root_subject_change() -> None:
    desired = {("ESLITE", "小說"): DesiredMapping("ESLITE", "小說", "literature", "eslite-l2:61", METHOD_RULE)}
    existing = [DbMapping("ESLITE", "小說", "eslite-l2:28", "literature", METHOD_RULE)]

    inserts, updates, unchanged, orphans = diff_mappings(desired, existing)

    assert inserts == () and unchanged == () and orphans == ()
    assert len(updates) == 1


def test_plan_applied_then_replanned_is_all_unchanged() -> None:
    r = rules(
        roots=[
            ProviderRoot("BOOKS_COM_TW", "文學小說", "literature"),
            ProviderRoot("ESLITE", "28", "literature"),
        ],
        manual=[ManualMapping("KINGSTONE", "童書", "children-teens", "童書", "")],
    )
    rows = [level3(28, 1001, "小說")]

    first = build_plan(r, rows, db_categories=[], db_mappings=[])
    assert has_drift(first)
    assert can_apply(first)

    # What --apply leaves in the database: the same categories and mappings.
    db_categories = [DbCategory(c.slug, c.display_name, c.sort_order, c.is_active) for c in r.categories]
    db_mappings = [DbMapping(m.source_code, m.subject, m.provider_root_subject, m.slug, m.method) for m in first.desired_mappings]

    second = build_plan(r, rows, db_categories=db_categories, db_mappings=db_mappings)

    assert not has_drift(second)
    assert second.category_inserts == second.category_updates == second.category_orphans == ()
    assert second.mapping_inserts == second.mapping_updates == second.mapping_orphans == ()
    assert len(second.category_unchanged) == len(r.categories)
    assert len(second.mapping_unchanged) == len(first.desired_mappings)


def test_orphans_alone_are_not_drift() -> None:
    r = rules()
    db_categories = [DbCategory(c.slug, c.display_name, c.sort_order, c.is_active) for c in r.categories]
    db_categories.append(DbCategory("retired", "退役", 99, True))

    plan = build_plan(r, [], db_categories=db_categories, db_mappings=[])

    assert len(plan.category_orphans) == 1
    assert not has_drift(plan)
    assert can_apply(plan)


def test_summarize_unmapped_counts_per_source_and_ranks_by_books() -> None:
    subject_books = {
        ("BOOKS_COM_TW", "文學小說"): 500,
        ("BOOKS_COM_TW", "語文"): 40,
        ("BOOKS_COM_TW", "日本"): 90,
        ("KINGSTONE", "參考書"): 7,
        ("KINGSTONE", "舊版"): 3,
    }
    desired_keys = {("BOOKS_COM_TW", "文學小說"), ("KINGSTONE", "參考書")}

    summary = summarize_unmapped(subject_books, desired_keys, top_n=2)

    assert summary.per_source["BOOKS_COM_TW"] == (3, 2)  # (distinct subjects, unmapped subjects)
    assert summary.per_source["KINGSTONE"] == (2, 1)
    assert summary.unmapped_subjects == 3
    assert [(src, subj, books) for src, subj, books in summary.top] == [
        ("BOOKS_COM_TW", "日本", 90),
        ("BOOKS_COM_TW", "語文", 40),
    ]
