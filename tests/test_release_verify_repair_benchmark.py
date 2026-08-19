"""Four-family convergence benchmark for release verify/repair evidence."""

from __future__ import annotations

import json
from pathlib import Path

from zaptrace.benchmark.release_convergence import (
    CANONICAL_RELEASE_CONVERGENCE_FAMILIES,
    run_release_convergence_benchmark,
)
from zaptrace.pipeline.verify_repair_models import VerifyRepairStopReason


def test_four_canonical_families_converge_under_automated_policy(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    report = run_release_convergence_benchmark(artifact_root, trusted_output_root=tmp_path)

    assert report.passed is True
    assert report.family_count == 4
    assert report.converged_count == 4
    assert [item.family_id for item in report.families] == list(CANONICAL_RELEASE_CONVERGENCE_FAMILIES)
    assert all(item.converged for item in report.families)
    assert all(item.stop_reason == VerifyRepairStopReason.ALL_GATES_PASSED for item in report.families)
    assert all(item.gate_history_count >= 1 for item in report.families)
    assert all(len(item.initial_design_state_hash) == 64 for item in report.families)
    assert all(len(item.final_design_state_hash) == 64 for item in report.families)
    assert all(len(item.verify_repair_report_sha256) == 64 for item in report.families)
    assert all(len(item.repair_scorecard_sha256) == 64 for item in report.families)
    assert report.report_sha256 == report.compute_sha256()

    for family in report.families:
        path = artifact_root / family.verify_repair_report_path
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["policy_version"] == "1.0-automated-convergence"
        assert payload["enabled_domains"] == ["erc"]
        assert payload["stop_reason"] == "all-gates-passed"
        assert payload["report_sha256"] == family.verify_repair_report_sha256
        scorecard_path = artifact_root / family.repair_scorecard_path
        scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
        assert scorecard["family_id"] == family.family_id
        assert scorecard["verify_repair_report_sha256"] == family.verify_repair_report_sha256
        assert scorecard["repair_count"] == family.repair_count
        assert scorecard["scorecard_sha256"] == family.repair_scorecard_sha256

    overall = json.loads((artifact_root / "release-convergence-report.json").read_text(encoding="utf-8"))
    assert overall["report_sha256"] == report.report_sha256
    assert any("not release" in claim.lower() for claim in overall["non_claims"])


def test_benchmark_rejects_unknown_family_before_writing_artifacts(tmp_path: Path) -> None:
    try:
        run_release_convergence_benchmark(tmp_path, family_ids=["not-a-family"])
    except ValueError as exc:
        assert "unknown benchmark family" in str(exc)
    else:
        raise AssertionError("unknown family must fail closed")
    assert not (tmp_path / "release-convergence-report.json").exists()


def test_benchmark_rejects_output_outside_trusted_root(tmp_path: Path) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()

    try:
        run_release_convergence_benchmark(
            tmp_path / "outside",
            trusted_output_root=trusted_root,
        )
    except ValueError as exc:
        assert "escapes trusted root" in str(exc)
    else:
        raise AssertionError("benchmark output outside trusted root must fail closed")
