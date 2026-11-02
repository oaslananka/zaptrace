"""A narrow phone must not hide or compress the native KiCad 3D camera controls."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "scripts/review_studio_native_template.html"
BUILDER = ROOT / "scripts/review_studio_build_deb.py"


def test_021_mobile_camera_controls_preserve_native_eight_frame_review() -> None:
    html = CSS.read_text()
    assert "@media(max-width:420px){" in html
    for selector in (
        "#render3dIso{grid-column:1/span 2;grid-row:1}",
        "#render3dTop{grid-column:3/span 2;grid-row:1}",
        "#render3dPrevious{grid-column:1;grid-row:2}",
        ".render3d-angle{grid-column:2/span 2;grid-row:2;min-height:44px}",
        "#render3dNext{grid-column:4;grid-row:2}",
        "max-height:calc(100% - 247px);overflow-y:auto;overscroll-behavior:contain",
        ".render3d-actions button{font-size:11px;min-height:44px;",
    ):
        assert selector in html
    for field in ("render3dPrevious", "render3dNext", "render3dFrameCount", "render3dAngle"):
        assert f'id="{field}"' in html
    assert "DATA.render3d?.orbit_frames?.length===8" in html
    assert "MODEL COVERAGE UNVERIFIED" in html
    assert "NOT FABRICATION APPROVED" in html
    assert (
        "model_geometry_approved"
        not in html[html.index("/* Real KiCad camera turntable") : html.index("/* The mobile inspector")]
    )


def test_021_unsigned_debian_candidate_is_byte_reproducible_and_has_real_mobile_css(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("local_021_builder", BUILDER)
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    assert "0.1.21" in builder.ACCEPTED_LOCAL_VERSIONS
    a = builder.build(ROOT, tmp_path / "first", version="0.1.21")
    b = builder.build(ROOT, tmp_path / "second", version="0.1.21")
    assert a.read_bytes() == b.read_bytes()
    assert a.read_bytes().startswith(b"!<arch>\n")
    install = tmp_path / "installed"
    subprocess.run(["dpkg-deb", "-x", str(a), str(install)], check=True, timeout=15)
    ui = (install / builder.APP_ROOT / "review_studio_native_template.html").read_text()
    assert "#render3dNext{grid-column:4;grid-row:2}" in ui
    assert "FABRICATION APPROVED" not in ui.replace("NOT FABRICATION APPROVED", "")
    assert "render3dModelDiagnostics" in ui
    assert "render3dPrevious" in ui
    assert "render3dNext" in ui
