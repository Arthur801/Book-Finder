"""Tests for deploy/lib/schema_dump.sh.

Why: the fresh-install check passes only when two real schema dumps match. A pg_dump that fails or prints nothing must make
the check fail, otherwise two empty dumps compare equal and the gate passes without comparing anything.
"""

import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "deploy" / "lib" / "schema_dump.sh"

NORMAL_DUMP = """--
-- PostgreSQL database dump
--

SET statement_timeout = 0;
SELECT pg_catalog.set_config('search_path', '', false);
\\restrict abc123

CREATE TABLE public.books (
    id integer NOT NULL
);

\\unrestrict abc123
"""


def fake_command(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def run_dump(label: str, command: Path) -> subprocess.CompletedProcess:
    # The command and label go through "$@" so paths stay literal, the same way the other lib tests call their helpers.
    return subprocess.run(
        ["bash", "-c", 'source "$1"; shift; schema_dump_normalized "$@"', "bash", str(LIB), label, str(command)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_failing_pg_dump_is_an_error_with_its_stderr(tmp_path):
    dump = fake_command(tmp_path, "pg_dump", "echo 'pg_dump: error: connection refused' >&2\nexit 1\n")
    result = run_dump("book_finder", dump)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "pg_dump failed for book_finder: pg_dump: error: connection refused" in result.stderr


def test_failing_pg_dump_does_not_print_partial_output(tmp_path):
    dump = fake_command(tmp_path, "pg_dump", f"cat <<'DUMP'\n{NORMAL_DUMP}DUMP\necho 'boom' >&2\nexit 2\n")
    result = run_dump("book_finder", dump)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "pg_dump failed for book_finder: boom" in result.stderr


def test_empty_output_is_an_error(tmp_path):
    dump = fake_command(tmp_path, "pg_dump", "exit 0\n")
    result = run_dump("book_finder_fresh", dump)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "no CREATE TABLE" in result.stderr


def test_output_with_only_comments_is_an_error(tmp_path):
    dump = fake_command(tmp_path, "pg_dump", "printf -- '-- empty\\nSET x = 1;\\n'\n")
    result = run_dump("book_finder_fresh", dump)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "no CREATE TABLE" in result.stderr


def test_normal_output_is_normalized(tmp_path):
    dump = fake_command(tmp_path, "pg_dump", f"cat <<'DUMP'\n{NORMAL_DUMP}DUMP\n")
    result = run_dump("book_finder", dump)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "CREATE TABLE public.books (\n    id integer NOT NULL\n);\n"


def test_normalized_output_keeps_every_create_table(tmp_path):
    body = "cat <<'DUMP'\nCREATE TABLE public.a (\n);\nCREATE TABLE public.b (\n);\nDUMP\n"
    result = run_dump("book_finder", fake_command(tmp_path, "pg_dump", body))
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("CREATE TABLE ") == 2


def test_two_failed_dumps_do_not_compare_equal(tmp_path):
    # The gate compares the two outputs; both failures must surface as errors, never as matching empty text.
    failing = fake_command(tmp_path, "pg_dump", "exit 1\n")
    first = run_dump("book_finder", failing)
    second = run_dump("book_finder_fresh", failing)
    assert first.returncode != 0
    assert second.returncode != 0
    assert first.stdout == second.stdout == ""
