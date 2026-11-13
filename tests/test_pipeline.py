"""Tests for pipeline autopilot."""

from __future__ import annotations

from pathlib import Path

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode, NetType
from zaptrace.pipeline.autopilot import Autopilot, PipelineContext, PipelineStage


def _design() -> Design:
    return Design(
        meta=DesignMeta(name="TestDesign", author="tester"),
        components={
            "c1": Component(id="c1", ref="R1", type="resistor", value="10k"),
            "c2": Component(id="c2", ref="C1", type="capacitor", value="100n"),
            "c3": Component(id="c3", ref="U1", type="mcu"),
        },
        nets={
            "n1": Net(
                id="n1",
                name="VCC",
                nodes=[
                    NetNode(component_ref="R1", pin_name="p1"),
                    NetNode(component_ref="C1", pin_name="p1"),
                ],
            ),
        },
    )


class TestAutopilot:
    def test_init(self) -> None:
        ap = Autopilot()
        assert ap is not None

    def test_run_from_design(self) -> None:
        ap = Autopilot()
        ctx = ap.run_from_design(_design())
        assert isinstance(ctx, PipelineContext)
        assert ctx.design is not None
        assert len(ctx.results) > 0

    def test_run_single_stage_validate(self) -> None:
        ap = Autopilot()
        ctx = PipelineContext(design=_design())
        ctx = ap.run_stage(ctx, PipelineStage.VALIDATE)
        assert ctx.erc_result is not None

    def test_run_single_stage_bom(self) -> None:
        ap = Autopilot()
        ctx = PipelineContext(design=_design())
        ctx = ap.run_stage(ctx, PipelineStage.BOM)
        assert ctx.bom_csv is not None
        assert ctx.bom_json is not None

    def test_run_single_stage_place(self) -> None:
        ap = Autopilot()
        ctx = PipelineContext(design=_design())
        ctx = ap.run_stage(ctx, PipelineStage.PLACE)
        assert ctx.positions is not None
        assert len(ctx.positions) == 3

    def test_run_single_stage_report(self, tmp_path: Path) -> None:
        ap = Autopilot(output_dir=str(tmp_path))
        ctx = PipelineContext(design=_design(), output_dir=tmp_path)
        ctx = ap.run_stage(ctx, PipelineStage.REPORT)
        assert ctx.report is not None
        assert "TestDesign" in ctx.report

    def test_run_single_stage_svg(self, tmp_path: Path) -> None:
        ap = Autopilot(output_dir=str(tmp_path))
        ctx = PipelineContext(design=_design(), output_dir=tmp_path)
        ctx = ap.run_stage(ctx, PipelineStage.SVG)
        assert ctx.svg is not None
        assert ctx.svg.startswith("<svg")

    def test_run_single_stage_kicad(self, tmp_path: Path) -> None:
        ap = Autopilot(output_dir=str(tmp_path))
        ctx = PipelineContext(design=_design(), output_dir=tmp_path)
        ctx = ap.run_stage(ctx, PipelineStage.KICAD)
        assert ctx.kicad_files is not None

    def test_stages_ordered(self) -> None:
        ordered = PipelineStage.ordered()
        assert len(ordered) == 10
        assert ordered[0] == PipelineStage.PARSE
        assert ordered[-1] == PipelineStage.PATCH

    def test_run_stages_subset(self) -> None:
        ap = Autopilot()
        ctx = PipelineContext(design=_design())
        ctx = ap.run_stages(ctx, [PipelineStage.VALIDATE, PipelineStage.BOM])
        assert ctx.erc_result is not None
        assert ctx.bom_csv is not None

    def test_pipeline_context_all_successful(self) -> None:
        ap = Autopilot()
        ctx = ap.run_from_design(_design())
        assert ctx.all_successful

    def test_pipeline_context_duration(self) -> None:
        ap = Autopilot()
        ctx = ap.run_from_design(_design())
        assert ctx.duration > 0.0


def test_place_stage_writes_design_placement() -> None:
    design = _design()
    ctx = Autopilot().run_stage(PipelineContext(design=design), PipelineStage.PLACE)
    assert ctx.positions is not None
    assert design.placement == ctx.positions


def test_route_stage_writes_design_routing() -> None:
    design = _design()
    ctx = PipelineContext(design=design)
    ap = Autopilot()
    ap.run_stage(ctx, PipelineStage.PLACE)
    ap.run_stage(ctx, PipelineStage.ROUTE)
    assert ctx.routing is not None
    assert design.routing is not None
    assert design.routing.traces
    assert {trace.net_id for trace in design.routing.traces} <= set(design.nets)
    assert ctx.routing.unrouted_nets == [
        net.id for net in design.nets.values() if net.id not in {trace.net_id for trace in design.routing.traces}
    ]


def test_route_stage_falls_back_when_grid_router_routes_nothing() -> None:
    # The A* grid router skips GROUND nets (left for copper pour), so a
    # ground-only design makes it route nothing — exercising the fallback to
    # the MST router so the pipeline still produces traces.
    design = Design(
        meta=DesignMeta(name="FallbackTest"),
        components={
            "c1": Component(id="c1", ref="R1", type="resistor", value="10k"),
            "c2": Component(id="c2", ref="C1", type="capacitor", value="100n"),
        },
        nets={
            "n1": Net(
                id="n1",
                name="GND",
                type=NetType.GROUND,
                nodes=[
                    NetNode(component_ref="R1", pin_name="p1"),
                    NetNode(component_ref="C1", pin_name="p1"),
                ],
            ),
        },
    )
    ctx = PipelineContext(design=design)
    ap = Autopilot()
    ap.run_stage(ctx, PipelineStage.PLACE)
    ap.run_stage(ctx, PipelineStage.ROUTE)
    assert ctx.routing is not None
    assert design.routing is not None
    assert design.routing.traces  # fallback router produced traces


def test_physical_demo_keeps_source_bound_safe_partial_copper(tmp_path: Path) -> None:
    from zaptrace.core.parser import parse_file

    demo = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"
    design = parse_file(demo)
    pilot = Autopilot(output_dir=tmp_path)
    ctx = PipelineContext(design=design, output_dir=tmp_path)
    pilot.run_stage(ctx, PipelineStage.PLACE)
    pilot.run_stage(ctx, PipelineStage.ROUTE)
    assert ctx.routing is not None
    assert ctx.routing.routed_nets == 4
    assert ctx.routing.total_nets > 0
    # USB-C CC1/CC2 and both I2C nets now have native-verifiable
    # physical copper. Power and GND remain unconnected.
    assert set(ctx.routing.unrouted_nets) == {
        "VCC_5V",
        "VCC_3V3",
        "GND",
    }
    assert len(ctx.routing.unrouted_nets) == 3
    assert ctx.routing.total_nets == 7
    assert design.routing is not None
    assert {trace.net_id for trace in design.routing.traces} == {"USB_CC1", "USB_CC2", "I2C_SDA", "I2C_SCL"}
    assert not design.routing.vias
    assert ctx.positions == design.placement
    # Reject the legacy source ground flood pending genuine RF keepout review.
    assert not design.copper_pours
    pilot.run_stage(ctx, PipelineStage.KICAD)
    assert ctx.kicad_files is not None
    pcb = ctx.kicad_files["pcb"].read_text(encoding="utf-8")
    assert "(footprint " in pcb
    assert "  (segment" in pcb


def test_pipeline_kicad_export_contains_routed_segments(tmp_path: Path) -> None:
    design = _design()
    ap = Autopilot(output_dir=tmp_path)
    ctx = PipelineContext(design=design, output_dir=tmp_path)
    for stage in [PipelineStage.PLACE, PipelineStage.ROUTE, PipelineStage.KICAD]:
        ap.run_stage(ctx, stage)
    assert ctx.kicad_files is not None
    pcb = ctx.kicad_files["pcb"]
    assert pcb.exists()
    assert "(segment" in pcb.read_text(encoding="utf-8")


def test_partial_copper_native_kicad_does_not_increase_physical_drc(tmp_path: Path) -> None:
    """Independently check routed copper on exact generated KiCad 10 geometry.

    Native manufacture violations and open copper are reported, not hidden:
    this is a measured partial improvement, not a whole-board signoff.
    """
    import json
    import shutil
    import subprocess
    from collections import Counter

    import pytest

    from zaptrace.core.models import RouteResult
    from zaptrace.core.parser import parse_file
    from zaptrace.export.kicad import export_kicad

    if shutil.which("kicad-cli") is None:
        pytest.skip("Real KiCad 10 CLI required for physical route acceptance")
    design = parse_file(Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml")
    ctx = PipelineContext(design=design, output_dir=tmp_path)
    pilot = Autopilot(output_dir=tmp_path)
    pilot.run_stage(ctx, PipelineStage.PLACE)
    assert ctx.positions is not None
    original = design.model_copy(deep=True)
    original.placement = dict(ctx.positions)
    original.routing = RouteResult(net_count=7)
    original_files = export_kicad(original, tmp_path / "original")

    pilot.run_stage(ctx, PipelineStage.ROUTE)
    assert ctx.routing is not None
    assert ctx.routing.routed_nets == 4
    routed_files = export_kicad(design, tmp_path / "partially-routed")

    reports = []
    for label, files in (("original", original_files), ("partially-routed", routed_files)):
        pcb_report = tmp_path / f"{label}-drc.json"
        sch_report = tmp_path / f"{label}-erc.json"
        pcb = subprocess.run(
            [
                "kicad-cli",
                "pcb",
                "drc",
                "--exit-code-violations",
                "--severity-all",
                "--schematic-parity",
                "--format",
                "json",
                "--output",
                str(pcb_report),
                str(files["pcb"]),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        sch = subprocess.run(
            [
                "kicad-cli",
                "sch",
                "erc",
                "--exit-code-violations",
                "--severity-all",
                "--format",
                "json",
                "--output",
                str(sch_report),
                str(files["schematic"]),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        assert pcb.returncode == 5, pcb.stderr
        assert sch.returncode == 0, sch.stderr
        native = json.loads(pcb_report.read_text(encoding="utf-8"))
        erc = json.loads(sch_report.read_text(encoding="utf-8"))
        reports.append(native)
        assert sum(len(sheet.get("violations", [])) for sheet in erc.get("sheets", [])) == 0
    before, after = reports
    assert Counter(v["type"] for v in before["violations"]) == Counter({"drill_out_of_range": 12, "hole_clearance": 4})
    assert Counter(v["type"] for v in after["violations"]) == Counter(v["type"] for v in before["violations"])
    assert len(before["unconnected_items"]) == 37
    assert len(after["unconnected_items"]) == 29
    assert design.routing is not None
    assert {x.net_id for x in design.routing.traces} == {"USB_CC1", "USB_CC2", "I2C_SDA", "I2C_SCL"}
