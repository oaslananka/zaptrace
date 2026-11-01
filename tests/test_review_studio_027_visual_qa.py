"""Real KiCad 3D canvas remains visible and ERC warnings never become false errors."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "scripts/review_studio_native_template.html"


def test_027_native_3d_viewport_reserves_model_clearance_and_explicit_erc_severity() -> None:
    html = TEMPLATE.read_text()
    assert "const controls=$('render3dControls')" in html
    assert "extent.bottom-controls.getBoundingClientRect().top+18" in html
    assert "Math.max(110,uiBottom+18)" in html
    assert "$('render3dModelDiagnostics').addEventListener('toggle'" in html
    assert "min-height:1010px;height:max(100dvh,1010px);overflow:hidden" in html
    assert "height:950px;min-height:950px" in html
    assert "const ercVerified=['reported','no_reported_findings'].includes(er.state)" in html
    assert "ercErrors?'critical':ercWarnings||ercUnclassified?'warn'" in html
    assert "ercErrors?'danger':ercWarnings||ercUnclassified?'caution'" in html
    assert "const ercCountText=ercErrors+' errors · '+ercWarnings+' warnings'" in html
    assert '<span class="health-note" id="kpiErcNote">Enabled rules only</span>' in html
    assert "NOT FABRICATION APPROVED" in html
    assert "all_findings_remain_unwaived:true" in html


def test_027_package_reproducible_with_actual_3d_and_erc_controls(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("local_027", ROOT / "scripts/review_studio_build_deb.py")
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    assert "0.1.27" in builder.ACCEPTED_LOCAL_VERSIONS
    first = builder.build(ROOT, tmp_path / "first", version="0.1.27")
    again = builder.build(ROOT, tmp_path / "again", version="0.1.27")
    assert first.read_bytes() == again.read_bytes()
    assert first.read_bytes().startswith(b"!<arch>\n")
    output = tmp_path / "installed"
    subprocess.run(["dpkg-deb", "-x", str(first), str(output)], check=True, timeout=15)
    original = (output / builder.APP_ROOT / "review_studio_native_template.html").read_text()
    assert "function bindCanvasRoving()" in original
    assert "extent.bottom-controls.getBoundingClientRect().top+18" in original
    assert "ercErrors?'critical':ercWarnings||ercUnclassified?'warn'" in original
    assert "fabrication_approved:false" in original
