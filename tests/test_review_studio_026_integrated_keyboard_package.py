"""The first immutable combined 0.1.26 candidate retains real EDA UX contracts."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_native_source_preserves_combined_mobile_and_keyboard_a11y() -> None:
    html = (ROOT / "scripts/review_studio_native_template.html").read_text()
    assert "function bindCanvasRoving()" in html
    assert "if((moveFocus||restoreFromHidden)&&chosen)chosen.focus({preventScroll:true})" in html
    assert "if(withPan && sel.kind==='issue' && window.innerWidth<=750)" in html
    assert "h.focus({preventScroll:true})" in html
    assert "#render3dNext{grid-column:4;grid-row:2}" in html
    assert "max-height:calc(100% - 247px);overflow-y:auto;overscroll-behavior:contain" in html
    assert "all_findings_remain_unwaived:true" in html
    assert "NOT FABRICATION APPROVED" in html


def test_026_exact_package_reproducible_and_contract_inside_deb(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("package_026", ROOT / "scripts/review_studio_build_deb.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "0.1.26" in mod.ACCEPTED_LOCAL_VERSIONS
    one = mod.build(ROOT, tmp_path / "first", version="0.1.26")
    two = mod.build(ROOT, tmp_path / "repro", version="0.1.26")
    assert one.read_bytes() == two.read_bytes()
    assert one.read_bytes().startswith(b"!<arch>\n")
    target = tmp_path / "unpacked"
    subprocess.run(["dpkg-deb", "-x", str(one), str(target)], check=True, timeout=15)
    installed = (target / mod.APP_ROOT / "review_studio_native_template.html").read_text()
    assert "function bindCanvasRoving()" in installed
    assert "h.focus({preventScroll:true})" in installed
    assert "#render3dNext{grid-column:4;grid-row:2}" in installed
    assert "fabrication_approved:false" in installed
