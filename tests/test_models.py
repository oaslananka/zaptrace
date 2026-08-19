"""Tests for core Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from zaptrace.core.models import (
    Block,
    BoardConfig,
    Component,
    Design,
    DesignMeta,
    Lifecycle,
    Net,
    NetConstraints,
    NetNode,
    NetType,
    Pin,
    PinType,
    resolve_variant,
)


class TestPin:
    def test_minimal(self) -> None:
        p = Pin(name="VCC", type=PinType.POWER)
        assert p.name == "VCC"
        assert p.type == PinType.POWER

    def test_full(self) -> None:
        p = Pin(
            name="TX",
            type=PinType.OUTPUT,
            net="uart_tx",
            position=(10.0, 20.0),
            voltage_level="3.3V",
            description="UART transmit",
        )
        assert p.net == "uart_tx"
        assert p.position == (10.0, 20.0)

    def test_default_description(self) -> None:
        p = Pin(name="GND", type=PinType.POWER)
        assert p.description == ""


class TestNet:
    def test_minimal(self) -> None:
        n = Net(id="n1", name="VCC")
        assert n.type == NetType.SIGNAL

    def test_with_nodes(self) -> None:
        n = Net(
            id="n1",
            name="I2C_SCL",
            type=NetType.CLOCK,
            nodes=[
                NetNode(component_ref="U1", pin_name="SCL"),
                NetNode(component_ref="U2", pin_name="SCL"),
            ],
        )
        assert len(n.nodes) == 2

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            Net(id="n1", name="   ")

    def test_net_constraints(self) -> None:
        n = Net(
            id="n1",
            name="USB_D_P",
            constraints=NetConstraints(impedance_target=90.0, length_match_group="usb_dp"),
        )
        assert n.constraints is not None
        assert n.constraints.impedance_target == 90.0
        assert n.constraints.length_match_group == "usb_dp"

    def test_round_trip(self) -> None:
        n1 = Net(
            id="n1",
            name="USB_D_P",
            constraints=NetConstraints(impedance_target=90.0, length_match_group="usb_dp"),
        )
        data = n1.model_dump()
        n2 = Net.model_validate(data)
        assert n1 == n2


class TestComponent:
    def test_minimal(self) -> None:
        c = Component(id="c1", ref="R1", type="resistor")
        assert c.lifecycle == Lifecycle.ACTIVE
        assert c.footprint == ""

    def test_with_pins(self) -> None:
        c = Component(
            id="c1",
            ref="U1",
            type="mcu",
            pins={
                "VCC": Pin(name="VCC", type=PinType.POWER),
                "GND": Pin(name="GND", type=PinType.POWER),
            },
        )
        assert len(c.pins) == 2

    def test_lifecycle_values(self) -> None:
        c = Component(id="c1", ref="D1", type="diode", lifecycle=Lifecycle.NRND)
        assert c.lifecycle == Lifecycle.NRND

    def test_variant_fields(self) -> None:
        c = Component(
            id="c1",
            ref="R1",
            type="resistor",
            dnp=True,
            variants={"v1": True},
            lcsc_id="C12345",
            basic_part=True,
            stock=1000,
        )
        assert c.dnp is True
        assert c.variants == {"v1": True}
        assert c.lcsc_id == "C12345"
        assert c.basic_part is True
        assert c.stock == 1000

    def test_round_trip(self) -> None:
        c1 = Component(
            id="c1",
            ref="R1",
            type="resistor",
            dnp=True,
            variants={"v1": True},
            lcsc_id="C12345",
            basic_part=True,
            stock=1000,
        )
        data = c1.model_dump()
        c2 = Component.model_validate(data)
        assert c1 == c2


class TestBoardConfig:
    def test_defaults(self) -> None:
        b = BoardConfig()
        assert b.width_mm == 100.0
        assert b.layers == 2

    def test_custom(self) -> None:
        b = BoardConfig(width_mm=50.0, height_mm=40.0, layers=4)
        assert b.width_mm == 50.0
        assert b.layers == 4


class TestDesign:
    def _make_design(self) -> Design:
        return Design(
            meta=DesignMeta(name="test"),
            components={
                "c1": Component(id="c1", ref="R1", type="resistor", value="10k"),
                "c2": Component(id="c2", ref="C1", type="capacitor", value="100n"),
            },
            nets={
                "n1": Net(
                    id="n1",
                    name="VCC",
                    nodes=[
                        NetNode(component_ref="R1", pin_name="pin1"),
                        NetNode(component_ref="C1", pin_name="pin1"),
                    ],
                ),
            },
        )

    def test_get_net_for_pin(self) -> None:
        d = self._make_design()
        net = d.get_net_for_pin("R1", "pin1")
        assert net is not None
        assert net.name == "VCC"

    def test_get_net_for_pin_not_found(self) -> None:
        d = self._make_design()
        net = d.get_net_for_pin("R1", "nonexistent")
        assert net is None

    def test_get_components_on_net(self) -> None:
        d = self._make_design()
        comps = d.get_components_on_net("n1")
        assert len(comps) == 2

    def test_get_components_on_net_unknown(self) -> None:
        d = self._make_design()
        comps = d.get_components_on_net("n99")
        assert comps == []

    def test_resolve_variant(self) -> None:
        d = Design(
            meta=DesignMeta(name="test"),
            components={
                "c1": Component(id="c1", ref="R1", type="resistor", dnp=False),
                "c2": Component(id="c2", ref="C1", type="capacitor", dnp=True, variants={"v1": True}),
                "c3": Component(id="c3", ref="C2", type="capacitor", dnp=False, variants={"v1": False}),
            },
        )

        # Default (no variant) should use standard dnp field (or we test just the variant)
        # Assuming we just call resolve_variant("v1")
        populated = d.resolve_variant("v1")
        assert "c1" in populated  # Not DNP, no variant override, should be populated
        assert "c2" in populated  # DNP=True, but variant override says True
        assert "c3" not in populated  # DNP=False, but variant override says False

        populated_v2 = d.resolve_variant("v2")
        assert "c1" in populated_v2
        assert "c2" not in populated_v2  # DNP=True, variant 'v2' not present, defaults to not DNP=False
        assert "c3" in populated_v2  # DNP=False, variant 'v2' not present, defaults to not DNP=True


class TestBlock:
    def test_minimal(self) -> None:
        b = Block(id="b1", name="Power")
        assert b.components == []

    def test_with_components(self) -> None:
        b = Block(id="b1", name="MCU", components=["u1", "u2"])
        assert len(b.components) == 2


class TestResolveVariant:
    def test_standalone_resolver(self) -> None:
        d = Design(
            meta=DesignMeta(name="test"),
            components={
                "c1": Component(id="c1", ref="R1", type="resistor", dnp=False),
                "c2": Component(id="c2", ref="C1", type="capacitor", dnp=True, variants={"v1": True}),
                "c3": Component(id="c3", ref="C2", type="capacitor", dnp=False, variants={"v1": False}),
            },
        )

        populated = resolve_variant(d, "v1")
        assert "c1" in populated  # Not DNP, no variant override, should be populated
        assert "c2" in populated  # DNP=True, but variant override says True
        assert "c3" not in populated  # DNP=False, but variant override says False

        populated_v2 = resolve_variant(d, "v2")
        assert "c1" in populated_v2
        assert "c2" not in populated_v2  # DNP=True, variant 'v2' not present
        assert "c3" in populated_v2  # DNP=False, variant 'v2' not present


class TestCanonicalIRExtensions:
    """Tests for Canonical Hardware IR extension fields."""

    def test_pin_function_field(self) -> None:
        from zaptrace.core.models import Pin, PinType

        p = Pin(name="SDA", type=PinType.BIDIRECTIONAL, pin_function="I2C_SDA")
        assert p.pin_function == "I2C_SDA"

    def test_pin_current_domain(self) -> None:
        from zaptrace.core.models import Pin, PinType

        p = Pin(name="VCC", type=PinType.POWER, current_domain="POWER_IN")
        assert p.current_domain == "POWER_IN"

    def test_net_constraints_diff_pair(self) -> None:
        from zaptrace.core.models import NetConstraints

        nc = NetConstraints(
            diff_pair_partner="NET_USB_DM",
            diff_pair_gap_mm=0.15,
            impedance_target=90.0,
        )
        assert nc.diff_pair_partner == "NET_USB_DM"
        assert nc.diff_pair_gap_mm == 0.15

    def test_net_constraints_high_current(self) -> None:
        from zaptrace.core.models import NetConstraints

        nc = NetConstraints(is_high_current=True, min_trace_width_mm=0.5)
        assert nc.is_high_current
        assert nc.min_trace_width_mm == 0.5

    def test_net_constraints_creepage_group(self) -> None:
        from zaptrace.core.models import NetConstraints

        nc = NetConstraints(creepage_group="MAINS", return_path_net="GND")
        assert nc.creepage_group == "MAINS"
        assert nc.return_path_net == "GND"

    def test_component_supply_graph_fields(self) -> None:
        from zaptrace.core.models import Component

        c = Component(
            id="u1",
            ref="U1",
            type="ic",
            mpn="ESP32-S3",
            alternates=["ESP32-S3-WROOM-1"],
            distributor_links={"Digi-Key": "1965-ESP32-S3-WROOM-1-N4CT-ND"},
            price_usd=3.25,
            supply_fetched_at="2026-06-27T00:00:00Z",
        )
        assert c.alternates == ["ESP32-S3-WROOM-1"]
        assert "Digi-Key" in c.distributor_links
        assert c.price_usd == 3.25

    def test_prov_record(self) -> None:
        from zaptrace.core.models import ProvRecord

        pr = ProvRecord(
            record_id="prov-001",
            tool="zaptrace-erc",
            tool_version="0.3.0",
            output_artifact_ids=["erc-result-001"],
            artifact_hashes={"erc-result-001": "abc123"},
            decision_summary="ERC ran 29 rules, 0 errors, 2 warnings",
        )
        assert pr.record_id == "prov-001"
        assert pr.tool == "zaptrace-erc"
        assert pr.artifact_hashes["erc-result-001"] == "abc123"

    def test_import_loss_record(self) -> None:
        from zaptrace.core.models import ImportLossRecord

        r = ImportLossRecord(
            source_format="KiCad 8",
            field_path="nets[3].constraints.creepage_group",
            behavior="warn",
            original_value="MAINS_ISOLATION",
            degraded_value=None,
            note="KiCad 8 does not encode creepage groups; field was dropped",
        )
        assert r.behavior == "warn"
        assert r.source_format == "KiCad 8"

    def test_hierarchy_sheet(self) -> None:
        from zaptrace.core.models import HierarchySheet

        s = HierarchySheet(
            sheet_id="sheet-1",
            name="Power Supply",
            component_ids=["U1", "C1", "C2"],
        )
        assert s.name == "Power Supply"
        assert s.parent_id is None

    def test_design_carries_prov_and_sheets(self) -> None:
        from zaptrace.core.models import Design, DesignMeta, HierarchySheet, ProvRecord

        d = Design(
            meta=DesignMeta(name="test"),
            prov_records=[
                ProvRecord(
                    record_id="p1",
                    tool="zaptrace-synth",
                    decision_summary="synthesized power tree",
                )
            ],
            sheets=[HierarchySheet(sheet_id="s1", name="Top", component_ids=[])],
        )
        assert len(d.prov_records) == 1
        assert d.prov_records[0].tool == "zaptrace-synth"
        assert len(d.sheets) == 1


class TestSupplyChainModels:
    """Tests for the Canonical Hardware IR — supply-chain, manufacturing, cable, enclosure."""

    def test_supply_record_minimal(self) -> None:
        from zaptrace.core.models import SupplyRecord

        s = SupplyRecord(mpn="LM4950")
        assert s.mpn == "LM4950"
        assert s.rohs is True
        assert s.lifecycle.value == "active"

    def test_supply_record_full(self) -> None:
        from zaptrace.core.models import Lifecycle, SupplyRecord

        s = SupplyRecord(
            mpn="STM32F411CEU6",
            manufacturer="STMicroelectronics",
            lifecycle=Lifecycle.ACTIVE,
            lcsc_id="C12345",
            stock=5000,
            price_usd=3.50,
            alternates=["STM32F411RET6"],
            distributor_links={"Digi-Key": "STM32F411CEU6-ND"},
        )
        assert s.manufacturer == "STMicroelectronics"
        assert s.stock == 5000
        assert s.lead_time_days is None
        assert len(s.alternates) == 1

    def test_supply_record_json_roundtrip(self) -> None:
        from zaptrace.core.models import SupplyRecord

        s = SupplyRecord(mpn="NRF52840", msl=3, rohs=True)
        data = s.model_dump_json()
        restored = SupplyRecord.model_validate_json(data)
        assert restored.mpn == "NRF52840"
        assert restored.msl == 3

    def test_manufacturing_record_defaults(self) -> None:
        from zaptrace.core.models import ManufacturingRecord

        m = ManufacturingRecord(profile_id="jlcpcb-2layer")
        assert m.min_trace_mm == 0.15
        assert m.min_hole_mm == 0.15
        assert m.assembly_side == "top"
        assert m.panelization == "none"

    def test_manufacturing_record_custom(self) -> None:
        from zaptrace.core.models import ManufacturingRecord

        m = ManufacturingRecord(
            profile_id="pcbway-std",
            min_trace_mm=0.1,
            min_clearance_mm=0.1,
            max_layers=4,
            impedance_control=True,
            assembly_side="both",
        )
        assert m.max_layers == 4
        assert m.impedance_control is True
        assert m.assembly_side == "both"

    def test_cable_harness(self) -> None:
        from zaptrace.core.models import CableHarness

        c = CableHarness(
            id="h1",
            name="Sensor ribbon",
            wire_count=10,
            connector_a="JST-SH 10-pin",
            connector_b="JST-SH 10-pin",
            max_length_mm=100.0,
        )
        assert c.wire_gauge_awg is None
        assert c.shielding == "none"
        assert c.max_length_mm == 100.0

    def test_cable_harness_full(self) -> None:
        from zaptrace.core.models import CableHarness

        c = CableHarness(
            id="h2",
            name="Power cable",
            wire_count=2,
            wire_gauge_awg=18,
            rated_voltage_v=300,
            rated_current_a=10,
            shielding="braid",
        )
        assert c.wire_gauge_awg == 18
        assert c.rated_voltage_v == 300
        assert c.shielding == "braid"

    def test_enclosure_def(self) -> None:
        from zaptrace.core.models import EnclosureDef

        e = EnclosureDef(
            id="enc1",
            name="Handheld ABS",
            material="ABS",
            ip_rating="IP54",
            external_dimensions_mm=(100.0, 60.0, 25.0),
            mounting="screw",
        )
        assert e.ip_rating == "IP54"
        assert e.external_dimensions_mm == (100.0, 60.0, 25.0)
        assert e.flammability == ""

    def test_board_to_board_connector(self) -> None:
        from zaptrace.core.models import BoardToBoardConnector

        b2b = BoardToBoardConnector(
            id="btb1",
            name="FPC-16",
            board_a="main",
            board_b="display",
            connector_on_a="J1",
            connector_on_b="J2",
            pin_count=16,
            signals=["LCD_D0", "LCD_D1", "LCD_CLK", "GND"],
        )
        assert b2b.pin_count == 16
        assert len(b2b.signals) == 4

    def test_multi_board_project(self) -> None:
        from zaptrace.core.models import BoardToBoardConnector, CableHarness, MultiBoardProject

        mb = MultiBoardProject(
            name="sensor_node",
            boards={"main": "main_board", "display": "display_board", "sensor": "sensor_board"},
            board_to_board_connectors=[
                BoardToBoardConnector(
                    id="btb1",
                    name="FPC-12",
                    board_a="main",
                    board_b="display",
                    connector_on_a="J1",
                    connector_on_b="J2",
                    pin_count=12,
                ),
            ],
            cable_harnesses=[
                CableHarness(id="h1", name="Ext sensor", wire_count=4),
            ],
        )
        assert len(mb.boards) == 3
        assert len(mb.board_to_board_connectors) == 1
        assert len(mb.cable_harnesses) == 1
        assert mb.system_ground_strategy == ""

    def test_design_carries_new_ir_fields(self) -> None:
        from zaptrace.core.models import (
            CableHarness,
            Design,
            DesignMeta,
            EnclosureDef,
            ManufacturingRecord,
            MultiBoardProject,
            SupplyRecord,
        )

        d = Design(meta=DesignMeta(name="test_ir"))
        d.supply_chain["R1"] = SupplyRecord(mpn="RMCF0402FT10K0")
        d.manufacturing_records.append(ManufacturingRecord(profile_id="jlcpcb-2layer"))
        d.cable_harnesses.append(CableHarness(id="h1", name="USB cable", wire_count=4))
        d.enclosure = EnclosureDef(id="enc1", name="ABS box")
        d.multi_board = MultiBoardProject(
            name="system",
            boards={"main": "main"},
        )

        assert d.supply_chain["R1"].mpn == "RMCF0402FT10K0"
        assert len(d.manufacturing_records) == 1
        assert len(d.cable_harnesses) == 1
        assert d.enclosure is not None
        assert d.multi_board is not None

        # JSON round-trip
        data = d.model_dump_json()
        restored = Design.model_validate_json(data)
        assert restored.supply_chain["R1"].mpn == "RMCF0402FT10K0"
        assert len(restored.cable_harnesses) == 1
        assert restored.multi_board is not None
