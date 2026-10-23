"""Unit tests for bookfinder_host.manifest.

Why: the host decides from these functions whether a deploy may touch the database, so every rejection rule is pinned
down, including the symlink case where docker cp copies a link that points into the host filesystem.
"""

import os
from pathlib import Path

import pytest
from bookfinder_host import manifest, safefile
from bookfinder_host.manifest import ManifestError, Migration

H1 = "a" * 64
H2 = "b" * 64
H3 = "c" * 64
ID1 = "20261010174616_EnablePgvector"
ID2 = "20261010174654_Catalog"
ID3 = "20261010174708_IdentityUserLibrary"
EMPTY_SHA256 = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def text(*entries: tuple[str, str]) -> str:
    return "".join(f"{migration_id} {digest}\n" for migration_id, digest in entries)


def write(path: Path, content: str) -> Path:
    path.write_bytes(content.encode("utf-8"))
    return path


def migrations(*entries: tuple[str, str]) -> list[Migration]:
    return [Migration(migration_id, digest) for migration_id, digest in entries]


def test_read_accepts_well_formed_manifest(tmp_path):
    path = write(tmp_path / "m.txt", text((ID1, H1), (ID2, H2)))
    assert manifest.read_manifest_file(path) == migrations((ID1, H1), (ID2, H2))


def test_read_accepts_empty_manifest(tmp_path):
    assert manifest.read_manifest_file(write(tmp_path / "m.txt", "")) == []


def test_read_rejects_symlink_even_when_target_is_valid(tmp_path):
    real = write(tmp_path / "real.txt", text((ID1, H1)))
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    with pytest.raises(ManifestError):
        manifest.read_manifest_file(link)


def test_read_rejects_directory_and_missing_file(tmp_path):
    with pytest.raises(ManifestError):
        manifest.read_manifest_file(tmp_path)
    with pytest.raises(ManifestError):
        manifest.read_manifest_file(tmp_path / "missing.txt")


def test_read_rejects_oversize_file(tmp_path):
    lines = []
    index = 0
    while sum(len(line) for line in lines) <= 65536:
        lines.append(f"2026{index:010d}_M{index} {H1}\n")
        index += 1
    with pytest.raises(ManifestError, match="65536"):
        manifest.read_manifest_file(write(tmp_path / "big.txt", "".join(lines)))


def test_read_accepts_exactly_max_size(tmp_path):
    name = "A" * (65536 - len("20261010174616_") - len(" ") - 64 - len("\n"))
    exact = f"20261010174616_{name} {H1}\n"
    assert len(exact.encode("utf-8")) == 65536
    assert manifest.read_manifest_file(write(tmp_path / "exact.txt", exact))[0].source_hash == H1


@pytest.mark.parametrize(
    "bad_line",
    [
        f"2026101017461_Short {H1}",  # 13-digit timestamp
        f"20261010174616_ {H1}",  # empty name
        f"20261010174616_Has-Dash {H1}",  # name outside [A-Za-z0-9]
        f"20261010174616_Name {H1[:-1]}",  # short hash
        f"20261010174616_Name {H1.upper()}",  # uppercase hex
        f"20261010174616_Name  {H1}",  # double space
        f"20261010174616_Name\t{H1}",  # tab separator
        f"20261010174616_Name {H1} extra",  # trailing field
        f"20261010174616_Name {H1}\r",  # CRLF line ending
        f"20261010174616_Name {H1}\n\n",  # blank line after the entry
    ],
)
def test_read_rejects_bad_line(tmp_path, bad_line):
    with pytest.raises(ManifestError):
        manifest.read_manifest_file(write(tmp_path / "m.txt", bad_line + "\n"))


def test_read_rejects_unsorted_and_duplicate_ids(tmp_path):
    with pytest.raises(ManifestError):
        manifest.read_manifest_file(write(tmp_path / "u.txt", text((ID2, H2), (ID1, H1))))
    with pytest.raises(ManifestError):
        manifest.read_manifest_file(write(tmp_path / "d.txt", text((ID1, H1), (ID1, H1))))


def test_read_rejects_missing_trailing_newline(tmp_path):
    with pytest.raises(ManifestError):
        manifest.read_manifest_file(write(tmp_path / "m.txt", f"{ID1} {H1}"))


def test_schema_digest_of_empty_manifest_is_digest_of_empty_input():
    assert manifest.schema_digest([]) == EMPTY_SHA256


def test_schema_digest_is_sha256_of_canonical_text():
    import hashlib

    entries = migrations((ID1, H1), (ID2, H2))
    expected = "sha256:" + hashlib.sha256(text((ID1, H1), (ID2, H2)).encode()).hexdigest()
    assert manifest.schema_digest(entries) == expected


def test_schema_digest_changes_with_one_hash_character():
    base = manifest.schema_digest(migrations((ID1, H1), (ID2, H2)))
    changed = manifest.schema_digest(migrations((ID1, H1), (ID2, "b" * 63 + "c")))
    assert base != changed


def test_classify_in_sync_when_equal():
    entries = migrations((ID1, H1), (ID2, H2))
    assert manifest.classify(entries, entries) == "in-sync"


def test_classify_empty_against_empty_is_in_sync():
    assert manifest.classify([], []) == "in-sync"


def test_classify_applied_strict_prefix_is_forward():
    assert manifest.classify(migrations((ID1, H1)), migrations((ID1, H1), (ID2, H2))) == "forward"


def test_classify_empty_applied_is_forward_for_non_empty_target():
    assert manifest.classify([], migrations((ID1, H1))) == "forward"


def test_classify_target_strict_prefix_is_schema_ahead():
    assert manifest.classify(migrations((ID1, H1), (ID2, H2)), migrations((ID1, H1))) == "schema-ahead"


def test_classify_same_id_different_hash_is_divergent():
    # N5: identity is (id, source_hash); the same id with another hash is a different migration.
    assert manifest.classify(migrations((ID1, H1)), migrations((ID1, H2), (ID2, H3))) == "divergent"


def test_classify_same_id_different_hash_on_last_line_is_divergent():
    assert manifest.classify(migrations((ID1, H1), (ID2, H2)), migrations((ID1, H1), (ID2, H3))) == "divergent"


def test_classify_inserted_in_middle_and_disjoint_are_divergent():
    assert manifest.classify(migrations((ID1, H1), (ID3, H3)), migrations((ID1, H1), (ID2, H2), (ID3, H3))) == "divergent"
    assert manifest.classify(migrations((ID2, H2)), migrations((ID1, H1))) == "divergent"


def test_pending_lists_target_entries_after_applied_prefix():
    applied = migrations((ID1, H1))
    target = migrations((ID1, H1), (ID2, H2), (ID3, H3))
    assert manifest.pending(applied, target) == migrations((ID2, H2), (ID3, H3))


def test_pending_is_empty_when_in_sync():
    entries = migrations((ID1, H1))
    assert manifest.pending(entries, entries) == []


def test_pending_refuses_schema_ahead_and_divergent():
    with pytest.raises(ValueError):
        manifest.pending(migrations((ID1, H1), (ID2, H2)), migrations((ID1, H1)))
    with pytest.raises(ValueError):
        manifest.pending(migrations((ID1, H1)), migrations((ID1, H2)))


def fake_docker(tmp_path, cid="0123456789ab", cp_source=None, rc_create=0, rc_pull=0):
    """Returns a runner whose docker create/cp/rm calls are scripted and recorded."""
    from bookfinder_host.ports import CommandResult
    from bookfinder_host.testing import ScriptedRunner

    calls = []

    def create(argv):
        return CommandResult(rc_create, f"{cid}\n", "" if rc_create == 0 else "no such image")

    def copy(argv):
        calls.append(argv)
        source = argv[2].split(":", 1)[1]
        dest = Path(argv[3])
        if cp_source is not None:
            cp_source(source, dest)
        return CommandResult(0, "", "")

    runner = ScriptedRunner(
        [
            (("docker", "pull"), lambda argv: CommandResult(rc_pull, "", "" if rc_pull == 0 else "manifest unknown")),
            (("docker", "create"), create),
            (("docker", "cp"), copy),
            (("docker", "rm"), lambda argv: CommandResult(0, "", "")),
        ]
    )
    return runner, calls


IMAGE = "ghcr.io/example/book-finder-web@sha256:" + "d" * 64


def test_extract_reads_both_files_from_container(tmp_path):
    def copy_files(source, dest):
        if source.endswith("migrations.txt"):
            dest.write_text(text((ID1, H1)))
        else:
            dest.write_text("1\n")

    runner, calls = fake_docker(tmp_path, cp_source=copy_files)
    dest = tmp_path / "out"
    dest.mkdir()
    metadata = manifest.extract_release_metadata(runner, IMAGE, dest)
    assert metadata.migrations == tuple(migrations((ID1, H1)))
    assert metadata.release_api == 1
    # docker cp must never dereference: -L would follow a link into the host filesystem.
    assert all("-L" not in argv for argv in calls)
    assert not any(argv[:2] == ["docker", "run"] for argv in runner.calls_argv())


def test_extract_rejects_symlink_without_reading_its_target(tmp_path, monkeypatch):
    host_secret = tmp_path / "host-secret.txt"
    host_secret.write_text(text((ID1, H1)))

    def copy_symlink(source, dest):
        if source.endswith("migrations.txt"):
            os.symlink(host_secret, dest)
        else:
            dest.write_text("1\n")

    opened = []
    real_open = os.open

    def spy_open(path, *args, **kwargs):
        opened.append(os.fspath(path))
        return real_open(path, *args, **kwargs)

    runner, _ = fake_docker(tmp_path, cp_source=copy_symlink)
    dest = tmp_path / "out"
    dest.mkdir()
    monkeypatch.setattr(safefile.os, "open", spy_open)
    with pytest.raises(ManifestError):
        manifest.extract_release_metadata(runner, IMAGE, dest)
    assert str(host_secret) not in opened


def test_extract_rejects_bad_release_api(tmp_path):
    def copy_files(source, dest):
        if source.endswith("migrations.txt"):
            dest.write_text("")
        else:
            dest.write_text("1.0\n")

    runner, _ = fake_docker(tmp_path, cp_source=copy_files)
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ManifestError):
        manifest.extract_release_metadata(runner, IMAGE, dest)


def test_extract_rejects_oversize_release_api(tmp_path):
    def copy_files(source, dest):
        dest.write_text("" if source.endswith("migrations.txt") else "1" * 17 + "\n")

    runner, _ = fake_docker(tmp_path, cp_source=copy_files)
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ManifestError):
        manifest.extract_release_metadata(runner, IMAGE, dest)


@pytest.mark.parametrize(
    "reference",
    [
        "-rm",
        "ghcr.io/example/book-finder-web:v1.0.0",  # tag, the thing digest pinning exists to avoid
        "ghcr.io/example/book-finder-web:v1.0.0@sha256:" + "d" * 64,  # tag plus digest is still a tag
        "ghcr.io/example/book-finder-web@sha256:" + "D" * 64,  # uppercase digest
    ],
)
def test_extract_refuses_references_that_are_not_digest_pinned(tmp_path, reference):
    runner, _ = fake_docker(tmp_path)
    with pytest.raises(ManifestError):
        manifest.extract_release_metadata(runner, reference, tmp_path)
    assert runner.calls_argv() == []


def test_extract_pulls_explicitly_then_creates_with_pull_never(tmp_path):
    def copy_files(source, dest):
        dest.write_text("" if source.endswith("migrations.txt") else "1\n")

    runner, _ = fake_docker(tmp_path, cp_source=copy_files)
    dest = tmp_path / "out"
    dest.mkdir()
    manifest.extract_release_metadata(runner, IMAGE, dest)
    commands = runner.calls_argv()
    assert commands[0] == ["docker", "pull", IMAGE]
    assert commands[1] == ["docker", "create", "--pull=never", IMAGE]
    assert commands[-1][:2] == ["docker", "rm"]


def test_extract_reports_pull_failure_clearly_and_never_creates(tmp_path):
    runner, _ = fake_docker(tmp_path, rc_pull=1)
    with pytest.raises(ManifestError, match="docker pull failed"):
        manifest.extract_release_metadata(runner, IMAGE, tmp_path)
    assert all(argv[:2] != ["docker", "create"] for argv in runner.calls_argv())


def test_extract_reports_docker_create_failure(tmp_path):
    runner, _ = fake_docker(tmp_path, rc_create=1)
    with pytest.raises(ManifestError, match="docker create"):
        manifest.extract_release_metadata(runner, IMAGE, tmp_path)
