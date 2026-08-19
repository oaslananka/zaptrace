from __future__ import annotations

from pathlib import Path

SAFE_SYNC = "uv lock --check && uv sync --locked --all-extras --all-groups --no-install-project --no-build"
TARGET_WORKFLOWS = (
    Path(".github/workflows/proof-pack.yml"),
    Path(".github/workflows/kicad-oracle.yml"),
    Path(".github/workflows/security-scan.yml"),
    Path(".github/workflows/release.yml"),
)


def test_target_workflows_disable_builds_for_every_locked_sync() -> None:
    native_wheel_exception = (
        'UV_PROJECT_ENVIRONMENT="$RUNNER_TEMP/zaptrace-native-smoke" '
        "uv sync --locked --all-extras --all-groups --no-install-project"
    )
    exceptions: list[str] = []

    for path in TARGET_WORKFLOWS:
        workflow = path.read_text(encoding="utf-8")
        for line in workflow.splitlines():
            if "uv sync" not in line:
                continue
            if path == Path(".github/workflows/release.yml") and native_wheel_exception in line:
                assert "--no-build" not in line, line.strip()
                exceptions.append(line.strip())
                continue
            assert "--no-build" in line, f"{path}: {line.strip()}"

    assert len(exceptions) == 1, exceptions
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "macOS x86_64 dependencies may require locked source builds" in release


def test_target_install_steps_skip_project_installation_and_builds() -> None:
    for path in TARGET_WORKFLOWS:
        workflow = path.read_text(encoding="utf-8")
        assert SAFE_SYNC in workflow, str(path)


def test_proof_and_kicad_jobs_use_only_the_pre_synced_environment() -> None:
    proof = Path(".github/workflows/proof-pack.yml").read_text(encoding="utf-8")
    oracle = Path(".github/workflows/kicad-oracle.yml").read_text(encoding="utf-8")

    assert "uv run" not in proof
    assert "uv run" not in oracle
    assert '.venv/bin/python -c "' in proof
    assert ".venv/bin/python scripts/ci_kicad_oracle.py --strict-skips" in oracle
