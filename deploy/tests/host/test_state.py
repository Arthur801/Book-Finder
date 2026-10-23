"""Tests for bookfinder_host.state: strict parsing, atomic CAS writes, and the pure transition helpers.

Why: state.json is the only record of what the host believes is running and applied. A torn write, a silently
accepted unknown key, or a lost revision would let a later deploy act on a false picture.
"""

import json
import os
import stat

import pytest
from bookfinder_host import state as st
from bookfinder_host.manifest import Migration, schema_digest
from bookfinder_host.testing import sample_state

H1 = "a" * 64
H2 = "b" * 64
ID1 = "20261010174616_EnablePgvector"
ID2 = "20261010174654_Catalog"
TAG1 = "v1.0.0"
TAG2 = "v1.1.0"
WEB1 = "sha256:" + "1" * 64
WEB2 = "sha256:" + "2" * 64
CRAWLER = "sha256:" + "3" * 64


def state_file(tmp_path, state):
    path = tmp_path / "state.json"
    st.write_state(path, st.replace_revision(state, 0), expected_revision=0)
    return path


def test_load_missing_file_raises_state_missing(tmp_path):
    with pytest.raises(st.StateMissing):
        st.load_state(tmp_path / "state.json")


def test_write_then_load_round_trips(tmp_path):
    written = sample_state(applied=[Migration(ID1, H1)])
    path = state_file(tmp_path, written)
    loaded = st.load_state(path)
    assert loaded.revision == 1
    assert loaded.schema == written.schema
    assert loaded.runtime == written.runtime


def test_write_bootstrap_uses_revision_zero_for_missing_file(tmp_path):
    written = st.write_state(tmp_path / "state.json", st.replace_revision(sample_state(), 0), expected_revision=0)
    assert written.revision == 1
    assert st.load_state(tmp_path / "state.json").revision == 1


def test_write_creates_file_with_mode_0600(tmp_path):
    path = state_file(tmp_path, sample_state())
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_write_increments_revision_by_exactly_one(tmp_path):
    path = state_file(tmp_path, sample_state())
    current = st.load_state(path)
    written = st.write_state(path, st.replace_revision(current, current.revision), expected_revision=current.revision)
    assert written.revision == current.revision + 1
    assert st.load_state(path).revision == current.revision + 1


def test_write_refuses_when_on_disk_revision_differs(tmp_path):
    path = state_file(tmp_path, sample_state())
    stale = st.replace_revision(sample_state(), 1)
    with pytest.raises(st.RevisionConflict):
        st.write_state(path, stale, expected_revision=5)
    assert st.load_state(path).revision == 1


def test_write_refuses_when_expected_revision_is_not_the_state_being_replaced(tmp_path):
    path = state_file(tmp_path, sample_state())
    current = st.load_state(path)
    with pytest.raises(ValueError):
        st.write_state(path, st.replace_revision(current, 9), expected_revision=current.revision)


def test_failed_replace_leaves_previous_state_and_no_temporary_files(tmp_path, monkeypatch):
    path = state_file(tmp_path, sample_state())
    before = path.read_bytes()

    def broken_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(st.os, "replace", broken_replace)
    with pytest.raises(OSError):
        st.write_state(path, st.replace_revision(sample_state(), 1), expected_revision=1)
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]


def valid_document():
    return json.loads(json.dumps(st.state_to_json(sample_state(applied=[Migration(ID1, H1)]))))


def write_document(tmp_path, document, text=None):
    path = tmp_path / "state.json"
    path.write_text(text if text is not None else json.dumps(document), encoding="utf-8")
    return path


def test_load_rejects_malformed_json(tmp_path):
    with pytest.raises(st.StateCorrupt):
        st.load_state(write_document(tmp_path, None, text="{not json"))


def test_load_rejects_unknown_top_level_key(tmp_path):
    document = valid_document()
    document["extra"] = 1
    with pytest.raises(st.StateCorrupt):
        st.load_state(write_document(tmp_path, document))


def test_load_rejects_missing_key(tmp_path):
    document = valid_document()
    del document["crawler"]
    with pytest.raises(st.StateCorrupt):
        st.load_state(write_document(tmp_path, document))


def test_load_rejects_duplicate_keys(tmp_path):
    with pytest.raises(st.StateCorrupt):
        st.load_state(write_document(tmp_path, None, text='{"revision": 1, "revision": 2}'))


def test_load_rejects_schema_digest_that_does_not_match_applied(tmp_path):
    document = valid_document()
    document["schema"]["digest"] = "sha256:" + "f" * 64
    with pytest.raises(st.StateCorrupt, match="digest"):
        st.load_state(write_document(tmp_path, document))


def test_load_rejects_dirty_flag_without_dirty_metadata(tmp_path):
    document = valid_document()
    document["schema"]["dirty"] = True
    with pytest.raises(st.StateCorrupt):
        st.load_state(write_document(tmp_path, document))


def test_load_rejects_symlink_even_to_a_valid_state(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real = state_file(real_dir, sample_state())
    link = tmp_path / "state.json"
    link.symlink_to(real)
    with pytest.raises(st.StateCorrupt):
        st.load_state(link)


def test_load_rejects_negative_revision(tmp_path):
    document = valid_document()
    document["revision"] = -1
    with pytest.raises(st.StateCorrupt):
        st.load_state(write_document(tmp_path, document))


# Pure transition helpers


def test_mark_dirty_sets_flags_and_keeps_revision():
    before = sample_state(revision=4)
    after = st.mark_dirty(before, TAG2, "2026-10-23T01:00:00Z")
    assert after.schema.dirty is True
    assert after.schema.dirty_release == TAG2
    assert after.schema.dirty_since == "2026-10-23T01:00:00Z"
    assert after.revision == 4
    assert before.schema.dirty is False


def test_mark_dirty_refuses_to_overwrite_existing_dirty_evidence():
    dirty = st.mark_dirty(sample_state(), TAG2, "t0")
    with pytest.raises(ValueError):
        st.mark_dirty(dirty, TAG2, "t1")


def test_mark_migrated_extends_applied_keeps_old_release_and_clears_dirty():
    base = sample_state(applied=[Migration(ID1, H1)])
    dirty = st.mark_dirty(base, TAG2, "t0")
    target = [Migration(ID1, H1), Migration(ID2, H2)]
    after = st.mark_migrated(dirty, TAG2, WEB2, target)
    assert [a.by_release for a in after.schema.applied] == [TAG1, TAG2]
    assert after.schema.digest == schema_digest(target)
    assert after.schema.rebuild == st.Rebuild(tag=TAG2, web_digest=WEB2)
    assert after.schema.dirty is False
    assert after.schema.dirty_since is None and after.schema.dirty_release is None


def test_mark_migrated_refuses_target_that_is_not_an_extension():
    base = sample_state(applied=[Migration(ID1, H1)])
    with pytest.raises(ValueError):
        st.mark_migrated(base, TAG2, WEB2, [Migration(ID1, H2)])
    with pytest.raises(ValueError):
        st.mark_migrated(sample_state(applied=[Migration(ID1, H1), Migration(ID2, H2)]), TAG2, WEB2, [Migration(ID1, H1)])


def test_pause_and_resume_crawler_round_trip():
    paused = st.pause_crawler(sample_state(), TAG2, "forward migration", "t0")
    assert paused.crawler.paused == st.Pause(since="t0", release=TAG2, reason="forward migration")
    assert st.resume_crawler(paused).crawler.paused is None


def test_pause_refuses_to_replace_an_existing_pause():
    paused = st.pause_crawler(sample_state(), TAG2, "first", "t0")
    with pytest.raises(ValueError):
        st.pause_crawler(paused, TAG2, "second", "t1")


def test_promote_runtime_moves_current_to_previous():
    current = sample_state(tag=TAG1, web_digest=WEB1)
    replacement = st.DockerRuntime(tag=TAG2, release_api=1, web_digest=WEB2, crawler_digest=CRAWLER, compose_sha256="e" * 64, release_dir="/opt/x")
    promoted = st.promote_runtime(current, replacement)
    assert promoted.runtime == replacement
    assert promoted.previous_runtime == current.runtime


def test_runtime_fingerprint_is_web_digest_or_systemd():
    assert st.runtime_fingerprint(sample_state(web_digest=WEB1).runtime) == WEB1
    assert st.runtime_fingerprint(st.SystemdRuntime(unit="book-finder.service", version="pre-cd")) == "systemd"
