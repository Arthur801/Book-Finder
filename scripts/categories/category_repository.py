"""psycopg I/O for the canonical category tables. All SQL for this tool lives here.

Schema is owned by the EF Core migration ``AddCanonicalCategories``; this module only checks it and reads or writes rows.
Writes happen only through ``apply_plan`` inside the caller's transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import psycopg
from category_mapper import DbCategory, DbMapping, DesiredMapping, Plan

MIGRATION_SUFFIX = "_AddCanonicalCategories"
TABLE_CATEGORIES = "canonical_categories"
TABLE_MAPPINGS = "provider_category_mappings"

# Names are the ones created by the migration (Infrastructure/Persistence/Migrations/20261114003848_AddCanonicalCategories.cs).
REQUIRED_CONSTRAINTS = (
    "PK_canonical_categories",
    "PK_provider_category_mappings",
    "FK_provider_category_mappings_canonical_categories_category_id",
    "FK_provider_category_mappings_source_providers_source_code",
)
REQUIRED_INDEXES = (
    "IX_canonical_categories_slug",
    "IX_provider_category_mappings_category_source_subject",
    "IX_book_subjects_source_code_subject",
)


@dataclass(frozen=True)
class SchemaCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ApplyCounts:
    categories_written: int
    mappings_written: int


def schema_checks(conn: psycopg.Connection) -> list[SchemaCheck]:
    checks: list[SchemaCheck] = []
    has_history = conn.execute("SELECT to_regclass('public.\"__EFMigrationsHistory\"') IS NOT NULL").fetchone()[0]
    if not has_history:
        checks.append(SchemaCheck("EF migrations history table", False, "__EFMigrationsHistory is missing"))
    else:
        row = conn.execute(
            'SELECT "MigrationId" FROM "__EFMigrationsHistory" WHERE right("MigrationId", %s) = %s',
            (len(MIGRATION_SUFFIX), MIGRATION_SUFFIX),
        ).fetchone()
        checks.append(
            SchemaCheck(
                "migration recorded",
                row is not None,
                row[0] if row else f"no MigrationId ends with {MIGRATION_SUFFIX}",
            )
        )

    for table in (TABLE_CATEGORIES, TABLE_MAPPINGS):
        exists = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (table,)).fetchone()[0]
        checks.append(SchemaCheck(f"table {table}", bool(exists), "present" if exists else "missing"))

    constraint_names = {r[0] for r in conn.execute("SELECT conname FROM pg_constraint").fetchall()}
    for name in REQUIRED_CONSTRAINTS:
        checks.append(SchemaCheck(f"constraint {name}", name in constraint_names, "present" if name in constraint_names else "missing"))

    indexes = dict(conn.execute("SELECT c.relname, i.indisunique FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid").fetchall())
    for name in REQUIRED_INDEXES:
        present = name in indexes
        detail = "present" if present else "missing"
        if present and name == "IX_canonical_categories_slug" and not indexes[name]:
            present, detail = False, "present but not UNIQUE"
        checks.append(SchemaCheck(f"index {name}", present, detail))
    return checks


def source_codes(conn: psycopg.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT code FROM source_providers").fetchall()}


def subject_book_counts(conn: psycopg.Connection) -> dict[tuple[str, str], int]:
    rows = conn.execute("SELECT source_code, subject, count(DISTINCT book_id) FROM book_subjects GROUP BY source_code, subject").fetchall()
    return {(source, subject): books for source, subject, books in rows}


def read_categories(conn: psycopg.Connection) -> list[DbCategory]:
    rows = conn.execute("SELECT slug, display_name, sort_order, is_active FROM canonical_categories").fetchall()
    return [DbCategory(slug, name, order, active) for slug, name, order, active in rows]


def read_mappings(conn: psycopg.Connection) -> list[DbMapping]:
    rows = conn.execute(
        """
        SELECT m.source_code, m.subject, m.provider_root_subject, c.slug, m.mapping_method
        FROM provider_category_mappings m
        JOIN canonical_categories c ON c.id = m.canonical_category_id
        """
    ).fetchall()
    return [DbMapping(*row) for row in rows]


def lock_for_sync(conn: psycopg.Connection) -> None:
    """Block other writers for the rest of the transaction so the plan and the writes see the same rows."""
    conn.execute(f"LOCK TABLE {TABLE_CATEGORIES}, {TABLE_MAPPINGS} IN SHARE ROW EXCLUSIVE MODE")


UPSERT_CATEGORY = """
INSERT INTO canonical_categories (id, slug, display_name, sort_order, is_active, created_at, updated_at)
VALUES (%s, %s, %s, %s, %s, now(), now())
ON CONFLICT (slug) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    sort_order = EXCLUDED.sort_order,
    is_active = EXCLUDED.is_active,
    updated_at = now()
WHERE (canonical_categories.display_name, canonical_categories.sort_order, canonical_categories.is_active)
      IS DISTINCT FROM (EXCLUDED.display_name, EXCLUDED.sort_order, EXCLUDED.is_active)
"""

UPSERT_MAPPING = """
INSERT INTO provider_category_mappings (source_code, subject, provider_root_subject, canonical_category_id, mapping_method, updated_at)
VALUES (%s, %s, %s, %s, %s, now())
ON CONFLICT (source_code, subject) DO UPDATE SET
    provider_root_subject = EXCLUDED.provider_root_subject,
    canonical_category_id = EXCLUDED.canonical_category_id,
    mapping_method = EXCLUDED.mapping_method,
    updated_at = now()
WHERE (provider_category_mappings.provider_root_subject, provider_category_mappings.canonical_category_id, provider_category_mappings.mapping_method)
      IS DISTINCT FROM (EXCLUDED.provider_root_subject, EXCLUDED.canonical_category_id, EXCLUDED.mapping_method)
"""


def upsert_category(cur: psycopg.Cursor[Any], slug: str, display_name: str, sort_order: int, is_active: bool) -> int:
    cur.execute(UPSERT_CATEGORY, (uuid.uuid4(), slug, display_name, sort_order, is_active))
    return cur.rowcount


def upsert_mapping(cur: psycopg.Cursor[Any], mapping: DesiredMapping, category_id: uuid.UUID) -> int:
    cur.execute(
        UPSERT_MAPPING,
        (mapping.source_code, mapping.subject, mapping.provider_root_subject, category_id, mapping.method),
    )
    return cur.rowcount


def apply_plan(conn: psycopg.Connection, plan: Plan) -> ApplyCounts:
    """Write every desired category, then every desired mapping, on ``conn``. Caller owns the transaction.

    Rows whose values already match are not touched (WHERE ... IS DISTINCT FROM), so a rerun writes nothing.
    Orphans are left alone.
    """
    categories_written = 0
    mappings_written = 0
    with conn.cursor() as cur:
        for category in plan.desired_categories:
            categories_written += upsert_category(cur, category.slug, category.display_name, category.sort_order, category.is_active)
        cur.execute("SELECT slug, id FROM canonical_categories")
        category_ids = {slug: category_id for slug, category_id in cur.fetchall()}
        for mapping in plan.desired_mappings:
            mappings_written += upsert_mapping(cur, mapping, category_ids[mapping.slug])
    return ApplyCounts(categories_written=categories_written, mappings_written=mappings_written)


@dataclass(frozen=True)
class AuditSource:
    source_code: str
    subjects: int
    mapped: int


@dataclass(frozen=True)
class AuditResult:
    sources: list[AuditSource]
    books: int
    books_with_category: int
    books_with_two_or_more: int
    unmapped: list[tuple[str, str, int]]  # (source_code, subject, books), no mapping to an active category


ACTIVE_MAPPING_EXISTS = """
EXISTS (
    SELECT 1 FROM provider_category_mappings m
    JOIN canonical_categories c ON c.id = m.canonical_category_id AND c.is_active
    WHERE m.source_code = sj.source_code AND m.subject = sj.subject
)
"""


def audit(conn: psycopg.Connection) -> AuditResult:
    sources = [
        AuditSource(code, subjects, mapped)
        for code, subjects, mapped in conn.execute(
            f"""
            SELECT sj.source_code,
                   count(DISTINCT sj.subject),
                   count(DISTINCT sj.subject) FILTER (WHERE {ACTIVE_MAPPING_EXISTS})
            FROM book_subjects sj
            GROUP BY sj.source_code
            ORDER BY sj.source_code
            """
        ).fetchall()
    ]
    unmapped = conn.execute(
        f"""
        SELECT sj.source_code, sj.subject, count(DISTINCT sj.book_id)
        FROM book_subjects sj
        WHERE NOT {ACTIVE_MAPPING_EXISTS}
        GROUP BY sj.source_code, sj.subject
        ORDER BY sj.source_code, count(DISTINCT sj.book_id) DESC, sj.subject
        """
    ).fetchall()
    books = conn.execute("SELECT count(*) FROM books").fetchone()[0]
    with_category, with_two = conn.execute(
        """
        WITH book_categories AS (
            SELECT sj.book_id, c.id AS category_id
            FROM book_subjects sj
            JOIN provider_category_mappings m ON m.source_code = sj.source_code AND m.subject = sj.subject
            JOIN canonical_categories c ON c.id = m.canonical_category_id AND c.is_active
            GROUP BY sj.book_id, c.id
        ), per_book AS (
            SELECT book_id, count(*) AS n FROM book_categories GROUP BY book_id
        )
        SELECT count(*) FILTER (WHERE n >= 1), count(*) FILTER (WHERE n >= 2) FROM per_book
        """
    ).fetchone()
    return AuditResult(
        sources=sources,
        books=books,
        books_with_category=with_category,
        books_with_two_or_more=with_two,
        unmapped=[(s, subj, n) for s, subj, n in unmapped],
    )


def snapshot_book_subjects(conn: psycopg.Connection) -> list[tuple[Any, ...]]:
    """Every book_subjects row, for tests that check the tool leaves them alone."""
    return conn.execute("SELECT book_id, subject, source_code FROM book_subjects ORDER BY 1, 2, 3").fetchall()
