from __future__ import annotations

from zaptrace.library.datasheet import extract_datasheet
from zaptrace.security.sandbox import detect_prompt_injection

_DATASHEET = """
ACME1234 regulator
Supply Voltage: 2.7 V to 5.5 V
Output Current: 250 mA maximum
Operating Temperature: -40 C to +125 C
Dropout Voltage: 180 mV
Quiescent Current: 55 uA
Package: SOT-23
"""


def test_bounded_datasheet_patterns_preserve_supported_values() -> None:
    result = extract_datasheet(_DATASHEET)

    assert result.supply_voltage_min_v.value == 2.7
    assert result.supply_voltage_max_v.value == 5.5
    assert result.output_current_max_a.value == 0.25
    assert result.operating_temp_min_c.value == -40.0
    assert result.operating_temp_max_c.value == 125.0
    assert result.dropout_voltage_v.value == 0.18
    assert result.quiescent_current_ua.value == 55.0

    unicode_digits = extract_datasheet("Quiescent Current: ٥٥ uA")
    assert unicode_digits.quiescent_current_ua.value is None


def test_bounded_patterns_handle_long_nonmatching_content() -> None:
    long_text = "x" * 100_000

    result = extract_datasheet(long_text)
    findings = detect_prompt_injection("'" + long_text + " benign")

    assert result.fill_rate == 0.0
    assert findings == []


def test_sql_injection_patterns_remain_detected() -> None:
    for text in ("'x' OR 'y'", "'value -- ", "'; DROP TABLE designs; --"):
        assert any(item["pattern"] == "sql-injection" for item in detect_prompt_injection(text))
