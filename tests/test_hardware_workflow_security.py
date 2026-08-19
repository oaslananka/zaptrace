from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/hardware.yml")
SAFE_SYNC = "uv lock --check && uv sync --locked --all-extras --all-groups --no-install-project --no-build"


def test_hardware_workflow_installs_locked_dependencies_without_building_project() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count(SAFE_SYNC) == 3
    for line in workflow.splitlines():
        if "uv sync" in line:
            assert SAFE_SYNC in line


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
        ".venv/bin/python scripts/ci_kicad_oracle.py --check",
        ".venv/bin/python scripts/ci_kicad_oracle.py --strict-skips",
        '.venv/bin/python -c "',
    ):
        assert command in workflow
