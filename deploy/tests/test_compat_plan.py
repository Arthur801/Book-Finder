"""Tests for deploy/lib/compat_plan.sh.

Why: each classification decides which checks compat.sh runs and which it records as skipped. A schema-ahead run must never
run the target bundle, and a skip must always carry a reason, otherwise the CI summary cannot say why a check did not apply.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "deploy" / "lib" / "compat_plan.sh"


def plan(classification: str) -> subprocess.CompletedProcess:
    # The classification goes through "$@" so it is passed as one argument, never interpolated into the script text.
    return subprocess.run(
        ["bash", "-c", 'source "$1"; shift; compat_plan_for "$@"', "bash", str(LIB), classification],
        capture_output=True,
        text=True,
        check=False,
    )


def parse(result: subprocess.CompletedProcess) -> list[tuple[str, ...]]:
    assert result.returncode == 0, result.stderr
    return [tuple(line.split("\t")) for line in result.stdout.splitlines()]


def runs(lines: list[tuple[str, ...]]) -> list[str]:
    return [line[1] for line in lines if line[0] == "run"]


def skips(lines: list[tuple[str, ...]]) -> dict[str, str]:
    return {line[1]: line[2] for line in lines if line[0] == "skip"}


@pytest.mark.parametrize("classification", ["forward", "in-sync"])
def test_forward_and_in_sync_run_every_upgrade_check(classification):
    lines = parse(plan(classification))
    assert runs(lines) == [
        "target upgrade applied",
        "upgraded history equals target manifest",
        "data preserved",
        "schema matches a fresh install",
    ]
    assert skips(lines) == {}


def test_schema_ahead_never_runs_the_target_bundle():
    lines = parse(plan("schema-ahead"))
    assert "target upgrade applied" not in runs(lines)
    assert "target upgrade applied" in skips(lines)


def test_schema_ahead_runs_the_history_data_and_schema_checks_after_the_target_starts():
    lines = parse(plan("schema-ahead"))
    assert runs(lines) == [
        "applied history unchanged by target",
        "data preserved",
        "schema unchanged by target",
    ]


def test_schema_ahead_skips_fresh_install_and_target_manifest_checks_with_reasons():
    skipped = skips(parse(plan("schema-ahead")))
    assert set(skipped) == {
        "target upgrade applied",
        "upgraded history equals target manifest",
        "schema matches a fresh install",
    }
    for name, reason in skipped.items():
        assert reason.strip(), f"{name} needs a reason"


def test_schema_ahead_and_forward_share_no_run_check_except_data():
    forward = set(runs(parse(plan("forward"))))
    ahead = set(runs(parse(plan("schema-ahead"))))
    assert forward & ahead == {"data preserved"}


@pytest.mark.parametrize("classification", ["divergent", "", "unknown"])
def test_unplanned_classification_is_rejected(classification):
    result = plan(classification)
    assert result.returncode != 0
    assert result.stdout == ""
