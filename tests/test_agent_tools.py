"""Tests for agent tool implementations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zaptrace.agent._tool_impls import (
    _get_session,
    call_tool,
    get_tool,
    list_tools,
    tool_design_parse_str,
    tool_drc_list_rules,
    tool_erc_list_rules,
    tool_erc_validate,
    tool_footprint_get,
    tool_footprint_search,
    tool_library_list_categories,
    tool_list_synthesis_templates,
)

_SESSION = "test-session"


class TestToolRegistry:
    def test_list_tools_count(self) -> None:
        tools = list_tools()
        assert len(tools) >= 47

    def test_get_tool_by_name(self) -> None:
        tool = get_tool("design_parse_file")
        assert tool["name"] == "design_parse_file"
        assert "description" in tool
        assert "fn" in tool

    def test_get_tool_unknown(self) -> None:
        import pytest

        with pytest.raises(KeyError):
            get_tool("nonexistent_tool")

    def test_call_tool_direct(self) -> None:
        result = tool_list_synthesis_templates()
        assert isinstance(result, list)
        assert len(result) >= 8

    def test_call_tool_via_registry(self) -> None:
        result = call_tool("list_synthesis_templates")
        assert isinstance(result, list)

    def test_call_tool_erc_rules(self) -> None:
        result = tool_erc_list_rules()
        assert "rules" in result
        assert len(result["rules"]) >= 20

    def test_call_tool_drc_rules(self) -> None:
        result = tool_drc_list_rules()
        assert result["count"] >= 8
        assert result["rules"][0]["id"]

    def test_call_tool_library_categories(self) -> None:
        result = tool_library_list_categories()
        assert "categories" in result


class TestDesignTools:
    def test_parse_str_tool(self) -> None:
        yaml = """
meta:
  name: TestTool
components:
  r1:
    ref: R1
    type: resistor
    value: 10k
nets:
  n1:
    name: VCC
    nodes:
      - R1.pin1
"""
        result = tool_design_parse_str(session_id=_SESSION, yaml_content=yaml)
        assert result["design_name"] == "TestTool"
        assert result["component_count"] == 1
        session = _get_session(_SESSION)
        assert "TestTool" in session["designs"]

    def test_synthesize_tool(self) -> None:
        result = call_tool("synthesize_design", session_id=_SESSION, intent="esp32 i2c sensor")
        assert result["design_name"] != ""

    def test_erc_validate_tool(self) -> None:
        # First parse a design
        yaml = """meta:
  name: TestERC
components:
  u1:
    ref: U1
    type: mcu
    pins:
      VCC: power
nets:
  vcc:
    name: VCC
    nodes:
      - U1.VCC
board:
  width_mm: 50
  height_mm: 50
"""
        tool_design_parse_str(session_id=_SESSION, yaml_content=yaml)
        result = call_tool("erc_validate", session_id=_SESSION, design_name="TestERC")
        assert "passed" in result
        assert "violations" in result

    def test_drc_run_accepts_fab_profile(self) -> None:
        syn = call_tool("synthesize_design", session_id=_SESSION, intent="esp32 i2c sensor")
        name = syn["design_name"]
        generic = call_tool("drc_run", session_id=_SESSION, design_name=name)
        assert generic["fab_profile"] is None
        profiled = call_tool("drc_run", session_id=_SESSION, design_name=name, fab_profile="jlcpcb-2layer")
        assert profiled["fab_profile"] == "jlcpcb-2layer"
        # A fab profile can only add profile-specific findings, never remove generic ones.
        assert profiled["total_violations"] >= generic["total_violations"]

    def test_mechanical_review_tool(self) -> None:
        name = call_tool("synthesize_design", session_id=_SESSION, intent="esp32 i2c sensor")["design_name"]
        result = call_tool("mechanical_review", session_id=_SESSION, design_name=name)
        assert result["design"] == name
        assert result["finding_count"] == len(result["findings"])

    def test_security_review_tool(self) -> None:
        name = call_tool("synthesize_design", session_id=_SESSION, intent="esp32 i2c sensor")["design_name"]
        result = call_tool("security_review", session_id=_SESSION, design_name=name)
        assert "findings" in result
        assert result["finding_count"] == len(result["findings"])

    def test_testability_report_tool(self) -> None:
        name = call_tool("synthesize_design", session_id=_SESSION, intent="esp32 i2c sensor")["design_name"]
        result = call_tool("testability_report", session_id=_SESSION, design_name=name)
        assert "report" in result
        assert "bringup_checklist" in result
        assert isinstance(result["bringup_checklist"], list)

    def test_electrical_analysis_tool(self) -> None:
        name = call_tool("synthesize_design", session_id=_SESSION, intent="esp32 i2c sensor")["design_name"]
        result = call_tool("electrical_analysis", session_id=_SESSION, design_name=name)
        report = result["report"]
        # The report must carry its honesty metadata (pre-check, not signoff).
        assert "findings" in report
        assert "limitations" in report

    def test_analysis_tool_missing_design_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            call_tool("mechanical_review", session_id=_SESSION, design_name="does-not-exist")

    def test_requirements_parse_tool(self) -> None:
        result = call_tool("requirements_parse", intent="esp32 usb-c li-ion 3.3v i2c sensor")
        req = result["requirements"]
        assert req["mcu"] == "esp32"
        assert req["usb_c"] is True
        assert req["battery"] is True
        assert 3.3 in req["rails_v"]
        # Constraints are derived and traceable from the requirements.
        constraints = result["constraints"]
        assert any(d["nominal"] == "3.3V" for d in constraints["voltage_domains"])
        assert any(r["differential_pair"] for r in constraints["routing"])

    def test_compliance_checklist_tool(self) -> None:
        result = call_tool("compliance_checklist", intent="esp32 usb-c li-ion battery 3.3v")
        assert result["item_count"] == len(result["items"])
        # A battery/USB-C product must surface at least one compliance item.
        assert result["item_count"] >= 1
        assert all({"standard", "category", "action"} <= set(item) for item in result["items"])

    def test_tool_session_isolation(self) -> None:
        """Different sessions should have independent state."""
        s1 = "session-a"
        s2 = "session-b"
        yaml = """meta:
  name: DesignA
components:
  r1:
    ref: R1
    type: resistor
"""
        tool_design_parse_str(session_id=s1, yaml_content=yaml)
        design_a = _get_session(s1)["designs"]
        design_b = _get_session(s2)["designs"]
        assert "DesignA" in design_a
        assert "DesignA" not in design_b


class TestLibraryTools:
    def test_search_tool(self) -> None:
        result = call_tool("library_search", query="esp32")
        assert "results" in result
        assert "count" in result

    def test_footprint_search_tool(self) -> None:
        result = tool_footprint_search("esp32")
        assert result["count"] >= 1
        assert result["footprints"][0]["footprint"]

    def test_footprint_get_tool(self) -> None:
        result = tool_footprint_get("esp32-wroom-32")
        assert result["component_id"] == "esp32-wroom-32"
        assert result["footprint"]


class TestBoardTool:
    def test_board_update(self) -> None:
        # Parse a simple design first
        yaml = """meta: {name: BoardTest}
components:
  r1: {ref: R1, type: resistor}
"""
        tool_design_parse_str(session_id=_SESSION, yaml_content=yaml)
        result = call_tool("board_update", session_id=_SESSION, design_name="BoardTest", width_mm=80.0)
        assert result["width_mm"] == 80.0


class TestPhase2Tools:
    def test_footprint_generate_0603(self) -> None:
        result = call_tool("footprint_generate", package="0603")
        assert "pads" in result
        assert len(result["pads"]) == 2

    def test_footprint_generate_unknown(self) -> None:
        result = call_tool("footprint_generate", package="BGA-900")
        assert "error" in result

    def test_footprint_generate_soic8(self) -> None:
        result = call_tool("footprint_generate", package="SOIC-8")
        assert len(result["pads"]) == 8

    def test_footprint_list_packages(self) -> None:
        result = call_tool("footprint_list_packages")
        assert "packages" in result
        assert result["count"] >= 40

    def test_schematic_render(self) -> None:
        yaml = """meta: {name: SchematicToolTest}
components:
  r1: {ref: R1, type: resistor, value: 10k}
  c1: {ref: C1, type: capacitor, value: 100n}
nets:
  n1: {name: VCC, nodes: [R1.1]}
"""
        tool_design_parse_str(session_id=_SESSION, yaml_content=yaml)
        result = call_tool("schematic_render", session_id=_SESSION, design_name="SchematicToolTest")
        assert "svg" in result
        assert "<svg" in result["svg"]

    def test_export_pick_and_place(self) -> None:
        yaml = """meta: {name: PnPToolTest}
components:
  r1: {ref: R1, type: resistor, value: 10k, footprint: '0603', position: [12.0, 20.0]}
  c1: {ref: C1, type: capacitor, value: 100n, footprint: '0603', position: [10.0, 20.0]}
nets:
  n1: {name: VCC, nodes: [R1.1]}
"""
        tool_design_parse_str(session_id=_SESSION, yaml_content=yaml)
        tool_erc_validate(session_id=_SESSION, design_name="PnPToolTest")
        call_tool("drc_run", session_id=_SESSION, design_name="PnPToolTest")
        result = call_tool(
            "export_pick_and_place",
            session_id=_SESSION,
            design_name="PnPToolTest",
            approval_id="test-pnp-approval",
            fab_profile_skip_reason="Unit-test fixture has no manufacturer profile",
            fab_profile_skip_approval_id="FAB-SKIP-APPROVAL-1",
        )
        assert "csv" in result
        assert "C1" in result["csv"]

    def test_export_manufacturing(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        import os

        monkeypatch.setenv("ZAPTRACE_WORKSPACE", str(tmp_path))
        import zaptrace.agent._tool_impls as _ti

        monkeypatch.setattr(_ti, "_WORKSPACE", None)

        yaml = """meta: {name: MfgToolTest}
components:
  r1: {ref: R1, type: resistor, value: 10k, footprint: '0603', position: [10.0, 20.0]}
nets:
  n1: {name: VCC, nodes: [R1.1]}
"""
        tool_design_parse_str(session_id=_SESSION, yaml_content=yaml)
        tool_erc_validate(session_id=_SESSION, design_name="MfgToolTest")
        call_tool("drc_run", session_id=_SESSION, design_name="MfgToolTest")
        result = call_tool(
            "export_manufacturing",
            session_id=_SESSION,
            design_name="MfgToolTest",
            output_dir=str(tmp_path),
            approval_id="test-manufacturing-approval",
            fab_profile_skip_reason="Unit-test fixture has no manufacturer profile",
            fab_profile_skip_approval_id="FAB-SKIP-APPROVAL-1",
        )
        assert "zip" in result
        assert os.path.exists(result["zip"])
        assert result["dfm_readiness_status"] == "approved-skip"
        assert os.path.exists(result["dfm_readiness"])
        readiness = json.loads(Path(result["dfm_readiness"]).read_text(encoding="utf-8"))
        assert readiness["approved_skips"][0]["approval_id"] == "FAB-SKIP-APPROVAL-1"
