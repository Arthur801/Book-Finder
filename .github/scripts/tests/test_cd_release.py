import copy
import json
import os
import shutil
from pathlib import Path

import cd_release as cd
import pytest
from cd_release import CdError, Result

TAG = "v1.2.3"
COMMIT = "1" * 40
WEB = "sha256:" + "a" * 64
WEB_OLD = "sha256:" + "b" * 64
CRAWLER_TARGET = "sha256:" + "c" * 64
CRAWLER_STATE = "sha256:" + "d" * 64
REBUILD_WEB = "sha256:" + "e" * 64
RUNTIME_WEB = "sha256:" + "f" * 64

ID1 = "20260101000000_First"
ID2 = "20260102000000_Second"
ID3 = "20260103000000_Third"
ID4 = "20260104000000_Fourth"
H1, H2, H3, H4 = ("1" * 64, "2" * 64, "3" * 64, "4" * 64)
MIGRATIONS = [(ID1, H1), (ID2, H2), (ID3, H3)]


def make_release_dir(root: Path, migrations=MIGRATIONS, release_api: bytes = b"1\n") -> Path:
    """An extracted release as extract_release would leave it: migrations.txt, RELEASE_API and sql/<id>.sql."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "migrations.txt").write_text("".join(f"{i} {h}\n" for i, h in migrations), encoding="ascii")
    (root / "RELEASE_API").write_bytes(release_api)
    (root / "sql").mkdir(exist_ok=True)
    for migration_id, _ in migrations:
        (root / "sql" / f"{migration_id}.sql").write_text(f"-- {migration_id}\nALTER TABLE t ADD c int;\n", encoding="utf-8")
    return root


def build(tmp_path: Path) -> cd.ReleaseRecord:
    release_dir = make_release_dir(tmp_path / "rel")
    return cd.build_release(TAG, COMMIT, WEB, CRAWLER_TARGET, release_dir, tmp_path / "assets")


def release_record(migrations=MIGRATIONS) -> cd.ReleaseRecord:
    obj = {
        "schema_version": 1,
        "tag": TAG,
        "commit": COMMIT,
        "web_digest": WEB,
        "crawler_digest": CRAWLER_TARGET,
        "release_api": 1,
        "migrations": [{"id": i, "source_hash": h} for i, h in migrations],
        "sql_assets": {f"{i}.sql": "0" * 64 for i, _ in migrations},
    }
    return cd.release_from_obj(obj)


def applied_list(*pairs):
    return [cd.Migration(i, h) for i, h in pairs]


def docker_runtime(web=RUNTIME_WEB):
    return {
        "kind": "docker",
        "tag": "v1.0.0",
        "release_api": 1,
        "web_digest": web,
        "crawler_digest": CRAWLER_STATE,
        "compose_sha256": "0" * 64,
        "release_dir": "/opt/book-finder/releases/v1.0.0",
    }


def systemd_runtime():
    return {"kind": "systemd", "unit": "book-finder.service", "version": "pre-cd"}


def plan(applied, classification, pending, runtime=None, drift=None, dirty=False, target_tag=TAG, target_web=WEB):
    applied_last = applied[-1].id if applied else None
    return {
        "revision": 3,
        "runtime": {"state": runtime or docker_runtime(), "observed": None},
        "drift": drift or [],
        "schema": {
            "digest": cd.schema_digest(applied),
            "applied_last": applied_last,
            "dirty": dirty,
            "dirty_since": None,
            "dirty_release": None,
            "rebuild": {"tag": "v1.1.0", "web_digest": REBUILD_WEB},
        },
        "crawler": {"paused": None, "digest": CRAWLER_STATE},
        "compose_version": "2.29.0",
        "target": {"tag": target_tag, "web_digest": target_web, "release_api": 1},
        "classification": classification,
        "pending": pending,
    }


def run_plan(plan_obj, **kwargs):
    release = kwargs.pop("release", release_record())
    return cd.plan_outputs(plan_obj, kwargs.pop("host_exit", 0), release, TAG, WEB, kwargs.pop("cutover", False))


# Release record


def test_release_round_trip_and_canonical_text(tmp_path):
    record = build(tmp_path)
    loaded = cd.load_release(tmp_path / "assets" / "release.json")
    assert loaded == record
    assert (tmp_path / "assets" / "release.json").read_text(encoding="utf-8") == record.text()
    assert json.loads(record.text())["schema_version"] == 1
    assert sorted(p.name for p in (tmp_path / "assets").iterdir()) == sorted(["release.json", "migrations.txt", f"{ID1}.sql", f"{ID2}.sql", f"{ID3}.sql"])
    assert cd.compare_releases(record, loaded) == []


def test_compare_detects_a_changed_field(tmp_path):
    record = build(tmp_path)
    other = copy.deepcopy(record)
    other.commit = "2" * 40
    assert cd.compare_releases(record, other) == ["commit"]


def test_build_rejects_symlinked_sql(tmp_path):
    release_dir = make_release_dir(tmp_path / "rel")
    target = tmp_path / "outside.sql"
    target.write_text("-- outside", encoding="utf-8")
    sql = release_dir / "sql" / f"{ID1}.sql"
    sql.unlink()
    os.symlink(target, sql)
    with pytest.raises(CdError, match="not a regular file"):
        cd.build_release(TAG, COMMIT, WEB, CRAWLER_TARGET, release_dir, tmp_path / "assets")


def test_build_rejects_extra_or_missing_sql_and_bad_manifest(tmp_path):
    release_dir = make_release_dir(tmp_path / "extra")
    (release_dir / "sql" / "SHA256SUMS").write_text("x", encoding="utf-8")
    with pytest.raises(CdError, match="exactly one"):
        cd.build_release(TAG, COMMIT, WEB, CRAWLER_TARGET, release_dir, tmp_path / "a1")

    release_dir = make_release_dir(tmp_path / "missing")
    (release_dir / "sql" / f"{ID2}.sql").unlink()
    with pytest.raises(CdError, match="exactly one"):
        cd.build_release(TAG, COMMIT, WEB, CRAWLER_TARGET, release_dir, tmp_path / "a2")

    release_dir = make_release_dir(tmp_path / "order", migrations=[(ID2, H2), (ID1, H1)])
    with pytest.raises(CdError, match="ascending"):
        cd.build_release(TAG, COMMIT, WEB, CRAWLER_TARGET, release_dir, tmp_path / "a3")

    release_dir = make_release_dir(tmp_path / "api", release_api=b"0\n")
    with pytest.raises(CdError, match="RELEASE_API"):
        cd.build_release(TAG, COMMIT, WEB, CRAWLER_TARGET, release_dir, tmp_path / "a4")


def test_build_rejects_a_non_empty_assets_dir_and_bad_inputs(tmp_path):
    release_dir = make_release_dir(tmp_path / "rel")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "old").write_text("x", encoding="utf-8")
    with pytest.raises(CdError, match="must be empty"):
        cd.build_release(TAG, COMMIT, WEB, CRAWLER_TARGET, release_dir, assets)
    for tag, commit, digest in [("v1.0.0; rm", COMMIT, WEB), (TAG, "A" * 40, WEB), (TAG, COMMIT, "sha256:XYZ")]:
        with pytest.raises(CdError):
            cd.build_release(tag, commit, digest, CRAWLER_TARGET, release_dir, tmp_path / f"n{len(tag)}")


def test_release_from_obj_rejects_bad_shapes(tmp_path):
    good = build(tmp_path).to_obj()
    bad_cases = [
        {**good, "extra": 1},
        {**good, "schema_version": True},
        {**good, "release_api": 0},
        {**good, "sql_assets": {"other.sql": "0" * 64}},
        {**good, "web_digest": "sha256:" + "A" * 64},
    ]
    for obj in bad_cases:
        with pytest.raises(CdError):
            cd.release_from_obj(obj)


# Extraction from an image (fake docker)


class FakeDocker:
    def __init__(self, image_dir: Path, cp_fail: bool = False):
        self.image_dir = image_dir
        self.cp_fail = cp_fail
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        if argv[:2] in (["docker", "pull"], ["docker", "rm"]):
            return Result(0, "", "")
        if argv[:3] == ["docker", "create", "--pull=never"]:
            return Result(0, "0123456789ab\n", "")
        if argv[:2] == ["docker", "cp"]:
            if self.cp_fail:
                return Result(1, "", "boom")
            _, _, source_spec, dest = argv
            relative = source_spec.split(":", 1)[1].removeprefix("/opt/release/")
            source = self.image_dir / relative
            try:
                if source.is_symlink():
                    os.symlink(os.readlink(source), dest)
                else:
                    shutil.copyfile(source, dest)
            except FileNotFoundError:
                return Result(1, "", "no such file")
            return Result(0, "", "")
        return Result(1, "", f"unexpected {argv}")


def test_extract_release_copies_only_the_named_files(tmp_path):
    image = make_release_dir(tmp_path / "image")
    (image / "compose.prod.yaml").write_text("services: {}", encoding="utf-8")
    docker = FakeDocker(image)
    image_ref = f"{cd.WEB_REPO}@{WEB}"
    cd.extract_release(image_ref, tmp_path / "dest", docker)
    assert sorted(p.name for p in (tmp_path / "dest").iterdir()) == ["RELEASE_API", "migrations.txt", "sql"]
    assert ["docker", "rm", "-f", "0123456789ab"] in docker.calls
    assert cd.build_release(TAG, COMMIT, WEB, CRAWLER_TARGET, tmp_path / "dest", tmp_path / "assets").tag == TAG


def test_extract_release_rejects_a_symlink_in_the_image(tmp_path):
    image = make_release_dir(tmp_path / "image")
    (image / "migrations.txt").unlink()
    os.symlink("/etc/shadow", image / "migrations.txt")
    with pytest.raises(CdError, match="not a regular file"):
        cd.extract_release(f"{cd.WEB_REPO}@{WEB}", tmp_path / "dest", FakeDocker(image))


def test_extract_release_rejects_symlinked_sql_and_bad_refs(tmp_path):
    image = make_release_dir(tmp_path / "image")
    sql = image / "sql" / f"{ID1}.sql"
    sql.unlink()
    os.symlink("/etc/passwd", sql)
    with pytest.raises(CdError, match="not a regular file"):
        cd.build_release(TAG, COMMIT, WEB, CRAWLER_TARGET, _copy_release(image, tmp_path), tmp_path / "assets")
    with pytest.raises(CdError, match="digest only"):
        cd.extract_release(f"{cd.WEB_REPO}:{TAG}", tmp_path / "d2", FakeDocker(image))
    with pytest.raises(CdError, match="docker cp failed"):
        cd.extract_release(f"{cd.WEB_REPO}@{WEB}", tmp_path / "d3", FakeDocker(image, cp_fail=True))


def _copy_release(image: Path, tmp_path: Path) -> Path:
    """Copies the extracted tree with its links intact, the way docker cp without -L leaves them."""
    dest = tmp_path / "copied"
    dest.mkdir()
    shutil.copy2(image / "RELEASE_API", dest / "RELEASE_API")
    shutil.copy2(image / "migrations.txt", dest / "migrations.txt")
    (dest / "sql").mkdir()
    for entry in (image / "sql").iterdir():
        if entry.is_symlink():
            os.symlink(os.readlink(entry), dest / "sql" / entry.name)
        else:
            shutil.copy2(entry, dest / "sql" / entry.name)
    return dest


# Image state and attestation


def test_image_state_absent_present_and_error():
    absent = lambda argv: Result(1, "", "ERROR: ghcr.io/x: not found")
    assert cd.image_state(f"{cd.WEB_REPO}:{TAG}", absent) == ("absent", None)
    present = lambda argv: Result(0, json.dumps({"mediaType": "x", "digest": WEB, "size": 1}), "")
    assert cd.image_state(f"{cd.WEB_REPO}:{TAG}", present) == ("present", WEB)
    denied = lambda argv: Result(1, "", "unauthorized: denied")
    with pytest.raises(CdError, match="cannot inspect"):
        cd.image_state(f"{cd.WEB_REPO}:{TAG}", denied)
    with pytest.raises(CdError, match="outside the CD repositories"):
        cd.image_state("docker.io/library/nginx:latest", present)


def test_verify_attestation_passes_only_with_the_full_policy():
    seen = []

    def ok(argv):
        seen.append(list(argv))
        return Result(0, "", "")

    cd.verify_attestation(f"{cd.WEB_REPO}@{WEB}", TAG, COMMIT, ok)
    argv = seen[0]
    for flag in ["--signer-workflow", "--source-ref", "--source-digest", "--deny-self-hosted-runners"]:
        assert flag in argv
    assert argv[argv.index("--source-ref") + 1] == f"refs/tags/{TAG}"
    assert argv[argv.index("--source-digest") + 1] == COMMIT
    assert argv[argv.index("--repo") + 1] == cd.REPO

    with pytest.raises(CdError, match="never rebuild"):
        cd.verify_attestation(f"{cd.WEB_REPO}@{WEB}", TAG, COMMIT, lambda argv: Result(1, "", "no attestation"))
    with pytest.raises(CdError):
        cd.verify_attestation(f"{cd.WEB_REPO}:{TAG}", TAG, COMMIT, ok)
    with pytest.raises(CdError):
        cd.verify_attestation(f"{cd.WEB_REPO}@{WEB}", "v1; x", COMMIT, ok)


def test_release_state_reads_absent_draft_and_published():
    assert cd.release_state(TAG, lambda argv: Result(1, "", "release not found")) == "absent"
    assert cd.release_state(TAG, lambda argv: Result(0, "true\n", "")) == "draft"
    assert cd.release_state(TAG, lambda argv: Result(0, "false\n", "")) == "published"
    with pytest.raises(CdError):
        cd.release_state(TAG, lambda argv: Result(1, "", "HTTP 500"))
    with pytest.raises(CdError):
        cd.release_state("v1.0.0 --repo x", lambda argv: Result(0, "false", ""))


# Plan outputs


def test_in_sync_docker_uses_the_target_crawler():
    applied = applied_list(*MIGRATIONS)
    out = run_plan(plan(applied, "in-sync", []))
    assert out["chain"] == "in-sync"
    assert out["pending"] == "none"
    assert out["expect_runtime"] == RUNTIME_WEB
    assert out["expect_schema"] == cd.schema_digest(applied)
    assert out["crawler_for_deploy"] == CRAWLER_TARGET
    assert out["cutover_ok"] == "false"
    assert out["runtime_web_digest"] == RUNTIME_WEB
    assert out["applied_last"] == ID3
    assert out["rebuild_web_digest"] == REBUILD_WEB


def test_forward_lists_pending_and_keeps_the_target_crawler():
    out = run_plan(plan(applied_list((ID1, H1)), "forward", [ID2, ID3]))
    assert out["chain"] == "forward"
    assert out["pending"] == f"{ID2} {ID3}"
    assert out["crawler_for_deploy"] == CRAWLER_TARGET


def test_schema_ahead_keeps_the_state_crawler():
    applied = applied_list(*MIGRATIONS, (ID4, H4))
    out = run_plan(plan(applied, "schema-ahead", []))
    assert out["chain"] == "schema-ahead"
    assert out["pending"] == "none"
    assert out["crawler_for_deploy"] == CRAWLER_STATE
    assert out["applied_last"] == ID4


def test_divergent_dirty_and_drift_are_refused():
    applied = applied_list((ID1, H1))
    with pytest.raises(CdError, match="divergent"):
        run_plan(plan(applied, "divergent", []))
    with pytest.raises(CdError, match="dirty"):
        run_plan(plan(applied, "forward", [ID2, ID3], dirty=True))
    with pytest.raises(CdError, match="drift"):
        run_plan(plan(applied, "forward", [ID2, ID3], drift=["runtime: changed"]))


def test_host_failure_is_refused_and_still_writes_the_summary(tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps({"revision": 4, "indeterminate": ["run-1"]}), encoding="utf-8")
    summary = tmp_path / "summary.md"
    out = tmp_path / "out.txt"
    code = cd.main(
        [
            "plan-outputs",
            "--plan-file",
            str(plan_file),
            "--host-exit",
            "8",
            "--release-json",
            _release_file(tmp_path),
            "--tag",
            TAG,
            "--web-digest",
            WEB,
            "--cutover",
            "false",
            "--github-output",
            str(out),
            "--summary",
            str(summary),
        ]
    )
    assert code == 1
    assert "indeterminate" in summary.read_text(encoding="utf-8")
    assert not out.exists()


def _release_file(tmp_path: Path) -> str:
    path = tmp_path / "release.json"
    path.write_text(release_record().text(), encoding="utf-8")
    return str(path)


def test_cli_plan_outputs_success_writes_github_output(tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan(applied_list(*MIGRATIONS), "in-sync", [])), encoding="utf-8")
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"
    code = cd.main(
        [
            "plan-outputs",
            "--plan-file",
            str(plan_file),
            "--host-exit",
            "0",
            "--release-json",
            _release_file(tmp_path),
            "--tag",
            TAG,
            "--web-digest",
            WEB,
            "--cutover",
            "false",
            "--github-output",
            str(out),
            "--summary",
            str(summary),
        ]
    )
    assert code == 0
    lines = dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines())
    assert lines["chain"] == "in-sync"
    assert lines["crawler_for_deploy"] == CRAWLER_TARGET
    assert "CD plan" in summary.read_text(encoding="utf-8")


def test_pending_must_match_the_target_release():
    applied = applied_list((ID1, H1))
    with pytest.raises(CdError, match="pending list"):
        run_plan(plan(applied, "forward", [ID2]))
    with pytest.raises(CdError, match="pending list"):
        run_plan(plan(applied_list(*MIGRATIONS), "in-sync", [ID3]))
    with pytest.raises(CdError):
        run_plan(plan(applied_list(*MIGRATIONS, (ID4, H4)), "schema-ahead", [ID4]))


def test_schema_ahead_with_an_applied_id_inside_the_target_is_refused():
    with pytest.raises(CdError, match="schema-ahead"):
        cd.expected_pending([ID1, ID2], ID2, "schema-ahead")


def test_cutover_rules():
    applied = applied_list(*MIGRATIONS)
    systemd = plan(applied, "in-sync", [], runtime=systemd_runtime())
    out = run_plan(systemd, cutover=True)
    assert out["cutover_ok"] == "true"
    assert out["expect_runtime"] == "systemd"
    assert out["runtime_web_digest"] == "none"
    with pytest.raises(CdError, match="already docker"):
        run_plan(plan(applied, "in-sync", []), cutover=True)
    with pytest.raises(CdError, match="in-sync"):
        run_plan(plan(applied_list((ID1, H1)), "forward", [ID2, ID3], runtime=systemd_runtime()), cutover=True)
    with pytest.raises(CdError, match="requested with cutover"):
        run_plan(systemd, cutover=False)


def test_target_mismatch_is_refused():
    applied = applied_list(*MIGRATIONS)
    with pytest.raises(CdError, match="target"):
        run_plan(plan(applied, "in-sync", [], target_tag="v9.9.9"))
    with pytest.raises(CdError, match="requested tag"):
        cd.plan_outputs(plan(applied, "in-sync", []), 0, release_record(), TAG, WEB_OLD, False)


def test_injected_values_are_rejected_before_outputs():
    applied = applied_list(*MIGRATIONS)
    with pytest.raises(CdError):
        cd.plan_outputs(plan(applied, "in-sync", []), 0, release_record(), "v1.2.3\nevil=1", WEB, False)
    bad = plan(applied, "in-sync", [])
    bad["schema"]["digest"] = "sha256:" + "Z" * 64
    with pytest.raises(CdError):
        run_plan(bad)
    bad = plan(applied, "in-sync", [])
    bad["pending"] = ["x; rm -rf /"]
    with pytest.raises(CdError):
        run_plan(bad)


# applied manifest (N1)


def test_applied_manifest_truncates_to_the_state_and_matches_its_digest():
    rebuild = "".join(f"{i} {h}\n" for i, h in MIGRATIONS).encode("ascii")
    expected = cd.schema_digest(applied_list((ID1, H1), (ID2, H2)))
    data = cd.applied_manifest(rebuild, ID2, expected)
    assert data == f"{ID1} {H1}\n{ID2} {H2}\n".encode("ascii")


def test_applied_manifest_null_is_empty_and_its_digest_is_checked():
    assert cd.applied_manifest(b"", None, cd.schema_digest([])) == b""
    rebuild = f"{ID1} {H1}\n".encode("ascii")
    with pytest.raises(CdError, match="N1"):
        cd.applied_manifest(rebuild, ID1, cd.schema_digest(applied_list((ID1, H2))))
    with pytest.raises(CdError, match="not in the rebuild"):
        cd.applied_manifest(rebuild, ID4, cd.schema_digest([]))
    with pytest.raises(CdError):
        cd.applied_manifest(rebuild, ID1, "not-a-digest")


# pending SQL (N8)


def test_pending_sql_summary_reads_only_verified_target_assets(tmp_path):
    record = build(tmp_path)
    assets = tmp_path / "assets"
    text = cd.pending_sql_summary(record, assets, ID1, "forward", [ID2, ID3])
    assert "ALTER TABLE" in text
    assert f"### {ID2}" in text and f"### {ID3}" in text
    assert f"### {ID1}" not in text
    assert "not executed" in text
    assert "No migrations are pending" in cd.pending_sql_summary(record, assets, ID3, "in-sync", [])


def test_pending_sql_summary_rejects_a_changed_file_and_a_wrong_pending_list(tmp_path):
    record = build(tmp_path)
    assets = tmp_path / "assets"
    (assets / f"{ID2}.sql").write_text("DROP TABLE users;", encoding="utf-8")
    with pytest.raises(CdError, match="does not match release.json"):
        cd.pending_sql_summary(record, assets, ID1, "forward", [ID2, ID3])
    with pytest.raises(CdError, match="pending list"):
        cd.pending_sql_summary(record, assets, ID1, "forward", [ID3])


def test_pending_sql_summary_uses_a_fence_longer_than_any_backtick_run(tmp_path):
    release_dir = make_release_dir(tmp_path / "rel")
    (release_dir / "sql" / f"{ID2}.sql").write_text("-- ``` inside\n", encoding="utf-8")
    record = cd.build_release(TAG, COMMIT, WEB, CRAWLER_TARGET, release_dir, tmp_path / "assets")
    text = cd.pending_sql_summary(record, tmp_path / "assets", ID1, "forward", [ID2, ID3])
    assert "````sql" in text


# deploy follow (N7)


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def status_line(status, run_id="123-1"):
    return json.dumps({"run_id": run_id, "status": status}) + "\n"


def test_follow_completed_success_without_polling():
    clock = FakeClock()
    out = cd.follow_deploy("123-1", status_line("completed:success"), lambda: pytest.fail("no poll"), clock.now, clock.sleep)
    assert out.ok and out.status == "completed:success"
    assert clock.sleeps == []


def test_follow_polls_after_a_dropped_ssh_until_completed():
    clock = FakeClock()
    answers = iter(["", status_line("running"), status_line("completed:success")])
    out = cd.follow_deploy("123-1", "", lambda: next(answers), clock.now, clock.sleep)
    assert out.ok
    # Three polls, each preceded by one interval: the empty answer after the dropped SSH, then running, then completed.
    assert clock.sleeps == [30.0, 30.0, 30.0]


def test_follow_failure_results_are_not_success():
    clock = FakeClock()
    assert not cd.follow_deploy("123-1", status_line("completed:rolled-back"), lambda: "", clock.now, clock.sleep).ok
    indeterminate = cd.follow_deploy("123-1", status_line("indeterminate"), lambda: "", clock.now, clock.sleep)
    assert not indeterminate.ok and "resolve-run" in indeterminate.message


def test_not_started_waits_for_the_grace_period_before_it_is_final():
    clock = FakeClock()
    out = cd.follow_deploy("123-1", "", lambda: status_line("not-started"), clock.now, clock.sleep)
    assert not out.ok and out.status == "not-started"
    assert "safe to re-dispatch" in out.message
    assert clock.t >= cd.NOT_STARTED_GRACE_S


def test_follow_times_out_as_failure_and_unknown_status_fails():
    clock = FakeClock()
    out = cd.follow_deploy("123-1", "", lambda: status_line("running"), clock.now, clock.sleep, interval=30, timeout=90)
    assert not out.ok and "poll status 123-1" in out.message
    bogus = cd.follow_deploy("123-1", status_line("weird"), lambda: "", clock.now, clock.sleep)
    assert not bogus.ok and "unexpected" in bogus.message


def test_status_for_another_run_is_no_answer():
    assert cd.parse_status(status_line("completed:success", run_id="999-1"), "123-1") is None
    assert cd.parse_status("not json\n", "123-1") is None
    assert cd.parse_status(status_line("running"), "123-1") == "running"


def test_follow_rejects_a_malformed_run_id():
    clock = FakeClock()
    with pytest.raises(CdError):
        cd.follow_deploy("123-1; rm", "", lambda: "", clock.now, clock.sleep)


# Summaries and outputs


def test_summarize_compat_handles_missing_and_valid_reports(tmp_path):
    assert "No report was written" in cd.summarize_compat(tmp_path / "missing.json")
    report = {
        "forward_ok": True,
        "classification": "in-sync",
        "pending": [],
        "runtime_smoke": {"result": "pass", "detail": ""},
        "checks": [{"name": "data", "result": "pass", "detail": "ok"}],
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    text = cd.summarize_compat(path)
    assert "| data | pass | ok |" in text
    assert "pending: none" in text


def test_write_outputs_rejects_newlines(tmp_path):
    with pytest.raises(CdError):
        cd.write_outputs(str(tmp_path / "o"), {"a": "x\ny"})


def test_cli_validate_tag_and_release_json_checks(tmp_path):
    out = tmp_path / "out"
    assert cd.main(["validate-tag", "--tag", TAG, "--github-output", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == f"tag={TAG}\n"
    assert cd.main(["validate-tag", "--tag", "v1.0.0\n", "--github-output", str(out)]) == 1
    record_path = tmp_path / "release.json"
    record_path.write_text(release_record().text(), encoding="utf-8")
    assert cd.main(["validate-release-json", "--file", str(record_path), "--tag", "v9.9.9"]) == 1
    assert cd.main(["validate-release-json", "--file", str(record_path), "--tag", TAG, "--commit", COMMIT, "--web-digest", WEB]) == 0


def test_deploy_follow_summary_is_written_and_failure_exits_nonzero(tmp_path):
    summary = tmp_path / "summary.md"
    first = tmp_path / "first.json"
    first.write_text(status_line("indeterminate", run_id="55-2"), encoding="utf-8")
    code = cd.main(
        [
            "deploy-follow",
            "--run-id",
            "55-2",
            "--first-output",
            str(first),
            "--host",
            "deploy@example.invalid",
            "--key",
            str(tmp_path / "key"),
            "--known-hosts",
            str(tmp_path / "kh"),
            "--summary",
            str(summary),
        ]
    )
    assert code == 1
    assert "manual resolve-run required" in summary.read_text(encoding="utf-8")


def test_status_ssh_argv_uses_the_plan_key_options(tmp_path):
    argv = cd.status_ssh_argv("u@h", "/k", "/kh", "55-2")
    assert argv[-1] == "status 55-2"
    assert "IdentitiesOnly=yes" in argv and "StrictHostKeyChecking=yes" in argv
    assert "UserKnownHostsFile=/kh" in argv
