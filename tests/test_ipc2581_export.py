"""Tests for IPC-2581 export, panelization, and fab capability DB."""

from __future__ import annotations

import socket
import xml.etree.ElementTree as ET

import pytest

from zaptrace.core.models import (
    BoardDefinition,
    Component,
    Design,
    DesignMeta,
    LayerSpec,
    Net,
    NetNode,
    RouteResult,
    TraceSegment,
)
from zaptrace.export.capabilities import (
    ExportBackend,
    ExportFormat,
    ExportSupport,
    get_export_capability,
)
from zaptrace.export.ipc2581 import (
    _NS,
    _SCHEMA_LOCATION,
    FabCapabilityDb,
    PanelLayout,
    compute_panel,
    export_ipc2581,
)

# ---------------------------------------------------------------------------
#  IPC-2581 export tests
# ---------------------------------------------------------------------------


def _make_design_for_ipc() -> Design:
    design = Design(meta=DesignMeta(name="ipc_test"))
    design.board_def = BoardDefinition(
        outline=[(0, 0), (100, 0), (100, 80), (0, 80)],
        layer_stack=[
            LayerSpec(name="F.Cu", type="signal"),
            LayerSpec(name="B.Cu", type="signal"),
        ],
    )
    design.components["R1"] = Component(
        id="R1",
        ref="R1",
        type="resistor",
        value="10k",
        footprint="0805",
        mpn="RC0805FR-0710KL",
        manufacturer="Yageo",
    )
    design.components["C1"] = Component(id="C1", ref="C1", type="capacitor", value="100nF", footprint="0805")
    design.nets["VCC"] = Net(
        id="VCC",
        name="VCC_3V3",
        nodes=[NetNode(component_ref="R1", pin_name="1"), NetNode(component_ref="C1", pin_name="1")],
    )
    design.nets["GND"] = Net(
        id="GND",
        name="GND",
        nodes=[NetNode(component_ref="R1", pin_name="2"), NetNode(component_ref="C1", pin_name="2")],
    )
    design.placement = {"R1": (10.0, 20.0), "C1": (30.0, 40.0)}
    design.routing = RouteResult(
        traces=[
            TraceSegment(layer="F.Cu", start=(10.0, 20.0), end=(30.0, 40.0), width=0.25, net_id="VCC"),
            TraceSegment(layer="B.Cu", start=(10.0, 20.0), end=(30.0, 40.0), width=0.3, net_id="GND"),
        ],
        vias=[(20.0, 30.0, 0.6, 0.3)],
        layers_used=["F.Cu", "B.Cu"],
        net_count=2,
        routed_net_count=2,
    )
    return design


class TestIpc2581Export:
    def test_exports_valid_xml(self) -> None:
        design = _make_design_for_ipc()
        xml = export_ipc2581(design)
        assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
        root = ET.fromstring(xml)
        assert root.tag.endswith("IPC-2581")
        assert root.get("schemaVersion") is not None

    def test_xml_namespace_identifiers_are_canonical_and_do_not_trigger_network_access(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_network(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("IPC-2581 export must not perform network access")

        monkeypatch.setattr(socket, "create_connection", fail_network)

        xml = export_ipc2581(_make_design_for_ipc())

        actual_schema_location = _SCHEMA_LOCATION
        expected_schema_location = f"{_NS} IPC-2581_D.xsd"
        assert _NS == "http://www.ipc2581.com/schema/IPC2581D"
        assert actual_schema_location == expected_schema_location
        assert _NS in xml
        assert _SCHEMA_LOCATION in xml

    def test_header_present(self) -> None:
        design = _make_design_for_ipc()
        root = ET.fromstring(export_ipc2581(design))
        ns = {"ipc": "http://www.ipc2581.com/schema/IPC2581D"}
        headers = root.findall("ipc:Header/ipc:projectName", ns)
        assert any(h.text == "ipc_test" for h in headers)

    def test_stackup_has_layers(self) -> None:
        design = _make_design_for_ipc()
        root = ET.fromstring(export_ipc2581(design))
        ns = {"ipc": "http://www.ipc2581.com/schema/IPC2581D"}
        layers = root.findall(".//ipc:Stackup/ipc:Layer", ns)
        assert len(layers) >= 2

    def test_stackup_layer_sides(self) -> None:
        design = _make_design_for_ipc()
        assert design.board_def is not None
        design.board_def.layer_stack.insert(1, LayerSpec(name="In1.Cu", type="signal"))
        root = ET.fromstring(export_ipc2581(design))
        ns = {"ipc": "http://www.ipc2581.com/schema/IPC2581D"}
        layers = root.findall(".//ipc:Stackup/ipc:Layer", ns)
        assert [layer.get("side") for layer in layers] == ["Top", "Inner", "Bottom"]

    def test_component_library(self) -> None:
        design = _make_design_for_ipc()
        root = ET.fromstring(export_ipc2581(design))
        ns = {"ipc": "http://www.ipc2581.com/schema/IPC2581D"}
        comps = root.findall(".//ipc:ComponentLibrary/ipc:Component", ns)
        assert len(comps) >= 2
        names = [c.get("name") for c in comps]
        assert "R1" in names
        assert "C1" in names

    def test_netlist(self) -> None:
        design = _make_design_for_ipc()
        root = ET.fromstring(export_ipc2581(design))
        ns = {"ipc": "http://www.ipc2581.com/schema/IPC2581D"}
        nets = root.findall(".//ipc:Netlist/ipc:Net", ns)
        assert len(nets) >= 2
        net_names = [n.get("name") for n in nets]
        assert "VCC_3V3" in net_names
        assert "GND" in net_names

    def test_placement(self) -> None:
        design = _make_design_for_ipc()
        root = ET.fromstring(export_ipc2581(design))
        ns = {"ipc": "http://www.ipc2581.com/schema/IPC2581D"}
        places = root.findall(".//ipc:Placement/ipc:Place", ns)
        assert len(places) >= 2
        refs = [p.get("refDes") for p in places]
        assert "R1" in refs
        assert "C1" in refs

    def test_routing_includes_wires_and_vias(self) -> None:
        design = _make_design_for_ipc()
        root = ET.fromstring(export_ipc2581(design))
        ns = {"ipc": "http://www.ipc2581.com/schema/IPC2581D"}
        wires = root.findall(".//ipc:Routing/ipc:Wire", ns)
        vias = root.findall(".//ipc:Routing/ipc:Via", ns)
        assert len(wires) >= 2
        assert len(vias) >= 1

    def test_panel_embedded(self) -> None:
        design = _make_design_for_ipc()
        panel = compute_panel(100.0, 80.0, cols=2, rows=2)
        xml = export_ipc2581(design, panel=panel)
        root = ET.fromstring(xml)
        ns = {"ipc": "http://www.ipc2581.com/schema/IPC2581D"}
        arrays = root.findall(".//ipc:Panel/ipc:BoardArray", ns)
        assert len(arrays) == 4  # 2x2 panel

    def test_ipc2581_capability_now_supported(self) -> None:
        """IPC-2581 via ZapTrace backend should now be SUPPORTED."""
        cap = get_export_capability("ipc2581", "zaptrace")
        assert cap is not None
        assert cap.support == ExportSupport.SUPPORTED
        assert cap.format == ExportFormat.IPC2581
        assert cap.backend == ExportBackend.ZAPTRACE


# ---------------------------------------------------------------------------
#  Panelization tests
# ---------------------------------------------------------------------------


class TestPanelization:
    def test_compute_panel_single(self) -> None:
        panel = compute_panel(100.0, 80.0, cols=1, rows=1)
        assert panel.panel_count == 1
        assert panel.total_width_mm == 100.0 + 2 * 5.0  # + tooling rails
        assert panel.total_height_mm == 80.0 + 2 * 5.0

    def test_compute_panel_2x2(self) -> None:
        panel = compute_panel(50.0, 40.0, cols=2, rows=2, spacing_mm=2.0)
        assert panel.panel_count == 4
        expected_w = 2 * 50.0 + 1 * 2.0 + 2 * 5.0
        expected_h = 2 * 40.0 + 1 * 2.0 + 2 * 5.0
        assert panel.total_width_mm == expected_w
        assert panel.total_height_mm == expected_h

    def test_compute_panel_invalid(self) -> None:

        with pytest.raises(ValueError, match="cols and rows"):
            compute_panel(100.0, 80.0, cols=0, rows=1)

    def test_panel_layout_dataclass(self) -> None:
        pl = PanelLayout(cols=2, rows=3, spacing_mm=2.0, panel_count=6)
        assert pl.cols == 2
        assert pl.rows == 3
        assert pl.panel_count == 6


# ---------------------------------------------------------------------------
#  Fab capability DB tests
# ---------------------------------------------------------------------------


class TestFabCapabilityDb:
    def test_db_has_builtin_profiles(self) -> None:
        db = FabCapabilityDb()
        names = db.profile_names
        assert len(names) >= 1
        assert "jlcpcb-2layer" in names

    def test_get_known_profile(self) -> None:
        db = FabCapabilityDb()
        profile = db.get_profile("jlcpcb-2layer")
        assert profile.manufacturer == "JLCPCB"
        assert profile.min_trace_mm > 0

    def test_get_unknown_profile_raises(self) -> None:

        db = FabCapabilityDb()
        with pytest.raises(ValueError, match="Unknown fab profile"):
            db.get_profile("nonexistent-fab")

    def test_find_profiles_for_design(self) -> None:
        db = FabCapabilityDb()
        candidates = db.find_profiles_for_design(
            None,  # type: ignore
            min_layers=2,
            max_trace_mm=0.15,
            max_board_dim_mm=100.0,
        )
        assert len(candidates) >= 1
        # At least one should be compatible
        compatible = [c for c in candidates if c["compatible"]]
        assert len(compatible) >= 1, f"No compatible profiles: {candidates}"

    def test_find_profiles_with_constraints(self) -> None:
        db = FabCapabilityDb()
        candidates = db.find_profiles_for_design(
            None,  # type: ignore
            min_layers=4,
            max_trace_mm=0.1,
            max_board_dim_mm=300.0,  # within jlcpcb-4layer limits (400x500)
        )
        # 4-layer requirement should filter out 2-layer profiles
        four_layer_candidates = [c for c in candidates if c["compatible"]]
        # At minimum jlcpcb-4layer should work
        names = [c["name"] for c in four_layer_candidates]
        assert "jlcpcb-4layer" in names, f"4-layer profiles not available: {names}"

    def test_diff_profiles(self) -> None:
        db = FabCapabilityDb()
        diff = db.diff_profiles("jlcpcb-2layer", "jlcpcb-4layer")
        assert diff["profile_a"] == "jlcpcb-2layer"
        assert diff["profile_b"] == "jlcpcb-4layer"
        assert "common" in diff
        assert "only_a" in diff
        assert "only_b" in diff

    def test_diff_identical_profiles(self) -> None:
        db = FabCapabilityDb()
        diff = db.diff_profiles("jlcpcb-2layer", "jlcpcb-2layer")
        assert len(diff["only_a"]) == 0
        assert len(diff["only_b"]) == 0
        assert len(diff["common"]) > 0
