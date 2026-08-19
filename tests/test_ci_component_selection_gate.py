from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.ci_component_selection_gate import build_gate_report, main
from zaptrace.library.migration import migrate_record


def _write_part(root: Path, part_id: str, *, category: str = "power") -> None:
    raw = {
        "id": part_id,
        "name": part_id,
        "category": category,
        "manufacturer": "Acme",
        "mpn": f"{part_id}-MPN",
        "description": "fixture",
        "datasheet": f"https://manufacturer.example/{part_id}.pdf",
        "package": "SOT-23-5",
        "footprint": "SOT-23-5",
        "pins": {"1": {"function": "VIN"}, "2": {"function": "GND"}},
        "electrical_limits": {"max_voltage_v": 6.0},
        "sourcing": {"status": "active"},
        "compliance": {"rohs": True},
        "provenance": {"source": "test-fixture"},
    }
    migrated, _changed = migrate_record(raw)
    path = root / category / f"{part_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(migrated, sort_keys=False), encoding="utf-8")


def _write_corpus(path: Path, *, candidate_id: str = "part-a") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "id": "fixture-selection",
                    "position": "U1",
                    "category": "power",
                    "candidate_ids": [candidate_id],
                    "expected_selected_id": candidate_id,
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_gate_passes_when_governed_coverage_and_corpus_meet_budget(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _write_part(root, "part-a")
    _write_part(root, "part-b")
    corpus = tmp_path / "prompts.yaml"
    _write_corpus(corpus)

    report = build_gate_report(root, corpus, minimum_governed_parts=2, allowed_root=tmp_path)

    assert report["passed"] is True
    assert report["governed_datasheet_and_footprint_count"] == 2
    assert report["verified_datasheet_and_footprint_count"] == 0
    assert report["release_eligible_count"] == 0
    assert report["human_review_required_count"] == 2
    assert report["corpus_case_count"] == 1
    assert report["corpus_passed_count"] == 1
    assert report["historical_snapshot"] is True
    assert report["evidence_status"] == "historical-governance-snapshot"


def test_strict_gate_fails_below_minimum_coverage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "library"
    _write_part(root, "part-a")
    corpus = tmp_path / "prompts.yaml"
    _write_corpus(corpus)
    output = tmp_path / "coverage.json"
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--library-root",
            str(root),
            "--corpus",
            str(corpus),
            "--minimum-governed-parts",
            "2",
            "--output",
            str(output),
            "--strict",
        ]
    )
    report = json.loads(output.read_text(encoding="utf-8"))

    assert code == 1
    assert report["passed"] is False
    assert report["coverage_shortfall"] == 1


def test_gate_reports_missing_corpus_component_ids(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _write_part(root, "part-a")
    corpus = tmp_path / "prompts.yaml"
    _write_corpus(corpus, candidate_id="missing-part")

    report = build_gate_report(root, corpus, minimum_governed_parts=1, allowed_root=tmp_path)

    assert report["passed"] is False
    assert report["corpus_failed_count"] == 1
    assert report["errors"] == ["fixture-selection: missing candidate id missing-part"]


def test_gate_report_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _write_part(root, "part-a")
    corpus = tmp_path / "prompts.yaml"
    _write_corpus(corpus)

    first = build_gate_report(root, corpus, minimum_governed_parts=1, allowed_root=tmp_path)
    second = build_gate_report(root, corpus, minimum_governed_parts=1, allowed_root=tmp_path)

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_quality_workflow_runs_component_selection_coverage_gate() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "scripts/ci_component_selection_gate.py" in workflow
    assert "--minimum-governed-parts 100" in workflow
    assert "tests/fixtures/component_selection/prompts.yaml" in workflow


def test_gate_rejects_corpus_outside_explicit_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    root = workspace / "library"
    _write_part(root, "part-a")
    corpus = tmp_path / "outside-prompts.yaml"
    _write_corpus(corpus)

    with pytest.raises(ValueError, match="outside allowed root"):
        build_gate_report(root, corpus, minimum_governed_parts=1, allowed_root=workspace)


def test_gate_rejects_symlinked_corpus(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _write_part(root, "part-a")
    target = tmp_path / "prompts.yaml"
    _write_corpus(target)
    link = tmp_path / "linked-prompts.yaml"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="symbolic link"):
        build_gate_report(root, link, minimum_governed_parts=1, allowed_root=tmp_path)
