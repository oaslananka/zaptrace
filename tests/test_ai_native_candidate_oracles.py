"""Negative and genuine native KiCad acceptance for local unapproved candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.ai_native_candidate_oracles import run_local_oracles
from scripts.ai_native_candidate_pilot import write_local_candidate

INTENT = "USB-C powered STM32 MCU board, 3.3V rail at 100 mA, I2C temperature sensor"


def test_integrity_rejects_tampered_design_before_oracle_runs(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    (candidate / "design.json").write_text('{"changed":true}')
    with pytest.raises(ValueError, match="SHA mismatch"):
        run_local_oracles(candidate, tmp_path / "should-not-exist")
    assert not (tmp_path / "should-not-exist").exists()


def test_oracle_input_symlink_and_existing_output_refused(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    alias = tmp_path / "symlink"
    alias.symlink_to(candidate, target_is_directory=True)
    with pytest.raises(ValueError):
        run_local_oracles(alias, tmp_path / "unused")
    preexisting = tmp_path / "preexisting"
    preexisting.mkdir()
    (preexisting / "important").write_text("KEEP")
    with pytest.raises(ValueError):
        run_local_oracles(candidate, preexisting)
    assert (preexisting / "important").read_text() == "KEEP"


def test_native_kicad_report_and_missing_simulation_remain_unapproved(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    result = run_local_oracles(candidate, tmp_path / "oracles")
    assert result["fabrication_approved"] is False
    assert result["native_erc"]["status"] in {"blocked", "not_checked"}
    assert result["simulation"]["status"] in {"not_checked", "blocked", "dc_only_passed_not_transient_qualified"}
    assert result["physical_routing_drc"] == "not_checked"
    evidence = tmp_path / "oracles/oracle-evidence.json"
    assert json.loads(evidence.read_text())["candidate_id"] == result["candidate_id"]
    for name, expected in result["source_sha256"].items():
        assert hashlib.sha256((candidate / name).read_bytes()).hexdigest() == expected
    if result["native_erc"]["status"] != "not_checked":
        assert result["native_erc"]["ignored_checks"] or (
            result["native_erc"]["errors"] or result["native_erc"]["warnings"]
        )
