"""Review annotations must be source-bound, session-only and never waive native DRC."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from review_studio_build_deb import build  # noqa: E402


def test_native_triage_cannot_override_drc_or_fabrication() -> None:
    html = (ROOT / "scripts/review_studio_native_template.html").read_text()
    assert "kind:'human_review_notes_not_verified_approval'" in html
    assert "source_sha256:DATA.source_sha256" in html
    assert "fabrication_approved:false,source_modified:false,all_findings_remain_unwaived:true" in html
    assert "const triageNotes=new Map()" in html
    assert "triageNotes.set(index,{status:value,note:content})" in html
    assert "updateTriageSummary();renderList();" in html
    assert "DATA.findings[index]" in html
    assert "REVIEW NOTE: repair required" in html
    assert "REVIEW NOTE: investigated" in html
    assert "URL.createObjectURL(blob)" in html
    assert "link.download='zaptrace-review-notes-'" in html
    assert "Local session only" in html
    assert "No KiCad DRC changes, no automatic waiver or manufacturing approval" in html
    assert 'role="status" aria-live="polite"' in html
    assert 'id="exportTriage"' in html
    assert 'id="importTriage"' in html
    assert 'id="triageFile"' in html
    assert "input.source_sha256!==DATA.source_sha256" in html
    assert "JSON.stringify(x.source_objects)!==JSON.stringify(original.objects)" in html
    assert "next.has(x.finding_index)" in html
    assert "triageNotes.clear();for(const [id,entry] of next)triageNotes.set(id,entry)" in html
    assert "Review notes are unsigned" in html
    assert "notes.maxLength=600" in html
    assert "localStorage.setItem(" in html  # only existing explicitly scoped layout prefs
    assert (
        "localStorage.setItem("
        not in html[html.index("const triageNotes=new Map()") : html.index("function node(tag,cls,text)")]
    )


def test_020_exact_deb_contains_review_editor_and_download(tmp_path: Path) -> None:
    first = build(ROOT, tmp_path / "main", version="0.1.20")
    second = build(ROOT, tmp_path / "repro", version="0.1.20")
    assert first.read_bytes() == second.read_bytes()
    extraction = tmp_path / "install"
    subprocess.run(["dpkg-deb", "-x", str(first), str(extraction)], check=True, timeout=15)
    scripts = extraction / "usr/lib/zaptrace-review-studio/scripts"
    src = (scripts / "review_studio_native_template.html").read_text()
    assert "human_review_notes_not_verified_approval" in src
    assert "showTriageEditor(d,sel.index)" in src
    assert "updateTriageSummary();renderList()" in src
    assert "downloadTriage" in src
    assert not any(k in src for k in ("fabrication_approved:true", "full_approval:true"))
