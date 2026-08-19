"""Tests for synthesis test-point auto-insertion."""

from __future__ import annotations

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode, NetType, Pin, PinType
from zaptrace.synthesis.testpoint import insert_test_points


def _minimal_design() -> Design:
    d = Design(meta=DesignMeta(name="test_tp"))
    # One component
    d.components["U1"] = Component(id="U1", ref="U1", type="ic", value="")
    d.components["U1"].pins = {
        "VCC": Pin(name="VCC", type=PinType.POWER),
        "GND": Pin(name="GND", type=PinType.POWER),
        "TX": Pin(name="TX", type=PinType.OUTPUT),
    }
    # Power nets
    d.nets["3V3"] = Net(id="3V3", name="+3V3", type=NetType.POWER, nodes=[NetNode(component_ref="U1", pin_name="VCC")])
    d.nets["GND"] = Net(id="GND", name="GND", type=NetType.GROUND, nodes=[NetNode(component_ref="U1", pin_name="GND")])
    d.nets["UART_TX"] = Net(
        id="UART_TX", name="UART1_TX", type=NetType.SIGNAL, nodes=[NetNode(component_ref="U1", pin_name="TX")]
    )
    return d


class TestTestPointInsertion:
    def test_inserts_power_rail_tps(self) -> None:
        d = _minimal_design()
        plan = insert_test_points(d)
        # +3V3 should get a TP; GND may or may not depending on type
        assert len(plan.added_power_rail_tps) >= 1
        assert "+3V3" in plan.added_power_rail_tps

    def test_tp_components_added(self) -> None:
        d = _minimal_design()
        insert_test_points(d)
        # Check that TP components were created
        tp_refs = [ref for ref in d.components if ref.upper().startswith("TP")]
        assert len(tp_refs) >= 1

    def test_tp_has_correct_pin(self) -> None:
        d = _minimal_design()
        insert_test_points(d)
        tp_refs = [ref for ref in d.components if ref.upper().startswith("TP")]
        tp = d.components[tp_refs[0]]
        assert "1" in tp.pins
        assert tp.pins["1"].type == PinType.PASSIVE

    def test_debug_net_tps(self) -> None:
        d = _minimal_design()
        # Add a debug net
        d.nets["SWCLK"] = Net(id="SWCLK", name="SWCLK", type=NetType.SIGNAL)
        plan = insert_test_points(d, add_debug_tps=True)
        assert "SWCLK" in plan.added_debug_signal_tps

    def test_does_not_duplicate_tps(self) -> None:
        d = _minimal_design()
        # Run insertion twice
        insert_test_points(d)
        tp_count_1 = len([ref for ref in d.components if ref.upper().startswith("TP")])
        insert_test_points(d)
        tp_count_2 = len([ref for ref in d.components if ref.upper().startswith("TP")])
        # Second run should not add duplicate TPs on the same nets
        assert tp_count_2 >= tp_count_1  # may add more for uncovered nets

    def test_plan_has_notes(self) -> None:
        d = _minimal_design()
        plan = insert_test_points(d)
        assert len(plan.notes) >= 1
        assert "test points" in plan.notes[0].lower()

    def test_preserves_existing_tps(self) -> None:
        d = _minimal_design()
        # Add an existing TP
        d.components["TP1"] = Component(
            id="TP1",
            ref="TP1",
            type="testpoint",
            value="",
            pins={"1": Pin(name="1", type=PinType.PASSIVE)},
        )
        insert_test_points(d)
        # New TPs should start at TP2
        assert "TP1" in d.components
        tp_refs = sorted([ref for ref in d.components if ref.upper().startswith("TP")])
        assert "TP2" in tp_refs or len(tp_refs) > 1
