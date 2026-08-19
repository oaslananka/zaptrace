"""Tests for connector synthesis (USB-C receptacle)."""

from __future__ import annotations

from zaptrace.core.models import Design, DesignMeta
from zaptrace.synthesis.architecture import build_architecture_design
from zaptrace.synthesis.connectors import instantiate_dc_input, instantiate_usb_c_connector
from zaptrace.synthesis.footprint_resolver import resolve_footprints
from zaptrace.synthesis.requirements import parse_requirements


class TestInstantiateConnector:
    def test_wires_power_ground_and_cc(self) -> None:
        design = Design(meta=DesignMeta(name="conn_test"))
        ref = instantiate_usb_c_connector(design, vbus_net="VBUS")
        assert ref.startswith("J")
        for net in ("VBUS", "GND", "CC1", "CC2"):
            assert any(n.component_ref == ref for n in design.nets[net].nodes)

    def test_shield_goes_to_ground(self) -> None:
        design = Design(meta=DesignMeta(name="conn_test"))
        ref = instantiate_usb_c_connector(design)
        gnd_pins = {n.pin_name for n in design.nets["GND"].nodes if n.component_ref == ref}
        assert {"GND", "SHIELD"} <= gnd_pins

    def test_data_pins_left_unconnected(self) -> None:
        # A power-only USB-C input does not wire D+/D-; no net should carry them.
        design = Design(meta=DesignMeta(name="conn_test"))
        ref = instantiate_usb_c_connector(design)
        for net in design.nets.values():
            for node in net.nodes:
                if node.component_ref == ref:
                    assert node.pin_name not in {"D+", "D-", "SBU1", "SBU2"}

    def test_ref_does_not_collide(self) -> None:
        from zaptrace.core.models import Component

        design = Design(meta=DesignMeta(name="conn_test"))
        design.components["J1"] = Component(id="J1", ref="J1", type="connector", value="X")
        ref = instantiate_usb_c_connector(design)
        assert ref != "J1"


class TestDcInput:
    def test_wires_rail_and_ground(self) -> None:
        design = Design(meta=DesignMeta(name="dc_test"))
        ref = instantiate_dc_input(design, vin_net="VDD_3V3")
        assert ref.startswith("J")
        assert any(n.component_ref == ref for n in design.nets["VDD_3V3"].nodes)
        assert any(n.component_ref == ref for n in design.nets["GND"].nodes)


class TestIntegration:
    def test_usb_c_board_gets_a_connector_and_cc_is_terminated(self) -> None:
        design, plan, _log = build_architecture_design(parse_requirements("ESP32-C3 USB-C 3.3V board, I2C sensor"))
        conn = next(c for c in design.components.values() if c.type == "connector")
        # CC1 now carries both the termination resistor and the connector
        cc1 = {n.component_ref for n in design.nets["CC1"].nodes}
        assert conn.ref in cc1
        assert len(design.nets["CC1"].nodes) >= 2
        # the connector is a realized block in the graph
        assert any(b.kind == "connector" and b.realized for b in plan.blocks)

    def test_non_usb_board_gets_a_dc_input_not_usb_c(self) -> None:
        # No stated power input → a DC power terminal drives the rail (not USB-C).
        design, plan, _log = build_architecture_design(parse_requirements("STM32 3.3V board, RS485 modbus"))
        connectors = [b for b in plan.blocks if b.kind == "connector"]
        assert connectors
        assert all(b.params.get("connector") == "dc_input" for b in connectors)
        # the rail it drives is no longer floating
        from zaptrace.analysis.dc_bias import resolve_dc_bias

        assert resolve_dc_bias(design).passed

    def test_connector_footprint_resolves(self) -> None:
        design, _plan, _log = build_architecture_design(parse_requirements("ESP32-C3 USB-C 3.3V board, I2C sensor"))
        resolve_footprints(design)
        conn = next(c for c in design.components.values() if c.type == "connector")
        assert conn.footprint_def is not None
        assert conn.footprint_def.pads
