"""Tests for 3D WebGL PCB viewer and mesh export (OBJ/STL)."""

from __future__ import annotations

from pathlib import Path

import pytest

from zaptrace.core.models import (
    BoardConfig,
    Component,
    Design,
    DesignMeta,
    Pin,
    PinType,
)
from zaptrace.export.mesh import export_pcb_obj, export_pcb_stl
from zaptrace.viewer.threedee import ThreeDeeBundle, generate_3d_viewer


@pytest.fixture
def sample_3d_design() -> Design:
    return Design(
        meta=DesignMeta(name="mesh-test-board", version="1.0.0"),
        components={
            "r1": Component(
                id="r1",
                ref="R1",
                type="resistor",
                value="10k",
                footprint="0402",
                pins={"1": Pin(name="1", type=PinType.PASSIVE), "2": Pin(name="2", type=PinType.PASSIVE)},
            ),
            "u1": Component(
                id="u1",
                ref="U1",
                type="ic",
                value="STM32F4",
                footprint="LQFP-64",
                pins={"1": Pin(name="1", type=PinType.POWER)},
            ),
        },
        board=BoardConfig(width_mm=80.0, height_mm=60.0, layers=4),
        placement={"r1": (20.0, 30.0), "u1": (40.0, 30.0)},
    )


class TestMeshExport:
    """Test OBJ and STL 3D geometry exporters."""

    def test_export_pcb_obj(self, sample_3d_design: Design) -> None:
        obj_text = export_pcb_obj(sample_3d_design)
        assert isinstance(obj_text, str)
        assert "# ZapTrace PCB 3D Model" in obj_text
        assert "o Substrate_FR4" in obj_text
        assert "o Comp_r1_0402" in obj_text or "o Comp_u1_LQFP-64" in obj_text
        assert "v " in obj_text
        assert "f " in obj_text

    def test_export_pcb_stl(self, sample_3d_design: Design) -> None:
        stl_text = export_pcb_stl(sample_3d_design)
        assert stl_text.startswith("solid mesh-test-board")
        assert stl_text.strip().endswith("endsolid mesh-test-board")
        assert "facet normal" in stl_text
        assert "outer loop" in stl_text
        assert "vertex" in stl_text


class TestThreeDeeViewer:
    """Test 3D WebGL HTML bundle generator."""

    def test_generate_3d_bundle(self, sample_3d_design: Design, tmp_path: Path) -> None:
        bundle = generate_3d_viewer(sample_3d_design, output_dir=tmp_path / "viewer3d")
        assert isinstance(bundle, ThreeDeeBundle)
        assert bundle.design_name == "mesh-test-board"
        assert bundle.board_width_mm == 80.0
        assert bundle.component_count == 2

        index_path = Path(bundle.index_path)
        assert index_path.exists()
        content = index_path.read_text(encoding="utf-8")
        assert "<!doctype html>" in content
        assert "canvas3d" in content
        assert "THREE.OrbitControls" in content
        assert "mesh-test-board" in content
