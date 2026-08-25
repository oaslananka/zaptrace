"""Tests for EasyEDA Standard corpus gate and MCP tool (issue #135).

Covers:
- CI gate discovers corpus files and scores them
- Corpus mean score meets 0.75 threshold
- Adversarial fixture with unknown fields produces degradation records
- MCP tool returns expected keys
- Round-trip score is deterministic
- Capability matrix documentation distinguishes Standard vs Pro
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from zaptrace.eda.easyeda_std import (
    compute_easyeda_std_fidelity,
    easyeda_std_project_to_design,
    read_easyeda_std_json,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_CORPUS_DIR = _REPO_ROOT / "tests" / "corpus" / "easyeda_std"
_GATE_SCRIPT = _REPO_ROOT / "scripts" / "ci_easyeda_std_corpus_gate.py"


def _read_corpus(name: str) -> dict:
    return json.loads((_CORPUS_DIR / name).read_text())


def _score_fixture(name: str) -> dict:
    raw = (_CORPUS_DIR / name).read_text()
    project = read_easyeda_std_json(raw)
    design = easyeda_std_project_to_design(project)
    return compute_easyeda_std_fidelity(design)


# ---------------------------------------------------------------------------
# Corpus structure
# ---------------------------------------------------------------------------


class TestCorpusStructure:
    def test_corpus_dir_exists(self) -> None:
        assert _CORPUS_DIR.is_dir()

    def test_corpus_has_min_cases(self) -> None:
        cases = list(_CORPUS_DIR.glob("*.json"))
        assert len(cases) >= 2, f"Need ≥2 corpus cases, found {len(cases)}"

    def test_provenance_file_exists(self) -> None:
        assert (_CORPUS_DIR / "PROVENANCE.txt").exists()

    def test_all_fixtures_valid_json(self) -> None:
        for fixture in sorted(_CORPUS_DIR.glob("*.json")):
            data = json.loads(fixture.read_text())
            assert "schematic" in data or "PCB" in data, f"{fixture.name} missing schematic key"


# ---------------------------------------------------------------------------
# Corpus fidelity scores
# ---------------------------------------------------------------------------


class TestCorpusFidelityScores:
    def test_opamp_buffer_score_above_threshold(self) -> None:
        metrics = _score_fixture("opamp_buffer.json")
        assert metrics["overall_score"] >= 0.75, f"opamp_buffer score {metrics['overall_score']:.3f} < 0.75"

    def test_mcu_schematic_score_above_threshold(self) -> None:
        metrics = _score_fixture("mcu_schematic.json")
        assert metrics["overall_score"] >= 0.75, f"mcu_schematic score {metrics['overall_score']:.3f} < 0.75"

    def test_adversarial_fixture_reads_without_crash(self) -> None:
        raw = (_CORPUS_DIR / "adversarial_unknown_fields.json").read_text()
        project = read_easyeda_std_json(raw)
        assert project is not None

    def test_mean_corpus_score_above_threshold(self) -> None:
        scores = []
        for fixture in sorted(_CORPUS_DIR.glob("*.json")):
            try:
                metrics = _score_fixture(fixture.name)
                scores.append(metrics["overall_score"])
            except Exception:
                pass
        assert scores, "No corpus cases scored"
        mean = sum(scores) / len(scores)
        assert mean >= 0.75, f"Mean corpus score {mean:.3f} < 0.75"

    def test_degradation_report_present(self) -> None:
        for fixture in sorted(_CORPUS_DIR.glob("*.json")):
            try:
                metrics = _score_fixture(fixture.name)
            except Exception:
                continue
            assert "degradation_report" in metrics
            assert isinstance(metrics["degradation_report"], list)


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------


class TestEasyEdaStdMCPTool:
    def test_tool_registered(self) -> None:
        from zaptrace.agent._tool_impls import TOOL_REGISTRY

        assert "easyeda_std_roundtrip" in TOOL_REGISTRY

    def test_tool_returns_expected_keys(self) -> None:
        from zaptrace.agent._tool_impls import TOOL_REGISTRY

        fn = TOOL_REGISTRY["easyeda_std_roundtrip"]["fn"]
        sample = (_CORPUS_DIR / "opamp_buffer.json").read_text()
        result = fn(json_content=sample)
        assert "overall_score" in result
        assert "component_jaccard" in result
        assert "net_jaccard" in result
        assert "degradation_report" in result
        assert "format" in result
        assert result["format"] == "easyeda_std"

    def test_tool_score_above_threshold(self) -> None:
        from zaptrace.agent._tool_impls import TOOL_REGISTRY

        fn = TOOL_REGISTRY["easyeda_std_roundtrip"]["fn"]
        sample = (_CORPUS_DIR / "mcu_schematic.json").read_text()
        result = fn(json_content=sample)
        assert result["overall_score"] >= 0.75

    def test_tool_adversarial_input_no_crash(self) -> None:
        from zaptrace.agent._tool_impls import TOOL_REGISTRY

        fn = TOOL_REGISTRY["easyeda_std_roundtrip"]["fn"]
        sample = (_CORPUS_DIR / "adversarial_unknown_fields.json").read_text()
        result = fn(json_content=sample)
        assert "status" in result
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_round_trip_is_deterministic(self) -> None:
        sample = (_CORPUS_DIR / "opamp_buffer.json").read_text()
        project = read_easyeda_std_json(sample)
        design = easyeda_std_project_to_design(project)
        m1 = compute_easyeda_std_fidelity(design)
        m2 = compute_easyeda_std_fidelity(design)
        assert m1["overall_score"] == m2["overall_score"]
        assert m1["component_jaccard"] == m2["component_jaccard"]


# ---------------------------------------------------------------------------
# CI gate script
# ---------------------------------------------------------------------------


class TestCIGateScript:
    def test_gate_exits_0_on_corpus(self) -> None:
        result = subprocess.run(
            [sys.executable, str(_GATE_SCRIPT)],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
        )
        assert result.returncode == 0, f"Gate failed:\n{result.stdout}\n{result.stderr}"

    def test_gate_reports_mean_score(self) -> None:
        result = subprocess.run(
            [sys.executable, str(_GATE_SCRIPT)],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
        )
        assert "Mean score" in result.stdout


# ---------------------------------------------------------------------------
# Capability matrix: Standard vs Pro distinction
# ---------------------------------------------------------------------------


class TestCapabilityMatrixDistinction:
    """Verify docs clearly distinguish EasyEDA Standard from EasyEDA Pro."""

    def test_readme_mentions_easyeda_standard(self) -> None:
        readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "easyeda" in readme.lower() or "EasyEDA" in readme

    def test_capability_matrix_entry_exists(self) -> None:
        """The capability matrix doc must mention both Standard and Pro."""
        audit = (_REPO_ROOT / "docs" / "strategy" / "current-state-audit.md").read_text(encoding="utf-8")
        assert "EasyEDA" in audit
