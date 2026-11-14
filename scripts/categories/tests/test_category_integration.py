"""CLI against a throwaway PostgreSQL with the EF schema. Every test gets a fresh database (see conftest.py)."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import category_repository as repo
import psycopg
import pytest
from category_config import load_rules
from category_mapper import build_plan
from eslite_tree import DEFAULT_TSV, read_level3_tsv, write_level3_tsv
from manage_categories import main

SHIPPED_CONFIG = Path(__file__).resolve().parents[1] / "config"
CONFIG_FILES = ("canonical_categories.toml", "provider_roots.toml", "subject_mappings.toml")


def temp_config(tmp_path: Path, *, rename_literature: str | None = None) -> Path:
    """A copy of the shipped rules whose Eslite list drops the two ambiguous names, so --apply is allowed."""
    config = tmp_path / "config"
    config.mkdir(parents=True)
    for name in CONFIG_FILES:
        shutil.copy(SHIPPED_CONFIG / name, config / name)
    if rename_literature is not None:
        path = config / "canonical_categories.toml"
        text = path.read_text(encoding="utf-8")
        text = text.replace('display_name = "文學小說"', f'display_name = "{rename_literature}"', 1)
        path.write_text(text, encoding="utf-8")
    rules = load_rules(SHIPPED_CONFIG)
    rows = read_level3_tsv(SHIPPED_CONFIG / DEFAULT_TSV.name)
    plan = build_plan(rules, rows, db_categories=[], db_mappings=[])
    ambiguous = {a.subject for a in plan.ambiguous}
    write_level3_tsv(config / DEFAULT_TSV.name, [r for r in rows if r.level3_name not in ambiguous])
    return config


def run(monkeypatch: pytest.MonkeyPatch, capsys, url: str, *argv: str) -> tuple[int, str]:
    monkeypatch.setenv("DATABASE_URL", url)
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out + err


def scalar(url: str, sql: str, params: tuple = ()):
    with psycopg.connect(url) as conn:
        return conn.execute(sql, params).fetchone()[0]


def rows(url: str, sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg.connect(url) as conn:
        return conn.execute(sql, params).fetchall()


def execute(url: str, sql: str, params: tuple = ()) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql, params)


def count_categories(url: str) -> int:
    return scalar(url, "SELECT count(*) FROM canonical_categories")


def count_mappings(url: str) -> int:
    return scalar(url, "SELECT count(*) FROM provider_category_mappings")


def seed_book(url: str, title: str, subjects: list[tuple[str, str]], sources: list[str]) -> uuid.UUID:
    """A book with its book_sources and book_subjects, as the crawler writes them. subjects: (source_code, subject)."""
    book_id = uuid.uuid4()
    execute(
        url,
        "INSERT INTO books (id, title, created_at, updated_at) VALUES (%s, %s, now(), now())",
        (book_id, title),
    )
    for source in sources:
        execute(
            url,
            "INSERT INTO book_sources (id, book_id, source_code, source_url, first_seen_at, last_seen_at) VALUES (%s, %s, %s, %s, now(), now())",
            (uuid.uuid4(), book_id, source, f"https://example.invalid/{source}/{book_id}"),
        )
    for source, subject in subjects:
        execute(
            url,
            "INSERT INTO book_subjects (book_id, subject, source_code) VALUES (%s, %s, %s)",
            (book_id, subject, source),
        )
    return book_id


def test_init_passes_on_a_migrated_database(fresh_db: str, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    code, out = run(monkeypatch, capsys, fresh_db, "init")

    assert code == 0
    assert "[FAIL]" not in out
    assert "[PASS] migration recorded" in out


def test_init_fails_with_exit_2_when_the_tables_are_dropped(fresh_db: str, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    execute(fresh_db, "DROP TABLE provider_category_mappings")
    execute(fresh_db, "DROP TABLE canonical_categories")

    code, out = run(monkeypatch, capsys, fresh_db, "init")

    assert code == 2
    assert "[FAIL] table canonical_categories" in out
    assert "dotnet ef database update" in out


def test_init_fails_when_an_index_is_missing(fresh_db: str, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    execute(fresh_db, 'DROP INDEX "IX_canonical_categories_slug"')

    code, out = run(monkeypatch, capsys, fresh_db, "init")

    assert code == 2
    assert "[FAIL] index IX_canonical_categories_slug" in out


def test_sync_dry_run_writes_nothing(fresh_db: str, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    config = temp_config(tmp_path)
    subjects_before = rows(fresh_db, "SELECT book_id, subject, source_code FROM book_subjects ORDER BY 1, 2, 3")

    code, out = run(monkeypatch, capsys, fresh_db, "sync", "--dry-run", "--config-dir", str(config))

    assert code == 0
    assert "dry-run: nothing written" in out
    assert count_categories(fresh_db) == 0
    assert count_mappings(fresh_db) == 0
    assert rows(fresh_db, "SELECT book_id, subject, source_code FROM book_subjects ORDER BY 1, 2, 3") == subjects_before


def test_apply_writes_categories_and_mappings_and_they_are_readable(fresh_db: str, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    config = temp_config(tmp_path)
    expected_mappings = len(build_plan(load_rules(config), read_level3_tsv(config / DEFAULT_TSV.name), [], []).desired_mappings)
    seed_book(fresh_db, "book with books.com subject", [("BOOKS_COM_TW", "文學小說")], ["BOOKS_COM_TW"])
    subjects_before = rows(fresh_db, "SELECT book_id, subject, source_code FROM book_subjects ORDER BY 1, 2, 3")

    code, out = run(monkeypatch, capsys, fresh_db, "sync", "--apply", "--config-dir", str(config))

    assert code == 0, out
    assert count_categories(fresh_db) == 18
    assert count_mappings(fresh_db) == expected_mappings
    assert rows(
        fresh_db,
        """
        SELECT m.source_code, m.subject, c.slug, m.mapping_method
        FROM provider_category_mappings m JOIN canonical_categories c ON c.id = m.canonical_category_id
        WHERE m.source_code = 'BOOKS_COM_TW' AND m.subject = '文學小說'
        """,
    ) == [("BOOKS_COM_TW", "文學小說", "literature", "VERIFIED_RULE")]
    assert rows(fresh_db, "SELECT slug, is_active FROM canonical_categories WHERE slug = 'simplified-chinese'") == [("simplified-chinese", True)]
    assert rows(fresh_db, "SELECT book_id, subject, source_code FROM book_subjects ORDER BY 1, 2, 3") == subjects_before


def test_second_apply_writes_nothing_and_keeps_timestamps(fresh_db: str, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    config = temp_config(tmp_path)
    run(monkeypatch, capsys, fresh_db, "sync", "--apply", "--config-dir", str(config))
    stamps_before = rows(
        fresh_db,
        "SELECT (SELECT json_agg(updated_at ORDER BY slug) FROM canonical_categories), "
        "(SELECT json_agg(updated_at ORDER BY source_code, subject) FROM provider_category_mappings)",
    )

    code, out = run(monkeypatch, capsys, fresh_db, "sync", "--apply", "--config-dir", str(config))

    assert code == 0
    assert "categories written 0, mappings written 0" in out
    assert (
        rows(
            fresh_db,
            "SELECT (SELECT json_agg(updated_at ORDER BY slug) FROM canonical_categories), "
            "(SELECT json_agg(updated_at ORDER BY source_code, subject) FROM provider_category_mappings)",
        )
        == stamps_before
    )


def test_changed_display_name_is_exactly_one_update(fresh_db: str, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    config = temp_config(tmp_path)
    run(monkeypatch, capsys, fresh_db, "sync", "--apply", "--config-dir", str(config))
    renamed = temp_config(tmp_path / "renamed", rename_literature="文學與小說")

    code, out = run(monkeypatch, capsys, fresh_db, "verify", "--config-dir", str(renamed))
    assert code == 1
    assert "categories: insert 0, update 1, unchanged 17, orphan 0" in out
    assert "~ category literature" in out

    code, out = run(monkeypatch, capsys, fresh_db, "sync", "--apply", "--config-dir", str(renamed))
    assert code == 0
    assert "categories written 1, mappings written 0" in out
    assert scalar(fresh_db, "SELECT display_name FROM canonical_categories WHERE slug = 'literature'") == "文學與小說"


def test_orphan_mapping_is_reported_and_kept(fresh_db: str, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    config = temp_config(tmp_path)
    run(monkeypatch, capsys, fresh_db, "sync", "--apply", "--config-dir", str(config))
    execute(
        fresh_db,
        """
        INSERT INTO provider_category_mappings (source_code, subject, provider_root_subject, canonical_category_id, mapping_method, updated_at)
        SELECT 'ESLITE', '已移除的名稱', 'eslite-l2:999', id, 'MANUAL', now() FROM canonical_categories WHERE slug = 'literature'
        """,
    )

    code, out = run(monkeypatch, capsys, fresh_db, "verify", "--config-dir", str(config))
    assert code == 0  # orphans are reported, not drift
    assert "orphan mapping ESLITE / 已移除的名稱" in out

    run(monkeypatch, capsys, fresh_db, "sync", "--apply", "--config-dir", str(config))
    assert scalar(fresh_db, "SELECT count(*) FROM provider_category_mappings WHERE subject = '已移除的名稱'") == 1


def test_apply_is_refused_while_names_are_ambiguous(fresh_db: str, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    code, out = run(monkeypatch, capsys, fresh_db, "sync", "--apply", "--config-dir", str(SHIPPED_CONFIG))

    assert code == 2
    assert "ambiguous" in out.lower()
    assert count_categories(fresh_db) == 0
    assert count_mappings(fresh_db) == 0


def test_failure_mid_transaction_rolls_back_everything(fresh_db: str, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    config = temp_config(tmp_path)
    calls = {"n": 0}
    real = repo.upsert_mapping

    def fail_after_some(cur, mapping, category_id):
        calls["n"] += 1
        if calls["n"] > 5:
            raise RuntimeError("simulated failure")
        return real(cur, mapping, category_id)

    monkeypatch.setattr(repo, "upsert_mapping", fail_after_some)

    code, out = run(monkeypatch, capsys, fresh_db, "sync", "--apply", "--config-dir", str(config))

    assert code == 1
    assert "simulated failure" in out
    assert "nothing was committed" in out
    assert count_categories(fresh_db) == 0
    assert count_mappings(fresh_db) == 0


def test_verify_exit_codes(fresh_db: str, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    config = temp_config(tmp_path)

    code, _ = run(monkeypatch, capsys, fresh_db, "verify", "--config-dir", str(config))
    assert code == 1  # nothing applied yet: inserts are drift

    run(monkeypatch, capsys, fresh_db, "sync", "--apply", "--config-dir", str(config))
    code, out = run(monkeypatch, capsys, fresh_db, "verify", "--config-dir", str(config))
    assert code == 0
    assert "verify: the database matches the rules" in out


def test_audit_counts_on_a_seeded_catalog(fresh_db: str, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    config = temp_config(tmp_path)
    run(monkeypatch, capsys, fresh_db, "sync", "--apply", "--config-dir", str(config))
    # B1: the same book under two sources, both mapping to literature: counted once.
    seed_book(
        fresh_db,
        "B1",
        [("BOOKS_COM_TW", "文學小說"), ("KINGSTONE", "文學")],
        ["BOOKS_COM_TW", "KINGSTONE"],
    )
    # B2: two different roots: two categories.
    seed_book(fresh_db, "B2", [("BOOKS_COM_TW", "漫畫/圖文書"), ("BOOKS_COM_TW", "心理勵志")], ["BOOKS_COM_TW"])
    # B3: only an unmapped subject.
    seed_book(fresh_db, "B3", [("BOOKS_COM_TW", "語文")], ["BOOKS_COM_TW"])
    # B4: no subjects at all.
    seed_book(fresh_db, "B4", [], ["BOOKS_COM_TW"])
    csv_path = tmp_path / "unmapped.csv"

    code, out = run(monkeypatch, capsys, fresh_db, "audit", "--unmapped-csv", str(csv_path))

    assert code == 0
    assert "BOOKS_COM_TW: subjects 4, mapped 3, unmapped 1" in out
    assert "KINGSTONE: subjects 1, mapped 1, unmapped 0" in out
    assert "total 4" in out
    assert "with at least one active category 2" in out
    assert "with no category 2" in out
    assert "with two or more categories 1" in out
    assert csv_path.read_text(encoding="utf-8").splitlines() == ["source_code,subject,books", "BOOKS_COM_TW,語文,1"]


def test_audit_on_an_empty_catalog(fresh_db: str, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    code, out = run(monkeypatch, capsys, fresh_db, "audit")

    assert code == 0
    assert "total 0" in out
