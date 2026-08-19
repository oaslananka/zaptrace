"""Tests for the calculator + SPICE export agent tools."""

from __future__ import annotations

import pytest

from zaptrace.agent._tool_impls import TOOL_REGISTRY, _get_session, call_tool
from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode, NetType, Pin

NEW_TOOLS = [
    "export_spice",
    "calc_led_resistor",
    "calc_voltage_divider",
    "calc_rc_filter",
    "calc_i2c_pullup",
    "calc_e_series",
]


def test_new_tools_registered() -> None:
    for name in NEW_TOOLS:
        assert name in TOOL_REGISTRY, f"{name} not registered"
        assert callable(TOOL_REGISTRY[name]["fn"])
        assert TOOL_REGISTRY[name]["params"]  # has a param schema


def test_calc_led_resistor_tool() -> None:
    r = call_tool("calc_led_resistor", supply_v=5.0, forward_v=2.0, current_ma=10.0)
    assert r["chosen_ohms"] == 300.0
    assert r["resistor_power_w"] == pytest.approx(0.03)


def test_calc_voltage_divider_tool() -> None:
    d = call_tool("calc_voltage_divider", input_v=5.0, output_v=2.5, r_bottom=10_000)
    assert d["r_top_ohms"] == 10_000
    assert d["actual_output_v"] == pytest.approx(2.5)


def test_calc_rc_filter_tool() -> None:
    r = call_tool("calc_rc_filter", r_ohms=1000, c_farads=1e-6)
    assert 159 < r["cutoff_hz"] < 160


def test_calc_i2c_pullup_tool() -> None:
    p = call_tool("calc_i2c_pullup", supply_v=3.3, bus_capacitance_pf=100.0)
    assert p["recommended_ohms"] == 11_000.0
    assert p["bus_speed_hz"] == 100_000


def test_calc_e_series_tool() -> None:
    assert call_tool("calc_e_series", value=263, mode="ceil")["value"] == 270.0
    assert call_tool("calc_e_series", value=263, mode="floor")["value"] == 240.0
    with pytest.raises(ValueError):
        call_tool("calc_e_series", value=100, mode="bogus")


def test_export_spice_tool() -> None:
    design = Design(
        meta=DesignMeta(name="SpiceToolTest"),
        components={
            "r1": Component(
                id="r1",
                ref="R1",
                type="resistor",
                value="10k",
                pins={"p1": Pin(name="p1", type="passive"), "p2": Pin(name="p2", type="passive")},
            ),
            "u1": Component(id="u1", ref="U1", type="mcu", pins={"VCC": Pin(name="VCC", type="power")}),
        },
        nets={
            "vcc": Net(
                id="vcc",
                name="VCC",
                type=NetType.POWER,
                nodes=[NetNode(component_ref="R1", pin_name="p1"), NetNode(component_ref="U1", pin_name="VCC")],
            ),
        },
    )
    session = _get_session("spice-tool-test")
    session["designs"]["SpiceToolTest"] = design
    res = call_tool("export_spice", design_name="SpiceToolTest", session_id="spice-tool-test")
    assert ".end" in res["netlist"]
    assert "R1 " in res["netlist"]
    assert res["unsupported_count"] >= 1  # the MCU has no SPICE model


def test_export_spice_missing_design_raises() -> None:
    with pytest.raises(ValueError):
        call_tool("export_spice", design_name="does-not-exist", session_id="empty-spice-session")
