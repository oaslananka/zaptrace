"""Tests for SPICE simulation orchestrator."""

from __future__ import annotations

from zaptrace.analysis.spice_orchestrator import (
    SpiceOrchestrationResult,
    annotate_design_from_spice,
    orchestrate_spice,
)
from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode, NetType, Pin, PinType


def _simple_design() -> Design:
    d = Design(meta=DesignMeta(name="SPICE-test"))
    d.components["r1"] = Component(
        id="r1",
        ref="R1",
        type="resistor",
        value="1k",
        pins={"1": Pin(name="1", type=PinType.PASSIVE), "2": Pin(name="2", type=PinType.PASSIVE)},
    )
    d.nets["vcc"] = Net(
        id="vcc",
        name="VCC",
        type=NetType.POWER,
        nodes=[NetNode(component_ref="R1", pin_name="1")],
    )
    d.nets["gnd"] = Net(
        id="gnd",
        name="GND",
        type=NetType.GROUND,
        nodes=[NetNode(component_ref="R1", pin_name="2")],
    )
    return d


def test_orchestrate_spice_without_ngspice_skips() -> None:
    """When ngspice is not installed, orchestration should return status=skipped."""
    d = _simple_design()
    result = orchestrate_spice(d)
    # ngspice not available in CI — status must be either skipped or ok (never error)
    assert result.status in ("skipped", "ok")
    assert result.design_name == "SPICE-test"


def test_orchestrate_produces_netlist_metadata() -> None:
    d = _simple_design()
    result = orchestrate_spice(d)
    assert result.netlist_lines > 0
    assert result.skipped_components >= 0  # could be 0 if R1 exported cleanly


def test_orchestrate_result_serializable() -> None:
    d = _simple_design()
    result = orchestrate_spice(d)
    data = result.to_dict()
    assert "status" in data
    assert "node_voltages" in data
    assert "checks" in data


def test_annotate_design_skipped_returns_empty() -> None:
    d = _simple_design()
    result = SpiceOrchestrationResult(
        status="skipped",
        design_name="x",
        netlist_lines=5,
        skipped_components=0,
    )
    assert annotate_design_from_spice(d, result) == {}


def test_annotate_design_ground_is_zero() -> None:
    d = _simple_design()
    result = SpiceOrchestrationResult(
        status="ok",
        design_name="x",
        netlist_lines=5,
        skipped_components=0,
        node_voltages={"vcc": 3.3},
    )
    annotated = annotate_design_from_spice(d, result)
    assert "GND" in annotated
    assert annotated["GND"] == 0.0
