"""Tests for the block-level power-tree architecture planner."""

from __future__ import annotations

from zaptrace.synthesis.power_tree import build_power_tree_design, plan_power_tree
from zaptrace.synthesis.requirements import parse_requirements


def _stage_topologies(plan: dict) -> dict[float, str]:
    return {s["to_rail_v"]: s["topology"] for s in plan["stages"] if s["stage"] == "regulator"}


def test_acceptance_scenario_usb_c_li_ion_3v3() -> None:
    # "ESP32 + BME280 + Li-ion + USB-C, 3.3V" -> VBUS source + battery + charger +
    # power-path + a 3.3V regulator, each justified.
    plan = plan_power_tree(parse_requirements("esp32 bme280 li-ion usb-c 3.3v i2c sensor"))
    source_names = {s["source"] for s in plan["sources"]}
    assert source_names == {"usb_c_vbus", "li_ion_battery"}
    stage_names = [s["stage"] for s in plan["stages"]]
    assert "charger" in stage_names
    assert "power_path" in stage_names
    assert _stage_topologies(plan)[3.3] in {"ldo", "buck"}
    # Every source and stage carries a rationale.
    assert all(s["rationale"] for s in plan["sources"])
    assert all(s["rationale"] for s in plan["stages"])


def test_charger_cites_the_lipo_calculator() -> None:
    plan = plan_power_tree(parse_requirements("usb-c li-ion 3.3v"))
    charger = next(s for s in plan["stages"] if s["stage"] == "charger")
    assert charger["calculator"] == "lipo_charge_resistor"


def test_low_drop_low_current_rail_picks_ldo() -> None:
    # 5V USB -> 3.3V at 100 mA (no current stated) dissipates ~0.17W -> LDO.
    plan = plan_power_tree(parse_requirements("usb-c 3.3v sensor"))
    assert _stage_topologies(plan)[3.3] == "ldo"


def test_high_current_rail_picks_buck() -> None:
    # 5V USB -> 3.3V at 2A dissipates 3.4W -> buck, citing the buck calculator.
    plan = plan_power_tree(parse_requirements("usb-c 3.3v 2a"))
    reg = next(s for s in plan["stages"] if s["stage"] == "regulator" and s["to_rail_v"] == 3.3)
    assert reg["topology"] == "buck"
    assert reg["calculator"] == "buck_inductor_capacitor"


def test_rail_above_system_voltage_needs_boost() -> None:
    # Battery-only (3.7V system) with a 5V rail -> boost.
    plan = plan_power_tree(parse_requirements("li-ion 5v"))
    assert _stage_topologies(plan)[5.0] == "boost"


def test_battery_without_charge_input_is_flagged() -> None:
    plan = plan_power_tree(parse_requirements("li-ion 3.3v"))
    assert any("charging input" in note for note in plan["notes"])


def test_bare_intent_plans_nothing() -> None:
    plan = plan_power_tree(parse_requirements("a simple LED blinker"))
    assert plan["sources"] == []
    assert plan["stages"] == []
    assert any("no input source" in note for note in plan["notes"])


def test_multiple_rails_are_planned_in_sorted_order() -> None:
    plan = plan_power_tree(parse_requirements("usb-c 5v 1.8v 3.3v sensor"))
    regulator_rails = [stage["to_rail_v"] for stage in plan["stages"] if stage["stage"] == "regulator"]

    assert plan["rails_v"] == sorted(plan["rails_v"])
    assert regulator_rails == sorted(regulator_rails)


def test_build_emits_ldo_and_cc_for_usb_c_low_current() -> None:
    design = build_power_tree_design(parse_requirements("usb-c 3.3v i2c sensor"))
    block_names = {b.name for b in design.blocks}
    assert "USB_C_UFP_CC" in block_names  # CC termination
    assert "LDO_Regulator" in block_names  # 5V->3.3V at light load -> LDO
    assert "I2C_Pullups" in block_names
    assert design.components  # real components emitted
    # The 3.3V rail net is produced.
    assert "VDD_3V3" in design.nets


def test_build_emits_buck_with_computed_values_for_high_current() -> None:
    design = build_power_tree_design(parse_requirements("usb-c 3.3v 2a"))
    buck = next(b for b in design.blocks if b.name == "Sync_Buck_TLV62569")
    inductors = [design.components[c] for c in buck.components if design.components[c].type == "inductor"]
    assert inductors
    assert inductors[0].value.endswith("uH")  # computed inductor value


def test_build_selects_battery_and_generic_input_nets() -> None:
    battery = build_power_tree_design(parse_requirements("battery 3.3v sensor"))
    generic = build_power_tree_design(parse_requirements("5v input 3.3v sensor"))
    assert "VBAT" in battery.nets
    assert "VIN" in generic.nets


def test_build_is_deterministic() -> None:
    a = build_power_tree_design(parse_requirements("usb-c 3.3v i2c sensor"))
    b = build_power_tree_design(parse_requirements("usb-c 3.3v i2c sensor"))
    assert set(a.components) == set(b.components)
    assert set(a.nets) == set(b.nets)


def test_build_bare_intent_emits_empty_design() -> None:
    design = build_power_tree_design(parse_requirements("a simple LED blinker"))
    assert design.components == {}
    assert design.blocks == []


def test_synthesize_power_tree_tool_emits_and_stores_design() -> None:
    from zaptrace.agent._tool_impls import _get_session, call_tool

    result = call_tool("synthesize_power_tree", intent="usb-c 3.3v i2c sensor", session_id="pt-test")
    assert result["component_count"] > 0
    assert result["net_count"] > 0
    assert "USB_C_UFP_CC" in result["blocks"]
    assert result["method"] == "rule_based_power_tree_synthesis"
    assert result["unrealized_stages"] == []  # no boost needed here
    # The design is stored in the session for downstream tools.
    assert result["design_name"] in _get_session("pt-test")["designs"]


def test_synthesize_power_tree_tool_reports_unrealized_boost() -> None:
    from zaptrace.agent._tool_impls import call_tool

    # Battery-only 3.7V system with a 5V rail -> boost, which has no block yet.
    result = call_tool("synthesize_power_tree", intent="li-ion 5v", session_id="pt-boost")
    assert any(s["topology"] == "boost" for s in result["unrealized_stages"])


def test_synthesize_and_check_closes_the_loop() -> None:
    from zaptrace.agent._tool_impls import _get_session, call_tool

    result = call_tool("synthesize_and_check", intent="usb-c 3.3v i2c sensor", session_id="sc-test")
    assert result["component_count"] > 0
    assert "erc" in result
    assert isinstance(result["erc"]["passed"], bool)
    assert result["erc"]["total_errors"] == 0  # a clean power tree has no ERC errors
    # ERC result is recorded in the session alongside the synthesized design.
    session = _get_session("sc-test")
    assert result["design_name"] in session["designs"]
    assert result["design_name"] in session["erc_results"]
