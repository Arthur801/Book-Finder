"""Tests for bookfinder_host.release_content: the release directory is refused when it holds anything but plain files.

Why: docker cp without -L copies a symlink as a link, and compose would then read through it into the host. Every
refusal here happens before the content is read, so a link's target is never opened.
"""

import hashlib
import os
from pathlib import Path

import pytest
from bookfinder_host import release_content as rc
from bookfinder_host.manifest import Migration
from bookfinder_host.safefile import UnsafeFileError
from bookfinder_host.testing import write_release

ID1 = "20261010174616_EnablePgvector"
H1 = "a" * 64


def valid(tmp_path: Path) -> Path:
    return write_release(tmp_path / "release", [Migration(ID1, H1)])


def test_valid_tree_is_accepted_and_hashed_by_its_compose_file(tmp_path):
    root = valid(tmp_path)
    content = rc.validate_tree(root)
    assert content.compose_sha256 == hashlib.sha256((root / "compose.prod.yaml").read_bytes()).hexdigest()


def test_nested_directories_are_allowed(tmp_path):
    root = valid(tmp_path)
    (root / "nested" / "deeper").mkdir(parents=True)
    (root / "nested" / "deeper" / "note.txt").write_text("ok")
    rc.validate_tree(root)


def test_symlink_to_a_file_is_refused_and_its_target_is_not_read(tmp_path):
    root = valid(tmp_path)
    (root / "shadow").symlink_to("/etc/shadow")
    with pytest.raises(rc.ReleaseRejected, match="shadow"):
        rc.validate_tree(root)


def test_symlink_to_a_directory_is_refused(tmp_path):
    root = valid(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(rc.ReleaseRejected, match="linked"):
        rc.validate_tree(root)


def test_a_symlink_that_replaces_a_required_file_is_refused(tmp_path):
    root = valid(tmp_path)
    (root / "migrations.txt").unlink()
    (root / "migrations.txt").symlink_to(root / "RELEASE_API")
    with pytest.raises(rc.ReleaseRejected):
        rc.validate_tree(root)


def test_fifo_is_refused_without_being_opened(tmp_path):
    root = valid(tmp_path)
    os.mkfifo(root / "pipe")
    with pytest.raises(rc.ReleaseRejected, match="pipe"):
        rc.validate_tree(root)


def test_release_root_that_is_a_symlink_is_refused(tmp_path):
    root = valid(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(rc.ReleaseRejected, match="not a directory"):
        rc.validate_tree(link)


def test_total_size_over_two_mebibytes_is_refused(tmp_path):
    root = valid(tmp_path)
    # The small required files already take a few hundred bytes, so this sum goes over the limit.
    (root / "big.bin").write_bytes(b"\0" * (rc.MAX_RELEASE_BYTES - 10))
    with pytest.raises(rc.ReleaseRejected, match="larger than"):
        rc.validate_tree(root)


def test_exactly_the_limit_is_accepted(tmp_path):
    root = valid(tmp_path)
    used = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, files in os.walk(root) for f in files)
    (root / "fill.bin").write_bytes(b"\0" * (rc.MAX_RELEASE_BYTES - used))
    rc.validate_tree(root)


@pytest.mark.parametrize("missing", ["compose.prod.yaml", "migrations.txt", "RELEASE_API"])
def test_missing_required_file_is_refused(tmp_path, missing):
    root = valid(tmp_path)
    (root / missing).unlink()
    with pytest.raises(rc.ReleaseRejected, match="missing"):
        rc.validate_tree(root)


def test_optional_crawler_files_may_be_absent_or_present(tmp_path):
    root = valid(tmp_path)
    rc.validate_tree(root)
    (root / "run-crawler.sh").write_text("#!/bin/sh\n")
    (root / "crawler.cron").write_text("* * * * * x\n")
    rc.validate_tree(root)


def test_compose_sha_of_an_installed_release_refuses_a_symlinked_directory(tmp_path):
    root = valid(tmp_path)
    link = tmp_path / "installed"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(UnsafeFileError):
        rc.compose_sha256_of(link)


def test_compose_sha_of_an_installed_release_matches_validation(tmp_path):
    root = valid(tmp_path)
    assert rc.compose_sha256_of(root) == rc.validate_tree(root).compose_sha256
