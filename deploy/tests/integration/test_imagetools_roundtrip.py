"""Runs deploy/integration/imagetools-roundtrip.sh against real docker (#92). Opt-in: BOOKFINDER_IT=1.

Why a wrapper: the same script runs in the CI docker job, so the pytest run and CI check one implementation.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "deploy" / "integration" / "imagetools-roundtrip.sh"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("BOOKFINDER_IT") != "1", reason="set BOOKFINDER_IT=1 to run the imagetools round trip"),
]


def test_release_tag_keeps_the_attested_digest():
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, check=False, timeout=900, cwd=REPO)
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "INFO source shape:" in result.stdout
    assert "PASS single-manifest: --prefer-index=false keeps the digest" in result.stdout
    assert "PASS control: default create wraps a single manifest into a new index" in result.stdout
