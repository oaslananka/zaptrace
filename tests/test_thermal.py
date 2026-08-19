"""Tests for thermal estimation helpers."""

from __future__ import annotations

import pytest

from zaptrace.analysis.thermal import (
    component_thermal_check,
    ipc2221_trace_temp_rise,
    ipc2221_trace_width_mm,
    junction_temperature,
    linear_regulator_dissipation,
    max_power_for_junction,
    resistor_dissipation_i,
    resistor_dissipation_v,
    thermal_vias_for_power,
)


def test_junction_temperature() -> None:
    assert junction_temperature(1.0, 50.0, ambient_c=25.0) == pytest.approx(75.0)


def test_max_power_for_junction() -> None:
    assert max_power_for_junction(125.0, 50.0, ambient_c=25.0) == pytest.approx(2.0)
    # already over ambient budget -> clamps at 0
    assert max_power_for_junction(20.0, 50.0, ambient_c=25.0) == 0.0


def test_linear_regulator_dissipation() -> None:
    assert linear_regulator_dissipation(5.0, 3.3, 1.0) == pytest.approx(1.7)
    with pytest.raises(ValueError):
        linear_regulator_dissipation(3.0, 5.0, 1.0)  # vin < vout


def test_resistor_dissipation() -> None:
    assert resistor_dissipation_v(3.0, 300.0) == pytest.approx(0.03)
    assert resistor_dissipation_i(0.01, 300.0) == pytest.approx(0.03)
    with pytest.raises(ValueError):
        resistor_dissipation_v(3.0, 0.0)


def test_ipc2221_trace_width_known_value() -> None:
    # 1 A, 10 °C rise, 1 oz external copper ~= 0.30 mm (classic trace-width chart)
    width = ipc2221_trace_width_mm(1.0, 10.0, copper_oz=1.0, external=True)
    assert width == pytest.approx(0.30, abs=0.02)


def test_ipc2221_internal_is_wider_than_external() -> None:
    ext = ipc2221_trace_width_mm(1.0, 10.0, external=True)
    intl = ipc2221_trace_width_mm(1.0, 10.0, external=False)
    assert intl > ext


def test_ipc2221_width_and_temp_rise_round_trip() -> None:
    width = ipc2221_trace_width_mm(1.0, 10.0, external=True)
    rise = ipc2221_trace_temp_rise(1.0, width, external=True)
    assert rise == pytest.approx(10.0, abs=0.3)


def test_thermal_vias_for_power() -> None:
    assert thermal_vias_for_power(2.0, target_rise_c=40.0, per_via_c_per_w=100.0) == 5
    assert thermal_vias_for_power(0.0) == 0
    assert thermal_vias_for_power(0.1) >= 1


def test_component_thermal_check_in_and_out_of_spec() -> None:
    ok = component_thermal_check(1.0, 50.0, ambient_c=25.0, tj_max_c=125.0)
    assert ok.junction_c == pytest.approx(75.0)
    assert ok.margin_c == pytest.approx(50.0)
    assert ok.within_limit is True

    hot = component_thermal_check(3.0, 50.0, ambient_c=25.0, tj_max_c=125.0)
    assert hot.junction_c == pytest.approx(175.0)
    assert hot.within_limit is False


def test_invalid_inputs_raise() -> None:
    with pytest.raises(ValueError):
        junction_temperature(-1.0, 50.0)
    with pytest.raises(ValueError):
        ipc2221_trace_width_mm(0.0, 10.0)
    with pytest.raises(ValueError):
        ipc2221_trace_temp_rise(1.0, 0.0)
