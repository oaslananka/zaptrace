from __future__ import annotations

from scripts.ci_validation_environment import _first_version_number
from zaptrace.analysis.rail_current import _parse_current
from zaptrace.analysis.regulator_margin import _parse_voltage
from zaptrace.ee.classifier import _extract_voltage
from zaptrace.kicad.step_export import _supports_step_export
from zaptrace.synthesis.mcu import _natural_key
from zaptrace.synthesis.requirements import _extract_dimensions_mm, _extract_temp_range_c


def test_numeric_extractors_preserve_supported_formats(monkeypatch) -> None:
    monkeypatch.setattr(
        "zaptrace.kicad.step_export.subprocess.run",
        lambda *args, **kwargs: type("R", (), {"returncode": 0})(),
    )

    assert _supports_step_export("kicad-cli", "KiCad 9.0.1") == (True, "")
    assert _first_version_number("Python 3.12.7") == (3, 12)
    assert _parse_voltage("3.3 V") == 3.3
    assert _parse_current("250mA") == 0.25
    assert _extract_voltage("3P3V") == 3.3
    assert _extract_temp_range_c("operating -40 to +85 c") == [-40.0, 85.0]
    assert _extract_dimensions_mm("board 50 mm x 30 mm") == [50.0, 30.0]
    assert _natural_key("GPIO2") < _natural_key("GPIO10")


def test_numeric_extractors_reject_long_nonmatching_inputs() -> None:
    long_digits = "9" * 100_000

    assert _first_version_number(long_digits) is None
    assert _parse_voltage(long_digits + "X") is None
    assert _parse_current(long_digits + "X") is None
    assert _extract_voltage(long_digits + "X") is None
    assert _extract_temp_range_c(long_digits + " volts") is None
    assert _extract_dimensions_mm(long_digits + " x missing") is None
