"""Regression coverage for nested KiCad record closing lines."""

from zaptrace.export.kicad import _INDENTED_CLOSE


def test_kicad_nested_records_keep_the_four_space_closing_form() -> None:
    assert _INDENTED_CLOSE == "    )"
