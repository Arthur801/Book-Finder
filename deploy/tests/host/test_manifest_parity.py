"""Parity between bookfinder_host.manifest and deploy/lib/manifest.sh.

Why: the compat check (bash) and the host (Python) must reach the same verdict on every manifest and pair of
manifests, or a database could be accepted by one and refused by the other.
"""

import itertools
import random
import subprocess
from pathlib import Path

import pytest
from bookfinder_host import manifest
from bookfinder_host.manifest import ManifestError, Migration

REPO_ROOT = Path(__file__).resolve().parents[3]
LIB = REPO_ROOT / "deploy" / "lib" / "manifest.sh"

IDS = [
    "20261010174616_EnablePgvector",
    "20261010174654_Catalog",
    "20261010174708_IdentityUserLibrary",
    "20261010174709_Name9",
    "20261010174709_Zeta",
]
HASHES = ["a" * 64, "b" * 64, "c" * 64, "0" * 64]


def bash_call(command: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f'source "$1"; shift; {command} "$@"', "bash", str(LIB), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def render(entries: list[tuple[str, str]]) -> str:
    return "".join(f"{migration_id} {digest}\n" for migration_id, digest in entries)


def valid_manifests() -> list[list[tuple[str, str]]]:
    """Every ascending subset of the id pool with the first hash, plus some hash variants."""
    manifests = []
    for size in range(len(IDS) + 1):
        for subset in itertools.combinations(IDS, size):
            manifests.append([(migration_id, HASHES[0]) for migration_id in subset])
    manifests.append([(IDS[0], HASHES[1])])
    manifests.append([(IDS[0], HASHES[0]), (IDS[1], HASHES[2])])
    return manifests


def invalid_texts() -> list[str]:
    good = render([(IDS[0], HASHES[0])])
    return [
        f"{IDS[1]} {HASHES[0]}\n{IDS[0]} {HASHES[0]}\n",  # not ascending
        good + good,  # duplicate id
        good.rstrip("\n"),  # no trailing newline
        good.replace("\n", "\r\n"),  # CRLF
        f"{IDS[0]} {HASHES[0].upper()}\n",  # uppercase hash
        "\n",  # blank line
        f"{IDS[0]}  {HASHES[0]}\n",  # double space
    ]


def write_bytes(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_bytes(content.encode("utf-8"))
    return path


def test_valid_and_invalid_manifests_agree_on_acceptance(tmp_path):
    for index, entries in enumerate(valid_manifests()):
        path = write_bytes(tmp_path, f"v{index}.txt", render(entries))
        assert bash_call("manifest_validate_file", str(path)).returncode == 0
        assert manifest.read_manifest_file(path) or entries == []
    for index, content in enumerate(invalid_texts()):
        path = write_bytes(tmp_path, f"i{index}.txt", content)
        assert bash_call("manifest_validate_file", str(path)).returncode != 0, content
        with pytest.raises(ManifestError):
            manifest.read_manifest_file(path)


def test_oversize_manifest_is_rejected_by_both(tmp_path):
    lines = "".join(f"2026{index:010d}_M{index} {HASHES[0]}\n" for index in range(3000))
    path = write_bytes(tmp_path, "big.txt", lines)
    assert len(lines.encode()) > 65536
    assert bash_call("manifest_validate_file", str(path)).returncode != 0
    with pytest.raises(ManifestError):
        manifest.read_manifest_file(path)


def test_symlink_is_rejected_by_both(tmp_path):
    real = write_bytes(tmp_path, "real.txt", render([(IDS[0], HASHES[0])]))
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    assert bash_call("manifest_validate_file", str(link)).returncode != 0
    with pytest.raises(ManifestError):
        manifest.read_manifest_file(link)


def test_digest_matches_bash_for_every_valid_manifest(tmp_path):
    for index, entries in enumerate(valid_manifests()):
        path = write_bytes(tmp_path, f"d{index}.txt", render(entries))
        bash = bash_call("manifest_schema_digest", str(path))
        assert bash.returncode == 0, bash.stderr
        python = manifest.schema_digest([Migration(i, h) for i, h in entries])
        assert python == bash.stdout.strip(), entries


def test_classify_and_pending_match_bash_for_generated_pairs(tmp_path):
    rng = random.Random(92)
    manifests = valid_manifests()
    pairs = [(a, b) for a in manifests for b in manifests]
    rng.shuffle(pairs)
    # Keep the runtime bounded: the full product is large, a seeded sample still covers every classification.
    checked = {"in-sync": 0, "forward": 0, "schema-ahead": 0, "divergent": 0}
    for index, (applied, target) in enumerate(pairs[:400]):
        applied_path = write_bytes(tmp_path, "a.txt", render(applied))
        target_path = write_bytes(tmp_path, "t.txt", render(target))
        bash = bash_call("manifest_classify", str(applied_path), str(target_path))
        assert bash.returncode == 0, bash.stderr
        python = manifest.classify([Migration(i, h) for i, h in applied], [Migration(i, h) for i, h in target])
        assert python == bash.stdout.strip(), (applied, target)
        checked[python] += 1
        if python in ("in-sync", "forward"):
            pending = bash_call("manifest_pending", str(applied_path), str(target_path))
            assert pending.returncode == 0, pending.stderr
            expected = [line for line in pending.stdout.splitlines()]
            got = [f"{m.id} {m.source_hash}" for m in manifest.pending([Migration(i, h) for i, h in applied], [Migration(i, h) for i, h in target])]
            assert got == expected, (applied, target)
    assert all(count > 0 for count in checked.values()), checked
