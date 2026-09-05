from __future__ import annotations

import json
from pathlib import Path

from scripts.ci_component_qualification_gate import run_gate
from zaptrace.library.qualification import ComponentQualificationReport

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COHORT = REPOSITORY_ROOT / "data/qualification/verified-core-cohort-a.yaml"
SCHEMA = REPOSITORY_ROOT / "schemas/component-qualification-report-v1.schema.json"


def test_strict_gate_fails_closed_on_known_machine_blockers(tmp_path: Path) -> None:
    output = tmp_path / "qualification.json"
    code, report = run_gate(
        cohort_path=COHORT,
        repository_root=REPOSITORY_ROOT,
        output_path=output,
    )

    assert code == 1
    assert report.review_ready_count == 2
    assert report.machine_blocked_count == 3
    assert report.human_review_required_count == 5
    assert report.release_eligible_count == 0
    assert json.loads(output.read_text(encoding="utf-8"))["report_sha256"] == report.report_sha256


def test_report_only_mode_does_not_relabel_blocked_components_as_ready(tmp_path: Path) -> None:
    code, report = run_gate(
        cohort_path=COHORT,
        repository_root=REPOSITORY_ROOT,
        output_path=tmp_path / "qualification.json",
        report_only=True,
    )

    assert code == 0
    assert report.machine_blocked_count == 3
    assert {row.component_id for row in report.components if row.review_ready} == {
        "esp32-c3-mini-1",
        "bme280",
    }


def test_committed_report_schema_matches_model() -> None:
    expected = ComponentQualificationReport.model_json_schema()
    observed = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert observed == expected
