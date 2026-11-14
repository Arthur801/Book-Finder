"""CLI behaviour that needs no database: exit codes, usage errors, eslite-import, DSN redaction. No network."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from eslite_tree import read_level3_tsv
from manage_categories import main, redact
from tree_fixtures import synthetic_tree

SHIPPED_CONFIG = Path(__file__).resolve().parents[1] / "config"
# A Unix-socket directory that does not exist: libpq fails at once, with no network traffic.
UNREACHABLE_DSN = "postgresql://tester:not-a-real-pw@%2Fnonexistent-socket-dir/nodb"


@pytest.fixture
def no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture
def unreachable_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DSN)


def write_tree(directory: Path, tree: list) -> Path:
    path = directory / "tree.json"
    path.write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")
    return path


def test_eslite_import_writes_the_tsv_without_a_database(tmp_path: Path, no_database: None) -> None:
    tree = write_tree(tmp_path, synthetic_tree())
    output = tmp_path / "eslite_level3.tsv"

    code = main(["eslite-import", "--tree", str(tree), "--output", str(output)])

    assert code == 0
    rows = read_level3_tsv(output)
    assert [(r.level2_id, r.level3_id, r.level3_name) for r in rows] == [
        (28, 1001, "小說"),
        (28, 1004, "科幻 小說"),
        (61, 3001, "哲學"),
        (61, 3002, "小說"),
    ]


def test_eslite_import_default_output_is_the_config_tsv(tmp_path: Path, no_database: None) -> None:
    tree = write_tree(tmp_path, synthetic_tree())
    config = tmp_path / "config"
    shutil.copytree(SHIPPED_CONFIG, config)

    code = main(["eslite-import", "--tree", str(tree), "--config-dir", str(config)])

    assert code == 0
    assert len(read_level3_tsv(config / "eslite_level3.tsv")) == 4


def test_eslite_import_tree_without_top_category_is_exit_2(tmp_path: Path, no_database: None, capsys) -> None:
    tree = write_tree(tmp_path, [{"id": 1057, "depth": 1, "description": "品牌旗艦", "children": []}])

    code = main(["eslite-import", "--tree", str(tree), "--output", str(tmp_path / "out.tsv")])

    assert code == 2
    assert "id 3" in capsys.readouterr().err
    assert not (tmp_path / "out.tsv").exists()


def test_eslite_import_bad_json_is_exit_2(tmp_path: Path, no_database: None) -> None:
    tree = tmp_path / "tree.json"
    tree.write_text("{not json", encoding="utf-8")

    assert main(["eslite-import", "--tree", str(tree), "--output", str(tmp_path / "out.tsv")]) == 2


def test_eslite_import_missing_tree_is_exit_2(tmp_path: Path, no_database: None) -> None:
    assert main(["eslite-import", "--tree", str(tmp_path / "nope.json"), "--output", str(tmp_path / "o.tsv")]) == 2


@pytest.mark.parametrize("command", [["init"], ["audit"], ["sync"], ["verify"]])
def test_database_commands_without_database_url_are_exit_2(command: list[str], no_database: None, capsys) -> None:
    assert main(command) == 2
    assert "DATABASE_URL" in capsys.readouterr().err


def test_unknown_command_is_a_usage_error() -> None:
    assert main(["bogus"]) == 2


def test_sync_dry_run_and_apply_are_mutually_exclusive(unreachable_database: None) -> None:
    assert main(["sync", "--dry-run", "--apply"]) == 2


def test_sync_with_broken_config_is_exit_2_before_connecting(tmp_path: Path, unreachable_database: None, capsys) -> None:
    config = tmp_path / "config"
    config.mkdir()

    assert main(["sync", "--dry-run", "--config-dir", str(config)]) == 2
    assert "canonical_categories.toml" in capsys.readouterr().err


def test_apply_is_refused_while_names_are_ambiguous_without_connecting(unreachable_database: None, capsys, tmp_path: Path) -> None:
    # Without the shipped manual rules two Eslite names are ambiguous, so --apply must refuse before any connection is attempted.
    config = tmp_path / "config"
    shutil.copytree(SHIPPED_CONFIG, config)
    (config / "subject_mappings.toml").write_text("# no manual rules\n", encoding="utf-8")
    assert main(["sync", "--apply", "--config-dir", str(config)]) == 2
    err = capsys.readouterr().err
    assert "ambiguous" in err.lower()
    assert "not-a-real-pw" not in err


def test_connection_failure_is_exit_1_and_never_prints_the_password(unreachable_database: None, capsys) -> None:
    code = main(["init"])

    out, err = capsys.readouterr()
    assert code == 1
    assert "not-a-real-pw" not in out + err


def test_redact_removes_the_dsn_and_its_password() -> None:
    dsn = "postgresql://tester:s3cret-pw@db.internal:5432/bf"
    text = f"connection to {dsn} failed; password s3cret-pw rejected"

    redacted = redact(text, dsn)

    assert "s3cret-pw" not in redacted
    assert "db.internal" not in redacted
    assert "<redacted>" in redacted


def test_redact_handles_key_value_dsn() -> None:
    dsn = "host=db.internal dbname=bf user=tester password=s3cret-pw"

    assert "s3cret-pw" not in redact(f"bad dsn: {dsn}", dsn)
