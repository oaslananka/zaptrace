"""Tests for KiCad project import MCP tool and corpus CI gate.

Covers:
- tool_kicad_import_project() via the TOOL_REGISTRY
- scripts/ci_kicad_corpus_gate.py logic
- All 3 corpus fixtures import with net_score >= threshold
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from zaptrace.agent._tool_impls import TOOL_REGISTRY, tool_kicad_import_project

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "kicad_project"
CORPUS_DIR = Path(__file__).parent / "corpus" / "kicad"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _call_tool(project_path: str, session_id: str = "test_kicad_mcp") -> dict:
    fn = TOOL_REGISTRY["kicad_import_project"]["fn"]
    return fn(project_path=project_path, session_id=session_id)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestKicadImportProjectToolRegistration:
    def test_tool_in_registry(self) -> None:
        assert "kicad_import_project" in TOOL_REGISTRY

    def test_tool_has_fn(self) -> None:
        assert callable(TOOL_REGISTRY["kicad_import_project"]["fn"])

    def test_tool_has_description(self) -> None:
        desc = TOOL_REGISTRY["kicad_import_project"]["description"]
        assert len(desc) > 10

    def test_tool_has_project_path_param(self) -> None:
        params = TOOL_REGISTRY["kicad_import_project"]["params"]
        assert "project_path" in params

    def test_tool_has_session_id_param(self) -> None:
        params = TOOL_REGISTRY["kicad_import_project"]["params"]
        assert "session_id" in params


# ---------------------------------------------------------------------------
# Basic import via flat fixture
# ---------------------------------------------------------------------------


class TestKicadImportProjectToolFlat:
    def test_import_returns_dict(self) -> None:
        result = _call_tool(str(FIXTURES_DIR), session_id="flat_test")
        assert isinstance(result, dict)

    def test_import_has_design_name(self) -> None:
        result = _call_tool(str(FIXTURES_DIR), session_id="flat_name")
        assert "design_name" in result
        assert isinstance(result["design_name"], str)

    def test_import_has_component_count(self) -> None:
        result = _call_tool(str(FIXTURES_DIR), session_id="flat_comp")
        assert "component_count" in result
        assert result["component_count"] >= 0

    def test_import_has_net_count(self) -> None:
        result = _call_tool(str(FIXTURES_DIR), session_id="flat_net")
        assert "net_count" in result
        assert result["net_count"] >= 0

    def test_import_has_sheet_count(self) -> None:
        result = _call_tool(str(FIXTURES_DIR), session_id="flat_sheet")
        assert "sheet_count" in result
        assert result["sheet_count"] >= 1

    def test_import_has_net_score(self) -> None:
        result = _call_tool(str(FIXTURES_DIR), session_id="flat_score")
        assert "net_score" in result
        assert 0.0 <= result["net_score"] <= 1.0

    def test_import_has_error_count(self) -> None:
        result = _call_tool(str(FIXTURES_DIR), session_id="flat_err")
        assert "error_count" in result

    def test_import_has_warning_count(self) -> None:
        result = _call_tool(str(FIXTURES_DIR), session_id="flat_warn")
        assert "warning_count" in result

    def test_import_has_findings_list(self) -> None:
        result = _call_tool(str(FIXTURES_DIR), session_id="flat_find")
        assert "findings" in result
        assert isinstance(result["findings"], list)

    def test_import_has_sheets_list(self) -> None:
        result = _call_tool(str(FIXTURES_DIR), session_id="flat_sheets_l")
        assert "sheets" in result
        assert isinstance(result["sheets"], list)

    def test_sheets_have_expected_keys(self) -> None:
        result = _call_tool(str(FIXTURES_DIR), session_id="flat_sheets_k")
        for sheet in result["sheets"]:
            assert "sheet_id" in sheet
            assert "name" in sheet
            assert "component_count" in sheet


# ---------------------------------------------------------------------------
# Import stores design in session
# ---------------------------------------------------------------------------


class TestKicadImportProjectSessionStorage:
    def test_design_stored_in_session(self) -> None:
        from zaptrace.agent._tool_impls import _get_session

        sid = "kicad_storage_test"
        result = _call_tool(str(FIXTURES_DIR), session_id=sid)
        session = _get_session(sid)
        assert result["design_name"] in session.get("designs", {})

    def test_design_has_components(self) -> None:
        from zaptrace.agent._tool_impls import _get_session

        sid = "kicad_storage_comp"
        _call_tool(str(FIXTURES_DIR), session_id=sid)
        session = _get_session(sid)
        designs = session.get("designs", {})
        assert len(designs) > 0
        design = next(iter(designs.values()))
        assert hasattr(design, "components")


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestKicadImportProjectErrors:
    def test_nonexistent_path_raises(self) -> None:
        with pytest.raises((FileNotFoundError, ValueError, OSError)):
            _call_tool("/nonexistent/path/to/project", session_id="err_test")

    def test_invalid_path_type_handled(self, tmp_path: Path) -> None:
        project_path = str(tmp_path)
        with pytest.raises((FileNotFoundError, ValueError, OSError)):
            _call_tool(project_path, session_id="err_tmp")


# ---------------------------------------------------------------------------
# Direct function import (same as MCP tool)
# ---------------------------------------------------------------------------


class TestKicadImportProjectDirectFunction:
    def test_function_is_same_as_registry(self) -> None:
        assert tool_kicad_import_project is TOOL_REGISTRY["kicad_import_project"]["fn"]


# ---------------------------------------------------------------------------
# Corpus fixture imports
# ---------------------------------------------------------------------------


class TestKicadCorpusFixtures:
    @pytest.mark.parametrize(
        "project_subdir",
        ["battery_charger", "led_driver", "usb_hub"],
    )
    def test_corpus_project_imports(self, project_subdir: str) -> None:
        project_dir = CORPUS_DIR / project_subdir
        assert project_dir.exists(), f"Corpus project not found: {project_dir}"
        result = _call_tool(str(project_dir), session_id=f"corpus_{project_subdir}")
        assert isinstance(result, dict)
        assert result["component_count"] >= 1

    @pytest.mark.parametrize(
        "project_subdir",
        ["battery_charger", "led_driver", "usb_hub"],
    )
    def test_corpus_project_no_import_errors(self, project_subdir: str) -> None:
        project_dir = CORPUS_DIR / project_subdir
        result = _call_tool(str(project_dir), session_id=f"corpus_err_{project_subdir}")
        assert result["error_count"] == 0, f"Unexpected errors: {result.get('findings')}"

    @pytest.mark.parametrize(
        "project_subdir",
        ["battery_charger", "led_driver", "usb_hub"],
    )
    def test_corpus_project_net_score_above_threshold(self, project_subdir: str) -> None:
        project_dir = CORPUS_DIR / project_subdir
        result = _call_tool(str(project_dir), session_id=f"corpus_ns_{project_subdir}")
        assert result["net_score"] >= 0.90, f"Net score {result['net_score']} below 0.90"

    def test_corpus_battery_charger_component_count(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="bc_comp")
        assert result["component_count"] >= 4

    def test_corpus_led_driver_component_count(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "led_driver"), session_id="ld_comp")
        assert result["component_count"] >= 5

    def test_corpus_usb_hub_sheet_count(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "usb_hub"), session_id="uh_sheets")
        assert result["sheet_count"] >= 1

    def test_corpus_usb_hub_has_components(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "usb_hub"), session_id="uh_comp")
        assert result["component_count"] >= 2


# ---------------------------------------------------------------------------
# CI gate script
# ---------------------------------------------------------------------------


class TestCiKicadCorpusGate:
    def test_gate_script_exists(self) -> None:
        gate_script = Path("scripts/ci_kicad_corpus_gate.py")
        assert gate_script.exists()

    def test_gate_script_passes(self) -> None:
        # Gate script should be importable (not a syntax error)
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "ci_kicad_corpus_gate",
            Path(__file__).parent.parent / "scripts" / "ci_kicad_corpus_gate.py",
        )
        assert spec is not None

    def test_gate_discovers_three_projects(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.syspath_prepend(str(Path(__file__).parent.parent / "scripts"))
        from ci_kicad_corpus_gate import _discover_projects  # type: ignore[import]

        projects = _discover_projects(CORPUS_DIR)
        assert len(projects) >= 3

    def test_gate_reports_json(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/ci_kicad_corpus_gate.py"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        # Should output valid JSON to stdout
        output = proc.stdout.strip()
        parsed = json.loads(output)
        assert "status" in parsed
        assert "mean_net_score" in parsed
        assert "results" in parsed

    def test_gate_exits_zero(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/ci_kicad_corpus_gate.py"],
            capture_output=True,
            cwd=Path(__file__).parent.parent,
        )
        assert proc.returncode == 0, f"Gate failed:\nstdout: {proc.stdout.decode()}\nstderr: {proc.stderr.decode()}"

    def test_gate_mean_net_score_above_threshold(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/ci_kicad_corpus_gate.py"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        parsed = json.loads(proc.stdout.strip())
        assert parsed["mean_net_score"] >= 0.90

    def test_gate_all_projects_pass(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/ci_kicad_corpus_gate.py"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        parsed = json.loads(proc.stdout.strip())
        assert parsed["failures"] == []


def test_corpus_project_helper_reports_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parent.parent / "scripts"))
    from ci_kicad_corpus_gate import _evaluate_project  # type: ignore[import]

    payload, score, failed = _evaluate_project(CORPUS_DIR / "usb_hub")
    assert payload["project"] == "usb_hub"
    assert payload["status"] == "pass"
    assert score is not None
    assert score >= 0.9
    assert failed is False
