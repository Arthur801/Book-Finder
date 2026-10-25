"""NFKC pinned to Unicode 15.1 (data-model §7.1): conformance and the startup guard.

The conformance test runs the segmented NFKC step against every c1 -> c4 pair of the vendored
NormalizationTest-NFKC.txt (trimmed from Unicode 15.1's NormalizationTest.txt by .github/scripts/unicode_tables.py).
The file is read from the repository root; no runtime code reads tests/Fixtures.
"""

import logging
import unicodedata
from pathlib import Path

import pytest

from books_crawler import cli
from catalog_core.normalize import compose_compatibility, ensure_runtime_unicode_supported
from catalog_core.unicode_15_1 import is_assigned

REPO_ROOT = Path(__file__).resolve().parents[2]
NFKC_PAIRS = REPO_ROOT / "tests" / "Fixtures" / "unicode-15.1" / "NormalizationTest-NFKC.txt"


def _code_points(hex_text: str) -> str:
    return "".join(chr(int(item, 16)) for item in hex_text.split())


def _pairs() -> list[tuple[str, str]]:
    pairs = []
    for raw in NFKC_PAIRS.read_text(encoding="utf-8").splitlines():
        if not raw or raw.startswith("#"):
            continue
        source, expected = raw.split(";")
        pairs.append((_code_points(source), _code_points(expected)))
    return pairs


def test_the_vendored_file_has_every_pair_of_the_trimmed_normalization_test():
    # 19081 lines: 7 comment lines, then one c1;c4 pair per line.
    assert len(_pairs()) == 19074


@pytest.mark.parametrize("source, expected", _pairs(), ids=[f"pair-{index}" for index in range(len(_pairs()))])
def test_segmented_nfkc_matches_every_unicode_15_1_pair(source, expected):
    assert compose_compatibility(source) == expected


def test_unassigned_code_points_pass_through_and_split_the_runs():
    # U+1CCF0 is OUTLINED DIGIT ZERO (Unicode 16.0): unassigned in 15.1, so it stays and blocks composition.
    assert not is_assigned(0x1CCF0)
    assert compose_compatibility("\U0001ccf0") == "\U0001ccf0"
    assert compose_compatibility("9\U0001ccf07") == "9\U0001ccf07"


def test_the_assigned_table_knows_the_boundaries_of_15_1():
    assert is_assigned(0x0041)
    assert is_assigned(0x1E030)  # added in 15.0
    assert not is_assigned(0x1CCF0)  # added in 16.0


def test_runtime_guard_accepts_a_runtime_with_unicode_15_0_or_newer():
    ensure_runtime_unicode_supported()  # must not raise on this runtime


def test_runtime_guard_rejects_an_older_runtime(monkeypatch):
    # An older runtime does not decompose U+1E030 to U+0430; simulate that by leaving the character unchanged.
    real = unicodedata.normalize
    monkeypatch.setattr(
        "catalog_core.normalize.unicodedata.normalize",
        lambda form, text: text if text == "\U0001e030" else real(form, text),
    )
    with pytest.raises(RuntimeError, match="older than 15.0"):
        ensure_runtime_unicode_supported()


def test_cli_exits_2_before_any_work_when_the_runtime_is_too_old(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="books_crawler")

    def too_old():
        raise RuntimeError("The runtime's Unicode data is older than 15.0")

    monkeypatch.setattr(cli, "ensure_runtime_unicode_supported", too_old)
    monkeypatch.setattr(cli, "create_fetcher", lambda *args, **kwargs: pytest.fail("no fetcher"))

    assert cli.main({"DATABASE_URL": "postgresql://unused"}) == 2
    assert "older than 15.0" in caplog.text
