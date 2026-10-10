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
    quality = yaml.safe_load((WORKFLOWS / "quality.yml").read_text(encoding="utf-8"))
    assert workflow["env"]["PYTHON_VERSION"] == quality["env"]["PYTHON_VERSION"]
    assert workflow["env"]["UV_VERSION"] == quality["env"]["UV_VERSION"]

    for job_id, expected_name in expected_jobs.items():
        job = workflow["jobs"][job_id]
        assert job["name"] == expected_name
        steps = job["steps"]
        checkouts = [step for step in steps if step.get("uses", "").startswith("actions/checkout@")]
        assert len(checkouts) == 1
        assert checkouts[0]["with"]["persist-credentials"] is False

        bootstraps = [step for step in steps if step.get("uses") == SHARED_ACTION]
        assert len(bootstraps) == 1, (workflow_name, job_id)
        bootstrap = bootstraps[0]
        assert bootstrap["with"] == {
            "uv-version": "${{ env.UV_VERSION }}",
            "python-version": "${{ env.PYTHON_VERSION }}",
        }
        assert "if" not in bootstrap
        assert steps.index(checkouts[0]) < steps.index(bootstrap)
        assert not any(step.get("uses", "").startswith("astral-sh/setup-uv@") for step in steps)


@pytest.mark.parametrize(
    ("workflow_name", "job_id", "run_jobset"),
    [("hardware.yml", "kicad", False), ("kicad-oracle.yml", "oracle", True)],
)
def test_kicad_oracle_retains_shared_runner_and_evidence_upload(
    workflow_name: str, job_id: str, run_jobset: bool
) -> None:
    workflow = yaml.safe_load((WORKFLOWS / workflow_name).read_text(encoding="utf-8"))
    steps = workflow["jobs"][job_id]["steps"]
    names = [step.get("name", "") for step in steps]
    assert names.index("Set up locked Python validation environment") < names.index("Run shared KiCad oracle checks")
    runner = next(step for step in steps if step.get("name") == "Run shared KiCad oracle checks")
    assert runner["uses"] == "./.github/actions/kicad-oracle"
    assert runner["with"]["record-availability"] == "true"
    assert (runner["with"].get("run-jobset") == "true") is run_jobset

    upload = next(step for step in steps if step.get("name") == "Upload KiCad oracle evidence")
    assert "kicad-oracle-check.json" in upload["with"]["path"]
    assert "kicad-oracle-summary.json" in upload["with"]["path"]
    assert upload["with"]["name"] == "kicad-oracle-evidence"
    assert upload["uses"].startswith("actions/upload-artifact@")


def test_shared_kicad_oracle_action_is_strict_and_optional_steps_are_explicit() -> None:
    action = yaml.safe_load((ROOT / ".github/actions/kicad-oracle/action.yml").read_text(encoding="utf-8"))
    assert action["runs"]["using"] == "composite"
    assert action["inputs"]["record-availability"]["default"] == "false"
    assert action["inputs"]["run-jobset"]["default"] == "false"
    steps = action["runs"]["steps"]
    assert [step["name"] for step in steps] == [
        "Install KiCad 10 CLI",
        "Record KiCad availability",
        "Run strict KiCad oracle",
        "Run atomic KiCad 10 jobset oracle",
    ]
    assert steps[0]["run"] == "bash scripts/ci_install_kicad.sh kicad"
    assert steps[1]["if"] == "inputs.record-availability == 'true'"
    assert steps[1]["run"] == (".venv/bin/python scripts/ci_kicad_oracle.py --check --output kicad-oracle-check.json")
    assert steps[2]["run"] == (
        ".venv/bin/python scripts/ci_kicad_oracle.py --strict-skips --output kicad-oracle-summary.json"
    )
    assert steps[3]["if"] == "inputs.run-jobset == 'true'"
    assert steps[3]["run"] == (
        ".venv/bin/python scripts/ci_kicad_jobset_oracle.py --output kicad-jobset-oracle-summary.json"
    )
    assert all(step["shell"] == "bash" for step in steps)
    assert all("uv run" not in step["run"] for step in steps)


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


def test_quality_oracle_reuses_shared_action_without_weakening_release_gate() -> None:
    quality = yaml.safe_load((WORKFLOWS / "quality.yml").read_text(encoding="utf-8"))
    job = quality["jobs"]["kicad-oracle"]
    assert job["name"] == "KiCad Oracle"
    assert job["needs"] == "changes"
    steps = job["steps"]
    shared = next(step for step in steps if step.get("name") == "Run shared KiCad oracle checks")
    assert shared["if"] == "needs.changes.outputs.heavy_ci == 'true'"
    assert shared["uses"] == "./.github/actions/kicad-oracle"
    assert shared["with"] == {"run-jobset": "true"}
    assert shared["env"]["ZAPTRACE_SOURCE_COMMIT"] == "${{ github.event.pull_request.head.sha || github.sha }}"

    oracle_upload = next(step for step in steps if step.get("name") == "Upload KiCad oracle summary")
    assert oracle_upload["if"] == "needs.changes.outputs.heavy_ci == 'true'"
    assert oracle_upload["with"]["name"] == "kicad-oracle-summary"
    assert oracle_upload["with"]["if-no-files-found"] == "error"
    for path in ("kicad-oracle-summary.json", "kicad-jobset-oracle-summary.json", "kicad-benchmark-corpus.json"):
        assert path in oracle_upload["with"]["path"]
    physical = next(step for step in steps if step.get("name") == "Upload physical candidate readiness")
    assert physical["with"]["name"] == "physical-candidate-readiness"
    assert physical["with"]["retention-days"] == 30

    summary = quality["jobs"]["release-gate-summary"]
    assert "kicad-oracle" in summary["needs"]
    assert '--required-oracle "kicad-oracle"' in summary["steps"][-2]["run"]
    assert '--gate "kicad-oracle=${{ needs.kicad-oracle.result }}"' in summary["steps"][-2]["run"]
