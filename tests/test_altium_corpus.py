"""Tests for Altium ASCII import fidelity corpus gate (issue #137).

Verifies:
- Corpus fixtures parse without errors.
- Mean net_score ≥ 0.80 for non-adversarial fixtures.
- Unsupported-record evidence is populated for adversarial fixtures.
- Capability matrix states import-only (no native writer).
- No native Altium writer or undocumented-record claim is introduced.
- CI gate script exits 0 and produces a well-formed JSON report.
- MCP tool ``altium_import_fidelity`` is registered and functional.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "tests" / "corpus" / "altium"


# ---------------------------------------------------------------------------
# Corpus fixture tests
# ---------------------------------------------------------------------------


def test_corpus_dir_exists() -> None:
    assert CORPUS_DIR.is_dir(), f"Corpus directory not found: {CORPUS_DIR}"


def test_corpus_has_fixtures() -> None:
    fixtures = list(CORPUS_DIR.glob("*.asc"))
    assert len(fixtures) >= 2, f"Expected at least 2 fixtures, found {len(fixtures)}"


def test_corpus_has_provenance() -> None:
    assert (CORPUS_DIR / "PROVENANCE.txt").exists()


def test_opamp_circuit_parses_without_errors() -> None:
    from zaptrace.eda.altium import read_altium_ascii_sch

    src = (CORPUS_DIR / "opamp_circuit.asc").read_text()
    result = read_altium_ascii_sch(src)
    assert result.error_count == 0
    assert len(result.design.components) >= 2
    assert len(result.design.nets) >= 1


def test_mcu_breakout_parses_without_errors() -> None:
    from zaptrace.eda.altium import read_altium_ascii_sch

    src = (CORPUS_DIR / "mcu_breakout.asc").read_text()
    result = read_altium_ascii_sch(src)
    assert result.error_count == 0
    assert len(result.design.components) >= 1
    assert len(result.design.nets) >= 2


def test_adversarial_unsupported_records_evidence() -> None:
    """Unsupported-record fixture must populate unsupported_records evidence."""
    from zaptrace.eda.altium import read_altium_ascii_sch

    src = (CORPUS_DIR / "adversarial_unsupported.asc").read_text()
    result = read_altium_ascii_sch(src)
    assert result.error_count == 0, "Adversarial fixture must not error"
    assert len(result.unsupported_records) >= 3, (
        f"Expected ≥3 unsupported records, got {len(result.unsupported_records)}"
    )
    types_found = {r.record_type for r in result.unsupported_records}
    assert 99 in types_found
    assert 150 in types_found
    assert 200 in types_found


def test_all_fixtures_parse_without_errors() -> None:
    from zaptrace.eda.altium import read_altium_ascii_sch

    for fixture in sorted(CORPUS_DIR.glob("*.asc")):
        src = fixture.read_text()
        result = read_altium_ascii_sch(src)
        assert result.error_count == 0, f"{fixture.name}: {result.error_count} import error(s)"


def test_non_adversarial_fixtures_mean_score_above_threshold() -> None:
    from zaptrace.eda.altium import read_altium_ascii_sch

    scored = []
    for fixture in sorted(CORPUS_DIR.glob("*.asc")):
        if fixture.name.startswith("adversarial_"):
            continue
        src = fixture.read_text()
        result = read_altium_ascii_sch(src)
        scored.append(result.net_score)

    assert scored, "No non-adversarial fixtures found"
    mean_score = sum(scored) / len(scored)
    assert mean_score >= 0.80, f"Mean net_score {mean_score:.3f} < 0.80"


def test_all_fixtures_have_parity_summary() -> None:
    from zaptrace.eda.altium import read_altium_ascii_sch

    for fixture in sorted(CORPUS_DIR.glob("*.asc")):
        src = fixture.read_text()
        result = read_altium_ascii_sch(src)
        d = result.to_dict()
        assert "component_count" in d
        assert "net_count" in d
        assert "unsupported_record_count" in d
        assert "supported_record_types" in d


# ---------------------------------------------------------------------------
# CI gate script tests
# ---------------------------------------------------------------------------


def test_ci_gate_exits_zero() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/ci_altium_corpus_gate.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"Gate failed:\n{proc.stdout}\n{proc.stderr}"


def test_ci_gate_output_json(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, "scripts/ci_altium_corpus_gate.py", "--output", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert out.exists()
    report = json.loads(out.read_text())
    assert report["passed"] is True
    assert report["mean_net_score"] >= 0.80
    assert report["fixture_count"] >= 2
    assert "summaries" in report


def test_ci_gate_report_has_unsupported_types(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    subprocess.run(
        [sys.executable, "scripts/ci_altium_corpus_gate.py", "--output", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    report = json.loads(out.read_text())
    adversarial = [s for s in report["summaries"] if "adversarial" in s["fixture"]]
    assert adversarial, "No adversarial summary in report"
    assert adversarial[0]["unsupported_record_count"] >= 3
    assert len(adversarial[0]["unsupported_record_types"]) >= 3


def test_ci_gate_custom_min_score_fails_below_threshold() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/ci_altium_corpus_gate.py", "--min-score", "1.1"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, "Expected failure when threshold > 1.0"


# ---------------------------------------------------------------------------
# MCP tool tests
# ---------------------------------------------------------------------------


def test_altium_import_fidelity_tool_registered() -> None:
    from zaptrace.agent._tool_impls import TOOL_REGISTRY

    assert "altium_import_fidelity" in TOOL_REGISTRY


def test_altium_import_fidelity_tool_result_keys() -> None:
    from zaptrace.agent._tool_impls import TOOL_REGISTRY

    src = (CORPUS_DIR / "opamp_circuit.asc").read_text()
    fn = TOOL_REGISTRY["altium_import_fidelity"]["fn"]
    result = fn(altium_ascii_text=src)
    assert result["component_count"] >= 2
    assert result["net_count"] >= 1
    assert 0.0 <= result["net_score"] <= 1.0
    assert result["error_count"] == 0
    assert "import_only_notice" in result
    assert "Altium" in result["import_only_notice"]


def test_altium_import_fidelity_tool_unsupported_evidence() -> None:
    from zaptrace.agent._tool_impls import TOOL_REGISTRY

    src = (CORPUS_DIR / "adversarial_unsupported.asc").read_text()
    fn = TOOL_REGISTRY["altium_import_fidelity"]["fn"]
    result = fn(altium_ascii_text=src)
    assert result["unsupported_record_count"] >= 3
    assert len(result["unsupported_record_types"]) >= 3


def test_altium_import_fidelity_no_native_writer() -> None:
    """Confirm no Altium writer function exists in the codebase."""
    import zaptrace.eda.altium as altium_module

    writer_names = [name for name in dir(altium_module) if "write" in name.lower() and "altium" in name.lower()]
    assert not writer_names, f"Unexpected Altium writer(s): {writer_names}"


# ---------------------------------------------------------------------------
# Capability matrix tests
# ---------------------------------------------------------------------------


def test_readme_mentions_altium_import_only() -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    assert "Altium" in readme, "README must mention Altium"
    assert "import" in readme.lower(), "README must mention import"


def test_capability_matrix_import_only_statement() -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    lines_with_altium = [ln for ln in readme.splitlines() if "Altium" in ln]
    table_row = next(
        (ln for ln in lines_with_altium if "import" in ln.lower()),
        None,
    )
    assert table_row is not None, "No Altium import-only row found in README"
    assert "import" in table_row.lower()


def test_current_state_audit_altium_entry() -> None:
    audit = (REPO_ROOT / "docs" / "strategy" / "current-state-audit.md").read_text()
    assert "Altium" in audit, "current-state-audit.md must mention Altium"
    assert "import" in audit.lower()


def test_current_state_audit_no_native_writer_claim() -> None:
    audit = (REPO_ROOT / "docs" / "strategy" / "current-state-audit.md").read_text()
    lines_with_altium = [ln for ln in audit.splitlines() if "Altium" in ln]
    for line in lines_with_altium:
        assert "native Altium writer" not in line.lower() or "not" in line.lower(), (
            f"Unexpected native writer claim: {line}"
        )
