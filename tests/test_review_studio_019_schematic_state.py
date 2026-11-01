"""Source-proven empty KiCad hierarchical pages must never look like a broken render."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from review_studio_build_deb import build  # noqa: E402
from review_studio_native_kicad import schematic_svg_drawn_elements  # noqa: E402


def test_actual_kicad_empty_child_must_not_be_conflated_with_render_failure() -> None:
    source = ROOT / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"
    multi = ROOT / "build/native-multi-sheet-test/index.html"
    current = ROOT / "build/native-review/index.html"
    if not multi.is_file() or not current.is_file():
        pytest.skip("Requires prior local KiCad multi-sheet/browser QA exports")
    html = multi.read_text()
    payload = re.search(r"(?m)^const DATA=(.*);$", html)
    assert payload, "First regenerate real KiCad source using native local build"
    data = json.loads(payload.group(1))
    assert data["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    pages = data["schematic"]["pages"]
    assert len(pages) == 2
    assert pages[0]["name"] == "Root sheet" and pages[1]["name"] == "Power supply"
    counts = [schematic_svg_drawn_elements(base64.b64decode(p["src"].split(",", 1)[1], validate=True)) for p in pages]
    assert counts[0] > 5000 and counts[1] == 0
    assert pages[1]["root_only_crossprobe"] is False
    native_data = re.search(r"(?m)^const DATA=(.*);$", current.read_text())
    assert native_data
    rendered = json.loads(native_data.group(1))
    assert rendered["schematic"]["pages"][0]["drawn_element_count"] > 0


def test_empty_state_is_semantic_and_only_available_in_schematic_mode() -> None:
    html = (ROOT / "scripts/review_studio_native_template.html").read_text()
    assert 'id="schematicEmptyState"' in html
    assert 'role="status" aria-live="polite" hidden' in html
    assert "page.drawn_element_count===0" in html
    assert "mode!=='schematic'||DATA.schematic?.pages?.[schematicPageIndex]?.drawn_element_count!==0" in html
    assert "No drawings on this original KiCad sheet" in html
    assert "not a rendering failure" in html
    assert "min-width:38px;min-height:38px" in html
    js = (ROOT / "scripts/review_studio_019_multisheet_responsive_browser_smoke.mjs").read_text()
    shared = (ROOT / "scripts/review_studio_multisheet_browser_smoke_shared.mjs").read_text()
    assert "SOURCE_VERIFIED_KICAD_EMPTY_CHILD_STATE" in shared
    assert "EXACT_019_MULTISHEET_NARROW_CHROME_GEOMETRY=PASS" in js
    assert "result.empty.bottom<=result.dock.top+2" in shared


def test_019_package_contains_source_aware_blank_page_and_touch_targets(tmp_path: Path) -> None:
    a = build(ROOT, tmp_path / "first", version="0.1.19")
    b = build(ROOT, tmp_path / "repro", version="0.1.19")
    assert a.read_bytes() == b.read_bytes()
    folder = tmp_path / "extracted"
    subprocess.run(["dpkg-deb", "-x", str(a), str(folder)], check=True, timeout=12)
    scripts = folder / "usr/lib/zaptrace-review-studio/scripts"
    html = (scripts / "review_studio_native_template.html").read_text()
    extractor = (scripts / "review_studio_native_kicad.py").read_text()
    assert 'id="schematicEmptyState"' in html
    assert "drawn_element_count" in extractor
    assert "min-height:38px" in html
    assert "0.1.19" in (scripts / "review_studio_workspace_template.html").read_text()
