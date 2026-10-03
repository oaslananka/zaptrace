from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci_component_evidence_gate import _resolve_output_cli_path, main


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


def test_output_path_confined_to_workspace_or_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert _resolve_output_cli_path(None, label="Output path") is None
    assert _resolve_output_cli_path(tmp_path / "gate.json", label="Output path") == (tmp_path / "gate.json").resolve()
    assert (
        _resolve_output_cli_path(Path("reports") / "gate.json", label="Output path")
        == (tmp_path / "reports" / "gate.json").resolve()
    )


def test_output_path_rejects_escape_from_allowed_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    outside = Path(tmp_path.anchor) / "zaptrace-escape-probe.json"

    with pytest.raises(ValueError, match="outside allowed roots"):
        _resolve_output_cli_path(outside, label="Output path")
    assert not outside.exists()


def test_output_path_accepts_runner_temp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    target = runner_temp / "summaries" / "gate.md"

    assert _resolve_output_cli_path(target, label="Markdown path") == target.resolve()
