"""Tests for deploy/lib/contract_allowance.sh and the contract directory it reads.

Why: a contract allowance is the only way compat.sh accepts a dropped column or a rewritten table, so each rule that decides
whether data loss is accepted is pinned here: unknown directives fail, an allowance for a migration that is not pending is
ignored, an allowed column that still exists fails, and a verify.sql that returns rows fails.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "deploy" / "lib" / "contract_allowance.sh"
CONTRACT_ROOT = REPO_ROOT / "deploy" / "migration-test" / "contract"
MIGRATION_011 = "20261025120000_ContractMultiSourceCatalog"


def call(function: str, *args: str) -> subprocess.CompletedProcess:
    # Arguments go through "$@" so they are never interpolated into the script text.
    return subprocess.run(
        ["bash", "-c", 'source "$1"; shift; "$@"', "bash", str(LIB), function, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def write_allow(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "allow.tsv"
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_normalizes_both_directives_and_skips_comments_and_blank_lines(tmp_path):
    allow = write_allow(
        tmp_path,
        "# reviewed\n\ndrop-column\tbook_sources\tsource_type\nrewrite\tbook_identifiers\n",
    )
    result = call("contract_allowance_parse", str(allow))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "drop-column\tbook_sources\tsource_type\nrewrite\tbook_identifiers\n"


@pytest.mark.parametrize(
    "text",
    [
        "drop-table\tbook_sources\n",
        "DROP-COLUMN\tbook_sources\tsource_type\n",
        "truncate\tbook_sources\n",
        "drop-column\tbook_sources\n",
        "drop-column\tbook_sources\tsource_type\textra\n",
        "rewrite\tbook_identifiers\textra\n",
        "rewrite\tBook-Identifiers\n",
        "drop-column\tbook_sources\tsource type\n",
        "rewrite\t\n",
    ],
)
def test_unknown_or_malformed_directives_fail_with_the_line_number(tmp_path, text):
    allow = write_allow(tmp_path, "# header\n" + text)
    result = call("contract_allowance_parse", str(allow))
    assert result.returncode != 0
    assert result.stdout == ""
    assert "line 2" in result.stderr


def test_an_allowance_for_a_migration_that_is_not_pending_is_ignored():
    assert call("contract_allowance_is_pending", MIGRATION_011, "").returncode != 0
    assert call("contract_allowance_is_pending", MIGRATION_011, "20261024160045_MultiSourceCatalog").returncode != 0
    assert call("contract_allowance_is_pending", MIGRATION_011, "20261024160045_MultiSourceCatalog,20261025120000_ContractMultiSourceCatalog").returncode == 0


def test_pending_match_is_on_the_whole_id_not_a_prefix():
    assert call("contract_allowance_is_pending", "2026102512", "20261025120000_ContractMultiSourceCatalog").returncode != 0


def test_drop_problems_report_an_allowed_column_that_still_exists(tmp_path):
    allow = write_allow(tmp_path, "drop-column\tbook_sources\tsource_type\n")
    before = tmp_path / "before.tsv"
    before.write_text("book_sources\tsource_type\nbook_sources\tsource_code\n", encoding="utf-8")
    after = tmp_path / "after.tsv"
    after.write_text("book_sources\tsource_type\nbook_sources\tsource_code\n", encoding="utf-8")
    result = call("contract_drop_problems", str(allow), str(before), str(after))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "allowed drop-column book_sources.source_type still exists after the upgrade\n"


def test_drop_problems_are_empty_when_the_allowed_column_is_gone(tmp_path):
    allow = tmp_path / "allow.tsv"
    allow.write_text("drop-column\tbook_sources\tsource_type\nrewrite\tbook_identifiers\n", encoding="utf-8")
    before = tmp_path / "before.tsv"
    before.write_text("book_sources\tsource_type\nbook_sources\tsource_code\n", encoding="utf-8")
    after = tmp_path / "after.tsv"
    after.write_text("book_sources\tsource_code\n", encoding="utf-8")
    result = call("contract_drop_problems", str(allow), str(before), str(after))
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_drop_problems_report_an_allowance_for_a_column_that_never_existed(tmp_path):
    allow = tmp_path / "allow.tsv"
    allow.write_text("drop-column\tbook_subjects\tsource_type\n", encoding="utf-8")
    before = tmp_path / "before.tsv"
    before.write_text("book_subjects\tsubject\n", encoding="utf-8")
    after = tmp_path / "after.tsv"
    after.write_text("book_subjects\tsubject\n", encoding="utf-8")
    result = call("contract_drop_problems", str(allow), str(before), str(after))
    assert "does not exist before the upgrade" in result.stdout


@pytest.mark.parametrize(("rows", "verdict"), [(0, "pass"), (1, "fail"), (7, "fail")])
def test_verify_passes_only_with_zero_rows(rows, verdict):
    result = call("contract_verify_verdict", str(rows))
    assert result.stdout == f"{verdict}\n"


def test_011_allowance_is_exact_and_names_only_the_contract_changes():
    allow = CONTRACT_ROOT / MIGRATION_011 / "allow.tsv"
    parsed = call("contract_allowance_parse", str(allow))
    assert parsed.returncode == 0, parsed.stderr
    assert parsed.stdout == ("drop-column\tbook_sources\tsource_type\ndrop-column\tbook_subjects\tsource_type\nrewrite\tbook_identifiers\n")
    assert (CONTRACT_ROOT / MIGRATION_011 / "verify.sql").is_file()


def test_contract_ids_list_only_directories_in_sorted_order(tmp_path):
    (tmp_path / "b_second").mkdir()
    (tmp_path / "a_first").mkdir()
    (tmp_path / "loose.tsv").write_text("", encoding="utf-8")
    result = call("contract_allowance_ids", str(tmp_path))
    assert result.stdout == "a_first\nb_second\n"


def test_the_shipped_contract_directory_has_only_the_011_allowance():
    result = call("contract_allowance_ids", str(CONTRACT_ROOT))
    assert result.stdout == f"{MIGRATION_011}\n"


COMPAT = REPO_ROOT / "deploy" / "migration-test" / "compat.sh"


def test_compat_before_is_dropped_before_the_schema_comparison_even_when_the_data_check_fails():
    # Why: the scratch copies must never reach the schema dump. A static check of main() is the cheapest way to pin the
    # order, because compat.sh needs docker to run. Every step before the comparison is "|| true", so a failed check
    # continues to the drop.
    text = COMPAT.read_text(encoding="utf-8")
    # The forward branch starts at upgrade_to_target; schema-ahead has its own branch that never upgrades.
    forward = text[text.index("    upgrade_to_target\n") :]
    steps = ["check_contract_verify || true", "check_data_preserved || true", "drop_contract_scratch || true"]
    positions = [forward.index(step) for step in steps]
    assert positions == sorted(positions)
    assert forward.index("drop_contract_scratch || true") < forward.index("check_schema_matches_fresh || true")
    assert "DROP SCHEMA IF EXISTS compat_before CASCADE" in text


def test_the_allowance_is_only_loaded_after_the_pending_set_is_known():
    text = COMPAT.read_text(encoding="utf-8")
    main = text[text.index("\nmain() {") :]
    assert main.index("check_manifests") < main.index("load_contract_allowances") < main.index("start_database")
    assert main.index("fingerprint_before") < main.index("snapshot_contract_tables")
