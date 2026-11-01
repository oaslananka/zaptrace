"""Real 320px toolbar collision is a release blocker; never re-ship 0.1.15 layout."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from review_studio_build_deb import build  # noqa: E402


def test_narrow_3d_model_dialog_must_scroll_inside_board_and_clear_toolbar() -> None:
    html = (ROOT / "scripts/review_studio_native_template.html").read_text()
    smoke = (ROOT / "scripts/review_studio_016_model_browser_smoke.mjs").read_text()
    shared = (ROOT / "scripts/review_studio_model_browser_smoke_shared.mjs").read_text()
    assert "runSmoke(" in smoke
    assert "max-height:calc(100% - 247px);overflow-y:auto;overscroll-behavior:contain" in html
    assert "toolbarOverlap<=1" in shared
    assert "320PX_3D_CONTROL_TOOLBAR_VERTICAL_OVERLAP_PX" in shared
    assert "320px real native 3D model disclosure does not cover the PCB mode" in shared
    assert "EXACT_016_SOURCE_LINKED_3D_MODEL_DIAGNOSTIC_CHROME=PASS" in smoke


def test_actual_016_deb_contains_narrow_layout_and_native_3d_diagnostics(tmp_path: Path) -> None:
    package = build(ROOT, tmp_path / "first", version="0.1.16")
    reproduced = build(ROOT, tmp_path / "repro", version="0.1.16")
    assert package.read_bytes() == reproduced.read_bytes()
    assert package.name == "zaptrace-review-studio_0.1.16_all.deb"
    target = tmp_path / "installed"
    subprocess.run(["dpkg-deb", "-x", str(package), str(target)], check=True, timeout=15)
    root = target / "usr/lib/zaptrace-review-studio/scripts"
    html = (root / "review_studio_native_template.html").read_text()
    assert "max-height:calc(100% - 247px);overflow-y:auto" in html
    assert "render3dModelDiagnostics" in html
    assert "model_assets" in (root / "review_studio_native_kicad.py").read_text()
    workspace = (root / "review_studio_workspace_template.html").read_text()
    assert "0.1.16" in workspace
