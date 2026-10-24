import importlib.util

import pytest
import unicode_tables as ut

DERIVED_HEADER = "# DerivedAge-15.1.0.txt\n#\n"


def test_adjacent_and_single_code_points_are_merged_into_ranges():
    text = DERIVED_HEADER + "0041..005A ; 1.1 # A..Z\n005B ; 1.1 # [\n005C..005D ; 1.1\n0100 ; 2.0\n"

    assert ut.parse_assigned_ranges(text) == [(0x41, 0x5D), (0x100, 0x100)]


def test_comment_and_blank_lines_are_ignored_and_order_does_not_matter():
    text = DERIVED_HEADER + "\n# comment only\n0200..0201 ; 3.0\n0100 ; 1.1\n"

    assert ut.parse_assigned_ranges(text) == [(0x100, 0x100), (0x200, 0x201)]


def test_a_file_that_is_not_the_15_1_derived_age_is_rejected():
    with pytest.raises(ValueError, match="not the Unicode 15.1 DerivedAge file"):
        ut.parse_assigned_ranges("# DerivedAge-16.0.0.txt\n0041 ; 1.1\n")


def test_a_code_point_newer_than_15_1_is_rejected():
    with pytest.raises(ValueError, match="newer than Unicode 15.1"):
        ut.parse_assigned_ranges(DERIVED_HEADER + "1CCF0 ; 16.0\n")


def test_trimming_keeps_license_header_and_only_the_source_and_nfkc_columns():
    text = (
        "# NormalizationTest-15.1.0.txt\n# Date: x\n# ©\n# tm\n# terms\n# more\n"
        "@Part0 # Specific cases\n"
        "1E0A;1E0A;0044 0307;1E0A;0044 0307; # comment\n"
        "1E0A 0323;1E0C 0307;0044 0323 0307;1E0C 0307;0044 0323 0307;\n"
    )

    trimmed = ut.trim_normalization_test(text).splitlines()

    assert trimmed[-2:] == ["1E0A;1E0A", "1E0A 0323;1E0C 0307"]
    assert "# NormalizationTest-15.1.0.txt" in trimmed


def test_a_malformed_normalization_line_is_rejected():
    with pytest.raises(ValueError, match="unexpected NormalizationTest line"):
        ut.trim_normalization_test("1E0A;1E0A\n")


def test_rendered_python_table_answers_membership_like_the_ranges(tmp_path):
    module_path = tmp_path / "table.py"
    module_path.write_text(ut.render_py([(0x41, 0x5A), (0x1E030, 0x1E06D)]), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("rendered_table", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.is_assigned(0x41)
    assert module.is_assigned(0x1E030)
    assert not module.is_assigned(0x40)
    assert not module.is_assigned(0x1CCF0)


def test_check_mode_fails_on_drift_and_passes_after_write(tmp_path):
    fixture = tmp_path / ut.FIXTURE_DIR
    fixture.mkdir(parents=True)
    (fixture / ut.DERIVED_AGE).write_text(DERIVED_HEADER + "0041 ; 1.1\n", encoding="utf-8")
    (fixture / ut.NORMALIZATION_TEST).write_text("# NormalizationTest-15.1.0.txt\n1E0A;1E0A;0044 0307;1E0A;0044 0307;\n", encoding="utf-8")

    assert ut.main(["--write"], root=tmp_path) == 0
    assert ut.main(["--check"], root=tmp_path) == 0

    (tmp_path / ut.CS_TABLE).write_text("// edited by hand\n", encoding="utf-8")
    assert ut.main(["--check"], root=tmp_path) == 1


def test_committed_tables_match_the_vendored_unicode_15_1_data():
    assert ut.main(["--check"]) == 0
