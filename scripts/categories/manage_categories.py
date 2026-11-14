#!/usr/bin/env python3
"""Canonical category maintenance CLI (Docs/plans/canonical-category-browse.md §3).

Run from the repository root:  python scripts/categories/manage_categories.py <command> [options]

Commands:
  audit           read-only coverage report (optionally --unmapped-csv PATH)
  init            read-only check that the EF migration and its tables, constraints and indexes exist (never runs DDL)
  sync            plan the rules against the database; --dry-run (default) writes nothing, --apply writes in one transaction
  verify          read-only; exit 1 when the database differs from the rules
  eslite-import   build config/eslite_level3.tsv from a saved Eslite category tree (no database, no network)

Environment: DATABASE_URL (required by the database commands). It is never printed.
Exit codes: 0 ok, 1 runtime failure or drift, 2 usage, configuration or schema problem.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlsplit

import category_repository as repo
import psycopg
from category_config import ConfigError, Rules, load_rules
from category_mapper import Plan, build_plan, can_apply, derive_desired, has_drift, summarize_unmapped
from eslite_tree import DEFAULT_TSV, Level3Row, build_level3_rows, read_level3_tsv, write_level3_tsv

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = SCRIPT_DIR / "config"
EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2
CONNECT_TIMEOUT_SECONDS = 10
READ_ONLY_OPTIONS = "-c default_transaction_read_only=on"
REDACTED = "<redacted>"
TOP_UNMAPPED = 10

MIGRATION_HINT = (
    "The schema is missing or incomplete. It is owned by the EF Core migration AddCanonicalCategories; this tool never runs DDL.\n"
    "  development: dotnet ef database update\n"
    "  production: deploy through CD (efbundle with the migration lock), not by hand."
)


def redact(text: str, dsn: str | None) -> str:
    """Remove the DSN, its password, and any key=value password from text before it is printed."""
    if dsn:
        text = text.replace(dsn, REDACTED)
        try:
            password = urlsplit(dsn).password
        except ValueError:
            password = None
        if password:
            text = text.replace(password, REDACTED)
    return re.sub(r"(password\s*=\s*)\S+", lambda m: m.group(1) + REDACTED, text)


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _connect(dsn: str, *, read_only: bool) -> psycopg.Connection:
    options = {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    if read_only:
        options["options"] = READ_ONLY_OPTIONS
    return psycopg.connect(dsn, **options)


def _run_database(dsn: str, *, read_only: bool, action: Callable[[psycopg.Connection], int]) -> int:
    try:
        with _connect(dsn, read_only=read_only) as conn:
            return action(conn)
    except Exception as exc:  # noqa: BLE001 - CLI boundary: any runtime failure exits 1, and the DSN is never printed
        _err(f"runtime failure: {type(exc).__name__}: {redact(str(exc), dsn)}")
        return EXIT_RUNTIME


def _load_config(config_dir: Path) -> tuple[Rules, list[Level3Row]]:
    rules = load_rules(config_dir)
    rows = read_level3_tsv(config_dir / DEFAULT_TSV.name)
    return rules, rows


def _print_checks(checks: Sequence[repo.SchemaCheck]) -> bool:
    for check in checks:
        print(f"[{'PASS' if check.ok else 'FAIL'}] {check.name}: {check.detail}")
    return all(check.ok for check in checks)


def _schema_ok(conn: psycopg.Connection) -> bool:
    """Print the schema checks; on failure print the migration hint. Returns True when every check passes."""
    if _print_checks(repo.schema_checks(conn)):
        return True
    print(MIGRATION_HINT)
    return False


def _missing_sources(conn: psycopg.Connection, rules: Rules) -> set[str]:
    wanted = {r.source_code for r in rules.provider_roots} | {m.source_code for m in rules.manual_mappings}
    return wanted - repo.source_codes(conn)


def _print_plan(plan: Plan) -> None:
    def count(label: str, inserts: int, updates: int, unchanged: int, orphans: int) -> None:
        print(f"{label}: insert {inserts}, update {updates}, unchanged {unchanged}, orphan {orphans} (orphans are reported, never deleted)")

    count(
        "categories",
        len(plan.category_inserts),
        len(plan.category_updates),
        len(plan.category_unchanged),
        len(plan.category_orphans),
    )
    count(
        "mappings",
        len(plan.mapping_inserts),
        len(plan.mapping_updates),
        len(plan.mapping_unchanged),
        len(plan.mapping_orphans),
    )
    for category in plan.category_inserts:
        print(f"  + category {category.slug} ({category.display_name})")
    for old, new in plan.category_updates:
        print(
            f"  ~ category {new.slug}: {old.display_name!r} -> {new.display_name!r}, sort {old.sort_order} -> {new.sort_order}, active {old.is_active} -> {new.is_active}"
        )
    for orphan in plan.category_orphans:
        print(f"  - orphan category {orphan.slug} (kept)")
    for mapping in plan.mapping_inserts:
        print(f"  + mapping {mapping.source_code} / {mapping.subject} -> {mapping.slug} [{mapping.method}]")
    for old, new in plan.mapping_updates:
        print(
            f"  ~ mapping {new.source_code} / {new.subject}: {old.slug} -> {new.slug}, root {old.provider_root_subject!r} -> {new.provider_root_subject!r}, method {old.method} -> {new.method}"
        )
    for orphan in plan.mapping_orphans:
        print(f"  - orphan mapping {orphan.source_code} / {orphan.subject} -> {orphan.slug} (kept)")
    if plan.ambiguous:
        print(f"AMBIGUOUS ({len(plan.ambiguous)}), not written; add a rule in subject_mappings.toml to resolve:")
        for item in plan.ambiguous:
            options = ", ".join(f"{slug} (level-2 {level2})" for slug, level2 in item.candidates)
            print(f"  {item.source_code} / {item.subject}: {options}")
    if plan.unruled:
        print(f"UNRULED eslite level-2 ({len(plan.unruled)}), blocks --apply; add a rule in provider_roots.toml:")
        for item in plan.unruled:
            print(f"  {item.level2_id} {item.level2_name}: {item.level3_count} level-3 categories")


def _print_unmapped(summary) -> None:
    print("Unmapped database subjects (no desired mapping; they classify through their root when it is mapped):")
    for source, (distinct, unmapped) in summary.per_source.items():
        print(f"  {source}: {unmapped} of {distinct} distinct subjects unmapped")
    if summary.top:
        print(f"  Top {len(summary.top)} unmapped by books:")
        for source, subject, books in summary.top:
            print(f"    {source}  {subject}  {books}")


def cmd_init(conn: psycopg.Connection) -> int:
    return EXIT_OK if _schema_ok(conn) else EXIT_USAGE


def cmd_audit(conn: psycopg.Connection, unmapped_csv: Path | None) -> int:
    if not _schema_ok(conn):
        return EXIT_USAGE
    result = repo.audit(conn)
    print("Subjects per source (mapped = has a mapping to an active category):")
    for source in result.sources:
        print(f"  {source.source_code}: subjects {source.subjects}, mapped {source.mapped}, unmapped {source.subjects - source.mapped}")
    print("Books:")
    print(f"  total {result.books}")
    print(f"  with at least one active category {result.books_with_category}")
    print(f"  with no category {result.books - result.books_with_category}")
    print(f"  with two or more categories {result.books_with_two_or_more}")
    if unmapped_csv is not None:
        with unmapped_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["source_code", "subject", "books"])
            writer.writerows(result.unmapped)
        print(f"Wrote {len(result.unmapped)} unmapped subject rows to {unmapped_csv}")
    return EXIT_OK


def _report(conn: psycopg.Connection, plan: Plan, rules: Rules, rows: list[Level3Row]) -> None:
    _print_plan(plan)
    desired_keys = set(derive_desired(rules, rows).mappings)
    _print_unmapped(summarize_unmapped(repo.subject_book_counts(conn), desired_keys))


def cmd_sync(conn: psycopg.Connection, rules: Rules, rows: list[Level3Row], *, apply: bool) -> int:
    if not _schema_ok(conn):
        return EXIT_USAGE
    missing = _missing_sources(conn, rules)
    if missing:
        _err(f"source_code not in source_providers: {', '.join(sorted(missing))}")
        return EXIT_USAGE
    if not apply:
        _report(conn, build_plan(rules, rows, repo.read_categories(conn), repo.read_mappings(conn)), rules, rows)
        print("dry-run: nothing written (use --apply to write)")
        return EXIT_OK
    # Lock first so the plan is computed from the same rows that the writes see; everything rolls back on any error.
    with conn.transaction():
        repo.lock_for_sync(conn)
        plan = build_plan(rules, rows, repo.read_categories(conn), repo.read_mappings(conn))
        _report(conn, plan, rules, rows)
        if not can_apply(plan):
            raise _Refusal("refused: ambiguous or unruled rules; nothing written")
        counts = repo.apply_plan(conn, plan)
    print(
        f"applied in one transaction: categories written {counts.categories_written}, "
        f"mappings written {counts.mappings_written} (a rerun with no rule change writes 0)"
    )
    return EXIT_OK


class _Refusal(Exception):
    """Raised inside the apply transaction so that it rolls back and the CLI exits 2."""


def cmd_verify(conn: psycopg.Connection, rules: Rules, rows: list[Level3Row]) -> int:
    if not _schema_ok(conn):
        return EXIT_USAGE
    missing = _missing_sources(conn, rules)
    if missing:
        _err(f"source_code not in source_providers: {', '.join(sorted(missing))}")
        return EXIT_USAGE
    plan = build_plan(rules, rows, repo.read_categories(conn), repo.read_mappings(conn))
    _print_plan(plan)
    if has_drift(plan):
        print("DRIFT: the database differs from the rules (inserts, updates, ambiguous or unruled).")
        return EXIT_RUNTIME
    print("verify: the database matches the rules.")
    return EXIT_OK


def cmd_eslite_import(tree_path: Path, output: Path) -> int:
    try:
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
    except OSError as exc:
        _err(f"cannot read tree file: {exc.strerror}")
        return EXIT_USAGE
    except ValueError as exc:
        _err(f"tree file is not valid JSON: {exc}")
        return EXIT_USAGE
    if not isinstance(tree, list):
        _err("tree file must contain a JSON list of top-level categories")
        return EXIT_USAGE
    try:
        rows, selection = build_level3_rows(tree)
    except (ValueError, TypeError) as exc:
        _err(f"tree rejected: {exc}")
        return EXIT_USAGE
    try:
        write_level3_tsv(output, rows)
        written = read_level3_tsv(output)
    except OSError as exc:
        _err(f"cannot write {output}: {exc.strerror}")
        return EXIT_RUNTIME
    except ConfigError as exc:
        _err(f"written TSV failed validation: {exc}")
        return EXIT_RUNTIME
    if len(written) != len(rows):
        _err("internal check failed: the written TSV does not hold every row")
        return EXIT_RUNTIME
    print(f"eslite-import: wrote {len(rows)} level-3 rows to {output}")
    print(
        f"  skipped: external link {selection.skipped_link}, brand {selection.skipped_brand}, "
        f"excluded level-2 {selection.skipped_excluded}, duplicate ids {selection.duplicates}"
    )
    for level2_id, name, count in selection.per_level2:
        print(f"  level-2 {level2_id} {name}: {count} kept")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config-dir", type=Path, default=CONFIG_DIR, help="directory with the rule files (default: scripts/categories/config)")

    parser = argparse.ArgumentParser(prog="manage_categories.py", description="Canonical category maintenance tool.")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", parents=[common], help="read-only coverage report")
    audit_p.add_argument("--unmapped-csv", type=Path, help="write unmapped (source_code, subject, books) rows to this CSV")

    sub.add_parser("init", parents=[common], help="check the schema (read-only, never runs DDL)")

    sync_p = sub.add_parser("sync", parents=[common], help="plan the rules against the database (dry-run by default)")
    mode = sync_p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report only (default)")
    mode.add_argument("--apply", action="store_true", help="write in one transaction")

    sub.add_parser("verify", parents=[common], help="exit 1 when the database differs from the rules")

    import_p = sub.add_parser("eslite-import", parents=[common], help="build the Eslite level-3 TSV from a saved tree")
    import_p.add_argument("--tree", type=Path, required=True, help="saved Eslite category tree JSON (data, not executed)")
    import_p.add_argument("--output", type=Path, help="TSV path (default: <config-dir>/eslite_level3.tsv)")
    return parser


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "eslite-import":
        output = args.output or (args.config_dir / DEFAULT_TSV.name)
        return cmd_eslite_import(args.tree, output)

    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        _err("DATABASE_URL is not set; the database commands need it (value is never printed)")
        return EXIT_USAGE

    if args.command == "init":
        return _run_database(dsn, read_only=True, action=cmd_init)
    if args.command == "audit":
        return _run_database(dsn, read_only=True, action=lambda conn: cmd_audit(conn, args.unmapped_csv))

    rules, rows = _load_config(args.config_dir)
    if args.command == "sync":
        apply = bool(args.apply)
        if apply:
            desired = derive_desired(rules, rows)
            if desired.ambiguous or desired.unruled:
                _err(
                    f"refused: {len(desired.ambiguous)} ambiguous name(s) and {len(desired.unruled)} unruled eslite level-2 "
                    "(run sync --dry-run for the list); nothing written"
                )
                return EXIT_USAGE
        try:
            with _connect(dsn, read_only=not apply) as conn:
                return cmd_sync(conn, rules, rows, apply=apply)
        except _Refusal as exc:
            _err(str(exc))
            return EXIT_USAGE
        except Exception as exc:  # noqa: BLE001 - CLI boundary: rollback already happened; exit 1
            _err(f"sync failed; nothing was committed: {type(exc).__name__}: {redact(str(exc), dsn)}")
            return EXIT_RUNTIME
    if args.command == "verify":
        return _run_database(dsn, read_only=True, action=lambda conn: cmd_verify(conn, rules, rows))
    raise AssertionError(f"unhandled command {args.command!r}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    try:
        return _dispatch(args)
    except ConfigError as exc:
        _err(f"config error: {exc}")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
