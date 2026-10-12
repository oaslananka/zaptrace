"""Two mobile improvements must ship together without changing KiCad verification claims."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mobile_3d_diagnostics_and_real_finding_focus_share_safe_source() -> None:
    s = (ROOT / "scripts/review_studio_native_template.html").read_text()
    assert s.count("@media(max-width:420px){") >= 1
    assert "max-height:calc(100% - 247px);overflow-y:auto;overscroll-behavior:contain" in s
    assert "#render3dNext{grid-column:4;grid-row:2}" in s
    assert "withPan && sel.kind==='issue' && window.innerWidth<=750" in s
    assert "h.focus({preventScroll:true})" in s
    assert "if(selected?.kind!=='issue'||selected.index!==sel.index||!h.isConnected)return" in s
    assert "all_findings_remain_unwaived:true" in s
    assert "NOT FABRICATION APPROVED" in s


def test_local_023_package_byte_for_byte_reproducible(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("build_023", ROOT / "scripts/review_studio_build_deb.py")
    assert spec and spec.loader
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    assert "0.1.23" in build.ACCEPTED_LOCAL_VERSIONS
    a = build.build(ROOT, tmp_path / "first", version="0.1.23")
    b = build.build(ROOT, tmp_path / "reproduction", version="0.1.23")
    assert a.read_bytes() == b.read_bytes()
    assert a.read_bytes().startswith(b"!<arch>\n")
    unpack = tmp_path / "unpacked"
    subprocess.run(["dpkg-deb", "-x", str(a), str(unpack)], check=True, timeout=15)
    template = (unpack / build.APP_ROOT / "review_studio_native_template.html").read_text()
    assert "#render3dNext{grid-column:4;grid-row:2}" in template
    assert "max-height:calc(100% - 247px);overflow-y:auto;overscroll-behavior:contain" in template
    assert "h.focus({preventScroll:true})" in template
    assert "fabrication_approved:false" in template
