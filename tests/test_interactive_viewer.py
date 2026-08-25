"""Tests for the interactive PCB viewer bundle generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zaptrace.core.models import (
    BoardConfig,
    Component,
    Design,
    DesignMeta,
    DRCResult,
    DRCViolation,
    Net,
    NetNode,
    Pin,
    PinType,
    RouteResult,
    TraceSegment,
)
from zaptrace.viewer.interactive import (
    InteractiveViewerBundle,
    _extract_viewer_data,
    generate_interactive_viewer,
)
from zaptrace.viewer.static import (
    ViewerBundle,
    generate_static_viewer,
)


@pytest.fixture
def simple_design() -> Design:
    """Minimal design with two components, one net, one trace, and one DRC violation."""
    return Design(
        meta=DesignMeta(name="test-viewer-design", version="0.1.0"),
        components={
            "r1": Component(
                id="r1",
                ref="R1",
                type="resistor",
                value="10k",
                footprint="0402",
                pins={
                    "1": Pin(name="1", type=PinType.PASSIVE, net="net_vcc"),
                    "2": Pin(name="2", type=PinType.PASSIVE, net="net_gnd"),
                },
            ),
            "u1": Component(
                id="u1",
                ref="U1",
                type="ic",
                value="ESP32-C3",
                footprint="QFN-32",
                mpn="ESP32-C3-MINI-1",
                manufacturer="Espressif",
                pins={
                    "VCC": Pin(name="VCC", type=PinType.POWER, net="net_vcc"),
                    "GND": Pin(name="GND", type=PinType.POWER, net="net_gnd"),
                },
            ),
        },
        nets={
            "net_vcc": Net(
                id="net_vcc",
                name="VCC_3V3",
                nodes=[
                    NetNode(component_ref="R1", pin_name="1"),
                    NetNode(component_ref="U1", pin_name="VCC"),
                ],
            ),
            "net_gnd": Net(
                id="net_gnd",
                name="GND",
                nodes=[
                    NetNode(component_ref="R1", pin_name="2"),
                    NetNode(component_ref="U1", pin_name="GND"),
                ],
            ),
        },
        board=BoardConfig(width_mm=50, height_mm=40, layers=2),
        placement={"r1": (10.0, 15.0), "u1": (30.0, 20.0)},
        routing=RouteResult(
            traces=[
                TraceSegment(
                    layer="F.Cu",
                    start=(10.0, 15.0),
                    end=(30.0, 20.0),
                    width=0.2,
                    net_id="net_vcc",
                ),
            ],
            vias=[(20.0, 17.0, 0.45, 0.2, "net_vcc")],
            layers_used=["F.Cu"],
            total_trace_length_mm=22.36,
            net_count=2,
            routed_net_count=1,
        ),
        drc_result=DRCResult(
            design_name="test-viewer-design",
            total_violations=1,
            errors=0,
            warnings=1,
            info=0,
            violations=[
                DRCViolation(
                    rule_id="DRC001",
                    severity="warning",
                    message="Trace too close to board edge",
                    location="(5.0, 3.0)",
                    net_id="net_vcc",
                ),
            ],
            passed=True,
        ),
    )


class TestViewerDataExtraction:
    """Test _extract_viewer_data correctness."""

    def test_extracts_components(self, simple_design: Design) -> None:
        data = _extract_viewer_data(simple_design)
        assert len(data.components) == 2
        refs = {c.ref for c in data.components}
        assert refs == {"R1", "U1"}

    def test_extracts_nets(self, simple_design: Design) -> None:
        data = _extract_viewer_data(simple_design)
        assert len(data.nets) == 2
        names = {n.name for n in data.nets}
        assert names == {"VCC_3V3", "GND"}

    def test_extracts_traces(self, simple_design: Design) -> None:
        data = _extract_viewer_data(simple_design)
        assert len(data.traces) == 1
        assert data.traces[0].net_id == "net_vcc"
        assert data.traces[0].layer == "F.Cu"

    def test_extracts_vias(self, simple_design: Design) -> None:
        data = _extract_viewer_data(simple_design)
        assert len(data.vias) == 1
        assert data.vias[0].x == 20.0
        assert data.vias[0].net_id == "net_vcc"

    def test_extracts_violations(self, simple_design: Design) -> None:
        data = _extract_viewer_data(simple_design)
        assert len(data.violations) == 1
        assert data.violations[0].rule_id == "DRC001"
        assert data.violations[0].x == 5.0
        assert data.violations[0].y == 3.0

    def test_component_positions_from_placement(self, simple_design: Design) -> None:
        data = _extract_viewer_data(simple_design)
        r1 = next(c for c in data.components if c.ref == "R1")
        assert r1.x == 10.0
        assert r1.y == 15.0

    def test_component_pins_serialized(self, simple_design: Design) -> None:
        data = _extract_viewer_data(simple_design)
        u1 = next(c for c in data.components if c.ref == "U1")
        assert len(u1.pins) == 2
        pin_names = {p["name"] for p in u1.pins}
        assert "VCC" in pin_names

    def test_board_dimensions(self, simple_design: Design) -> None:
        data = _extract_viewer_data(simple_design)
        assert data.board.width_mm == 50.0
        assert data.board.height_mm == 40.0
        assert data.board.layers == 2

    def test_non_claims_present(self, simple_design: Design) -> None:
        data = _extract_viewer_data(simple_design)
        assert len(data.non_claims) >= 1
        assert any("human review" in nc for nc in data.non_claims)

    def test_schema_version(self, simple_design: Design) -> None:
        data = _extract_viewer_data(simple_design)
        assert data.schema_version == "2.0"
        assert data.viewer == "zaptrace-interactive-viewer"


class TestViewerDataSerialization:
    """Test JSON serialization round-trip."""

    def test_serializes_to_json(self, simple_design: Design) -> None:
        data = _extract_viewer_data(simple_design)
        dumped = data.model_dump(mode="json")
        json_str = json.dumps(dumped)
        parsed = json.loads(json_str)
        assert parsed["design_name"] == "test-viewer-design"
        assert len(parsed["components"]) == 2

    def test_viewer_data_fields_complete(self, simple_design: Design) -> None:
        data = _extract_viewer_data(simple_design)
        dumped = data.model_dump(mode="json")
        required_keys = {
            "schema_version",
            "viewer",
            "design_name",
            "board",
            "components",
            "nets",
            "traces",
            "vias",
            "violations",
            "bom",
            "non_claims",
        }
        assert required_keys.issubset(set(dumped.keys()))


class TestInteractiveViewerGeneration:
    """Test generate_interactive_viewer produces valid HTML bundle."""

    def test_generates_index_html(self, simple_design: Design, tmp_path: Path) -> None:
        result = generate_interactive_viewer(simple_design, tmp_path)
        assert isinstance(result, InteractiveViewerBundle)
        index = Path(result.index_path)
        assert index.exists()
        assert index.name == "index.html"

    def test_generates_data_json(self, simple_design: Design, tmp_path: Path) -> None:
        result = generate_interactive_viewer(simple_design, tmp_path)
        data_path = Path(result.data_path)
        assert data_path.exists()
        data = json.loads(data_path.read_text(encoding="utf-8"))
        assert data["design_name"] == "test-viewer-design"

    def test_html_contains_design_name(self, simple_design: Design, tmp_path: Path) -> None:
        result = generate_interactive_viewer(simple_design, tmp_path)
        html_content = Path(result.index_path).read_text(encoding="utf-8")
        assert "test-viewer-design" in html_content

    def test_html_contains_interactive_elements(self, simple_design: Design, tmp_path: Path) -> None:
        result = generate_interactive_viewer(simple_design, tmp_path)
        html_content = Path(result.index_path).read_text(encoding="utf-8")
        # Key interactive UI elements
        assert "searchInput" in html_content
        assert "btnMeasure" in html_content
        assert "btnBom" in html_content
        assert "btnTheme" in html_content
        assert "layerSection" in html_content
        assert "infoPanel" in html_content
        assert "statusBar" in html_content

    def test_html_contains_viewer_data(self, simple_design: Design, tmp_path: Path) -> None:
        result = generate_interactive_viewer(simple_design, tmp_path)
        html_content = Path(result.index_path).read_text(encoding="utf-8")
        # Data is embedded as JSON
        assert '"schema_version":"2.0"' in html_content
        assert '"zaptrace-interactive-viewer"' in html_content

    def test_non_claims_propagated(self, simple_design: Design, tmp_path: Path) -> None:
        result = generate_interactive_viewer(simple_design, tmp_path)
        assert len(result.non_claims) >= 1

    def test_html_is_valid_document(self, simple_design: Design, tmp_path: Path) -> None:
        result = generate_interactive_viewer(simple_design, tmp_path)
        html_content = Path(result.index_path).read_text(encoding="utf-8")
        assert html_content.startswith("<!doctype html>")
        assert "</html>" in html_content
        assert "<script>" in html_content
        assert "</script>" in html_content


class TestStaticViewer:
    """Test static review viewer bundle generation."""

    def test_generate_static_bundle(self, simple_design: Design, tmp_path: Path) -> None:
        bundle = generate_static_viewer(simple_design, output_dir=tmp_path / "static_viewer")
        assert isinstance(bundle, ViewerBundle)
        assert Path(bundle.index_path).exists()
        assert Path(bundle.assets["schematic"]).exists()
        assert Path(bundle.assets["pcb_top"]).exists()
        assert Path(bundle.assets["pcb_bottom"]).exists()
        assert Path(bundle.data["bom"]).exists()
        assert Path(bundle.data["manifest"]).exists()
        assert len(bundle.non_claims) >= 1

        index_content = Path(bundle.index_path).read_text(encoding="utf-8")
        assert "ZapTrace Review Viewer" in index_content
        assert "test-viewer-design" in index_content
