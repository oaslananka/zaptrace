"""Regression coverage for stale documentation test-total references."""

from scripts.ci_docs_status_sync import BANNED_REFERENCES


def test_stale_test_total_references_share_the_same_actionable_reason() -> None:
    expected = "test totals should not be hard-coded in docs"

    for stale_reference in ("629+ tests", "629 passing", "629 tests", "543 tests passing"):
        assert BANNED_REFERENCES[stale_reference] == expected
