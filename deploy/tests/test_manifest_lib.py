"""Tests for deploy/lib/manifest.sh.

Why: the host and compat scripts trust these helpers to decide whether a deploy can proceed, so each rule is tested on
its own, including the boundary cases that would otherwise silently let a divergent database through.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "deploy" / "lib" / "manifest.sh"

H1 = "a" * 64
H2 = "b" * 64
H3 = "c" * 64
ID1 = "20261010174616_EnablePgvector"
ID2 = "20261010174654_Catalog"
ID3 = "20261010174708_IdentityUserLibrary"


def manifest(*entries: tuple[str, str]) -> str:
    return "".join(f"{migration_id} {digest}\n" for migration_id, digest in entries)


def write(path: Path, text: str) -> Path:
    path.write_bytes(text.encode("utf-8"))
    return path


def run_lib(command: str, *args: str) -> subprocess.CompletedProcess:
    # Arguments go through "$@" rather than string interpolation so paths with spaces or quotes stay literal.
    return subprocess.run(
        ["bash", "-c", f'source "$1"; shift; {command} "$@"', "bash", str(LIB), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def classify(tmp_path: Path, applied: str, target: str) -> str:
    result = run_lib("manifest_classify", str(write(tmp_path / "a.txt", applied)), str(write(tmp_path / "t.txt", target)))
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def validate(path: Path) -> subprocess.CompletedProcess:
    return run_lib("manifest_validate_file", str(path))


# manifest_classify

def test_classify_in_sync_when_lines_are_equal(tmp_path):
    text = manifest((ID1, H1), (ID2, H2))
    assert classify(tmp_path, text, text) == "in-sync"


def test_classify_empty_against_empty_is_in_sync(tmp_path):
    assert classify(tmp_path, "", "") == "in-sync"


def test_classify_empty_applied_against_non_empty_target_is_forward(tmp_path):
    assert classify(tmp_path, "", manifest((ID1, H1))) == "forward"


def test_classify_applied_strict_prefix_is_forward(tmp_path):
    assert classify(tmp_path, manifest((ID1, H1)), manifest((ID1, H1), (ID2, H2))) == "forward"


def test_classify_target_strict_prefix_is_schema_ahead(tmp_path):
    assert classify(tmp_path, manifest((ID1, H1), (ID2, H2)), manifest((ID1, H1))) == "schema-ahead"


def test_classify_same_id_different_hash_is_divergent(tmp_path):
    assert classify(tmp_path, manifest((ID1, H1)), manifest((ID1, H2), (ID2, H3))) == "divergent"


def test_classify_same_id_different_hash_on_last_line_is_divergent(tmp_path):
    assert classify(tmp_path, manifest((ID1, H1), (ID2, H2)), manifest((ID1, H1), (ID2, H3))) == "divergent"


def test_classify_inserted_in_middle_is_divergent(tmp_path):
    applied = manifest((ID1, H1), (ID3, H3))
    target = manifest((ID1, H1), (ID2, H2), (ID3, H3))
    assert classify(tmp_path, applied, target) == "divergent"


def test_classify_disjoint_manifests_are_divergent(tmp_path):
    assert classify(tmp_path, manifest((ID2, H2)), manifest((ID1, H1))) == "divergent"


# manifest_pending

def test_pending_lists_target_lines_after_the_applied_prefix(tmp_path):
    applied = write(tmp_path / "a.txt", manifest((ID1, H1)))
    target = write(tmp_path / "t.txt", manifest((ID1, H1), (ID2, H2), (ID3, H3)))
    result = run_lib("manifest_pending", str(applied), str(target))
    assert result.returncode == 0, result.stderr
    assert result.stdout == manifest((ID2, H2), (ID3, H3))


def test_pending_is_empty_when_in_sync(tmp_path):
    text = manifest((ID1, H1))
    result = run_lib("manifest_pending", str(write(tmp_path / "a.txt", text)), str(write(tmp_path / "t.txt", text)))
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_pending_from_empty_applied_is_the_whole_target(tmp_path):
    target = manifest((ID1, H1), (ID2, H2))
    result = run_lib("manifest_pending", str(write(tmp_path / "a.txt", "")), str(write(tmp_path / "t.txt", target)))
    assert result.returncode == 0, result.stderr
    assert result.stdout == target


@pytest.mark.parametrize("applied_entries,target_entries", [
    ([(ID1, H1), (ID2, H2)], [(ID1, H1)]),
    ([(ID1, H1)], [(ID1, H2)]),
])
def test_pending_refuses_non_forward_manifests(tmp_path, applied_entries, target_entries):
    result = run_lib(
        "manifest_pending",
        str(write(tmp_path / "a.txt", manifest(*applied_entries))),
        str(write(tmp_path / "t.txt", manifest(*target_entries))),
    )
    assert result.returncode != 0
    assert result.stdout == ""


# manifest_validate_file

def test_validate_accepts_a_well_formed_manifest(tmp_path):
    assert validate(write(tmp_path / "m.txt", manifest((ID1, H1), (ID2, H2)))).returncode == 0


def test_validate_accepts_an_empty_manifest(tmp_path):
    assert validate(write(tmp_path / "m.txt", "")).returncode == 0


def test_validate_rejects_symlink_even_when_target_is_valid(tmp_path):
    real = write(tmp_path / "real.txt", manifest((ID1, H1)))
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    result = validate(link)
    assert result.returncode != 0
    assert "symlink" in result.stderr or "regular file" in result.stderr


def test_validate_rejects_directory(tmp_path):
    assert validate(tmp_path).returncode != 0


def test_validate_rejects_missing_file(tmp_path):
    assert validate(tmp_path / "missing.txt").returncode != 0


def test_validate_rejects_oversize_file(tmp_path):
    # Padding with comments-free valid lines keeps only the size rule failing.
    lines = []
    index = 0
    while sum(len(line) for line in lines) <= 65536:
        lines.append(f"2026{index:010d}_M{index} {H1}\n")
        index += 1
    result = validate(write(tmp_path / "big.txt", "".join(lines)))
    assert result.returncode != 0
    assert "65536" in result.stderr


def test_validate_accepts_exactly_max_size(tmp_path):
    # One long migration name fills the file to the limit: 15 (timestamp_) + name + space + 64 (hash) + newline.
    name = "A" * (65536 - len("20261010174616_") - len(" ") - 64 - len("\n"))
    exact = f"20261010174616_{name} {H1}\n"
    assert len(exact.encode("utf-8")) == 65536
    assert validate(write(tmp_path / "exact.txt", exact)).returncode == 0


@pytest.mark.parametrize("bad_line", [
    f"2026101017461_Short {H1}",           # 13-digit timestamp
    f"20261010174616_ {H1}",               # empty name
    f"20261010174616_Has-Dash {H1}",       # name outside [A-Za-z0-9]
    f"20261010174616_Name {H1[:-1]}",      # short hash
    f"20261010174616_Name {H1.upper()}",   # uppercase hex
    f"20261010174616_Name  {H1}",          # double space
    f"20261010174616_Name\t{H1}",          # tab separator
    f"20261010174616_Name {H1} extra",     # trailing field
    f"20261010174616_Name {H1}\r",         # CRLF line ending
])
def test_validate_rejects_bad_line(tmp_path, bad_line):
    assert validate(write(tmp_path / "m.txt", bad_line + "\n")).returncode != 0


def test_validate_rejects_unsorted_ids(tmp_path):
    assert validate(write(tmp_path / "m.txt", manifest((ID2, H2), (ID1, H1)))).returncode != 0


def test_validate_rejects_duplicate_ids(tmp_path):
    assert validate(write(tmp_path / "m.txt", manifest((ID1, H1), (ID1, H1)))).returncode != 0


def test_validate_rejects_missing_trailing_newline(tmp_path):
    assert validate(write(tmp_path / "m.txt", f"{ID1} {H1}")).returncode != 0


# manifest_schema_digest

def test_digest_is_sha256_prefixed(tmp_path):
    result = run_lib("manifest_schema_digest", str(write(tmp_path / "m.txt", manifest((ID1, H1)))))
    assert result.returncode == 0, result.stderr
    digest = result.stdout.strip()
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_digest_of_empty_manifest_is_digest_of_empty_input(tmp_path):
    result = run_lib("manifest_schema_digest", str(write(tmp_path / "m.txt", "")))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_digest_is_stable_and_changes_with_one_hash_character(tmp_path):
    base = manifest((ID1, H1), (ID2, H2))
    changed = manifest((ID1, H1), (ID2, "b" * 63 + "c"))
    first = run_lib("manifest_schema_digest", str(write(tmp_path / "a.txt", base))).stdout
    again = run_lib("manifest_schema_digest", str(write(tmp_path / "b.txt", base))).stdout
    other = run_lib("manifest_schema_digest", str(write(tmp_path / "c.txt", changed))).stdout
    assert first == again
    assert first != other
