"""Tests for KiCad → EasyEDA Pro conversion MCP tool and corpus CI gate.

Covers:
- tool_kicad_to_easyeda_pro() via the TOOL_REGISTRY
- scripts/ci_kicad_to_easyeda_pro_corpus_gate.py logic
- All 3 corpus fixtures convert with overall_score >= 0.75
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from zaptrace.agent._tool_impls import TOOL_REGISTRY, tool_kicad_to_easyeda_pro

CORPUS_DIR = Path(__file__).parent / "corpus" / "kicad"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _call_tool(project_path: str, session_id: str = "test_easyeda") -> dict:
    fn = TOOL_REGISTRY["kicad_to_easyeda_pro"]["fn"]
    return fn(project_path=project_path, session_id=session_id)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestKicadToEasyEdaProToolRegistration:
    def test_tool_in_registry(self) -> None:
        assert "kicad_to_easyeda_pro" in TOOL_REGISTRY

    def test_tool_has_fn(self) -> None:
        assert callable(TOOL_REGISTRY["kicad_to_easyeda_pro"]["fn"])

    def test_tool_has_description(self) -> None:
        desc = TOOL_REGISTRY["kicad_to_easyeda_pro"]["description"]
        assert len(desc) > 20

    def test_tool_has_project_path_param(self) -> None:
        params = TOOL_REGISTRY["kicad_to_easyeda_pro"]["params"]
        assert "project_path" in params

    def test_tool_has_output_path_param(self) -> None:
        params = TOOL_REGISTRY["kicad_to_easyeda_pro"]["params"]
        assert "output_path" in params

    def test_tool_has_session_id_param(self) -> None:
        params = TOOL_REGISTRY["kicad_to_easyeda_pro"]["params"]
        assert "session_id" in params


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------


class TestKicadToEasyEdaProResultStructure:
    def test_returns_dict(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="struct_test")
        assert isinstance(result, dict)

    def test_has_design_name(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="name_test")
        assert "design_name" in result

    def test_has_kicad_source_score(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="kscore_test")
        assert "kicad_source_score" in result
        assert 0.0 <= result["kicad_source_score"] <= 1.0

    def test_has_component_jaccard(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="cj_test")
        assert "component_jaccard" in result
        assert 0.0 <= result["component_jaccard"] <= 1.0

    def test_has_net_jaccard(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="nj_test")
        assert "net_jaccard" in result
        assert 0.0 <= result["net_jaccard"] <= 1.0

    def test_has_overall_score(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="os_test")
        assert "overall_score" in result
        assert 0.0 <= result["overall_score"] <= 1.0

    def test_has_artifact_sha256(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="hash_test")
        assert "artifact_sha256" in result
        assert len(result["artifact_sha256"]) == 64  # SHA-256 hex

    def test_has_write_degradation(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="wd_test")
        assert "write_degradation" in result
        assert isinstance(result["write_degradation"], dict)

    def test_has_roundtrip_errors(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="re_test")
        assert "roundtrip_errors" in result

    def test_has_kicad_findings(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="kf_test")
        assert "kicad_findings" in result
        assert isinstance(result["kicad_findings"], list)

    def test_has_zip_size_bytes(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="zip_test")
        assert "zip_size_bytes" in result
        assert result["zip_size_bytes"] > 0

    def test_output_path_none_by_default(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="op_test")
        assert result["output_path"] is None


# ---------------------------------------------------------------------------
# Determinism: same input → same hash
# ---------------------------------------------------------------------------


class TestKicadToEasyEdaProDeterminism:
    def test_artifact_hash_deterministic(self) -> None:
        r1 = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="det1")
        r2 = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="det2")
        assert r1["artifact_sha256"] == r2["artifact_sha256"]


# ---------------------------------------------------------------------------
# Session storage
# ---------------------------------------------------------------------------


class TestKicadToEasyEdaProSessionStorage:
    def test_design_stored_in_session(self) -> None:
        from zaptrace.agent._tool_impls import _get_session

        sid = "conv_storage_test"
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id=sid)
        session = _get_session(sid)
        assert result["design_name"] in session.get("designs", {})


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestKicadToEasyEdaProErrors:
    def test_nonexistent_path_raises(self) -> None:
        with pytest.raises((FileNotFoundError, ValueError, OSError)):
            _call_tool("/nonexistent/path/to/project", session_id="err_test")


# ---------------------------------------------------------------------------
# Direct function reference
# ---------------------------------------------------------------------------


class TestKicadToEasyEdaProDirectFunction:
    def test_function_is_same_as_registry(self) -> None:
        assert tool_kicad_to_easyeda_pro is TOOL_REGISTRY["kicad_to_easyeda_pro"]["fn"]


# ---------------------------------------------------------------------------
# Corpus conversion scores
# ---------------------------------------------------------------------------


class TestKicadToEasyEdaProCorpusScores:
    @pytest.mark.parametrize(
        "project_subdir",
        ["battery_charger", "led_driver", "usb_hub"],
    )
    def test_corpus_project_converts(self, project_subdir: str) -> None:
        result = _call_tool(str(CORPUS_DIR / project_subdir), session_id=f"conv_{project_subdir}")
        assert isinstance(result, dict)
        assert result["zip_size_bytes"] > 0

    @pytest.mark.parametrize(
        "project_subdir",
        ["battery_charger", "led_driver", "usb_hub"],
    )
    def test_corpus_overall_score_above_threshold(self, project_subdir: str) -> None:
        result = _call_tool(str(CORPUS_DIR / project_subdir), session_id=f"score_{project_subdir}")
        assert result["overall_score"] >= 0.75, f"{project_subdir} overall score {result['overall_score']} < 0.75"

    @pytest.mark.parametrize(
        "project_subdir",
        ["battery_charger", "led_driver", "usb_hub"],
    )
    def test_corpus_kicad_source_score_above_threshold(self, project_subdir: str) -> None:
        result = _call_tool(str(CORPUS_DIR / project_subdir), session_id=f"kscore_{project_subdir}")
        assert result["kicad_source_score"] >= 0.75

    def test_battery_charger_component_jaccard(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "battery_charger"), session_id="bc_cj")
        assert result["component_jaccard"] >= 0.75

    def test_led_driver_net_jaccard(self) -> None:
        result = _call_tool(str(CORPUS_DIR / "led_driver"), session_id="ld_nj")
        assert result["net_jaccard"] >= 0.75


# ---------------------------------------------------------------------------
# CI gate script
# ---------------------------------------------------------------------------


class TestCiKicadToEasyEdaProCorpusGate:
    def test_gate_script_exists(self) -> None:
        gate_script = Path("scripts/ci_kicad_to_easyeda_pro_corpus_gate.py")
        assert gate_script.exists()

    def test_gate_script_importable(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "ci_kicad_to_easyeda_pro_corpus_gate",
            Path("scripts/ci_kicad_to_easyeda_pro_corpus_gate.py"),
        )
        assert spec is not None

    def test_gate_reports_json(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/ci_kicad_to_easyeda_pro_corpus_gate.py"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        parsed = json.loads(proc.stdout.strip())
        assert "status" in parsed
        assert "mean_overall_score" in parsed
        assert "results" in parsed

    def test_gate_exits_zero(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/ci_kicad_to_easyeda_pro_corpus_gate.py"],
            capture_output=True,
            cwd=Path(__file__).parent.parent,
        )
        assert proc.returncode == 0, f"Gate failed:\nstdout: {proc.stdout.decode()}\nstderr: {proc.stderr.decode()}"

    def test_gate_mean_score_above_threshold(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/ci_kicad_to_easyeda_pro_corpus_gate.py"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        parsed = json.loads(proc.stdout.strip())
        assert parsed["mean_overall_score"] >= 0.75

    def test_gate_all_projects_pass(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/ci_kicad_to_easyeda_pro_corpus_gate.py"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        parsed = json.loads(proc.stdout.strip())
        assert parsed["failures"] == []

    def test_gate_result_has_artifact_hashes(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/ci_kicad_to_easyeda_pro_corpus_gate.py"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        parsed = json.loads(proc.stdout.strip())
        for r in parsed["results"]:
            assert "artifact_sha256" in r
            assert len(r["artifact_sha256"]) == 64


def test_conversion_corpus_project_helper_reports_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parent.parent / "scripts"))
    from ci_kicad_to_easyeda_pro_corpus_gate import _convert_project  # type: ignore[import]

    payload, score, failed = _convert_project(Path("tests/corpus/kicad/usb_hub"))
    assert payload["project"] == "usb_hub"
    assert payload["status"] == "pass"
    assert len(str(payload["artifact_sha256"])) == 64
    assert score is not None
    assert score >= 0.75
    assert failed is False
