"""Native KiCad 3D link report cannot overclaim qualified assembly models."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"


def test_013_native_models_fail_closed_with_source_sha_and_no_geometry_signoff() -> None:
    command = (
        "import json,sys;"
        f"sys.path.insert(0,{str(ROOT / 'scripts')!r});"
        "from review_studio_013_3d_asset_audit import inspect;"
        f"print(json.dumps(inspect(__import__('pathlib').Path({str(BOARD)!r}),"
        " __import__('pathlib').Path('/usr/share/kicad/3dmodels'))))"
    )
    result = subprocess.run(["/usr/bin/python3", "-B", "-c", command], text=True, capture_output=True, timeout=25)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert len(report["board_sha256"]) == 64
    assert report["footprints"] == 14
    assert report["footprints_with_model_references"] == 12
    assert report["declared_model_links"] == 12
    assert report["locally_present_model_files"] == 10
    assert report["unresolved_references"] == ["J1", "U1"]
    assert report["no_model_link_declared"] == ["TP1", "TP2"]
    assert report["exact_stem_step_alternatives_only"] == ["J1", "U1"]
    assert report["physical_assembly_fit_certified"] is False
    assert report["all_models_independently_geometry_verified"] is False
    assert report["fabrication_approved"] is False
