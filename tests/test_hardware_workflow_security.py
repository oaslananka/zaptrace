from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/hardware.yml")
ACTION = Path(".github/actions/setup-locked-python/action.yml")
SHARED_SETUP = "./.github/actions/setup-locked-python"


def test_hardware_workflow_installs_locked_dependencies_without_building_project() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    action = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    sync_script = action["runs"]["steps"][-1]["run"]

    assert "uv lock --check" in sync_script
    assert "sync_args=(--locked --all-extras --all-groups --no-install-project --no-build)" in sync_script
    assert 'uv sync "${sync_args[@]}"' in sync_script
    assert set(workflow["jobs"]) == {"regression", "examples", "kicad"}
    for job in workflow["jobs"].values():
        matches = [step for step in job["steps"] if step.get("uses") == SHARED_SETUP]
        assert len(matches) == 1
        assert matches[0]["with"] == {
            "uv-version": "${{ env.UV_VERSION }}",
            "python-version": "${{ env.PYTHON_VERSION }}",
        }
        assert not any("uv sync" in step.get("run", "") for step in job["steps"])


def test_hardware_workflow_exposes_the_checked_out_source_tree_to_python() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'PYTHONPATH: "."' in workflow


def test_hardware_workflow_executes_only_the_pre_synced_environment() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "uv run" not in workflow
    assert ".venv/bin/pytest tests/test_export_regression.py" in workflow
    for command in (
        ".venv/bin/python scripts/ci_smoke.py gerber",
        ".venv/bin/python scripts/ci_smoke.py proof",
        ".venv/bin/python scripts/ci_kicad_roundtrip_scorecard.py",
        ".venv/bin/python scripts/ci_examples.py",
        "uses: ./.github/actions/kicad-oracle",
        '.venv/bin/python -c "',
    ):
        assert command in workflow
