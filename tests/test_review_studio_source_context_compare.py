"""Snapshot comparison never promotes incompatible native KiCad DRC count deltas."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/review_studio_workspace.py"
SPEC = importlib.util.spec_from_file_location("compare_native_context", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
workspace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workspace)


def _review(root: Path, *, source: str, context: str | None, open_findings: int) -> Path:
    root.mkdir()
    (root / "index.html").write_text("<title>source</title>")
    (root / "REVIEW_REPORT.html").write_text("Independent KiCad DRC · no production approval")
    evidence = {
        "source_sha256": source,
        "board_name": "Verified board",
        "drc_state": "reported",
        "board": {
            "pads": [{"ref": "U1", "pad": "1"}],
            "copper": [{"net": "GND"}],
            "size": [80.0, 60.0],
            "kicad": "10.0.7-10.0.7~ubuntu24.04.1",
        },
        "findings": [{"rule": "unconnected_items"}] * open_findings + [{"rule": "hole_clearance"}],
        "erc": {"state": "reported", "count": 2},
        "project_settings": {
            "project_provided": True,
            "custom_rules_provided": False,
            "analysis_context_sha256": context,
        },
    }
    (root / "evidence.json").write_text(json.dumps(evidence))
    return root


@pytest.mark.parametrize("different_context", [True, False])
def test_verification_context_controls_comparability(tmp_path: Path, different_context: bool) -> None:
    a = _review(tmp_path / "a", source="a" * 64, context="b" * 64, open_findings=12)
    b = _review(
        tmp_path / "b",
        source="c" * 64 if different_context else "a" * 64,
        context="d" * 64 if different_context else "b" * 64,
        open_findings=35,
    )
    entries = [
        {"name": "Source A", "review": a, "evidence": workspace._evidence(a)},
        {"name": "Source B", "review": b, "evidence": workspace._evidence(b)},
    ]
    html = workspace.workspace_html(tmp_path / "catalog", entries)
    assert html.count('data-analysis-context="') == 2
    assert html.count('data-kicad-tool="10.0.7-10.0.7~ubuntu24.04.1"') == 2
    assert f'data-analysis-context="{"d" * 64 if different_context else "b" * 64}"' in html
    assert "SOURCE / ANALYSIS CONTEXT OR KICAD TOOL UNVERIFIED" in html
    assert "NOT COMPARABLE" in html
    assert "NEXT ACTION: inspect both source reviews and evidence reports" in html
    assert "2 of 2 snapshots · inspect evidence only" in html
    assert "COUNT ONLY" in html
    assert "MATCHED SOURCE, INPUTS AND KICAD TOOL · NOT FABRICATION EQUIVALENCE" in html
    assert "sameContext&&sameSource&&sameTool&&!settingsDiffer" in html
    assert "NOT FABRICATION APPROVED" in html


def test_missing_or_invalid_context_is_never_implicitly_equivalent(tmp_path: Path) -> None:
    a = _review(tmp_path / "a", source="a" * 64, context=None, open_findings=5)
    b = _review(tmp_path / "b", source="b" * 64, context="bad<untrusted>", open_findings=10)
    entries = [
        {"name": "Unverified A", "review": a, "evidence": workspace._evidence(a)},
        {"name": "Unverified B", "review": b, "evidence": workspace._evidence(b)},
    ]
    html = workspace.workspace_html(tmp_path / "catalog", entries)
    assert html.count('data-analysis-context=""') == 2
    assert "bad<untrusted>" not in html
    assert "SOURCE / ANALYSIS CONTEXT OR KICAD TOOL UNVERIFIED" in html
