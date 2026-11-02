"""Actual 390px Chrome visual findings remain a local RC packaging blocker."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from review_studio_build_deb import build  # noqa: E402


def test_native_three_d_mobile_readable_warning_must_span_grid_row() -> None:
    html = (ROOT / "scripts/review_studio_native_template.html").read_text()
    assert ".render3d-warning{display:block;grid-column:1/-1;" in html
    assert 'id="render3dModelDiagnostics"' in html
    assert 'id="render3dModelDetails"' in html
    smoke = (ROOT / "scripts/review_studio_015_model_browser_smoke.mjs").read_text()
    shared = (ROOT / "scripts/review_studio_model_browser_smoke_shared.mjs").read_text()
    assert "mobile.warningWidth>=mobile.actionGridWidth*.88" in shared
    assert "mobile.warningHeight<85" in shared
    assert "EXACT_015_SOURCE_LINKED_3D_MODEL_DIAGNOSTIC_CHROME=PASS" in smoke


def test_015_package_contains_new_mobile_layout_and_keeps_versions_isolated(tmp_path: Path) -> None:
    artifact = build(ROOT, tmp_path / "package", version="0.1.15")
    assert artifact.name == "zaptrace-review-studio_0.1.15_all.deb"
    extracted = tmp_path / "extracted"
    subprocess.run(["dpkg-deb", "-x", str(artifact), str(extracted)], check=True, timeout=18)
    scripts = extracted / "usr/lib/zaptrace-review-studio/scripts"
    native = (scripts / "review_studio_native_template.html").read_text()
    assert ".render3d-warning{display:block;grid-column:1/-1;" in native
    assert 'id="render3dModelSummary"' in native
    assert "_model_inventory" in (scripts / "review_studio_native_kicad.py").read_text()
    workspace = (scripts / "review_studio_workspace_template.html").read_text()
    assert "0.1.15" in workspace and "0.1.14" not in workspace
    executable = extracted / "usr/bin/zaptrace-review-studio"
    version = subprocess.run(
        [str(executable), "--version"], check=True, capture_output=True, text=True, timeout=10
    ).stdout
    assert "0.1.15" in version
    assert build(ROOT, tmp_path / "repro", version="0.1.15").read_bytes() == artifact.read_bytes()
