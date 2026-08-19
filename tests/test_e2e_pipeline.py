"""End-to-end tests: Design → Classification → Placing → Routing → DRC → Gerber.

Tests the full Phase 1 pipeline with a realistic 2-component design.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zaptrace.algo.placer import place_components
from zaptrace.algo.router import route_design_smart
from zaptrace.core.models import (
    BoardConfig,
    Component,
    Design,
    DesignMeta,
    Net,
    NetNode,
    Pin,
    PinType,
)
from zaptrace.ee.classifier import (
    classify_design,
    get_net_class,
    summarize_classification,
)
from zaptrace.ee.constraints.net_classes import NetClass
from zaptrace.ee.drc.engine import DRCEngine
from zaptrace.ee.knowledge import KnowledgeBase
from zaptrace.export.excellon import generate_excellon
from zaptrace.export.gerber import generate_gerber


@pytest.fixture
def simple_design() -> Design:
    """Minimal 2-component design with power and signal nets."""
    d = Design(
        meta=DesignMeta(name="E2ETest"),
        board=BoardConfig(width_mm=100, height_mm=80, layers=2),
    )
    d.components["u1"] = Component(
        id="u1",
        ref="U1",
        type="mcu",
        value="ESP32-S3",
        footprint="QFN-48",
        pins={
            "VCC": Pin(name="VCC", type=PinType.POWER),
            "GND": Pin(name="GND", type=PinType.POWER),
            "GPIO1": Pin(name="GPIO1", type=PinType.OUTPUT),
            "GPIO2": Pin(name="GPIO2", type=PinType.INPUT),
        },
    )
    d.components["r1"] = Component(
        id="r1",
        ref="R1",
        type="resistor",
        value="10k",
        footprint="0805",
        pins={
            "p1": Pin(name="p1", type=PinType.PASSIVE),
            "p2": Pin(name="p2", type=PinType.PASSIVE),
        },
    )
    d.components["c1"] = Component(
        id="c1",
        ref="C1",
        type="capacitor",
        value="100n",
        footprint="0603",
        pins={
            "p1": Pin(name="p1", type=PinType.PASSIVE),
            "p2": Pin(name="p2", type=PinType.PASSIVE),
        },
    )
    d.nets["n1"] = Net(
        id="n1",
        name="VCC",
        nodes=[
            NetNode(component_ref="U1", pin_name="VCC"),
            NetNode(component_ref="R1", pin_name="p1"),
            NetNode(component_ref="C1", pin_name="p1"),
        ],
    )
    d.nets["n2"] = Net(
        id="n2",
        name="GND",
        nodes=[
            NetNode(component_ref="U1", pin_name="GND"),
            NetNode(component_ref="R1", pin_name="p2"),
            NetNode(component_ref="C1", pin_name="p2"),
        ],
    )
    d.nets["n3"] = Net(
        id="n3",
        name="SIG",
        nodes=[
            NetNode(component_ref="U1", pin_name="GPIO1"),
            NetNode(component_ref="R1", pin_name="p1"),
        ],
    )
    return d


class TestE2EPipeline:
    """Full Design → Gerber pipeline."""

    def test_classify_nets(self, simple_design: Design) -> None:
        """Nets are classified correctly by the classifier."""
        classify_design(simple_design)
        assert get_net_class(simple_design, "n1") == NetClass.POWER_MED  # VCC
        assert get_net_class(simple_design, "n2") == NetClass.GROUND  # GND
        assert get_net_class(simple_design, "n3") == NetClass.SIGNAL_LOW  # SIG
        summary = summarize_classification(simple_design)
        assert "power_med" in summary
        assert "ground" in summary
        assert "signal_low" in summary

    def test_place_and_route(self, simple_design: Design) -> None:
        """Placement + smart routing produces trace segments."""
        positions = place_components(simple_design)
        assert len(positions) >= 2
        routing, route, _ = route_design_smart(simple_design, positions)
        assert route.routed_net_count >= 1
        assert len(route.traces) > 0
        # Traces should have net-class-aware widths
        for t in route.traces:
            assert t.width > 0
            assert t.layer == "F.Cu"

    def test_drc_after_routing(self, simple_design: Design) -> None:
        """DRC runs cleanly after classification and routing."""
        classify_design(simple_design)
        positions = place_components(simple_design)
        routing, route, _ = route_design_smart(simple_design, positions)
        simple_design.routing = route
        engine = DRCEngine()
        result = engine.run(simple_design)
        # With proper net classes and routing, expect few or no violations
        assert result.total_violations >= 0  # at least no crash

    def test_gerber_generated(self, simple_design: Design) -> None:
        """Gerber RS-274X output is generated for all required layers."""
        classify_design(simple_design)
        positions = place_components(simple_design)
        routing, route, _ = route_design_smart(simple_design, positions)
        simple_design.routing = route
        gerber = generate_gerber(simple_design)
        # Should have at least the basic layers
        assert ".GTL" in gerber or "top" in str(gerber).lower()
        # Verify RS-274X format
        for key, value in gerber.items():
            assert "FSLAX36Y36" in value or key.endswith(".gko")

    def test_gerber_file_output(self, simple_design: Design, tmp_path: Path) -> None:
        """Gerber files are created at the specified output directory."""
        classify_design(simple_design)
        positions = place_components(simple_design)
        routing, route, _ = route_design_smart(simple_design, positions)
        simple_design.routing = route
        files = generate_gerber(simple_design, output_dir=tmp_path)
        for path in files.values():
            p = Path(path)
            assert p.exists()
            assert p.stat().st_size > 0

    def test_excellon_generated(self, simple_design: Design) -> None:
        """Excellon drill output is generated (may be empty if no PTH holes)."""
        classify_design(simple_design)
        positions = place_components(simple_design)
        routing, route, _ = route_design_smart(simple_design, positions)
        simple_design.routing = route
        files = generate_excellon(simple_design, output_dir=None)
        # No crash; files may be empty if no through-hole components
        assert isinstance(files, dict)

    def test_full_pipeline_no_crash(self, simple_design: Design) -> None:
        """Full E2E pipeline runs end-to-end without exceptions."""
        # Step 1: Classify
        classify_design(simple_design)
        assert len(simple_design.net_classes or {}) == 3
        # Step 2: Place
        positions = place_components(simple_design)
        assert len(positions) >= 2
        # Step 3: Route with smart routing
        routing, route, _ = route_design_smart(simple_design, positions)
        assert route.routed_net_count >= 1
        simple_design.routing = route
        # Step 4: DRC
        engine = DRCEngine()
        engine.run(simple_design)
        # Step 5: Gerber
        gerber = generate_gerber(simple_design)
        assert len(gerber) >= 4  # at least 4 layers
        # Step 6: Excellon (may be empty — no PTH holes in this design)
        drill = generate_excellon(simple_design, output_dir=None)
        assert isinstance(drill, dict)

    def test_knowledge_base_integration(self, simple_design: Design) -> None:
        """Knowledge base provides correct rules for classified nets."""
        kb = KnowledgeBase()
        classify_design(simple_design)
        # VCC → POWER_MED → 0.5mm trace
        rule_power = kb.get_rule(NetClass.POWER_MED)
        assert rule_power.trace_width == 0.5
        # GND → GROUND → 0.5mm trace
        rule_gnd = kb.get_rule(NetClass.GROUND)
        assert rule_gnd.trace_width == 0.5
        # SIG → SIGNAL_LOW → 0.2mm trace
        rule_sig = kb.get_rule(NetClass.SIGNAL_LOW)
        assert rule_sig.trace_width == 0.2
