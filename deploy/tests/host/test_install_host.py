"""install-host swap (N4): <root>/host/deploy-entry resolves to a complete tree at every crash point.

Why: the forced commands and book-finder-admin live under <root>/host, so an interrupted install must never leave that
path missing or half-copied. Each test injects a BaseException after one named step (the same thing a SIGKILL or a
reboot does to the rest of the process) and then checks what <root>/host resolves to.
"""

import os
import shutil
from pathlib import Path

import pytest
from bookfinder_host import operator_cli as op

LINKED_STEPS = ["staged", "version-installed", "link-created", "pointer-swapped", "root-synced"]
LEGACY_STEPS = ["staged", "version-installed", "legacy-link-created", "legacy-exchanged", "legacy-moved", "root-synced"]


class Crash(BaseException):
    """A process death after the named step; nothing catches it."""


def make_source(root: Path, marker: str) -> Path:
    source = root / f"source-{marker}"
    if source.exists():
        shutil.rmtree(source)
    (source / "bookfinder_host").mkdir(parents=True)
    (source / "bookfinder_host" / "__init__.py").write_text("", encoding="utf-8")
    (source / "bookfinder_host" / "HOST_API_RANGE").write_text("1 2\n" if marker == "v2" else "1 1\n", encoding="utf-8")
    (source / "bookfinder_host" / "payload.txt").write_text(marker, encoding="utf-8")
    (source / "deploy-entry").write_text(f"#!/usr/bin/env python3\n# {marker}\n", encoding="utf-8")
    (source / "book-finder-admin").write_text(f"#!/usr/bin/env python3\n# {marker}\n", encoding="utf-8")
    return source


def legacy_host(root: Path) -> Path:
    host = root / "host"
    (host / "bookfinder_host").mkdir(parents=True)
    (host / "bookfinder_host" / "HOST_API_RANGE").write_text("1 1\n", encoding="utf-8")
    (host / "bookfinder_host" / "payload.txt").write_text("v1", encoding="utf-8")
    (host / "bookfinder_host" / "marker").write_text("old install", encoding="utf-8")
    (host / "deploy-entry").write_text("#!/usr/bin/env python3\n# v1\n", encoding="utf-8")
    (host / "book-finder-admin").write_text("#!/usr/bin/env python3\n# v1\n", encoding="utf-8")
    return host


def tree_of(host: Path) -> dict[str, bytes]:
    """Contents of the tree that <host> currently resolves to, as {relative path: bytes}."""
    real = Path(os.path.realpath(host))
    return {str(p.relative_to(real)): p.read_bytes() for p in sorted(real.rglob("*")) if p.is_file()}


def crash_after(step):
    def checkpoint(name):
        if name == step:
            raise Crash(name)

    return checkpoint


def new_tree_after_clean_install(tmp_path: Path) -> dict[str, bytes]:
    root = tmp_path / "reference"
    root.mkdir()
    host = legacy_host(root)
    op._swap_install(make_source(root, "v2"), host)
    return tree_of(host)


@pytest.mark.parametrize("step", LINKED_STEPS)
def test_crash_at_every_step_of_a_linked_install_leaves_a_complete_tree(tmp_path, step):
    root = tmp_path / "linked"
    root.mkdir()
    host = legacy_host(root)
    op._swap_install(make_source(root, "v1"), host)  # first install: host is now a link to v1
    assert host.is_symlink()
    old_tree = tree_of(host)
    new_tree = new_tree_after_clean_install(tmp_path)
    with pytest.raises(Crash):
        op._swap_install(make_source(root, "v2"), host, checkpoint=crash_after(step))
    assert (host / "deploy-entry").exists()
    assert tree_of(host) in (old_tree, new_tree)
    if step in ("pointer-swapped", "root-synced"):
        assert tree_of(host) == new_tree
    # Recovery: a rerun completes the install whatever the crash left behind.
    result = op._swap_install(make_source(root, "v2"), host)
    assert tree_of(host) == new_tree
    assert result["version"] == Path(os.readlink(host)).name


@pytest.mark.parametrize("step", LEGACY_STEPS)
def test_crash_at_every_step_of_the_legacy_migration_leaves_a_complete_tree(tmp_path, step):
    root = tmp_path / "legacy"
    root.mkdir()
    host = legacy_host(root)
    old_tree = tree_of(host)
    new_tree = new_tree_after_clean_install(tmp_path)
    with pytest.raises(Crash):
        op._swap_install(make_source(root, "v2"), host, checkpoint=crash_after(step))
    assert (host / "deploy-entry").exists()
    assert tree_of(host) in (old_tree, new_tree)
    if step == "legacy-exchanged":
        # The old tree is complete but sits under host.new-<token>; the next install refuses and says what to do.
        with pytest.raises(op.Refusal, match="move it into"):
            op._swap_install(make_source(root, "v2"), host)
        leftover = next(p for p in root.iterdir() if p.name.startswith("host.new-") and p.is_dir())
        leftover.rename(root / "host-versions" / "legacy-recovered")
    result = op._swap_install(make_source(root, "v2"), host)
    assert tree_of(host) == new_tree
    # Once the exchange has happened the link already names the new version, so the rerun is a no-op.
    assert result["version"] == Path(os.readlink(host)).name


def test_identical_content_is_reused_and_changes_nothing(tmp_path):
    root = tmp_path / "reuse"
    root.mkdir()
    host = legacy_host(root)
    op._swap_install(make_source(root, "v1"), host)
    op._swap_install(make_source(root, "v2"), host)
    before = sorted(p.name for p in (root / "host-versions").iterdir())
    first = Path(os.readlink(host)).name
    again = op._swap_install(make_source(root, "v2"), host)
    assert again == {"version": first, "previous": None}
    assert sorted(p.name for p in (root / "host-versions").iterdir()) == before
    assert not [p for p in (root / "host-versions").iterdir() if p.name.startswith(".stage-")]


def test_current_and_previous_are_kept_and_older_versions_are_pruned(tmp_path):
    root = tmp_path / "prune"
    root.mkdir()
    host = legacy_host(root)
    first = op._swap_install(make_source(root, "v1"), host)  # v1 is the legacy migration's previous
    second = op._swap_install(make_source(root, "v2"), host)
    third_source = make_source(root, "v3")
    (third_source / "bookfinder_host" / "payload.txt").write_text("v3", encoding="utf-8")
    third = op._swap_install(third_source, host)
    kept = sorted(p.name for p in (root / "host-versions").iterdir())
    assert kept == sorted([third["version"], second["version"]])
    assert third["previous"] == second["version"]
    assert first["version"] not in kept
    assert tree_of(host)[str(Path("bookfinder_host") / "payload.txt")] == b"v3"


def test_legacy_directory_is_moved_into_versions_and_the_link_takes_its_place(tmp_path):
    root = tmp_path / "migrate"
    root.mkdir()
    host = legacy_host(root)
    result = op._swap_install(make_source(root, "v2"), host)
    assert host.is_symlink()
    assert os.readlink(host) == str(root / "host-versions" / result["version"])
    legacy = root / "host-versions" / result["previous"]
    assert (legacy / "bookfinder_host" / "marker").read_text(encoding="utf-8") == "old install"
    assert not [p for p in root.iterdir() if p.name.startswith("host.new-")]
