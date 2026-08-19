"""Tests for export modules (BOM, report, SVG, KiCad)."""

from __future__ import annotations

from pathlib import Path

from zaptrace.core.models import (
    BoardConfig,
    BoardDefinition,
    Component,
    CopperPourArea,
    Design,
    DesignMeta,
    FootprintDef,
    MountingHole,
    Net,
    NetNode,
    Pad,
    PadShape,
    Pin,
    RouteResult,
    TraceSegment,
)
from zaptrace.erc.models import ERCResult, ERCSeverity, ERCViolation
from zaptrace.export.bom import generate_bom_csv, generate_bom_json
from zaptrace.export.gerber import generate_gerber, generate_gerber_job_file, validate_gerber_x2_attributes
from zaptrace.export.kicad import export_kicad_pcb, export_kicad_schematic
from zaptrace.export.report import generate_report
from zaptrace.export.svg import render_schematic_svg


def _design() -> Design:
    return Design(
        meta=DesignMeta(name="TestDesign", author="tester"),
        components={
            "c1": Component(id="c1", ref="R1", type="resistor", value="10k", footprint="0805"),
            "c2": Component(id="c2", ref="C1", type="capacitor", value="100n", footprint="0603"),
        },
        nets={
            "n1": Net(
                id="n1",
                name="VCC",
                nodes=[NetNode(component_ref="R1", pin_name="p1")],
            ),
        },
    )


class TestBOM:
    def test_bom_csv(self) -> None:
        csv = generate_bom_csv(_design())
        assert "R1" in csv
        assert "C1" in csv
        assert "10k" in csv
        assert csv.startswith("Ref")

    def test_bom_csv_empty(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        csv = generate_bom_csv(d)
        assert "Ref,Type,Value,Footprint,MPN,Manufacturer,Lifecycle,Datasheet" in csv

    def test_bom_json(self) -> None:
        import json

        result = generate_bom_json(_design())
        data = json.loads(result)
        assert data["design"] == "TestDesign"
        assert data["count"] == 2
        assert data["items"][0]["ref"] == "C1"

    def test_bom_basic_extended_labels(self) -> None:
        import json

        d = Design(
            meta=DesignMeta(name="labels"),
            components={
                "basic": Component(id="basic", ref="R1", type="resistor", basic_part=True),
                "extended": Component(id="extended", ref="R2", type="resistor", basic_part=False),
                "unknown": Component(id="unknown", ref="R3", type="resistor", basic_part=None),
            },
        )
        items = {item["ref"]: item for item in json.loads(generate_bom_json(d))["items"]}
        assert items["R1"]["basic_extended"] == "Basic"
        assert items["R2"]["basic_extended"] == "Extended"
        assert items["R3"]["basic_extended"] == ""

    def test_bom_json_empty(self) -> None:
        import json

        d = Design(meta=DesignMeta(name="empty"))
        result = json.loads(generate_bom_json(d))
        assert result["count"] == 0


class TestReport:
    def test_report_generated(self) -> None:
        report = generate_report(_design())
        assert "TestDesign" in report
        assert "R1" in report
        assert "VCC" in report

    def test_report_with_erc(self) -> None:
        erc = ERCResult(
            violations=[
                ERCViolation(rule_id="ERC001", severity=ERCSeverity.ERROR, message="Test violation"),
            ],
            design_name="TestDesign",
            total_errors=1,
            total_warnings=0,
            total_info=0,
        )
        report = generate_report(_design(), erc_result=erc)
        assert "ERC001" in report
        assert "FAIL" in report

    def test_report_without_erc(self) -> None:
        report = generate_report(_design())
        assert "ERC" not in report

    def test_report_renders_suggestion_and_coverage_gap_sections(self) -> None:
        erc = ERCResult(
            violations=[
                ERCViolation(
                    rule_id="ERC002",
                    severity=ERCSeverity.WARNING,
                    message="Review this net",
                    patch_suggestion="Add a pull-up",
                ),
            ],
            coverage_gaps=["Transient startup behavior"],
            design_name="TestDesign",
            total_errors=0,
            total_warnings=1,
            total_info=0,
        )

        report = generate_report(_design(), erc_result=erc)

        assert "- **W** `ERC002` Review this net" in report
        assert "  - Suggestion: Add a pull-up" in report
        assert "## ERC Coverage Gaps" in report
        assert "- Transient startup behavior" in report


class TestSvg:
    def test_svg_generated(self) -> None:
        svg = render_schematic_svg(_design())
        assert svg.startswith("<svg")
        assert "TestDesign" in svg
        assert "R1" in svg

    def test_svg_empty_design(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        svg = render_schematic_svg(d)
        assert "No components" in svg

    def test_svg_with_positions(self) -> None:
        design = _design()
        design.nets["n1"].nodes.append(NetNode(component_ref="C1", pin_name="p1"))
        positions = {"c1": (100.0, 100.0), "c2": (300.0, 200.0)}
        svg = render_schematic_svg(design, positions=positions)
        assert "100" in svg
        assert '<line class="net-line"' in svg


class TestKiCad:
    """Schematic export tests."""

    def test_export_creates_files(self, tmp_path: Path) -> None:
        files = export_kicad_schematic(_design(), tmp_path)
        assert "schematic" in files
        assert "project" in files
        assert files["schematic"].exists()
        assert files["project"].exists()

    def test_kicad_schematic_content(self, tmp_path: Path) -> None:
        files = export_kicad_schematic(_design(), tmp_path)
        content = files["schematic"].read_text(encoding="utf-8")
        assert "TestDesign" in content
        assert "R1" in content

    def test_kicad_project_content(self, tmp_path: Path) -> None:
        import json

        files = export_kicad_schematic(_design(), tmp_path)
        content = json.loads(files["project"].read_text(encoding="utf-8"))
        assert content["meta"]["version"] == 1

    def test_empty_design(self, tmp_path: Path) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        files = export_kicad_schematic(d, tmp_path)
        assert len(files) == 2

    # ------------------------------------------------------------------
    # PCB export (export_kicad_pcb)
    # ------------------------------------------------------------------

    def _pcb_design(self) -> Design:
        """Minimal design with routing data for PCB tests."""
        d = Design(
            meta=DesignMeta(name="PCBLayout"),
            board=BoardConfig(width_mm=50, height_mm=40, layers=4),
            components={
                "c1": Component(
                    id="c1",
                    ref="R1",
                    type="resistor",
                    value="10k",
                    position=(25.0, 30.0),
                    footprint_def=FootprintDef(
                        pads=[
                            Pad(id="1", position=(0, 0), size=(1.5, 1.5), drill=0.6),
                            Pad(id="2", position=(2, 0), size=(1.5, 1.5), drill=0.6),
                        ],
                    ),
                    pins={
                        "1": Pin(name="A", type="passive"),
                        "2": Pin(name="B", type="passive"),
                    },
                ),
            },
            nets={"n1": Net(id="n1", name="NET1")},
            routing=RouteResult(
                traces=[
                    TraceSegment(
                        start=(10.0, 10.0),
                        end=(20.0, 10.0),
                        layer="F.Cu",
                        width=0.25,
                        net_id="n1",
                    ),
                    TraceSegment(
                        start=(20.0, 10.0),
                        end=(25.0, 30.0),
                        layer="In1.Cu",
                        width=0.25,
                        net_id="n1",
                    ),
                ],
                vias=[(20.0, 10.0, 0.6, 0.3)],
            ),
            copper_pours={
                "p1": CopperPourArea(
                    id="p1",
                    net_id="n1",
                    polygon=[(5, 5), (15, 5), (15, 15), (5, 15)],
                    layer="F.Cu",
                ),
            },
        )
        return d

    def test_pcb_export_creates_file(self, tmp_path: Path) -> None:
        files = export_kicad_pcb(self._pcb_design(), tmp_path)
        assert "pcb" in files
        assert files["pcb"].exists()
        assert files["pcb"].suffix == ".kicad_pcb"

    def test_pcb_content_start(self, tmp_path: Path) -> None:
        files = export_kicad_pcb(self._pcb_design(), tmp_path)
        content = files["pcb"].read_text(encoding="utf-8")
        assert "(kicad_pcb" in content
        assert 'generator "zaptrace"' in content

    def test_pcb_layers_4layer(self, tmp_path: Path) -> None:
        files = export_kicad_pcb(self._pcb_design(), tmp_path)
        content = files["pcb"].read_text(encoding="utf-8")
        assert '(0 "F.Cu" signal)' in content
        assert '(4 "In1.Cu" signal)' in content
        assert '(6 "In2.Cu" signal)' in content
        assert '(2 "B.Cu" signal)' in content

    def test_pcb_layers_2layer_default(self, tmp_path: Path) -> None:
        d = Design(meta=DesignMeta(name="two"), board=BoardConfig(width_mm=10, height_mm=10, layers=2))
        files = export_kicad_pcb(d, tmp_path)
        content = files["pcb"].read_text(encoding="utf-8")
        assert '(0 "F.Cu" signal)' in content
        assert '(2 "B.Cu" signal)' in content

    def test_pcb_copper_pour_without_routing(self, tmp_path: Path) -> None:
        d = Design(
            meta=DesignMeta(name="pour-only"),
            nets={"gnd": Net(id="gnd", name="GND")},
            copper_pours={
                "gnd": CopperPourArea(
                    net_id="gnd",
                    polygon=[(1.0, 1.0), (9.0, 1.0), (9.0, 9.0), (1.0, 9.0)],
                )
            },
        )
        files = export_kicad_pcb(d, tmp_path)
        assert "(zone" in files["pcb"].read_text(encoding="utf-8")

    def test_pcb_board_outline(self, tmp_path: Path) -> None:
        files = export_kicad_pcb(self._pcb_design(), tmp_path)
        content = files["pcb"].read_text(encoding="utf-8")
        assert "gr_rect" in content
        assert "(start 0 0)" in content
        assert "(end 50.0 40.0)" in content
        assert '"Edge.Cuts"' in content

    def test_pcb_nets(self, tmp_path: Path) -> None:
        files = export_kicad_pcb(self._pcb_design(), tmp_path)
        content = files["pcb"].read_text(encoding="utf-8")
        assert '(net 1 "NET1")' in content

    def test_pcb_footprint_and_pads(self, tmp_path: Path) -> None:
        files = export_kicad_pcb(self._pcb_design(), tmp_path)
        content = files["pcb"].read_text(encoding="utf-8")
        assert 'footprint "zaptrace:resistor"' in content
        assert '"R1"' in content
        assert '"10k"' in content
        assert '(pad "1" thru_hole' in content
        assert '(pad "2" thru_hole' in content

    def test_pcb_segments(self, tmp_path: Path) -> None:
        files = export_kicad_pcb(self._pcb_design(), tmp_path)
        content = files["pcb"].read_text(encoding="utf-8")
        assert "(segment" in content
        assert "(start 10.0 10.0)" in content
        assert "(end 20.0 10.0)" in content
        assert '(layer "F.Cu")' in content
        assert '(layer "In1.Cu")' in content
        assert "(net 1)" in content

    def test_pcb_vias(self, tmp_path: Path) -> None:
        files = export_kicad_pcb(self._pcb_design(), tmp_path)
        content = files["pcb"].read_text(encoding="utf-8")
        assert "(via" in content
        assert "(at 20.0 10.0)" in content
        assert "(size 0.6)" in content
        assert "(drill 0.3)" in content

    def test_pcb_copper_pour(self, tmp_path: Path) -> None:
        files = export_kicad_pcb(self._pcb_design(), tmp_path)
        content = files["pcb"].read_text(encoding="utf-8")
        assert "(zone" in content
        assert "(net 1)" in content
        assert '(net_name "n1")' in content
        assert "polygon" in content
        assert "(xy 5.0 5.0)" in content
        assert "(xy 15.0 15.0)" in content

    def test_pcb_empty_design(self, tmp_path: Path) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        files = export_kicad_pcb(d, tmp_path)
        assert files["pcb"].exists()
        content = files["pcb"].read_text(encoding="utf-8")
        assert "(kicad_pcb" in content
        assert "(layers" in content  # should have default 2 layers

    def test_export_kicad_combined(self, tmp_path: Path) -> None:
        """export_kicad() returns both schematic and PCB files."""
        from zaptrace.export.kicad import export_kicad

        files = export_kicad(self._pcb_design(), tmp_path)
        assert "schematic" in files
        assert "project" in files
        assert "pcb" in files
        assert files["schematic"].exists()
        assert files["pcb"].exists()

    def test_pcb_segment_skips_unconnected_net(self, tmp_path: Path) -> None:
        """Segments for nets not in net_idx are skipped (net 0 = unconnected)."""
        d = Design(
            meta=DesignMeta(name="skip"),
            board=BoardConfig(width_mm=10, height_mm=10),
            routing=RouteResult(
                traces=[
                    TraceSegment(
                        start=(1.0, 1.0),
                        end=(2.0, 2.0),
                        layer="F.Cu",
                        width=0.25,
                        net_id="nonexistent",
                    ),
                ],
            ),
        )
        files = export_kicad_pcb(d, tmp_path)
        content = files["pcb"].read_text(encoding="utf-8")
        assert "(segment" not in content  # net 0 → skipped

    def test_layer_name_mapping(self, tmp_path: Path) -> None:
        """Verify _layer_name produces correct KiCad names."""
        from zaptrace.export.kicad import _layer_name

        assert _layer_name(0, 2) == "F.Cu"
        assert _layer_name(1, 2) == "B.Cu"
        assert _layer_name(0, 4) == "F.Cu"
        assert _layer_name(1, 4) == "In1.Cu"
        assert _layer_name(2, 4) == "In2.Cu"
        assert _layer_name(3, 4) == "B.Cu"

    def test_copper_layers(self, tmp_path: Path) -> None:
        """Verify _copper_layers returns correct list."""
        from zaptrace.export.kicad import _copper_layers

        assert _copper_layers(2) == ["F.Cu", "B.Cu"]
        assert _copper_layers(4) == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]

    def test_kicad_layer_name_mapping(self, tmp_path: Path) -> None:
        """Verify _kicad_layer_name handles all aliases."""
        from zaptrace.export.kicad import _kicad_layer_name

        assert _kicad_layer_name("F.Cu", 2) == "F.Cu"
        assert _kicad_layer_name("top", 2) == "F.Cu"
        assert _kicad_layer_name("layer_0", 2) == "F.Cu"
        assert _kicad_layer_name("B.Cu", 2) == "B.Cu"
        assert _kicad_layer_name("bottom", 2) == "B.Cu"
        assert _kicad_layer_name("layer_1", 2) == "B.Cu"
        assert _kicad_layer_name("layer_1", 4) == "In1.Cu"
        assert _kicad_layer_name("In2.Cu", 4) == "In2.Cu"

    def test_pcb_mounting_holes(self, tmp_path: Path) -> None:
        """Mounting holes are exported as NPTH footprints."""
        d = Design(
            meta=DesignMeta(name="mh_pcb"),
            board=BoardConfig(width_mm=10, height_mm=10),
            board_def=BoardDefinition(
                mounting_holes=[MountingHole(position=(5.0, 5.0), diameter=3.0, plated=True)],
            ),
        )
        files = export_kicad_pcb(d, tmp_path)
        content = files["pcb"].read_text(encoding="utf-8")
        assert 'footprint "MountingHole"' in content
        assert 'pad "" np_thru_hole' in content
        assert "(at 5.0 5.0 0)" in content
        assert "(size 3.0 3.0)" in content

    def test_net_index(self, tmp_path: Path) -> None:
        """_net_index produces correct mapping."""
        from zaptrace.export.kicad import _net_index

        d = self._pcb_design()
        idx = _net_index(d)
        assert idx["n1"] == 1
        assert len(idx) == 1


# ---------------------------------------------------------------------------
# Gerber tests
# ---------------------------------------------------------------------------


class TestGerber:
    def test_gerber_copper_layer(self) -> None:
        from zaptrace.export.gerber import generate_copper_layer

        d = Design(meta=DesignMeta(name="test"))
        gerber = generate_copper_layer(d, layer="top")
        assert gerber.startswith("G04")
        assert "MOMM" in gerber
        assert "FSLAX36Y36" in gerber
        assert "M02*" in gerber

    def test_board_outline(self) -> None:
        from zaptrace.export.gerber import generate_board_outline

        gerber = generate_board_outline(100.0, 80.0)
        assert "G04" in gerber
        assert "M02*" in gerber
        assert "OUTLINE" in gerber

    def test_gerber_with_traces(self) -> None:
        from zaptrace.export.gerber import generate_copper_layer

        d = Design(
            meta=DesignMeta(name="test"),
            routing=RouteResult(
                traces=[
                    TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="n1"),
                ],
            ),
        )
        gerber = generate_copper_layer(d, layer="top")
        assert "D01*" in gerber  # draw command present
        assert "X" in gerber
        assert "Y" in gerber

    def test_full_gerber_generation(self) -> None:
        from zaptrace.export.gerber import generate_gerber

        d = Design(
            meta=DesignMeta(name="TestPCB"),
            board=BoardConfig(width_mm=50.0, height_mm=40.0, layers=2),
            components={
                "u1": Component(
                    id="u1",
                    ref="U1",
                    type="mcu",
                    value="STM32",
                    position=(25.0, 20.0),
                    footprint_def=FootprintDef(
                        pads=[Pad(id="1", position=(0, 0), size=(1.5, 1.5), shape=PadShape.RECT)],
                    ),
                ),
            },
            routing=RouteResult(
                traces=[TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.25, net_id="n1")],
            ),
            board_def=BoardDefinition(width=50.0, height=40.0),
        )
        result = generate_gerber(d)
        assert "top" in result
        assert "bottom" in result
        assert "outline" in result
        assert "top_mask" in result
        assert "bottom_mask" in result
        assert "top_silk" in result
        assert "top_paste" in result
        for layer, content in result.items():
            assert isinstance(content, str)
            assert "MOMM" in content
            assert "M02*" in content, f"{layer} missing M02*"

    def test_gerber_to_directory(self, tmp_path: Path) -> None:
        from zaptrace.export.gerber import generate_gerber

        d = Design(
            meta=DesignMeta(name="DirTest"),
            board=BoardConfig(width_mm=30.0, height_mm=20.0, layers=2),
        )
        result = generate_gerber(d, output_dir=tmp_path, prefix="mytest")
        for _layer, path_str in result.items():
            p = Path(path_str)
            assert p.exists(), f"{p} should exist"
            assert p.stat().st_size > 0

    def test_copper_layer_has_apertures(self) -> None:
        from zaptrace.export.gerber import generate_copper_layer

        d = Design(
            meta=DesignMeta(name="test"),
            routing=RouteResult(
                traces=[TraceSegment(layer="top", start=(0, 0), end=(5, 0), width=0.3, net_id="n1")],
            ),
        )
        gerber = generate_copper_layer(d, layer="top")
        assert "%ADD" in gerber, "Should contain aperture definitions"

    def test_gerber_x2_attributes_present(self) -> None:
        from zaptrace.export.gerber import generate_copper_layer

        gerber = generate_copper_layer(Design(meta=DesignMeta(name="x2")), layer="top")
        validation = validate_gerber_x2_attributes(gerber)

        assert validation["passed"] is True
        assert "%TF.GenerationSoftware" in gerber
        assert "%TF.FileFunction,Copper,L1,Top" in gerber
        assert "%TF.FilePolarity,Positive" in gerber

    def test_gerber_x2_validation_reports_missing_attributes(self) -> None:
        validation = validate_gerber_x2_attributes("G04 no x2*\nMOMM\n%FSLAX36Y36*%\nM02*\n")

        assert validation["passed"] is False
        assert "%TF.GenerationSoftware" in validation["missing_attributes"]

    def test_gerber_job_file_shape(self, tmp_path: Path) -> None:
        d = Design(meta=DesignMeta(name="JobFile"), board=BoardConfig(width_mm=30.0, height_mm=20.0, layers=2))
        gerbers = generate_gerber(d, output_dir=tmp_path, prefix="job")
        data = __import__("json").loads(generate_gerber_job_file(d, gerbers))

        assert data["format"] == "Gerber Job File"
        assert data["board"]["layers"] == 2
        assert len(data["files"]) == 7
        assert any(item["function"] == "Copper,L1,Top" for item in data["files"])


# ---------------------------------------------------------------------------
# Excellon drill tests
# ---------------------------------------------------------------------------


class TestExcellon:
    def test_tool_definitions_cover_plated_and_non_plated_tools(self) -> None:
        from zaptrace.export.excellon import _ToolManager

        manager = _ToolManager()
        manager.get_or_create(0.8, plated=True)
        manager.get_or_create(1.0, plated=False)

        assert manager.tool_defs_lines() == ["T01C0.8000\n", "T02C1.0000\n"]

    def test_generate_excellon_string(self) -> None:
        from zaptrace.export.excellon import generate_excellon

        d = Design(
            meta=DesignMeta(name="DrillTest"),
            components={
                "j1": Component(
                    id="j1",
                    ref="J1",
                    type="connector",
                    position=(10.0, 10.0),
                    footprint_def=FootprintDef(
                        pads=[Pad(id="1", position=(0, 0), size=(2.0, 2.0), drill=0.8)],
                    ),
                ),
            },
        )
        result = generate_excellon(d)
        assert "plated" in result
        content = str(result["plated"])
        assert "M48" in content
        assert "M30" in content
        assert "T01" in content

    def test_generate_composite_drill(self) -> None:
        from zaptrace.export.excellon import generate_composite_drill

        d = Design(
            meta=DesignMeta(name="DrillTest2"),
            components={
                "j1": Component(
                    id="j1",
                    ref="J1",
                    type="connector",
                    position=(5.0, 5.0),
                    footprint_def=FootprintDef(
                        pads=[Pad(id="1", position=(0, 0), size=(2.0, 2.0), drill=1.0)],
                    ),
                ),
            },
        )
        content = str(generate_composite_drill(d))
        assert "M48" in content
        assert "M30" in content
        assert "C1.0000" in content

    def test_excellon_to_directory(self, tmp_path: Path) -> None:
        from zaptrace.export.excellon import generate_excellon

        d = Design(
            meta=DesignMeta(name="FileDrill"),
            components={
                "j1": Component(
                    id="j1",
                    ref="J1",
                    type="connector",
                    position=(10.0, 10.0),
                    footprint_def=FootprintDef(
                        pads=[Pad(id="1", position=(0, 0), size=(2.0, 2.0), drill=0.8)],
                    ),
                ),
            },
        )
        result = generate_excellon(d, output_dir=tmp_path, prefix="filedrill")
        for _key, val in result.items():
            if isinstance(val, (Path, str)):
                p = Path(val) if isinstance(val, str) else val
                assert p.exists()
                assert p.stat().st_size > 0

    def test_excellon_no_holes(self) -> None:
        from zaptrace.export.excellon import generate_excellon

        d = Design(meta=DesignMeta(name="NoHoles"))
        result = generate_excellon(d)
        assert "plated" not in result
        assert "non_plated" not in result

    def test_excellon_mounting_holes(self) -> None:
        from zaptrace.export.excellon import generate_excellon

        d = Design(
            meta=DesignMeta(name="MHTest"),
            board_def=BoardDefinition(
                mounting_holes=[MountingHole(position=(5.0, 5.0), diameter=3.0, plated=True)],
            ),
        )
        result = generate_excellon(d)
        assert "plated" in result

    def test_excellon_multiple_tools(self) -> None:
        from zaptrace.export.excellon import generate_excellon

        d = Design(
            meta=DesignMeta(name="MultiTool"),
            components={
                "j1": Component(
                    id="j1",
                    ref="J1",
                    type="connector",
                    position=(10.0, 10.0),
                    footprint_def=FootprintDef(
                        pads=[
                            Pad(id="1", position=(0, 0), size=(2.0, 2.0), drill=0.8),
                            Pad(id="2", position=(5, 0), size=(2.0, 2.0), drill=1.2),
                        ],
                    ),
                ),
            },
        )
        result = generate_excellon(d)
        content = str(result["plated"])
        assert "T01" in content
        assert "T02" in content


def test_kicad_netlist_evidence_helpers_report_mapped_and_missing_nodes() -> None:
    from collections import Counter

    from zaptrace.export.kicad import _net_evidence, _net_node_evidence

    design = _design()
    mapped, complete = _net_node_evidence(design, "R1", "1")
    assert complete is True
    assert mapped["component_present"] is True

    missing, complete = _net_node_evidence(design, "MISSING", "1")
    assert complete is False
    assert missing["pcb_pad_present"] is False

    net_id = next(iter(design.nets))
    payload, node_count, missing_count = _net_evidence(design, net_id, Counter({net_id: 2}), Counter({net_id: 1}))
    assert node_count == len(design.nets[net_id].nodes)
    assert missing_count == 0
    assert payload["routed_segment_count"] == 2
    assert payload["routed_via_count"] == 1
