"""Operator commands: preconditions, refusals, confirmation, CAS and the operator history record (plan section 2, M3c).

Why: each command changes the state the automated path refuses to change, so every precondition gets a refusal test,
and every success checks the state file, the history record and the exit code together.
"""

import dataclasses
import hashlib
import io
import json
import os
import re
import stat
from pathlib import Path

import pytest
from bookfinder_host import history as hi
from bookfinder_host import operator_cli as op
from bookfinder_host import state as st
from bookfinder_host.manifest import schema_digest
from bookfinder_host.testing import sample_state
from worlds import (
    CRAWLER,
    CRAWLER2,
    DEFAULT_STATE,
    H1,
    H2,
    H3,
    ID1,
    ID2,
    ID3,
    NOW,
    SYSTEMD_UNIT,
    TAG1,
    TAG2,
    WEB1,
    WEB2,
    applied,
    make_world,
)

REASON = ["--reason", "planned operator action"]
DEPLOY_LOCK = "deploy.lock"


def run_admin(world, argv, *, typed="", environ=None, host_dir=None):
    out, err = io.StringIO(), io.StringIO()
    env = {"SUDO_USER": "operator1", **(environ or {})}
    code = op.main(
        list(argv),
        env,
        out,
        err,
        deps=world.deps,
        stdin=io.StringIO(typed),
        host_dir=host_dir if host_dir is not None else world.tmp_path / "host",
    )
    return code, out.getvalue(), err.getvalue()


def operator_records(world):
    """Every operator-started and operator-completed record, in history order."""
    return [entry for entry in world.history().entries if entry.get("phase") in ("operator-started", "operator-completed")]


def op_pair(world, index=-1):
    """(started, completed) of the index-th operation in history; completed is None while the op is open."""
    started_ids = [e["op_id"] for e in operator_records(world) if e["phase"] == "operator-started"]
    op_id = started_ids[index]
    started = next(e for e in operator_records(world) if e["phase"] == "operator-started" and e["op_id"] == op_id)
    completed = [e for e in operator_records(world) if e["phase"] == "operator-completed" and e["op_id"] == op_id]
    return started, (completed[0] if completed else None)


def dirty_state(applied_migrations, *, rebuild_tag=TAG1, release=TAG2):
    base = sample_state(applied=applied_migrations, revision=4, tag=rebuild_tag, web_digest=WEB1)
    schema = dataclasses.replace(base.schema, dirty=True, dirty_since=NOW, dirty_release=release)
    return dataclasses.replace(base, schema=schema)


# common behaviour


@pytest.mark.parametrize(
    "argv",
    [
        ["bootstrap-state", "--release", TAG1, "--web-digest", WEB1, "--crawler-digest", CRAWLER, "--systemd-unit", SYSTEMD_UNIT, *REASON],
        ["resume-crawler", "--crawler-digest", CRAWLER2, *REASON],
        ["resolve-run", "1234-5", "--result", "drift", *REASON],
        ["install-host", "--source", "/nonexistent", *REASON],
    ],
)
def test_refused_through_the_forced_command_path(tmp_path, argv):
    world = make_world(tmp_path, state=DEFAULT_STATE)
    before = world.load_state()
    code, _, err = run_admin(world, argv, environ={"SSH_ORIGINAL_COMMAND": "plan " + TAG1})
    assert code == 2
    assert "SSH_ORIGINAL_COMMAND" in err
    assert world.load_state() == before
    assert operator_records(world) == []


def test_reason_is_required_and_must_be_printable_text(tmp_path):
    world = make_world(tmp_path, state=dirty_state(applied(*[(ID1, H1)])))
    for reason in ("   ", "line\nbreak", "x" * 401):
        code, _, err = run_admin(world, ["resume-crawler", "--crawler-digest", CRAWLER2, "--reason", reason])
        assert code == 2, reason
        assert "reason" in err
    code, _, _ = run_admin(world, ["resume-crawler", "--crawler-digest", CRAWLER2])
    assert code == 2


def test_operator_commands_refuse_non_root_outside_tests(tmp_path, monkeypatch):
    make_world(tmp_path, state=DEFAULT_STATE)
    monkeypatch.setattr(op.os, "geteuid", lambda: 1000)
    err = io.StringIO()
    code = op.main(["resume-crawler", "--crawler-digest", CRAWLER2, *REASON], {"SUDO_USER": "x"}, io.StringIO(), err)
    assert code == 2
    assert "root" in err.getvalue()


def test_busy_deploy_lock_exits_3(tmp_path):
    import fcntl

    world = make_world(tmp_path, state=dirty_state(applied(*[(ID1, H1)])))
    with open(world.settings.deploy_lock_file, "a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        code, _, err = run_admin(world, ["resume-crawler", "--crawler-digest", CRAWLER2, *REASON])
    assert code == 3
    assert "busy" in err


def test_confirmation_must_match_the_value_shown(tmp_path):
    world = paused_world(tmp_path)
    before = world.load_state()
    code, _, err = run_admin(world, ["resume-crawler", "--crawler-digest", CRAWLER2, *REASON], typed="wrong")
    assert code == 2
    assert "nothing was changed" in err
    code, _, _ = run_admin(world, ["resume-crawler", "--crawler-digest", CRAWLER2, "--yes-i-verified", "sha256:" + "0" * 64, *REASON])
    assert code == 2
    assert world.load_state() == before
    assert operator_records(world) == []


def test_state_changed_during_confirmation_is_a_cas_conflict(tmp_path):
    world = paused_world(tmp_path)

    class Racing(io.StringIO):
        # Another writer lands a newer revision while the operator is still reading the prompt.
        def readline(self, *args):
            current = world.load_state()
            world.write_state(dataclasses.replace(current, revision=current.revision + 1))
            return CRAWLER2 + "\n"

    out, err = io.StringIO(), io.StringIO()
    code = op.main(
        ["resume-crawler", "--crawler-digest", CRAWLER2, *REASON],
        {"SUDO_USER": "operator1"},
        out,
        err,
        deps=world.deps,
        stdin=Racing(),
        host_dir=world.tmp_path / "host",
    )
    assert code == 3
    assert "changed while the command ran" in err.getvalue()
    assert world.load_state().crawler.paused is not None


# bootstrap-state (N6)


def bootstrap_argv(*, web=WEB1, crawler=CRAWLER, unit=SYSTEMD_UNIT, tag=TAG1):
    return ["bootstrap-state", "--release", tag, "--web-digest", web, "--crawler-digest", crawler, "--systemd-unit", unit, *REASON]


def bootstrap_world(tmp_path, *, db_ids=None, active=True, state=None):
    world = make_world(tmp_path, state=state, target=applied((ID1, H1), (ID2, H2)), db_ids=[ID1, ID2] if db_ids is None else db_ids)
    world.host.unit_states[SYSTEMD_UNIT] = "active" if active else "inactive"
    return world


def test_bootstrap_writes_revision_one_systemd_state(tmp_path):
    world = bootstrap_world(tmp_path)
    code, _out, err = run_admin(world, bootstrap_argv(), typed=WEB1)
    assert code == 0, err
    assert "trust assumption" in err
    stored = world.load_state()
    assert stored.revision == 1
    assert stored.runtime == st.SystemdRuntime(unit=SYSTEMD_UNIT, version="pre-cd")
    assert stored.previous_runtime is None
    assert [(e.id, e.source_hash, e.by_release) for e in stored.schema.applied] == [(ID1, H1, TAG1), (ID2, H2, TAG1)]
    assert stored.schema.rebuild == st.Rebuild(tag=TAG1, web_digest=WEB1)
    assert stored.schema.dirty is False
    assert stored.crawler == st.Crawler(digest=CRAWLER, paused=None)
    started, completed = op_pair(world)
    assert started["action"] == "bootstrap-state"
    assert started["operator"] == "operator1"
    assert started["reason"] == "planned operator action"
    assert started["before"] is None
    assert completed["result"] == "success"
    assert completed["after"]["revision"] == 1


def test_bootstrap_refuses_when_state_exists(tmp_path):
    world = make_world(tmp_path, state=DEFAULT_STATE, target=applied((ID1, H1)))
    code, _, err = run_admin(world, bootstrap_argv(), typed=WEB1)
    assert code == 3
    assert "already exists" in err


def test_bootstrap_refuses_an_inactive_unit(tmp_path):
    world = bootstrap_world(tmp_path, active=False)
    code, _, err = run_admin(world, bootstrap_argv(), typed=WEB1)
    assert code == 3
    assert "not active" in err
    assert not Path(world.settings.state_file).exists()


def test_bootstrap_refuses_when_database_ids_differ_from_manifest(tmp_path):
    world = bootstrap_world(tmp_path, db_ids=[ID1])
    code, _, err = run_admin(world, bootstrap_argv(), typed=WEB1)
    assert code == 3
    assert "in-sync" in err
    assert not Path(world.settings.state_file).exists()


def test_bootstrap_refuses_release_api_outside_host_range(tmp_path):
    world = make_world(tmp_path, state=None, target=applied((ID1, H1), (ID2, H2)), db_ids=[ID1, ID2], release_api="2")
    world.host.unit_states[SYSTEMD_UNIT] = "active"
    code, _, err = run_admin(world, bootstrap_argv(), typed=WEB1)
    assert code == 2
    assert "outside the host range" in err


def test_bootstrap_rejects_malformed_digests_and_units(tmp_path):
    world = bootstrap_world(tmp_path)
    assert run_admin(world, bootstrap_argv(web="sha256:short"), typed="x")[0] == 2
    assert run_admin(world, bootstrap_argv(crawler="latest"), typed="x")[0] == 2
    assert run_admin(world, bootstrap_argv(unit="book finder; rm"), typed="x")[0] == 2
    assert run_admin(world, bootstrap_argv(tag="latest"), typed="x")[0] == 2
    assert not Path(world.settings.state_file).exists()


def test_bootstrap_confirmation_is_required(tmp_path):
    world = bootstrap_world(tmp_path)
    code, _, _ = run_admin(world, bootstrap_argv(), typed="")
    assert code == 2
    assert not Path(world.settings.state_file).exists()
    code, _, _ = run_admin(world, bootstrap_argv(), environ={}, typed="")
    assert code == 2


# reconcile-schema (N2)


def reconcile_world(tmp_path, *, db_ids, recorded=(ID1, ID2), dirty=True):
    target = applied((ID1, H1), (ID2, H2), (ID3, H3))
    state = dirty_state(applied(*[(i, h) for i, h in [(ID1, H1), (ID2, H2)] if i in recorded]))
    if not dirty:
        state = dataclasses.replace(state, schema=dataclasses.replace(state.schema, dirty=False, dirty_since=None, dirty_release=None))
    return make_world(tmp_path, state=state, target=target, db_ids=db_ids)


def reconcile_argv(digest, *, rebuild=TAG1):
    return [
        "reconcile-schema",
        "--mark-clean",
        "--rebuild-release",
        rebuild,
        "--rebuild-web-digest",
        WEB2,
        "--expect-schema-digest",
        digest,
        *REASON,
    ]


def expected_digest(ids):
    manifest = applied((ID1, H1), (ID2, H2), (ID3, H3))
    return schema_digest(manifest[: len(ids)])


def test_reconcile_marks_clean_to_the_database_prefix(tmp_path):
    world = reconcile_world(tmp_path, db_ids=[ID1, ID2, ID3])
    digest = expected_digest([ID1, ID2, ID3])
    code, _, err = run_admin(world, reconcile_argv(digest), typed=digest)
    assert code == 0, err
    stored = world.load_state()
    assert stored.schema.dirty is False and stored.schema.dirty_release is None
    assert [(e.id, e.source_hash) for e in stored.schema.applied] == [(ID1, H1), (ID2, H2), (ID3, H3)]
    assert stored.schema.applied[2].by_release == TAG2  # the release whose migration left the database dirty
    assert stored.schema.rebuild == st.Rebuild(tag=TAG1, web_digest=WEB2)
    assert stored.schema.digest == digest
    started, completed = op_pair(world)
    assert started["action"] == "reconcile-schema" and completed["result"] == "success"


def test_reconcile_prints_ids_and_requires_the_expected_digest(tmp_path):
    world = reconcile_world(tmp_path, db_ids=[ID1, ID2, ID3])
    before = world.load_state()
    code, _, err = run_admin(world, reconcile_argv("sha256:" + "0" * 64), typed="x")
    assert code == 2
    assert ID3 in err and expected_digest([ID1, ID2, ID3]) in err
    assert world.load_state() == before


def test_reconcile_refuses_a_clean_schema(tmp_path):
    world = reconcile_world(tmp_path, db_ids=[ID1, ID2], dirty=False)
    code, _, err = run_admin(world, reconcile_argv(expected_digest([ID1, ID2])), typed="x")
    assert code == 3
    assert "not dirty" in err


def test_reconcile_refuses_divergent_database(tmp_path):
    world = reconcile_world(tmp_path, db_ids=[ID1, ID3])
    code, _, err = run_admin(world, reconcile_argv(expected_digest([ID1])), typed="x")
    assert code == 2
    assert "divergent" in err


def test_reconcile_refuses_a_source_hash_that_differs_from_the_manifest(tmp_path):
    target = applied((ID1, H1), (ID2, H2), (ID3, H3))
    state = dirty_state(applied((ID1, H1), (ID2, "f" * 64)))
    world = make_world(tmp_path, state=state, target=target, db_ids=[ID1, ID2, ID3])
    code, _, err = run_admin(world, reconcile_argv(expected_digest([ID1, ID2, ID3])), typed="x")
    assert code == 2
    assert "divergent" in err


def test_reconcile_never_touches_the_database(tmp_path):
    world = reconcile_world(tmp_path, db_ids=[ID1, ID2, ID3])
    digest = expected_digest([ID1, ID2, ID3])
    run_admin(world, reconcile_argv(digest), typed=digest)
    for call in world.host.calls:
        assert call[:2] != ["docker", "exec"]
        assert "ALTER" not in " ".join(call) and "INSERT" not in " ".join(call)


# resume-crawler (N3)


def paused_world(tmp_path, *, dirty=False, conf_digest=CRAWLER2, installed_text=None, shipped_text="#!/bin/bash\necho ok\n", runtime_docker=True):
    base = sample_state(applied=[], revision=5, tag=TAG1, web_digest=WEB1)
    release = tmp_path / "releases" / "v1"
    release.mkdir(parents=True)
    (release / "run-crawler.sh").write_text(shipped_text, encoding="utf-8")
    runtime = dataclasses.replace(base.runtime, release_dir=str(release))
    if not runtime_docker:
        runtime = st.SystemdRuntime(unit=SYSTEMD_UNIT, version="pre-cd")
    state = dataclasses.replace(
        base,
        runtime=runtime,
        schema=dataclasses.replace(base.schema, dirty=dirty, dirty_since=NOW if dirty else None, dirty_release=TAG2 if dirty else None),
        crawler=st.Crawler(digest=CRAWLER, paused=st.Pause(NOW, TAG2, "forward migration")),
    )
    world = make_world(tmp_path, state=state, target=[])
    Path(world.settings.crawler_conf).write_text(f"CRAWLER_IMAGE=ghcr.io/example/book-finder-crawler@{conf_digest}\nSCHEDULE=0 3 * * *\n", encoding="utf-8")
    Path(world.settings.crawler_runner).write_text(installed_text if installed_text is not None else shipped_text, encoding="utf-8")
    return world


def test_resume_clears_the_pause_and_sets_the_digest(tmp_path):
    world = paused_world(tmp_path)
    code, _, err = run_admin(world, ["resume-crawler", "--crawler-digest", CRAWLER2, *REASON], typed=CRAWLER2)
    assert code == 0, err
    stored = world.load_state()
    assert stored.crawler == st.Crawler(digest=CRAWLER2, paused=None)
    started, completed = op_pair(world)
    assert started["action"] == "resume-crawler" and completed["result"] == "success"


def test_resume_refuses_when_not_paused(tmp_path):
    world = paused_world(tmp_path)
    state = world.load_state()
    world.write_state(dataclasses.replace(state, crawler=st.Crawler(digest=CRAWLER, paused=None)))
    code, _, err = run_admin(world, ["resume-crawler", "--crawler-digest", CRAWLER2, *REASON], typed=CRAWLER2)
    assert code == 3
    assert "not paused" in err


def test_resume_refuses_a_dirty_schema(tmp_path):
    world = paused_world(tmp_path, dirty=True)
    code, _, _ = run_admin(world, ["resume-crawler", "--crawler-digest", CRAWLER2, *REASON], typed=CRAWLER2)
    assert code == 6


def test_resume_refuses_when_crawler_conf_names_another_image(tmp_path):
    world = paused_world(tmp_path, conf_digest=CRAWLER)
    code, _, err = run_admin(world, ["resume-crawler", "--crawler-digest", CRAWLER2, *REASON], typed=CRAWLER2)
    assert code == 3
    assert "fix CRAWLER_IMAGE" in err


def test_resume_refuses_when_installed_runner_differs_from_the_release(tmp_path):
    world = paused_world(tmp_path, installed_text="#!/bin/bash\necho stale\n")
    code, _, err = run_admin(world, ["resume-crawler", "--crawler-digest", CRAWLER2, *REASON], typed=CRAWLER2)
    assert code == 3
    assert "differs" in err
    assert world.load_state().crawler.paused is not None


def test_resume_refuses_a_systemd_runtime(tmp_path):
    world = paused_world(tmp_path, runtime_docker=False)
    code, _, err = run_admin(world, ["resume-crawler", "--crawler-digest", CRAWLER2, *REASON], typed=CRAWLER2)
    assert code == 3
    assert "release directory" in err


# resolve-run (N7)


def start_run(world, run_id="1234-5", unit_active=False):
    hi.append(
        world.settings.history_file,
        hi.started_record(run_id=run_id, unit=f"book-finder-deploy-{run_id}", at=NOW, target={"tag": TAG2}, expected_revision=1),
    )
    if unit_active:
        world.host.unit_states[f"book-finder-deploy-{run_id}"] = "active"


def test_resolve_records_the_operator_outcome(tmp_path):
    world = make_world(tmp_path, state=DEFAULT_STATE)
    start_run(world)
    code, _out, err = run_admin(world, ["resolve-run", "1234-5", "--result", "rolled-back", *REASON], typed="1234-5")
    assert code == 0, err
    completed = [e for e in world.history().entries if e.get("phase") == "completed"]
    assert completed[-1]["run_id"] == "1234-5"
    assert completed[-1]["result"] == "rolled-back"
    assert completed[-1]["exit_code"] == 1
    assert completed[-1]["resolved_by_operator"] is True
    assert completed[-1]["operator"] == "operator1"
    assert completed[-1]["reason"] == "planned operator action"
    assert world.load_state() == DEFAULT_STATE  # resolve-run never changes state


def test_resolve_reminds_about_dirty_and_paused(tmp_path):
    world = make_world(tmp_path, state=dirty_state(applied(*[(ID1, H1)])))
    start_run(world)
    code, _, err = run_admin(world, ["resolve-run", "1234-5", "--result", "failed-migration", *REASON], typed="1234-5")
    assert code == 0
    assert "reconcile-schema" in err


def test_resolve_refuses_an_active_run(tmp_path):
    world = make_world(tmp_path, state=DEFAULT_STATE)
    start_run(world, unit_active=True)
    code, _, err = run_admin(world, ["resolve-run", "1234-5", "--result", "drift", *REASON], typed="1234-5")
    assert code == 3
    assert "still active" in err


def test_resolve_refuses_a_run_that_never_started(tmp_path):
    world = make_world(tmp_path, state=DEFAULT_STATE)
    code, _, err = run_admin(world, ["resolve-run", "1234-5", "--result", "drift", *REASON], typed="1234-5")
    assert code == 3
    assert "never started" in err


def test_resolve_refuses_a_run_that_already_completed(tmp_path):
    world = make_world(tmp_path, state=DEFAULT_STATE)
    start_run(world)
    hi.append(world.settings.history_file, hi.completed_record(run_id="1234-5", result="success", exit_code=0, at=NOW, state_summary={}))
    code, _, err = run_admin(world, ["resolve-run", "1234-5", "--result", "drift", *REASON], typed="1234-5")
    assert code == 3
    assert "already has a completed record" in err


def test_resolve_rejects_unknown_results_and_malformed_ids(tmp_path):
    world = make_world(tmp_path, state=DEFAULT_STATE)
    start_run(world)
    assert run_admin(world, ["resolve-run", "1234-5", "--result", "maybe", *REASON], typed="1234-5")[0] == 2
    assert run_admin(world, ["resolve-run", "../etc", "--result", "drift", *REASON], typed="x")[0] == 2


def test_resolve_repairs_an_incomplete_history_tail(tmp_path):
    world = make_world(tmp_path, state=DEFAULT_STATE)
    start_run(world)
    with open(world.settings.history_file, "ab") as handle:
        handle.write(b'{"run_id":"9999-1","pha')
    code, out, err = run_admin(world, ["resolve-run", "1234-5", "--result", "drift", *REASON], typed="1234-5")
    assert code == 0, err
    assert json.loads(out)["truncated_tail_bytes"] > 0
    records = hi.read(world.settings.history_file)
    assert records.tail_corrupt is False
    assert hi.status(records, "1234-5", "missing") == "completed:drift"


# install-host (N4)


def make_source(tmp_path, range_text):
    source = tmp_path / "source"
    (source / "bookfinder_host").mkdir(parents=True)
    (source / "bookfinder_host" / "__init__.py").write_text("", encoding="utf-8")
    (source / "bookfinder_host" / "HOST_API_RANGE").write_text(range_text, encoding="utf-8")
    (source / "deploy-entry").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    (source / "book-finder-admin").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    return source


def installed(tmp_path, range_text="1 1\n"):
    host = tmp_path / "host"
    (host / "bookfinder_host").mkdir(parents=True)
    (host / "bookfinder_host" / "HOST_API_RANGE").write_text(range_text, encoding="utf-8")
    (host / "marker").write_text("old install", encoding="utf-8")
    return host


def runtime_state(*, runtime_api=1, previous_api=None):
    base = sample_state(applied=[], revision=2, tag=TAG1, web_digest=WEB1)
    previous = None
    if previous_api is not None:
        previous = dataclasses.replace(base.runtime, tag=TAG2, release_api=previous_api, web_digest=WEB2)
    return dataclasses.replace(base, runtime=dataclasses.replace(base.runtime, release_api=runtime_api), previous_runtime=previous)


def test_install_keeps_the_previous_host_and_records_both_ranges(tmp_path):
    world = make_world(tmp_path, state=runtime_state())
    source = make_source(tmp_path, "1 2\n")
    host = installed(tmp_path)
    code, _out, err = run_admin(world, ["install-host", "--source", str(source), *REASON], typed="1-2", host_dir=host)
    assert code == 0, err
    assert "old=1-1 new=1-2" in err
    assert (host / "bookfinder_host" / "HOST_API_RANGE").read_text() == "1 2\n"
    assert (host / "book-finder-admin").exists()
    assert host.is_symlink()
    legacy = [p for p in (host.parent / "host-versions").iterdir() if p.name.startswith("legacy-")]
    assert len(legacy) == 1 and (legacy[0] / "marker").read_text() == "old install"
    started, completed = op_pair(world)
    assert started["before"]["host_api_range"] == "1-1"
    assert completed["after"]["host_api_range"] == "1-2"
    assert completed["after"]["previous"] == legacy[0].name


def test_install_refuses_when_the_current_runtime_is_outside_the_new_range(tmp_path):
    world = make_world(tmp_path, state=runtime_state(runtime_api=1))
    source = make_source(tmp_path, "2 3\n")
    host = installed(tmp_path)
    code, _, err = run_admin(world, ["install-host", "--source", str(source), *REASON], typed="2-3", host_dir=host)
    assert code == 2
    assert "outside the new range" in err
    assert (host / "marker").read_text() == "old install"


def test_install_refuses_when_the_previous_runtime_is_outside_the_new_range(tmp_path):
    world = make_world(tmp_path, state=runtime_state(runtime_api=2, previous_api=1))
    source = make_source(tmp_path, "2 3\n")
    host = installed(tmp_path)
    code, _, err = run_admin(world, ["install-host", "--source", str(source), *REASON], typed="2-3", host_dir=host)
    assert code == 2
    assert "previous_runtime" in err


def test_install_allows_a_pre_cd_systemd_state(tmp_path):
    world = make_world(tmp_path, state=None, target=applied((ID1, H1)))
    world.write_state(
        st.State(
            revision=1,
            runtime=st.SystemdRuntime(unit=SYSTEMD_UNIT, version="pre-cd"),
            previous_runtime=None,
            schema=sample_state().schema,
            crawler=sample_state().crawler,
        )
    )
    source = make_source(tmp_path, "1 1\n")
    host = installed(tmp_path)
    code, _, err = run_admin(world, ["install-host", "--source", str(source), *REASON], typed="1-1", host_dir=host)
    assert code == 0, err


def test_install_refuses_relative_paths_and_symlinked_sources(tmp_path):
    world = make_world(tmp_path, state=None, target=applied((ID1, H1)))
    host = installed(tmp_path)
    assert run_admin(world, ["install-host", "--source", "relative/path", *REASON], typed="x", host_dir=host)[0] == 2
    source = make_source(tmp_path, "1 1\n")
    link = tmp_path / "linked"
    link.symlink_to(source / "bookfinder_host")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "deploy-entry").write_text("x", encoding="utf-8")
    (broken / "book-finder-admin").write_text("x", encoding="utf-8")
    (broken / "bookfinder_host").symlink_to(source / "bookfinder_host")
    code, _, err = run_admin(world, ["install-host", "--source", str(broken), *REASON], typed="1-1", host_dir=host)
    assert code == 2
    assert "symlink" in err


def test_install_confirmation_must_match_the_new_range(tmp_path):
    world = make_world(tmp_path, state=None, target=applied((ID1, H1)))
    source = make_source(tmp_path, "1 1\n")
    host = installed(tmp_path)
    code, _, _ = run_admin(world, ["install-host", "--source", str(source), *REASON], typed="1-9", host_dir=host)
    assert code == 2
    assert (host / "marker").read_text() == "old install"
    assert not (host.parent / "host-versions").exists()


def test_yes_i_verified_must_equal_the_value_shown(tmp_path):
    world = make_world(tmp_path, state=dirty_state(applied(*[(ID1, H1)])))
    start_run(world)
    code, _, _ = run_admin(world, ["resolve-run", "1234-5", "--result", "drift", "--yes-i-verified", "1234-6", *REASON])
    assert code == 2
    code, _, _ = run_admin(world, ["resolve-run", "1234-5", "--result", "drift", "--yes-i-verified", "1234-5", *REASON])
    assert code == 0


FRAGMENT = b'{"run_id":"9999-1","pha'
SIDECAR_STAMP = "20261023T000000Z"  # NOW with the separators removed, as operator_cli builds it


def _tail_world(tmp_path):
    world = make_world(tmp_path, state=DEFAULT_STATE)
    start_run(world)
    with open(world.settings.history_file, "ab") as handle:
        handle.write(FRAGMENT)
    return world


def test_resolve_keeps_the_removed_bytes_in_a_sidecar(tmp_path):
    world = _tail_world(tmp_path)
    code, _, err = run_admin(world, ["resolve-run", "1234-5", "--result", "drift", *REASON], typed="1234-5")
    assert code == 0, err
    started, completed = op_pair(world)
    assert started["action"] == "resolve-run"
    tail = started["intended"]["tail_repair"]
    assert completed["tail_repair"] == tail
    assert tail["bytes"] == len(FRAGMENT)
    assert tail["sha256"] == hashlib.sha256(FRAGMENT).hexdigest()
    sidecar = Path(tail["path"])
    assert sidecar.name == f"history.jsonl.tail-{SIDECAR_STAMP}-1234-5"
    assert sidecar.read_bytes() == FRAGMENT
    assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600
    assert hi.read(world.settings.history_file).tail_corrupt is False


def test_truncation_happens_only_after_the_sidecar_is_durable(tmp_path, monkeypatch):
    world = _tail_world(tmp_path)
    real_replace = os.replace
    seen = {}

    def checked_replace(source, target):
        # The tail is removed by the atomic rewrite of history, so the sidecar must already exist at that point.
        if Path(target) == Path(world.settings.history_file):
            seen["sidecars"] = [p.read_bytes() for p in Path(target).parent.glob("history.jsonl.tail-*")]
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", checked_replace)
    code, _, err = run_admin(world, ["resolve-run", "1234-5", "--result", "drift", *REASON], typed="1234-5")
    assert code == 0, err
    assert seen["sidecars"] == [FRAGMENT]
    assert hi.read(world.settings.history_file).tail_corrupt is False


def test_a_failed_sidecar_write_leaves_history_untouched(tmp_path):
    world = _tail_world(tmp_path)
    before = Path(world.settings.history_file).read_bytes()
    # A directory where the sidecar must be created makes the exclusive create fail before anything is removed.
    (Path(world.settings.history_file).parent / f"history.jsonl.tail-{SIDECAR_STAMP}-1234-5").mkdir()
    code, _, err = run_admin(world, ["resolve-run", "1234-5", "--result", "drift", *REASON], typed="1234-5")
    assert code == 3
    assert "filesystem error" in err
    assert Path(world.settings.history_file).read_bytes() == before
    assert not [e for e in hi.read(world.settings.history_file).entries if e.get("phase") == "completed"]
    assert operator_records(world) == []


# operator protocol (M3c review): started -> mutation -> completed for every mutating command

PROTOCOL_COMMANDS = ["bootstrap-state", "reconcile-schema", "resume-crawler", "install-host", "resolve-run"]
OTHER_OPERATOR_ARGV = ["install-host", "--source", "/nonexistent", *REASON]


class Crash(BaseException):
    """Stands in for a process that dies mid-command: it is not an Exception, so nothing catches it and nothing is recorded."""


def protocol_case(name, tmp_path):
    if name == "bootstrap-state":
        return {"world": bootstrap_world(tmp_path), "argv": bootstrap_argv(), "typed": WEB1, "host_dir": None}
    if name == "reconcile-schema":
        world = reconcile_world(tmp_path, db_ids=[ID1, ID2, ID3])
        digest = expected_digest([ID1, ID2, ID3])
        return {"world": world, "argv": reconcile_argv(digest), "typed": digest, "host_dir": None}
    if name == "resume-crawler":
        world = paused_world(tmp_path)
        return {"world": world, "argv": ["resume-crawler", "--crawler-digest", CRAWLER2, *REASON], "typed": CRAWLER2, "host_dir": None}
    if name == "install-host":
        world = make_world(tmp_path, state=runtime_state())
        source = make_source(tmp_path, "1 2\n")
        return {"world": world, "argv": ["install-host", "--source", str(source), *REASON], "typed": "1-2", "host_dir": installed(tmp_path)}
    world = make_world(tmp_path, state=DEFAULT_STATE)
    start_run(world)
    return {"world": world, "argv": ["resolve-run", "1234-5", "--result", "drift", *REASON], "typed": "1234-5", "host_dir": None}


def snapshot(root: Path) -> dict[str, bytes]:
    # Lock files are created empty by the lock itself, before any command decides anything; they carry no state.
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file() and not path.name.endswith(".lock")}


def fail_appends(monkeypatch, phase, make_error):
    real = hi.append

    def patched(path, record):
        if record.get("phase") == phase:
            raise make_error()
        return real(path, record)

    monkeypatch.setattr(hi, "append", patched)


def fail_mutation(monkeypatch, name, make_error):
    def boom(*args, **kwargs):
        raise make_error()

    if name == "install-host":
        monkeypatch.setattr(op, "_swap_install", boom)
    elif name == "resolve-run":
        fail_appends(monkeypatch, "completed", make_error)
    else:
        monkeypatch.setattr(st, "write_state", boom)


def mutation_happened(name, world, before_revision):
    if name == "install-host":
        return (world.tmp_path / "host" / "bookfinder_host" / "HOST_API_RANGE").read_text() == "1 2\n"
    if name == "resolve-run":
        return any(e.get("run_id") == "1234-5" and e.get("phase") == "completed" for e in world.history().entries)
    return revision_of(world) != before_revision


def revision_of(world):
    try:
        return world.load_state().revision
    except st.StateMissing:
        return 0


@pytest.mark.parametrize("name", PROTOCOL_COMMANDS)
def test_a_failed_start_record_changes_nothing(tmp_path, monkeypatch, name):
    case = protocol_case(name, tmp_path)
    world = case["world"]
    before = snapshot(tmp_path)
    fail_appends(monkeypatch, "operator-started", lambda: OSError("disk full"))
    code, _, err = run_admin(world, case["argv"], typed=case["typed"], host_dir=case["host_dir"])
    assert code == 3, err
    assert "could not record the start" in err and "nothing was changed" in err
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("name", PROTOCOL_COMMANDS)
def test_started_is_durable_before_the_mutation_runs(tmp_path, monkeypatch, name):
    case = protocol_case(name, tmp_path)
    world = case["world"]
    seen = []
    if name == "install-host":
        real = op._swap_install

        def spy(source, target):
            seen.append(any(e.get("phase") == "operator-started" for e in world.history().entries))
            return real(source, target)

        monkeypatch.setattr(op, "_swap_install", spy)
    elif name == "resolve-run":
        real_append = hi.append

        def spy_append(path, record):
            if record.get("phase") == "completed":
                seen.append(any(e.get("phase") == "operator-started" for e in hi.read(path).entries))
            return real_append(path, record)

        monkeypatch.setattr(hi, "append", spy_append)
    else:
        real_write = st.write_state

        def spy_write(path, state, expected_revision):
            seen.append(any(e.get("phase") == "operator-started" for e in world.history().entries))
            return real_write(path, state, expected_revision)

        monkeypatch.setattr(st, "write_state", spy_write)
    code, _, err = run_admin(world, case["argv"], typed=case["typed"], host_dir=case["host_dir"])
    assert code == 0, err
    assert seen == [True]
    started, completed = op_pair(world)
    assert started["op_id"] == completed["op_id"]
    assert completed["result"] == "success" and completed["action"] == started["action"]
    assert re.fullmatch(r"op-20261023000000-[0-9a-f]{4}", started["op_id"])


@pytest.mark.parametrize("name", PROTOCOL_COMMANDS)
def test_crash_after_started_leaves_an_indeterminate_operation(tmp_path, monkeypatch, name):
    case = protocol_case(name, tmp_path)
    world = case["world"]
    fail_mutation(monkeypatch, name, Crash) if name != "resolve-run" else fail_appends(monkeypatch, "completed", Crash)
    with pytest.raises(Crash):
        run_admin(world, case["argv"], typed=case["typed"], host_dir=case["host_dir"])
    started, completed = op_pair(world)
    assert completed is None
    code, _, err = run_admin(world, OTHER_OPERATOR_ARGV, typed="x")
    assert code == 8 and started["op_id"] in err
    if name != "bootstrap-state":
        # The state exists here, so the plan gate is the one that must refuse (exit 8).
        assert world.run(f"plan {TAG1} {WEB1}", plan_only=True) == 8
    code, _, err = run_admin(world, ["resolve-run", started["op_id"], "--result", "failed", *REASON], typed=started["op_id"])
    assert code == 0, err
    _, completed = op_pair(world)
    assert completed["result"] == "failed" and completed["resolved_by_operator"] is True
    assert completed["operator"] == "operator1" and completed["reason"] == "planned operator action"
    code, _, _ = run_admin(world, OTHER_OPERATOR_ARGV, typed="x")
    assert code != 8


@pytest.mark.parametrize("name", PROTOCOL_COMMANDS)
def test_failed_completion_after_a_real_change_stays_indeterminate(tmp_path, monkeypatch, name):
    case = protocol_case(name, tmp_path)
    world = case["world"]
    before_revision = revision_of(world)
    fail_appends(monkeypatch, "operator-completed", lambda: OSError("disk full"))
    code, _, err = run_admin(world, case["argv"], typed=case["typed"], host_dir=case["host_dir"])
    assert code == 3
    assert "outcome is recorded as unknown" in err and "stays indeterminate" in err
    assert mutation_happened(name, world, before_revision)
    _started, completed = op_pair(world)
    assert completed is None
    code, _, _ = run_admin(world, OTHER_OPERATOR_ARGV, typed="x")
    assert code == 8


@pytest.mark.parametrize("name", PROTOCOL_COMMANDS)
def test_a_known_failure_is_recorded_as_failed(tmp_path, monkeypatch, name):
    case = protocol_case(name, tmp_path)
    world = case["world"]
    before_revision = revision_of(world)
    fail_mutation(monkeypatch, name, lambda: OSError("write refused"))
    code, _, err = run_admin(world, case["argv"], typed=case["typed"], host_dir=case["host_dir"])
    assert code == 3
    started, completed = op_pair(world)
    assert completed["result"] == "failed" and completed["op_id"] == started["op_id"]
    assert "write refused" in completed["error"]
    note = {"install-host": "host unchanged (verified)", "resolve-run": "history unchanged (verified)"}.get(name, "state unchanged (verified)")
    assert note in err and "outcome unknown" not in err
    assert not mutation_happened(name, world, before_revision)
    # A recorded failure closes the operation, so the other operator commands run again.
    assert run_admin(world, OTHER_OPERATOR_ARGV, typed="x")[0] != 8


def linked_host(tmp_path):
    """An installed host that is already a versioned link (the normal state after the first install)."""
    version = tmp_path / "host-versions" / ("0" * 16)
    (version / "bookfinder_host").mkdir(parents=True)
    (version / "bookfinder_host" / "HOST_API_RANGE").write_text("1 1\n", encoding="utf-8")
    host = tmp_path / "host"
    os.symlink(version, host)
    return host


@pytest.mark.parametrize("name", ["bootstrap-state", "reconcile-schema", "resume-crawler"])
def test_a_failure_after_the_state_was_replaced_stays_indeterminate(tmp_path, monkeypatch, name):
    # The rename happens and then the directory fsync fails: the new state is on disk, so the outcome is unknown.
    case = protocol_case(name, tmp_path)
    world = case["world"]
    before_revision = revision_of(world)
    real_write = st.write_state

    def replaced_then_failed(path, state, expected_revision):
        real_write(path, state, expected_revision)
        raise OSError("directory fsync failed after the rename")

    monkeypatch.setattr(st, "write_state", replaced_then_failed)
    code, _, err = run_admin(world, case["argv"], typed=case["typed"], host_dir=case["host_dir"])
    assert code == 3, err
    assert "outcome is unknown" in err and "resolve-run" in err
    assert revision_of(world) == before_revision + 1
    started, completed = op_pair(world)
    assert completed is None
    assert started["op_id"] in err
    if name != "bootstrap-state":
        assert world.run(f"plan {TAG1} {WEB1}", plan_only=True) == 8
        assert started["op_id"] in world.out.getvalue()
    code, _, err = run_admin(world, OTHER_OPERATOR_ARGV, typed="x")
    assert code == 8 and started["op_id"] in err
    code, _, err = run_admin(world, ["resolve-run", started["op_id"], "--result", "success", *REASON], typed=started["op_id"])
    assert code == 0, err
    _, completed = op_pair(world)
    assert completed["result"] == "success" and completed["resolved_by_operator"] is True
    assert run_admin(world, OTHER_OPERATOR_ARGV, typed="x")[0] != 8


@pytest.mark.parametrize("layout", ["legacy-directory", "versioned-link"])
def test_install_failure_after_the_pointer_moved_stays_indeterminate(tmp_path, monkeypatch, layout):
    # The directory fsync after the host pointer changed fails. The new tree is live, so the op must stay open.
    world = make_world(tmp_path, state=runtime_state())
    source = make_source(tmp_path, "1 2\n")
    host = installed(tmp_path) if layout == "legacy-directory" else linked_host(tmp_path)
    before_target = os.readlink(host) if os.path.islink(host) else None
    real_fsync = op._fsync_dir

    def fsync_then_fail_on_root(directory):
        real_fsync(directory)
        if Path(directory) == host.parent and os.path.islink(host):
            raise OSError("directory fsync failed after the link swap")

    monkeypatch.setattr(op, "_fsync_dir", fsync_then_fail_on_root)
    code, _, err = run_admin(world, ["install-host", "--source", str(source), *REASON], typed="1-2", host_dir=host)
    assert code == 3, err
    assert "outcome is unknown" in err and "resolve-run" in err
    assert os.path.islink(host) and os.readlink(host) != before_target
    assert (host / "bookfinder_host" / "HOST_API_RANGE").read_text() == "1 2\n"
    started, completed = op_pair(world)
    assert completed is None and started["op_id"] in err
    assert world.run(f"plan {TAG1} {WEB1}", plan_only=True) == 8
    assert started["op_id"] in world.out.getvalue()
    code, _, err = run_admin(world, OTHER_OPERATOR_ARGV, typed="x", host_dir=host)
    assert code == 8 and started["op_id"] in err
    code, _, err = run_admin(world, ["resolve-run", started["op_id"], "--result", "success", *REASON], typed=started["op_id"])
    assert code == 0, err
    assert run_admin(world, OTHER_OPERATOR_ARGV, typed="x", host_dir=host)[0] != 8


def test_open_operation_refuses_every_operator_command_but_resolve(tmp_path):
    world = make_world(tmp_path, state=DEFAULT_STATE)
    start_run(world)
    hi.append(
        world.settings.history_file,
        hi.operator_started_record(op_id="op-20261023000000-beef", action="resume-crawler", at=NOW, operator="op", reason="r", intended={}, before=None),
    )
    before = snapshot(tmp_path)
    for argv in (
        ["bootstrap-state", "--release", TAG1, "--web-digest", WEB1, "--crawler-digest", CRAWLER, "--systemd-unit", SYSTEMD_UNIT, *REASON],
        ["reconcile-schema", "--mark-clean", "--rebuild-release", TAG1, "--rebuild-web-digest", WEB2, "--expect-schema-digest", "sha256:" + "0" * 64, *REASON],
        ["resume-crawler", "--crawler-digest", CRAWLER2, *REASON],
        OTHER_OPERATOR_ARGV,
    ):
        code, _, err = run_admin(world, argv, typed="x")
        assert code == 8, argv
        assert "op-20261023000000-beef" in err
    assert snapshot(tmp_path) == before


def test_resolve_operation_refuses_unknown_closed_and_malformed_ids(tmp_path):
    world = make_world(tmp_path, state=DEFAULT_STATE)
    code, _, err = run_admin(world, ["resolve-run", "op-20261023000000-beef", "--result", "success", *REASON], typed="op-20261023000000-beef")
    assert code == 3 and "not open" in err
    assert run_admin(world, ["resolve-run", "op-x", "--result", "success", *REASON], typed="op-x")[0] == 2
    assert run_admin(world, ["resolve-run", "op-20261023000000-beef", "--result", "drift", *REASON], typed="x")[0] == 2
    assert run_admin(world, ["resolve-run", "1234-5", "--result", "failed", *REASON], typed="x")[0] == 2


def test_resolve_operation_repairs_a_damaged_tail_in_the_same_rewrite(tmp_path):
    world = make_world(tmp_path, state=DEFAULT_STATE)
    hi.append(
        world.settings.history_file,
        hi.operator_started_record(op_id="op-20261023000000-beef", action="resume-crawler", at=NOW, operator="op", reason="r", intended={}, before=None),
    )
    with open(world.settings.history_file, "ab") as handle:
        handle.write(FRAGMENT)
    code, _, err = run_admin(world, ["resolve-run", "op-20261023000000-beef", "--result", "success", *REASON], typed="op-20261023000000-beef")
    assert code == 0, err
    records = hi.read(world.settings.history_file)
    assert records.tail_corrupt is False and hi.open_operations(records) == []
    completed = next(e for e in records.entries if e.get("phase") == "operator-completed")
    assert completed["tail_repair"]["bytes"] == len(FRAGMENT)
    assert Path(completed["tail_repair"]["path"]).read_bytes() == FRAGMENT
