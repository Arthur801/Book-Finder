"""Gate 9 evidence (Docs/data/data-model.md 11.3, Docs/testing/test-plan.md section 7 rows 13 and 14).

What is proven: the previous release (v0.0.6: web and crawler images, pinned by digest) runs on a database migrated to
011 by the target bundle. The checks themselves live in deploy/migration-test/prev-release-on-contract.sh; this test only
builds (or accepts) the target image, runs the script and asserts that every named check passed.

Opt-in: BOOKFINDER_IT=1. Not part of CI. The crawler check is offline; nothing here connects to books.com.tw.
Set PREV_RELEASE_TARGET_IMAGE to a prebuilt target image to skip the docker build. The previous-release digests can be
overridden with PREV_RELEASE_WEB_IMAGE and PREV_RELEASE_CRAWLER_IMAGE.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "deploy" / "migration-test" / "prev-release-on-contract.sh"

PREV_WEB_IMAGE = os.environ.get(
    "PREV_RELEASE_WEB_IMAGE",
    "ghcr.io/arthur801/book-finder-web@sha256:38fc701f9b652640c24a28aa207bdbaf078febed34ab2cec1c86fd068328c441",
)
PREV_CRAWLER_IMAGE = os.environ.get(
    "PREV_RELEASE_CRAWLER_IMAGE",
    "ghcr.io/arthur801/book-finder-crawler@sha256:8675e6a7f43db669a931e74a1ada96a9a9c89d3172ad7b28c75989661446217b",
)

# One line per check the script must print as PASS. A missing name fails the test even when the script exits 0.
REQUIRED_PASSES = [
    "migrate: efbundle applied to 011 on an empty database",
    "migrate: migration history ends at 011 and source_type is gone",
    "seed: 011 seed loaded",
    "web: GET / -> 200",
    "web: GET /books -> 200",
    "web: keyword search finds the seeded Book",
    "web: hyphenated ISBN search finds the seeded Book",
    "web: detail shows the ISBN and the books.com.tw source link",
    "web: no unhandled exception in the container log",
    "crawler: existing Source resolves by URL and touch advances last_seen_at",
    "crawler: ISBN row matches the draft, the Source is attached and no Book is created",
    "crawler: new Source with a fresh ISBN creates a Book with source_code BOOKS_COM_TW",
    "crawler: 100-row ranking validates and replaces the bestsellers",
    "crawler: incomplete ranking is rejected",
    "crawler: Source of another Book is rejected and the bestseller list is unchanged",
]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("BOOKFINDER_IT") != "1", reason="set BOOKFINDER_IT=1 to run the gate 9 check"),
]


@pytest.fixture(scope="module")
def target_image(tmp_path_factory):
    prebuilt = os.environ.get("PREV_RELEASE_TARGET_IMAGE")
    if prebuilt:
        yield prebuilt
        return
    tag = f"bf-it-prev-target:{uuid.uuid4().hex[:12]}"
    log_file = tmp_path_factory.mktemp("prev-release") / "docker-build.log"
    with log_file.open("w", encoding="utf-8") as handle:
        result = subprocess.run(
            ["docker", "build", "-t", tag, str(REPO)],
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=3600,
        )
    assert result.returncode == 0, f"docker build {tag} failed; see {log_file}"
    yield tag
    subprocess.run(["docker", "rmi", "-f", tag], capture_output=True, check=False)


def test_previous_release_runs_on_the_011_contract_schema(target_image, tmp_path):
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--target-image",
            target_image,
            "--prev-web-image",
            PREV_WEB_IMAGE,
            "--prev-crawler-image",
            PREV_CRAWLER_IMAGE,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=1800,
    )
    log_file = tmp_path / "prev-release-on-contract.log"
    log_file.write_text(result.stdout + result.stderr, encoding="utf-8")
    lines = result.stdout.splitlines()
    failures = [line for line in lines if line.startswith("FAIL ")]
    # The script prints "PASS <name>" with the name alone; details go on separate "INFO" lines, so names may contain ": ".
    passes = {line[len("PASS ") :] for line in lines if line.startswith("PASS ")}
    missing = [name for name in REQUIRED_PASSES if name not in passes]

    assert result.returncode == 0, f"script exited {result.returncode}; output in {log_file}"
    assert failures == [], f"checks failed: {failures}; output in {log_file}"
    assert missing == [], f"checks did not pass: {missing}; output in {log_file}"
