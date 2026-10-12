"""Real KiCad PCB canvas shall be keyboard navigable without 150+ Tab stops."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_single_canvas_tab_stop_arrow_navigation_and_selection_remain_source_readonly() -> None:
    native = (ROOT / "scripts/review_studio_native_template.html").read_text()
    assert "const MARKER_SELECTOR='.fp-hit,.pad-hit,.fault'" in native
    assert "for(const marker of stage.querySelectorAll(MARKER_SELECTOR))marker.tabIndex=-1" in native
    assert "stage.setAttribute('role','group')" in native
    assert "stage.addEventListener('focusin',event=>" in native
    assert "stage.addEventListener('keydown',event=>" in native
    assert "['ArrowRight','ArrowDown','ArrowLeft','ArrowUp','Home','End']" in native
    assert "event.preventDefault();event.stopPropagation();event.target.click();return;" in native
    assert (
        "const markers=sel.kind==='part'?focusButtons.parts:sel.kind==='pad'?focusButtons.pads:focusButtons.issues"
        in native
    )
    assert "stage.classList.toggle(cls,!$(id).checked);roveCanvasMarker();updatePreferences()" in native
    assert "const restoreFromHidden=active instanceof Element&&stage.contains(active)" in native
    assert "if((moveFocus||restoreFromHidden)&&chosen)chosen.focus({preventScroll:true})" in native
    assert "Ctrl K" in native
    assert "NOT FABRICATION APPROVED" in native
    assert "all_findings_remain_unwaived:true" in native


def test_025_deb_exact_bytes_and_embedded_ki_cad_keyboard_ui(tmp_path: Path) -> None:
    module = ROOT / "scripts/review_studio_build_deb.py"
    spec = importlib.util.spec_from_file_location("candidate_024", module)
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    assert "0.1.25" in builder.ACCEPTED_LOCAL_VERSIONS
    a = builder.build(ROOT, tmp_path / "first", version="0.1.25")
    b = builder.build(ROOT, tmp_path / "repro", version="0.1.25")
    assert a.read_bytes() == b.read_bytes() and a.read_bytes().startswith(b"!<arch>\n")
    out = tmp_path / "installed"
    subprocess.run(["dpkg-deb", "-x", str(a), str(out)], check=True, timeout=15)
    html = (out / builder.APP_ROOT / "review_studio_native_template.html").read_text()
    assert "function bindCanvasRoving()" in html
    assert "function roveCanvasMarker(target=null,moveFocus=false)" in html
    assert "h.focus({preventScroll:true})" in html
    assert "#render3dNext{grid-column:4;grid-row:2}" in html
    assert "all_findings_remain_unwaived:true" in html
