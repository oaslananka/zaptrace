"""Mobile preview navigation must retain actual source and approval semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from zaptrace.viewer.interactive import generate_interactive_viewer

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("source", ["real", "synthetic"])
def test_source_bound_mobile_jump_preserves_real_vs_synthetic_evidence(source: str, tmp_path: Path) -> None:
    if source == "real":
        design = ROOT / "examples/esp32_i2c_sensor_node/design.yaml"
        proof = None
    else:
        design = ROOT / "examples/review_studio_ux_fixture/design.yaml"
        proof = ROOT / "examples/review_studio_ux_fixture/synthetic-proof-manifest.yaml"

    output = generate_interactive_viewer(design, tmp_path, proof_path=proof)
    index = Path(output.index_path).read_text()
    data = json.loads(Path(output.data_path).read_text())

    assert 'id="btnJumpToBoard" aria-controls="canvasArea"' in index
    assert 'id="canvasArea" tabindex="-1"' in index
    assert 'document.getElementById("btnJumpToBoard").addEventListener("click"' in index
    assert 'board.scrollIntoView({behavior:"auto",block:"start"})' in index
    assert "board.focus({preventScroll:true})" in index
    assert ".review-status .btn-board-jump { display:none;" in index
    assert "@media(max-width:650px) {.review-status .btn-board-jump{display:inline-flex;min-height:44px;}" in index
    assert 'id="btnReviewFindings"' in index
    assert "Engineering preview, not fabrication geometry." in index
    assert data["review"]["fabrication_state"] == "human_review_required"
    if source == "real":
        assert len(data["components"]) == 14
        # This repository's real ESP32 design has explicit provisional
        # source placement. The preview must reflect the exact source
        # coordinates, not silently claim components are unplaced.
        placement = yaml.safe_load(design.read_text())["placement"]
        assert {item["ref"]: (item["x"], item["y"]) for item in data["components"] if item["placed"]} == {
            ref: (float(coords[0]), float(coords[1])) for ref, coords in placement.items()
        }
        assert all(item["placed"] for item in data["components"])
        # Placement is not manufactured copper or a measured DRC result.
        assert len(data["traces"]) == 0
        assert data["review"]["drc_state"] == "not_checked"
        assert data["review"]["proof_state"] == "not_provided"
    else:
        assert len(data["components"]) == 8
        assert len(data["traces"]) == 9
        assert data["review"]["drc_state"] == "blocking"
        assert data["review"]["proof_state"] == "manifest_only"
