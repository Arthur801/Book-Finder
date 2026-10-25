"""ISBN normalization against the shared cross-language fixture (data-model §7.1).

The same file is read by the C# unit tests. Every vector must match byte for byte, so the test
compares encoded bytes, not only Python string equality.
"""

import json
from pathlib import Path

import pytest

from catalog_core.normalize import normalize_isbn, normalize_isbn_value

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "Fixtures" / "isbn-normalization.json"
VECTORS = json.loads(FIXTURE.read_text(encoding="utf-8"))["vectors"]

# Unicode 15.1 White_Space property, written out as code points (not taken from str.isspace).
WHITE_SPACE = [
    0x0009, 0x000A, 0x000B, 0x000C, 0x000D, 0x0020, 0x0085, 0x00A0, 0x1680,
    *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000,
]  # fmt: skip


@pytest.mark.parametrize("vector", VECTORS, ids=[vector["name"] for vector in VECTORS])
def test_vector_matches_byte_for_byte(vector):
    actual = normalize_isbn_value(vector["input"])

    assert actual.encode("utf-8") == vector["expected"].encode("utf-8")


def test_every_white_space_code_point_has_a_vector():
    covered = {ord(char) for vector in VECTORS for char in vector["input"]}

    missing = [f"U+{code:04X}" for code in WHITE_SPACE if code not in covered]
    assert missing == []


@pytest.mark.parametrize("code", [0x001C, 0x001D, 0x001E, 0x001F, 0x180E, 0x200B])
def test_runtime_space_characters_that_are_not_white_space_are_kept(code):
    value = normalize_isbn_value(f"9{chr(code)}7")

    assert value == f"9{chr(code)}7"


def test_normalized_value_is_stored_as_isbn_type_and_empty_is_not_written():
    identifier = normalize_isbn("978-0-306-40615-7")

    assert identifier is not None and identifier.identifier_type == "ISBN"
    assert identifier.identifier_value == "9780306406157"
    assert normalize_isbn(" \t ") is None
    assert normalize_isbn(None) is None


def test_no_checksum_or_length_validation():
    assert normalize_isbn_value("9780306406158") == "9780306406158"  # wrong checksum is kept
    assert normalize_isbn_value("12345") == "12345"
