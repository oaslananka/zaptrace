"""Regression coverage for nested Specctra DSN closing records."""

from zaptrace.export.dsn import _INDENTED_CLOSE


def test_dsn_nested_records_keep_the_four_space_closing_form() -> None:
    assert _INDENTED_CLOSE == "    )"
