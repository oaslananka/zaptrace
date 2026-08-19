from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.ci_component_metadata_gate import build_gate_summary, main
from zaptrace.library.loader import LibraryLoader


def _write_part(root: Path, comp_id: str, *, datasheet: str = "https://example.com/ds.pdf") -> None:
    path = root / "power" / f"{comp_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(
            {
                "id": comp_id,
                "name": comp_id,
                "category": "power",
                "manufacturer": "Acme",
                "mpn": f"{comp_id}-MPN",
                "datasheet": datasheet,
                "package": "SOT-23-5",
                "footprint": "SOT-23-5",
                "pins": {"1": {"type": "input"}},
                "electrical_limits": {"max_voltage_v": 6},
                "sourcing": {"authorized_distributors": ["Digi-Key"]},
                "compliance": {"rohs": True},
                "provenance": {"source": "test-fixture", "reviewed_by": "ci"},
                "schema_version": "2.0",
                "trust_tier": "heuristic",
                "field_provenance": {
                    field: {
                        "source_type": "internal_manifest",
                        "source_locator": "test-fixture",
                        "source_identity": "fixture-v1",
                        "source_version": "1",
                        "extraction_method": "test-fixture",
                        "confidence": "low",
                    }
                    for field in (
                        "mpn",
                        "datasheet",
                        "pin_map",
                        "package",
                        "footprint",
                        "electrical_limits",
                        "lifecycle",
                        "sourcing",
                    )
                },
            }
        ),
        encoding="utf-8",
    )


def test_component_metadata_gate_passes_within_budget(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _write_part(root, "good")
    out = tmp_path / "gate.json"
    code = main(
        ["--library-root", str(root), "--max-errors", "0", "--max-warnings", "0", "--strict", "--output", str(out)]
    )
    data = json.loads(out.read_text(encoding="utf-8"))

    assert code == 0
    assert data["blocked"] is False
    assert data["component_count"] == 1


def test_component_metadata_gate_fails_when_errors_exceed_budget(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _write_part(root, "bad", datasheet="")
    out = tmp_path / "gate.json"

    code = main(
        ["--library-root", str(root), "--max-errors", "0", "--max-warnings", "99", "--strict", "--output", str(out)]
    )
    data = json.loads(out.read_text(encoding="utf-8"))

    assert code == 1
    assert data["blocked"] is True
    assert data["error_count"] == 1
    assert data["report"]["validations"][0]["findings"][0]["field"] == "datasheet"


def test_build_gate_summary_allows_baseline_budget(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _write_part(root, "bad", datasheet="")
    report = LibraryLoader(root).governance_report()

    summary = build_gate_summary(report, max_errors=1, max_warnings=99)

    assert summary["blocked"] is False
    assert summary["error_count"] == 1


def test_component_metadata_release_gate_blocks_heuristic_records(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _write_part(root, "heuristic")
    out = tmp_path / "gate.json"

    code = main(
        [
            "--library-root",
            str(root),
            "--max-errors",
            "0",
            "--max-warnings",
            "99",
            "--require-release-eligible",
            "--strict",
            "--output",
            str(out),
        ]
    )
    data = json.loads(out.read_text(encoding="utf-8"))

    assert code == 1
    assert data["blocked"] is True
    assert data["release_eligible_count"] == 0
    assert data["blocked_component_count"] == 1
    assert data["trust_tier_counts"] == {"heuristic": 1}


def test_component_metadata_gate_enforces_monotonic_trust_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from zaptrace.library.trust_baseline import generate_trust_baseline, write_trust_baseline

    root = tmp_path / "library"
    _write_part(root, "part")
    baseline = generate_trust_baseline(LibraryLoader(root).load_all())
    baseline_path = write_trust_baseline(baseline, tmp_path / "baseline.json")

    component_path = root / "power" / "part.yaml"
    payload = yaml.safe_load(component_path.read_text(encoding="utf-8"))
    payload["trust_tier"] = "placeholder"
    component_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    out = tmp_path / "gate.json"
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--library-root",
            str(root),
            "--trust-baseline",
            str(baseline_path),
            "--max-errors",
            "0",
            "--max-warnings",
            "99",
            "--strict",
            "--output",
            str(out),
        ]
    )
    data = json.loads(out.read_text(encoding="utf-8"))

    assert code == 1
    assert data["trust_baseline"]["passed"] is False
    assert data["trust_baseline"]["downgraded_component_ids"] == ["part"]


def test_quality_workflow_enforces_component_trust_baseline() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    component_gate = workflow[
        workflow.index("- name: Component metadata gate") : workflow.index("\n  mcp-compatibility:")
    ]

    assert "--trust-baseline config/component-trust-baseline.json" in component_gate
