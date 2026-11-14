"""Pure mapping rules and plan: desired (source, subject) → slug mappings, diffed against the database.

No I/O here. The repository reads existing rows and applies the plan; this module only decides what should change.
Orphans (database rows whose key is no longer desired) are reported and never deleted.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from category_config import ESLITE_SOURCE, CanonicalCategory, Rules
from eslite_tree import Level3Row

METHOD_RULE = "VERIFIED_RULE"
METHOD_MANUAL = "MANUAL"
ESLITE_ROOT_PREFIX = "eslite-l2:"

MappingKey = tuple[str, str]


@dataclass(frozen=True)
class DesiredMapping:
    source_code: str
    subject: str
    slug: str
    provider_root_subject: str
    method: str

    @property
    def key(self) -> MappingKey:
        return (self.source_code, self.subject)


@dataclass(frozen=True)
class DbCategory:
    slug: str
    display_name: str
    sort_order: int
    is_active: bool


@dataclass(frozen=True)
class DbMapping:
    source_code: str
    subject: str
    provider_root_subject: str
    slug: str
    method: str

    @property
    def key(self) -> MappingKey:
        return (self.source_code, self.subject)


@dataclass(frozen=True)
class Ambiguous:
    source_code: str
    subject: str
    candidates: tuple[tuple[str, int], ...]  # (slug, level-2 id), in TSV order, de-duplicated

    @property
    def key(self) -> MappingKey:
        return (self.source_code, self.subject)


@dataclass(frozen=True)
class Unruled:
    level2_id: int
    level2_name: str
    level3_count: int


@dataclass(frozen=True)
class Desired:
    mappings: dict[MappingKey, DesiredMapping]
    ambiguous: list[Ambiguous]
    unruled: list[Unruled]


@dataclass(frozen=True)
class Plan:
    desired_categories: tuple[CanonicalCategory, ...]
    desired_mappings: tuple[DesiredMapping, ...]
    category_inserts: tuple[CanonicalCategory, ...]
    category_updates: tuple[tuple[DbCategory, CanonicalCategory], ...]
    category_unchanged: tuple[str, ...]
    category_orphans: tuple[DbCategory, ...]
    mapping_inserts: tuple[DesiredMapping, ...]
    mapping_updates: tuple[tuple[DbMapping, DesiredMapping], ...]
    mapping_unchanged: tuple[MappingKey, ...]
    mapping_orphans: tuple[DbMapping, ...]
    ambiguous: tuple[Ambiguous, ...]
    unruled: tuple[Unruled, ...]


@dataclass(frozen=True)
class UnmappedSummary:
    per_source: dict[str, tuple[int, int]]  # source -> (distinct subjects, subjects without a desired mapping)
    unmapped_subjects: int
    top: list[tuple[str, str, int]] = field(default_factory=list)  # (source, subject, books), most books first


def derive_desired(rules: Rules, level3_rows: Sequence[Level3Row]) -> Desired:
    """Desired mappings from the provider roots, the ESLITE level-3 list and the manual overrides."""
    mappings: dict[MappingKey, DesiredMapping] = {}
    for root in rules.provider_roots:
        if root.source_code == ESLITE_SOURCE:
            continue
        mappings[(root.source_code, root.root)] = DesiredMapping(root.source_code, root.root, root.slug, root.root, METHOD_RULE)

    eslite_roots = {r.root: r.slug for r in rules.provider_roots if r.source_code == ESLITE_SOURCE}
    unruled: dict[int, Unruled] = {}
    candidates: dict[str, list[tuple[str, int]]] = {}
    for row in level3_rows:
        slug = eslite_roots.get(str(row.level2_id))
        if slug is None:
            previous = unruled.get(row.level2_id)
            count = previous.level3_count + 1 if previous else 1
            unruled[row.level2_id] = Unruled(row.level2_id, row.level2_name, count)
            continue
        pairs = candidates.setdefault(row.level3_name, [])
        if (slug, row.level2_id) not in pairs:
            pairs.append((slug, row.level2_id))
    # The first level-2 in TSV order decides provider_root_subject for a name whose slugs all agree.
    first_level2: dict[str, int] = {}
    for row in level3_rows:
        if str(row.level2_id) in eslite_roots:
            first_level2.setdefault(row.level3_name, row.level2_id)

    ambiguous: list[Ambiguous] = []
    for name, pairs in candidates.items():
        slugs = {slug for slug, _ in pairs}
        if len(slugs) == 1:
            slug = pairs[0][0]
            mappings[(ESLITE_SOURCE, name)] = DesiredMapping(ESLITE_SOURCE, name, slug, f"{ESLITE_ROOT_PREFIX}{first_level2[name]}", METHOD_RULE)
        else:
            ambiguous.append(Ambiguous(ESLITE_SOURCE, name, tuple(pairs)))

    for manual in rules.manual_mappings:
        key = (manual.source_code, manual.subject)
        mappings[key] = DesiredMapping(manual.source_code, manual.subject, manual.slug, manual.root, METHOD_MANUAL)
    ambiguous = [a for a in ambiguous if a.key not in mappings]

    return Desired(mappings=mappings, ambiguous=ambiguous, unruled=list(unruled.values()))


def diff_categories(
    desired: Iterable[CanonicalCategory], existing: Iterable[DbCategory]
) -> tuple[
    tuple[CanonicalCategory, ...],
    tuple[tuple[DbCategory, CanonicalCategory], ...],
    tuple[str, ...],
    tuple[DbCategory, ...],
]:
    """Compare by slug. Updates when display_name, sort_order or is_active differ."""
    existing_by_slug = {c.slug: c for c in existing}
    desired_list = list(desired)
    desired_slugs = {c.slug for c in desired_list}
    inserts: list[CanonicalCategory] = []
    updates: list[tuple[DbCategory, CanonicalCategory]] = []
    unchanged: list[str] = []
    for category in desired_list:
        current = existing_by_slug.get(category.slug)
        if current is None:
            inserts.append(category)
        elif (current.display_name, current.sort_order, current.is_active) != (
            category.display_name,
            category.sort_order,
            category.is_active,
        ):
            updates.append((current, category))
        else:
            unchanged.append(category.slug)
    orphans = tuple(c for c in existing_by_slug.values() if c.slug not in desired_slugs)
    return tuple(inserts), tuple(updates), tuple(unchanged), orphans


def diff_mappings(
    desired: Mapping[MappingKey, DesiredMapping], existing: Iterable[DbMapping]
) -> tuple[
    tuple[DesiredMapping, ...],
    tuple[tuple[DbMapping, DesiredMapping], ...],
    tuple[MappingKey, ...],
    tuple[DbMapping, ...],
]:
    """Compare by (source_code, subject). Updates when provider_root_subject, slug or method differ."""
    existing_by_key = {m.key: m for m in existing}
    inserts: list[DesiredMapping] = []
    updates: list[tuple[DbMapping, DesiredMapping]] = []
    unchanged: list[MappingKey] = []
    for key, want in desired.items():
        current = existing_by_key.get(key)
        if current is None:
            inserts.append(want)
        elif (current.provider_root_subject, current.slug, current.method) != (
            want.provider_root_subject,
            want.slug,
            want.method,
        ):
            updates.append((current, want))
        else:
            unchanged.append(key)
    orphans = tuple(m for key, m in existing_by_key.items() if key not in desired)
    return tuple(inserts), tuple(updates), tuple(unchanged), orphans


def build_plan(
    rules: Rules,
    level3_rows: Sequence[Level3Row],
    db_categories: Sequence[DbCategory],
    db_mappings: Sequence[DbMapping],
) -> Plan:
    desired = derive_desired(rules, level3_rows)
    cat_inserts, cat_updates, cat_unchanged, cat_orphans = diff_categories(rules.categories, db_categories)
    map_inserts, map_updates, map_unchanged, map_orphans = diff_mappings(desired.mappings, db_mappings)
    return Plan(
        desired_categories=rules.categories,
        desired_mappings=tuple(sorted(desired.mappings.values(), key=lambda m: m.key)),
        category_inserts=cat_inserts,
        category_updates=cat_updates,
        category_unchanged=cat_unchanged,
        category_orphans=cat_orphans,
        mapping_inserts=map_inserts,
        mapping_updates=map_updates,
        mapping_unchanged=tuple(map_unchanged),
        mapping_orphans=map_orphans,
        ambiguous=tuple(desired.ambiguous),
        unruled=tuple(desired.unruled),
    )


def has_drift(plan: Plan) -> bool:
    """True when the database differs from the rules (inserts, updates, ambiguous or unruled). Orphans are not drift."""
    return bool(plan.category_inserts or plan.category_updates or plan.mapping_inserts or plan.mapping_updates or plan.ambiguous or plan.unruled)


def can_apply(plan: Plan) -> bool:
    """--apply is refused while any name is ambiguous or any level-2 has no rule."""
    return not plan.ambiguous and not plan.unruled


def summarize_unmapped(subject_books: Mapping[MappingKey, int], desired_keys: set[MappingKey], top_n: int = 10) -> UnmappedSummary:
    per_source: dict[str, list[int]] = {}
    unmapped: list[tuple[str, str, int]] = []
    for (source, subject), books in subject_books.items():
        counts = per_source.setdefault(source, [0, 0])
        counts[0] += 1
        if (source, subject) not in desired_keys:
            counts[1] += 1
            unmapped.append((source, subject, books))
    unmapped.sort(key=lambda item: (-item[2], item[0], item[1]))
    return UnmappedSummary(
        per_source={source: (counts[0], counts[1]) for source, counts in sorted(per_source.items())},
        unmapped_subjects=len(unmapped),
        top=unmapped[:top_n],
    )
