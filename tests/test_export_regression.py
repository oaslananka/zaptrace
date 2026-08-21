"""Export regression tests — golden-file comparison for all export formats.

On first run (or with UPDATE_GOLDENS=1), generates golden output files from
a reference design. Subsequent runs regenerate exports and diff against the
stored goldens to catch regressions in the export pipeline.

Deterministic exports (BOM, pick-and-place, report) use full golden comparison.
RS-274X Gerber and Excellon exports use AST-level Geometric Semantic Comparison
to eliminate formatting/LSB jitter while strictly validating geometric integrity.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from zaptrace.algo.copper_pour import CopperPourGenerator, _component_keepout
from zaptrace.core.models import (
    BoardConfig,
    BoardDefinition,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    LayerSet,
    MountingHole,
    Net,
    NetNode,
    Pad,
    PadShape,
    RouteResult,
    TraceSegment,
)
from zaptrace.export.bom import generate_bom_csv, generate_bom_json
from zaptrace.export.gerber import (
    generate_board_outline,
    generate_copper_layer,
    generate_gerber,
)
from zaptrace.export.kicad import export_kicad_pcb, export_kicad_schematic
from zaptrace.export.manufacturing import generate_manufacturing_bundle
from zaptrace.export.report import generate_report
from zaptrace.export.svg import render_schematic_svg
from zaptrace.testing.gerber_ast import (
    parse_excellon,
    parse_gerber,
)

GOLDENS_DIR = Path(__file__).resolve().parent / "corpus" / "goldens"
UPDATE_GOLDENS = os.environ.get("UPDATE_GOLDENS", "").lower() in ("1", "true", "yes")


def _reference_design() -> Design:
    """Build a reference design exercising all major export features.

    Covers: multi-component, mixed SMD/THT, routing, copper pour,
    mounting holes, multiple nets, power/signal traces.
    """
    smd_pads = [
        Pad(id="1", layer=LayerSet.TOP, shape=PadShape.RECT, position=(-1.5, -1.0), size=(1.0, 2.0)),
        Pad(id="2", layer=LayerSet.TOP, shape=PadShape.RECT, position=(1.5, -1.0), size=(1.0, 2.0)),
    ]
    tht_pads = [
        Pad(id="1", shape=PadShape.CIRCLE, position=(-3.0, 0.0), size=(2.5, 2.5), drill=1.0),
        Pad(id="2", shape=PadShape.CIRCLE, position=(3.0, 0.0), size=(2.5, 2.5), drill=1.0),
    ]
    r1_fp = FootprintDef(pads=smd_pads, description="0805 resistor")
    j1_fp = FootprintDef(pads=tht_pads, description="2-pin header")

    return Design(
        meta=DesignMeta(name="RegressionTest", author="zaptrace", version="1.0"),
        board=BoardConfig(
            width_mm=100.0,
            height_mm=80.0,
            layers=2,
            thickness_mm=1.6,
            copper_weight_oz=1.0,
        ),
        board_def=BoardDefinition(
            outline=[(0, 0), (100, 0), (100, 80), (0, 80)],
        ),
        components={
            "r1": Component(
                id="r1",
                ref="R1",
                type="resistor",
                value="10k",
                footprint="0805",
                footprint_def=r1_fp,
                position=(20.0, 40.0),
            ),
            "r2": Component(
                id="r2",
                ref="R2",
                type="resistor",
                value="1k",
                footprint="0805",
                footprint_def=r1_fp,
                position=(40.0, 40.0),
            ),
            "c1": Component(
                id="c1",
                ref="C1",
                type="capacitor",
                value="100n",
                footprint="0805",
                footprint_def=r1_fp,
                position=(30.0, 60.0),
            ),
            "j1": Component(
                id="j1",
                ref="J1",
                type="connector",
                value="Header_2x1",
                footprint="PinHeader_2x1_P2.54mm",
                footprint_def=j1_fp,
                position=(80.0, 40.0),
            ),
        },
        nets={
            "n1": Net(
                id="n1",
                name="VCC",
                nodes=[NetNode(component_ref="R1", pin_name="1")],
            ),
            "n2": Net(
                id="n2",
                name="GND",
                nodes=[NetNode(component_ref="R2", pin_name="2")],
            ),
            "n3": Net(
                id="n3",
                name="SIG",
                nodes=[NetNode(component_ref="R1", pin_name="2"), NetNode(component_ref="C1", pin_name="1")],
            ),
        },
        routing=RouteResult(
            traces=[
                TraceSegment(layer="top", net_id="n1", start=(20, 38), end=(20, 30), width=0.5),
                TraceSegment(layer="top", net_id="n1", start=(20, 30), end=(80, 30), width=0.5),
                TraceSegment(layer="top", net_id="n2", start=(40, 38), end=(40, 20), width=0.3),
                TraceSegment(layer="top", net_id="n3", start=(20, 42), end=(30, 58), width=0.25),
            ],
        ),
        mounting_holes=[
            MountingHole(diameter=3.2, position=(5.0, 5.0)),
            MountingHole(diameter=3.2, position=(95.0, 5.0)),
        ],
        properties={"design_type": "regression_test"},
    )


def _copper_pour_thermal_fixture_design() -> tuple[Design, dict[str, tuple[float, float]]]:
    """Synthetic design exercising copper pour with thermal relief and clearance isolation."""
    smd_gnd = FootprintDef(
        pads=[Pad(id="1", layer=LayerSet.TOP, shape=PadShape.RECT, position=(0.0, 0.0), size=(1.0, 1.0))],
        courtyard=(1.0, 1.0),
    )
    smd_vcc = FootprintDef(
        pads=[Pad(id="1", layer=LayerSet.TOP, shape=PadShape.RECT, position=(0.0, 0.0), size=(1.0, 1.0))],
        courtyard=(2.0, 2.0),
    )
    design = Design(
        meta=DesignMeta(name="CopperPourThermalRegression", author="zaptrace", version="1.0"),
        board=BoardConfig(width_mm=30.0, height_mm=30.0, layers=2),
        board_def=BoardDefinition(outline=[(0, 0), (30, 0), (30, 30), (0, 30)]),
        components={
            "c_gnd": Component(
                id="c_gnd",
                ref="C_GND",
                type="capacitor",
                value="100n",
                footprint="0805",
                footprint_def=smd_gnd,
                position=(15.0, 15.0),
            ),
            "c_vcc": Component(
                id="c_vcc",
                ref="C_VCC",
                type="capacitor",
                value="100n",
                footprint="0805",
                footprint_def=smd_vcc,
                position=(0.0, 15.0),
            ),
        },
        nets={
            "GND": Net(id="GND", name="GND", nodes=[NetNode(component_ref="C_GND", pin_name="1")]),
            "VCC": Net(id="VCC", name="VCC", nodes=[NetNode(component_ref="C_VCC", pin_name="1")]),
        },
    )
    positions = {"c_gnd": (15.0, 15.0), "c_vcc": (0.0, 15.0)}
    return design, positions


# ---------------------------------------------------------------------------
# Deterministic golden comparison helpers
# ---------------------------------------------------------------------------


def _strip_timestamps(text: str) -> str:
    """Replace ISO timestamps and UUIDs with placeholders for diff stability."""
    text = re.sub(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?",
        "<TIMESTAMP>",
        text,
    )
    text = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "<UUID>",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\bversion: \S+", "version: <VERSION>", text)
    text = re.sub(r'"zaptrace_version":\s*"[^"]*"', '"zaptrace_version": "<VERSION>"', text)
    text = re.sub(r'"tool_version":\s*"[^"]*"', '"tool_version": "<VERSION>"', text)
    return text


def _golden_path(name: str) -> Path:
    return GOLDENS_DIR / name


def _load_golden(name: str) -> str | None:
    p = _golden_path(name)
    return p.read_text(encoding="utf-8") if p.exists() else None


def _save_golden(name: str, content: str) -> None:
    GOLDENS_DIR.mkdir(parents=True, exist_ok=True)
    p = _golden_path(name)
    p.write_text(content, encoding="utf-8")


def _assert_golden(name: str, content: str, strip: bool = True) -> None:
    """Compare generated content against stored golden, or store if missing."""
    normalized = _strip_timestamps(content) if strip else content
    # Normalize line endings to avoid Windows/POSIX golden drift
    normalized = normalized.replace("\r\n", "\n")
    golden = _load_golden(name)
    if golden is None or UPDATE_GOLDENS:
        _save_golden(name, normalized)
        return
    golden = golden.replace("\r\n", "\n")
    assert normalized == golden, f"Golden mismatch for {name!r}. Run with UPDATE_GOLDENS=1 to regenerate."


def _assert_gerber_ast_golden(name: str, gerber_content: str) -> None:
    """Compare generated Gerber AST against stored golden JSON."""
    ast = parse_gerber(gerber_content)
    ast_json = ast.to_json(indent=2)
    _assert_golden(name, ast_json, strip=False)


def _assert_excellon_ast_golden(name: str, excellon_content: str) -> None:
    """Compare generated Excellon AST against stored golden JSON."""
    ast = parse_excellon(excellon_content)
    ast_json = ast.to_json(indent=2)
    _assert_golden(name, ast_json, strip=False)


# ===========================================================================
# Regression tests
# ===========================================================================


class TestBOMRegression:
    def test_bom_csv_golden(self) -> None:
        csv = generate_bom_csv(_reference_design())
        _assert_golden("bom.csv", csv)

    def test_bom_json_golden(self) -> None:
        j = generate_bom_json(_reference_design())
        text = json.dumps(j, indent=2, sort_keys=True)
        _assert_golden("bom.json", text)


class TestPickAndPlaceRegression:
    def test_pnp_csv_golden(self) -> None:
        from zaptrace.export.manufacturing import generate_pick_and_place

        csv = generate_pick_and_place(_reference_design())
        _assert_golden("pick_and_place.csv", csv)


class TestReportRegression:
    def test_report_golden(self) -> None:
        report = generate_report(_reference_design())
        _assert_golden("report.md", report)


class TestSVGRegression:
    def test_svg_golden(self) -> None:
        svg = render_schematic_svg(_reference_design())
        # Strip viewBox dimensions (may vary)
        svg_normalized = re.sub(r'\sviewBox="[^"]*"', ' viewBox="<VIEWBOX>"', svg)
        _assert_golden("schematic.svg", svg_normalized)


class TestKiCadRegression:
    def test_kicad_sch_golden(self, tmp_path: Path) -> None:
        result = export_kicad_schematic(_reference_design(), tmp_path)
        sch_text = Path(result["schematic"]).read_text(encoding="utf-8")
        _assert_golden("design.kicad_sch", sch_text)

    def test_kicad_pcb_golden(self, tmp_path: Path) -> None:
        result = export_kicad_pcb(_reference_design(), tmp_path)
        pcb_text = Path(result["pcb"]).read_text(encoding="utf-8")
        _assert_golden("design.kicad_pcb", pcb_text)


class TestCopperPourThermalRegression:
    """EDA regression tests for copper pour flood fill, thermal relief, and clearance boundaries."""

    def test_copper_pour_thermal_golden(self) -> None:
        """Positive baseline: GND pour with thermal relief spokes on GND pad and void on VCC pad."""
        design, positions = _copper_pour_thermal_fixture_design()

        def keepout_fn(comp: Component, pos: tuple[float, float] | None) -> list[tuple[float, float]]:
            if comp.ref == "C_GND":
                return []
            return _component_keepout(comp, pos, clearance=0.5)

        gen = CopperPourGenerator(resolution_mm=0.5)
        pour = gen.generate_ground_pour(
            design=design,
            positions=positions,
            layer="top",
            net_id="GND",
            add_thermal_reliefs=True,
            add_stitching_vias=False,
            keepout_fn=keepout_fn,
        )
        assert len(pour.thermal_reliefs) == 1
        design.copper_pours["top_GND"] = pour

        gerber_content = generate_copper_layer(design, layer="top")
        _assert_gerber_ast_golden("copper_pour_thermal.gerber.json", gerber_content)

        ast = parse_gerber(gerber_content)
        assert len(ast.regions) >= 1
        assert ast.regions[0].area > 0
        assert len(ast.flashes) == 2
        # 4 thermal relief spokes rendered as GerberLine items
        assert len(ast.lines) == 4

    def test_copper_pour_clearance_violation(self) -> None:
        """Negative regression: altered clearance changes geometry and fails semantic AST match."""
        design, positions = _copper_pour_thermal_fixture_design()

        # Baseline run
        def base_keepout(comp: Component, pos: tuple[float, float] | None) -> list[tuple[float, float]]:
            if comp.ref == "C_GND":
                return []
            return _component_keepout(comp, pos, clearance=0.5)

        gen = CopperPourGenerator(resolution_mm=0.5)
        pour_base = gen.generate_ground_pour(
            design=design,
            positions=positions,
            layer="top",
            net_id="GND",
            add_thermal_reliefs=True,
            add_stitching_vias=False,
            keepout_fn=base_keepout,
        )
        design.copper_pours["top_GND"] = pour_base
        base_ast = parse_gerber(generate_copper_layer(design, layer="top"))

        # Altered run with enlarged clearance around VCC (creates larger void)
        def altered_keepout(comp: Component, pos: tuple[float, float] | None) -> list[tuple[float, float]]:
            if comp.ref == "C_GND":
                return []
            return _component_keepout(comp, pos, clearance=3.0)

        pour_altered = gen.generate_ground_pour(
            design=design,
            positions=positions,
            layer="top",
            net_id="GND",
            add_thermal_reliefs=True,
            add_stitching_vias=False,
            keepout_fn=altered_keepout,
        )
        design.copper_pours["top_GND"] = pour_altered
        altered_ast = parse_gerber(generate_copper_layer(design, layer="top"))

        matched, diffs = base_ast.compare(altered_ast)
        assert not matched, "Geometric AST comparison should have failed for altered copper pour clearance"
        assert any("area mismatch" in d or "vertex" in d for d in diffs), (
            f"Expected region area/vertex diff, got: {diffs}"
        )


class TestGerberStructural:
    """Gerber structural and AST golden validation."""

    def _check_gerber(self, name: str, content: str) -> None:
        assert content.startswith("G04"), f"{name}: missing G04 header comment"
        assert "MOMM" in content, f"{name}: missing MOMM unit"
        assert "M02*" in content.rstrip(), f"{name}: missing M02* EOF"
        assert "%FS" in content, f"{name}: missing FS format spec"

    def test_top_copper(self) -> None:
        gerber = generate_copper_layer(_reference_design(), layer="top")
        self._check_gerber("top_copper", gerber)
        _assert_gerber_ast_golden("top_copper.gerber.json", gerber)

    def test_bottom_copper(self) -> None:
        gerber = generate_copper_layer(_reference_design(), layer="bottom")
        self._check_gerber("bottom_copper", gerber)
        _assert_gerber_ast_golden("bottom_copper.gerber.json", gerber)

    def test_board_outline(self) -> None:
        board = _reference_design().board
        gerber = generate_board_outline(board.width_mm, board.height_mm)
        self._check_gerber("outline", gerber)
        _assert_gerber_ast_golden("board_outline.gerber.json", gerber)

    def test_gerber_bundle_contains_all_layers(self, tmp_path: Path) -> None:
        result = generate_gerber(_reference_design(), output_dir=tmp_path)
        expected_layers = {"top", "bottom", "top_silk", "top_mask", "bottom_mask", "outline", "top_paste"}
        for layer in expected_layers:
            assert layer in result, f"Missing gerber layer: {layer}"
            p = Path(result[layer])
            assert p.exists(), f"Gerber layer file not found: {p}"
            assert p.stat().st_size > 0, f"Empty gerber layer: {p}"


class TestManufacturingBundleStructural:
    """Manufacturing bundle structural validation."""

    def test_bundle_contains_all_artifacts(self, tmp_path: Path) -> None:
        result = generate_manufacturing_bundle(_reference_design(), tmp_path)
        assert "gerber_layers" in result
        assert "bom" in result
        assert "pick_and_place" in result
        assert "manifest" in result
        assert "drill_plated" in result
        assert "zip" in result

        # Verify all referenced files exist
        for key in ("bom", "pick_and_place", "manifest", "drill_plated"):
            p = Path(result[key])
            assert p.exists(), f"Missing {key}: {p}"
            assert p.stat().st_size > 0, f"Empty {key}: {p}"

        # Verify ZIP contains expected entries
        import zipfile

        with zipfile.ZipFile(result["zip"], "r") as zf:
            names = zf.namelist()

        def lower_endswith(ext: str) -> bool:
            return any(n.lower().endswith(ext.lower()) for n in names)

        assert lower_endswith(".GTL"), "Missing top copper in ZIP"
        assert lower_endswith(".GBL"), "Missing bottom copper in ZIP"
        assert lower_endswith(".GKO"), "Missing outline in ZIP"
        assert lower_endswith(".GTO"), "Missing top silk in ZIP"
        assert lower_endswith(".GTS"), "Missing top mask in ZIP"
        assert any("bom" in n.lower() for n in names), "Missing BOM in ZIP"
        assert any("pnp" in n.lower() or "pick" in n.lower() for n in names), "Missing PnP in ZIP"
        assert any("manifest" in n.lower() for n in names), "Missing manifest in ZIP"
        assert lower_endswith(".DRL"), "Missing drill in ZIP"

    def test_manifest_structure(self, tmp_path: Path) -> None:
        result = generate_manufacturing_bundle(_reference_design(), tmp_path)
        with open(result["manifest"], encoding="utf-8") as f:
            manifest = json.load(f)
        assert "design" in manifest
        assert "board" in manifest
        assert "statistics" in manifest
        assert "output_files" in manifest
        assert manifest["statistics"]["components"] >= 2
        assert manifest["board"]["layers"] >= 2


class TestExcellonStructural:
    """Excellon drill structural and AST golden validation."""

    def test_drill_format(self) -> None:
        from zaptrace.export.excellon import generate_excellon

        result = generate_excellon(_reference_design())
        assert "plated" in result
        content = str(result["plated"])
        assert content.startswith("M48"), "Excellon should start with M48"
        assert "M30" in content, "Excellon should end with M30"
        assert "T01" in content, "Excellon should have tool definitions"
        assert "%" in content, "Excellon should have percent delimiters"
        _assert_excellon_ast_golden("drill_plated.excellon.json", content)


class TestGoldenUpdate:
    """Verify goldens exist and are up to date (runs at end of suite)."""

    def test_all_goldens_exist(self) -> None:
        expected = [
            "bom.csv",
            "bom.json",
            "pick_and_place.csv",
            "report.md",
            "schematic.svg",
            "design.kicad_sch",
            "design.kicad_pcb",
            "copper_pour_thermal.gerber.json",
            "top_copper.gerber.json",
            "bottom_copper.gerber.json",
            "board_outline.gerber.json",
            "drill_plated.excellon.json",
        ]
        missing = [n for n in expected if not _golden_path(n).exists()]
        if missing and not UPDATE_GOLDENS:
            raise AssertionError(f"Missing golden files: {missing}. Run with UPDATE_GOLDENS=1 to generate.")


def test_generate_copper_layer_ignores_unpositioned_components() -> None:
    design = Design(
        meta=DesignMeta(name="unpositioned-component"),
        components={
            "r1": Component(id="r1", ref="R1", type="resistor"),
        },
    )

    gerber = generate_copper_layer(design, "top")

    assert gerber.endswith("M02*\n")
