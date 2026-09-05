from __future__ import annotations

import json
from pathlib import Path

from scripts.ci_component_qualification_gate import run_gate
from zaptrace.library.qualification import ComponentQualificationReport

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COHORT = REPOSITORY_ROOT / "data/qualification/verified-core-cohort-a.yaml"
SCHEMA = REPOSITORY_ROOT / "schemas/component-qualification-report-v1.schema.json"


def test_strict_gate_passes_after_machine_evidence_is_bound(tmp_path: Path) -> None:
    output = tmp_path / "qualification.json"
    code, report = run_gate(
        cohort_path=COHORT,
        repository_root=REPOSITORY_ROOT,
        output_path=output,
    )

    assert code == 0
    assert report.review_ready_count == 5
    assert report.machine_blocked_count == 0
    assert report.human_review_required_count == 5
    assert report.release_eligible_count == 0
    assert json.loads(output.read_text(encoding="utf-8"))["report_sha256"] == report.report_sha256


def test_report_only_mode_preserves_machine_ready_and_human_blocked_state(tmp_path: Path) -> None:
    code, report = run_gate(
        cohort_path=COHORT,
        repository_root=REPOSITORY_ROOT,
        output_path=tmp_path / "qualification.json",
        report_only=True,
    )

    assert code == 0
    assert report.machine_blocked_count == 0
    assert {row.component_id for row in report.components if row.review_ready} == {
        "esp32-c3-mini-1",
        "usb-c-16p",
        "ap2112k-3.3",
        "bme280",
        "atecc608b",
    }
    assert report.human_review_required_count == 5
    assert report.release_eligible_count == 0


def test_committed_report_schema_matches_model() -> None:
    expected = ComponentQualificationReport.model_json_schema()
    observed = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert observed == expected
