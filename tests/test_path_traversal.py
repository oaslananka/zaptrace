"""Tests for workspace sandboxing / path-traversal prevention."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from zaptrace.agent import _tool_impls


@pytest.fixture(autouse=True)
def _cleanup_workspace() -> None:
    """Save and restore workspace state to avoid cross-test pollution."""
    old_env = os.environ.get("ZAPTRACE_WORKSPACE", "")
    old_cache = _tool_impls._WORKSPACE
    yield
    if old_env:
        os.environ["ZAPTRACE_WORKSPACE"] = old_env
    else:
        os.environ.pop("ZAPTRACE_WORKSPACE", None)
    _tool_impls._WORKSPACE = old_cache


def _set_workspace(p: Path) -> None:
    os.environ["ZAPTRACE_WORKSPACE"] = str(p)
    _tool_impls._WORKSPACE = None


def test_accepts_workspace_path(tmp_path: Path) -> None:
    _set_workspace(tmp_path)
    f = tmp_path / "design.yaml"
    f.write_text("meta:\n  name: test\n")
    p = _tool_impls._validate_path(str(f), must_exist=True)
    assert p == f.resolve()


def test_relative_path_resolves_from_configured_workspace(tmp_path: Path) -> None:
    _set_workspace(tmp_path)
    resolved = _tool_impls._validate_path("reports/output.md")
    assert resolved == (tmp_path / "reports" / "output.md").resolve()


def test_accepts_subdirectory(tmp_path: Path) -> None:
    _set_workspace(tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    f = sub / "design.yaml"
    f.write_text("meta:\n  name: test\n")
    p = _tool_impls._validate_path(str(f), must_exist=True)
    assert p == f.resolve()


def test_rejects_absolute_outside(tmp_path: Path) -> None:
    _set_workspace(tmp_path)
    outside = Path(os.environ.get("TEMP", "/tmp")) / "evil.yaml"
    with pytest.raises(ValueError, match="outside workspace"):
        _tool_impls._validate_path(str(outside), must_exist=False)


def test_rejects_dotdot_escape(tmp_path: Path) -> None:
    _set_workspace(tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    malicious = sub / ".." / ".." / "etc" / "passwd"
    with pytest.raises(ValueError, match="outside workspace"):
        _tool_impls._validate_path(str(malicious), must_exist=False)


def test_rejects_non_existent_with_must_exist(tmp_path: Path) -> None:
    _set_workspace(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        _tool_impls._validate_path(str(tmp_path / "nope.yaml"), must_exist=True)


def test_rejects_prefix_sibling_workspace(tmp_path: Path) -> None:
    root = tmp_path / "work"
    sibling = tmp_path / "work-evil"
    root.mkdir()
    sibling.mkdir()
    _set_workspace(root)
    with pytest.raises(ValueError, match="outside workspace"):
        _tool_impls._validate_path(sibling / "out.svg")


def test_export_svg_validates_output_path(tmp_path: Path) -> None:
    _set_workspace(tmp_path / "workspace")
    _tool_impls._get_workspace().mkdir(parents=True, exist_ok=True)
    design = _tool_impls.parse_str("meta: {name: Demo}\ncomponents: {}\nnets: {}\n")
    _tool_impls._sessions["s1"] = {"designs": {"Demo": design}}
    outside = tmp_path / "outside.svg"
    with pytest.raises(ValueError, match="outside workspace"):
        _tool_impls.tool_export_svg("Demo", output_path=str(outside), session_id="s1")


def test_export_report_writes_validated_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _set_workspace(workspace)
    workspace.mkdir()
    design = _tool_impls.parse_str("meta: {name: Demo}\ncomponents: {}\nnets: {}\n")
    _tool_impls._sessions["s2"] = {"designs": {"Demo": design}}
    out = workspace / "reports" / "demo.md"
    _tool_impls.tool_export_report("Demo", output_path=str(out), session_id="s2")
    assert out.exists()


def test_pipeline_source_path_is_sandboxed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("meta: {name: Demo}\ncomponents: {}\nnets: {}\n", encoding="utf-8")
    _set_workspace(workspace)
    with pytest.raises(ValueError, match="outside workspace"):
        _tool_impls.tool_pipeline_run(source=str(outside), session_id="s3")


def test_proof_list_checks_path_is_sandboxed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "proof.yaml"
    outside.write_text("name: Outside\ndesign_path: design.yaml\nchecks: []\n", encoding="utf-8")
    _set_workspace(workspace)
    with pytest.raises(ValueError, match="outside workspace"):
        _tool_impls.tool_proof_list_checks(str(outside))
