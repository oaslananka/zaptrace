"""CI contracts for the shared Hardware and KiCad Python bootstrap."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SHARED_ACTION = "./.github/actions/setup-locked-python"


@pytest.mark.parametrize(
    ("workflow_name", "expected_jobs"),
    [
        ("hardware.yml", {"regression": "Export regression", "examples": "Example designs", "kicad": "KiCad oracle"}),
        ("kicad-oracle.yml", {"oracle": "Run KiCad oracle"}),
    ],
)
def test_hardware_oracle_jobs_reuse_pinned_locked_python(workflow_name: str, expected_jobs: dict[str, str]) -> None:
    workflow = yaml.safe_load((WORKFLOWS / workflow_name).read_text(encoding="utf-8"))
    assert workflow["permissions"] == {"contents": "read"}
    assert {"PYTHON_VERSION": "3.13", "UV_VERSION": "0.11"}.items() <= workflow["env"].items()

    for job_id, expected_name in expected_jobs.items():
        job = workflow["jobs"][job_id]
        assert job["name"] == expected_name
        steps = job["steps"]
        assert steps[0]["uses"].startswith("actions/checkout@")
        assert steps[0]["with"]["persist-credentials"] is False

        bootstraps = [step for step in steps if step.get("uses") == SHARED_ACTION]
        assert len(bootstraps) == 1, (workflow_name, job_id)
        bootstrap = bootstraps[0]
        assert bootstrap["with"] == {
            "uv-version": "${{ env.UV_VERSION }}",
            "python-version": "${{ env.PYTHON_VERSION }}",
        }
        assert "if" not in bootstrap
        assert steps.index(bootstrap) == 1
        assert not any(step.get("uses", "").startswith("astral-sh/setup-uv@") for step in steps)


@pytest.mark.parametrize(
    ("workflow_name", "job_id", "run_step"),
    [("hardware.yml", "kicad", "Run KiCad oracle"), ("kicad-oracle.yml", "oracle", "Run focused oracle checks")],
)
def test_kicad_oracle_retains_cli_install_and_evidence_upload(workflow_name: str, job_id: str, run_step: str) -> None:
    workflow = yaml.safe_load((WORKFLOWS / workflow_name).read_text(encoding="utf-8"))
    steps = workflow["jobs"][job_id]["steps"]
    names = [step.get("name", "") for step in steps]
    assert names.index("Set up locked Python validation environment") < names.index("Install KiCad 10 CLI")
    assert names.index("Install KiCad 10 CLI") < names.index(run_step)

    upload = next(step for step in steps if step.get("name") == "Upload KiCad oracle evidence")
    assert upload["with"]["name"] == "kicad-oracle-evidence"
    assert upload["uses"].startswith("actions/upload-artifact@")


def test_hardware_scorecard_and_example_evidence_unchanged() -> None:
    workflow = yaml.safe_load((WORKFLOWS / "hardware.yml").read_text(encoding="utf-8"))
    regression = workflow["jobs"]["regression"]["steps"]
    assert any(step.get("name") == "Run KiCad round-trip scorecard" for step in regression)
    artifact = next(step for step in regression if step.get("name") == "Upload KiCad round-trip scorecard")
    assert artifact["with"]["name"] == "kicad-roundtrip-scorecard"
    assert any(
        step.get("name") == "Validate all examples through full pipeline"
        for step in workflow["jobs"]["examples"]["steps"]
    )
