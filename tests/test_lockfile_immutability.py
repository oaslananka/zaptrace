from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


def _uv() -> str:
    executable = os.environ.get("UV_BIN") or shutil.which("uv")
    if executable is None:
        pytest.skip("uv is required for lockfile contract tests")
    return executable


def test_current_lockfile_matches_project_metadata() -> None:
    result = subprocess.run(
        [_uv(), "lock", "--check", "--project", str(ROOT)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_stale_project_metadata_is_rejected_without_rewriting_lock(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    pyproject = ROOT / "pyproject.toml"
    lock = ROOT / "uv.lock"
    shutil.copy2(pyproject, project / "pyproject.toml")
    shutil.copy2(lock, project / "uv.lock")
    original_lock = (project / "uv.lock").read_bytes()

    metadata = (project / "pyproject.toml").read_text(encoding="utf-8")
    # Mutate the dependency array itself, not a specific version of rich.
    # Renovate routinely rewrites individual minimum versions; the test must
    # still prove that uv rejects a stale lock after *any* such update.
    marker = "dependencies = [\n"
    assert metadata.count(marker) == 1
    assert not any(
        Requirement(dependency).name == "packaging" for dependency in tomllib.loads(metadata)["project"]["dependencies"]
    )
    changed = metadata.replace(marker, marker + '    "packaging>=26.0",\n', 1)
    assert changed != metadata
    (project / "pyproject.toml").write_text(changed, encoding="utf-8")

    result = subprocess.run(
        [_uv(), "lock", "--check", "--project", str(project)],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert (project / "uv.lock").read_bytes() == original_lock


def test_optional_mcp_dependencies_have_explicit_major_bounds() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional = data["project"]["optional-dependencies"]

    mcp_dependencies = {requirement.name: requirement for requirement in map(Requirement, optional["mcp"])}
    assert set(mcp_dependencies) == {"fastmcp", "mcp"}
    assert set(optional["mcp"]) <= set(optional["all"])

    # Changes to the approved minimum are allowed within the supported major
    # bands; silently widening a major boundary or lowering the security floor
    # is not. This contract applies to every Renovate-generated update.
    for name, min_version, max_major in (
        ("fastmcp", Version("4.0.2"), "5"),
        ("mcp", Version("2.0.0"), "3"),
    ):
        specifiers = list(mcp_dependencies[name].specifier)
        assert any(specifier.operator == ">=" and Version(specifier.version) >= min_version for specifier in specifiers)
        assert any(specifier.operator == "<" and specifier.version == max_major for specifier in specifiers)


def test_every_python_workflow_checks_and_uses_committed_lock() -> None:
    workflows = ROOT / ".github" / "workflows"
    sync_lines: list[tuple[Path, str]] = []
    for path in sorted(workflows.glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "uv sync" in line:
                sync_lines.append((path, line.strip()))

    assert sync_lines
    for path, line in sync_lines:
        assert "uv lock --check" in line, f"{path}: {line}"
        assert "uv sync --locked" in line, f"{path}: {line}"


def test_quality_workflow_has_named_mcp_compatibility_contract() -> None:
    workflow = (ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")

    assert "mcp-compatibility:" in workflow
    assert "name: MCP compatibility contract" in workflow
    assert "tests/test_mcp_dependency_contract.py" in workflow
    assert "tests/test_mcp_server.py" in workflow
    assert "tests/test_network_transport_security.py" in workflow
    assert "mcp-compatibility=${{ needs.mcp-compatibility.result }}" in workflow
