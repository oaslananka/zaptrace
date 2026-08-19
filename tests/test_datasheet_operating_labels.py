"""Regression coverage for recommended-operating provenance labels."""

from zaptrace.library.datasheet import build_datasheet_fact_report

_TEXT = """
Regulator Features:
Supply (Input) Voltage: 5V to 15V
Operating Temperature: -40°C to +125°C
"""


def test_recommended_operating_facts_share_stable_provenance_labels() -> None:
    report = build_datasheet_fact_report("regulator", _TEXT, page=7)

    assert len(report.recommended_operating) == 4
    assert {fact.source.table for fact in report.recommended_operating} == {"Recommended Operating Conditions"}
    assert {fact.source.section for fact in report.recommended_operating} == {"recommended operating conditions"}
