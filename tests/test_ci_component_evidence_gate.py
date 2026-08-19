from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci_component_evidence_gate import main


def test_component_evidence_gate_passes_empty_verified_subset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    library_root = tmp_path / "library"
    library_root.mkdir()
    manifest_path = tmp_path / "component-evidence.json"
    manifest_path.write_text(
        json.dumps({"schema_version": "1.0", "components": {}}),
        encoding="utf-8",
    )
    output = tmp_path / "component-evidence-gate.json"

    code = main(
        [
            "--library-root",
            str(library_root),
            "--manifest",
            str(manifest_path),
            "--as-of",
            "2026-08-09",
            "--strict",
            "--output",
            str(output),
        ]
    )
    result = json.loads(output.read_text(encoding="utf-8"))

    assert code == 0
    assert result["blocked"] is False
    assert result["verified_component_count"] == 0
    assert result["manifest_component_count"] == 0
    assert result["library_error_count"] == 0


def test_committed_manifest_preserves_current_heuristic_library(tmp_path: Path) -> None:
    output = tmp_path / "component-evidence-gate.json"

    code = main(
        [
            "--manifest",
            "config/component-evidence-manifest.json",
            "--as-of",
            "2026-08-09",
            "--strict",
            "--output",
            str(output),
        ]
    )
    result = json.loads(output.read_text(encoding="utf-8"))

    assert code == 0
    assert result["blocked"] is False
    assert result["verified_component_count"] == 0
    assert result["manifest_component_count"] == 0
    assert result["bound_verified_component_count"] == 0
    assert result["library_error_count"] == 0


def test_quality_workflow_runs_component_evidence_gate() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "- name: Component evidence gate" in workflow
    assert "scripts/ci_component_evidence_gate.py" in workflow
    assert "--manifest config/component-evidence-manifest.json" in workflow
    assert "--strict" in workflow
    assert "--output component-evidence-gate.json" in workflow
