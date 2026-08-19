"""Tests for the manufacturing export module (ZIP bundle, pick-and-place, manifest)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from zaptrace.core.models import (
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
)
from zaptrace.export.manufacturing import (
    generate_manufacturing_bundle,
    generate_manufacturing_manifest,
    generate_pick_and_place,
)


def _design() -> Design:
    fp = FootprintDef(
        pads=[
            Pad(id="1", layer=LayerSet.TOP, shape=PadShape.RECT, position=(0.0, 0.0), size=(0.6, 0.6)),
            Pad(id="2", layer=LayerSet.TOP, shape=PadShape.RECT, position=(0.0, 0.0), size=(0.6, 0.6)),
        ],
        outline=[],
    )
    return Design(
        meta=DesignMeta(name="TestBoard"),
        components={
            "c1": Component(
                id="c1",
                ref="R1",
                type="resistor",
                value="10k",
                footprint="0603",
                footprint_def=fp,
                position=(10.0, 20.0),
            ),
            "c2": Component(
                id="c2",
                ref="C1",
                type="capacitor",
                value="100n",
                footprint="0603",
                footprint_def=fp,
                position=(30.0, 40.0),
            ),
            "c3": Component(id="c3", ref="U1", type="mcu", value="ESP32", footprint="QFN-48", position=(50.0, 60.0)),
        },
        nets={
            "n1": Net(id="n1", name="VCC", nodes=[NetNode(component_ref="R1", pin_name="1")]),
        },
        placement={
            "c1": (10.0, 20.0),
            "c2": (30.0, 40.0),
            "c3": (50.0, 60.0),
        },
        board_def=BoardDefinition(
            mounting_holes=[
                MountingHole(position=(5.0, 5.0), diameter=3.0, plated=True),
            ],
        ),
    )


class TestPickAndPlace:
    def test_generates_csv(self) -> None:
        csv = generate_pick_and_place(_design())
        assert "Ref" in csv
        assert "PosX" in csv
        assert "R1" in csv
        assert "C1" in csv
        assert "Side" in csv

    def test_contains_positions(self) -> None:
        csv = generate_pick_and_place(_design())
        assert "10.000" in csv
        assert "20.000" in csv

    def test_placement_fallback(self) -> None:
        d = _design()
        d.placement = None
        csv = generate_pick_and_place(d)
        # Components have position set directly
        assert "10.000" in csv

    def test_empty_design(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        csv = generate_pick_and_place(d)
        assert csv.strip() == "Ref,Value,Package,PosX,PosY,Rotation,Side"

    def test_no_position_skipped(self) -> None:
        d = _design()
        d.components["c4"] = Component(id="c4", ref="X1", type="unknown", value="")
        csv = generate_pick_and_place(d)
        assert "X1" not in csv

    def test_dnp_component_is_excluded(self) -> None:
        d = _design()
        d.components["c2"].dnp = True

        csv = generate_pick_and_place(d)

        assert "C1" not in csv
        assert "R1" in csv

    def test_side_top_default(self) -> None:
        csv = generate_pick_and_place(_design())
        assert "top" in csv.lower() or "Top" in csv

    def test_side_bottom(self) -> None:
        fp = FootprintDef(
            pads=[Pad(id="1", layer=LayerSet.BOTTOM, shape=PadShape.RECT, position=(0.0, 0.0), size=(0.6, 0.6))],
            outline=[],
        )
        d = _design()
        d.components["c1"].footprint_def = fp
        d.components["c1"].position = (10.0, 10.0)
        csv = generate_pick_and_place(d)
        assert "bottom" in csv.lower()


class TestManifest:
    def test_manifest_json(self) -> None:
        manifest = generate_manufacturing_manifest(_design())
        data = json.loads(manifest)
        assert data["design"]["name"] == "TestBoard"
        assert data["statistics"]["components"] == 3
        assert data["statistics"]["nets"] == 1

    def test_manifest_contains_layer_info(self) -> None:
        data = json.loads(generate_manufacturing_manifest(_design()))
        assert data["board"]["layers"] == 2
        assert data["board"]["width_mm"] == 100.0
        assert data["board"]["height_mm"] == 80.0

    def test_manifest_has_tool_info(self) -> None:
        data = json.loads(generate_manufacturing_manifest(_design()))
        assert "ZapTrace" in data["tool"]

    def test_manifest_output_files(self) -> None:
        data = json.loads(generate_manufacturing_manifest(_design()))
        assert len(data["output_files"]) >= 9
        assert any(item["file"] == ".IPC" for item in data["output_files"])
        assert any(item["file"] == ".GBRJOB" for item in data["output_files"])

    def test_empty_design(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        data = json.loads(generate_manufacturing_manifest(d))
        assert data["statistics"]["components"] == 0


class TestManufacturingBundle:
    def test_creates_files(self, tmp_path: Path) -> None:
        result = generate_manufacturing_bundle(_design(), tmp_path)
        assert "gerber_layers" in result
        assert "bom" in result
        assert "pick_and_place" in result
        assert "manifest" in result
        assert "ipc_d356" in result
        assert "gerber_job" in result
        assert "zip" in result

    def test_gerber_layers_produced(self, tmp_path: Path) -> None:
        result = generate_manufacturing_bundle(_design(), tmp_path)
        layers = result["gerber_layers"]
        assert "top" in layers
        assert "bottom" in layers
        assert "outline" in layers
        assert "top_silk" in layers

    def test_bom_file_exists(self, tmp_path: Path) -> None:
        result = generate_manufacturing_bundle(_design(), tmp_path)
        assert Path(result["bom"]).exists()

    def test_pnp_file_exists(self, tmp_path: Path) -> None:
        result = generate_manufacturing_bundle(_design(), tmp_path)
        assert Path(result["pick_and_place"]).exists()

    def test_manifest_file_exists(self, tmp_path: Path) -> None:
        result = generate_manufacturing_bundle(_design(), tmp_path)
        assert Path(result["manifest"]).exists()

    def test_ipc_d356_file_exists(self, tmp_path: Path) -> None:
        result = generate_manufacturing_bundle(_design(), tmp_path)
        ipc_path = Path(result["ipc_d356"])
        assert ipc_path.exists()
        assert ipc_path.suffix == ".ipc"
        assert "P NET VCC REF R1 PIN 1" in ipc_path.read_text(encoding="utf-8")

    def test_gerber_job_file_exists(self, tmp_path: Path) -> None:
        result = generate_manufacturing_bundle(_design(), tmp_path)
        job_path = Path(result["gerber_job"])
        assert job_path.exists()
        assert job_path.suffix == ".gbrjob"
        assert '"Gerber Job File"' in job_path.read_text(encoding="utf-8")

    def test_zip_created(self, tmp_path: Path) -> None:
        result = generate_manufacturing_bundle(_design(), tmp_path)
        zip_path = Path(result["zip"])
        assert zip_path.exists()
        assert zip_path.suffix == ".zip"

    def test_zip_contains_files(self, tmp_path: Path) -> None:
        result = generate_manufacturing_bundle(_design(), tmp_path)
        with zipfile.ZipFile(result["zip"], "r") as zf:
            names = zf.namelist()
        assert any(n.endswith(".GTL") for n in names)
        assert any("bom" in n for n in names)
        assert any("manifest" in n for n in names)
        assert any(n.endswith(".ipc") for n in names)
        assert any(n.endswith(".gbrjob") for n in names)

    def test_drill_produced(self, tmp_path: Path) -> None:
        result = generate_manufacturing_bundle(_design(), tmp_path)
        assert "drill_plated" in result
        # Only plated holes in this design; NPTH may be absent

    def test_custom_prefix(self, tmp_path: Path) -> None:
        result = generate_manufacturing_bundle(_design(), tmp_path, prefix="MyDesign")
        zip_path = Path(result["zip"])
        assert "MyDesign" in zip_path.name

    def test_empty_design(self, tmp_path: Path) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        result = generate_manufacturing_bundle(d, tmp_path)
        assert "zip" in result
        assert Path(result["zip"]).exists()
