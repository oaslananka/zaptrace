"""Unified simulation-backed sign-off evidence contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from zaptrace.analysis.simulation_signoff import (
    SimulationCheckEvidence,
    SimulationDomain,
    SimulationEvidenceMethod,
    SimulationEvidenceStatus,
    SimulationFamilyReport,
    SimulationModelEvidence,
    SimulationRiskClass,
    _normalized_gate_decision,
    normalize_simulation_gate,
)

_SHA = "a" * 64


def _model(*, method: SimulationEvidenceMethod, degraded: bool = False) -> SimulationModelEvidence:
    return SimulationModelEvidence(
        model_id="model-1",
        source="fixture:test-v1",
        version="1.0",
        model_sha256=_SHA,
        method=method,
        binding="family-fixture",
        degraded=degraded,
        confidence=0.95 if method == SimulationEvidenceMethod.NGSPICE and not degraded else 0.65,
        assumptions=["bounded test assumption"],
    )


def test_failed_gate_requires_repair_hint() -> None:
    with pytest.raises(ValidationError, match="repair hint"):
        SimulationCheckEvidence(
            check_id="transient:ripple",
            domain=SimulationDomain.TRANSIENT,
            method=SimulationEvidenceMethod.NGSPICE,
            engine_status="fail",
            status=SimulationEvidenceStatus.FAIL,
            risk_class=SimulationRiskClass.HIGH,
            blocking=True,
            human_review_required=True,
            summary="ripple exceeds threshold",
            model_ids=["model-1"],
        )


def test_analytical_pass_requires_human_review() -> None:
    evidence = normalize_simulation_gate(
        check_id="usb-c-inrush",
        domain=SimulationDomain.TRANSIENT,
        engine_status="pass",
        method=SimulationEvidenceMethod.ANALYTICAL,
        summary="all analytical checks passed",
        models=[_model(method=SimulationEvidenceMethod.ANALYTICAL)],
        metrics={"check_count": 4},
    )

    assert evidence.status == SimulationEvidenceStatus.HUMAN_REVIEW_REQUIRED
    assert evidence.blocking is False
    assert evidence.human_review_required is True
    assert evidence.risk_class == SimulationRiskClass.MODERATE


def test_degraded_ngspice_pass_requires_human_review() -> None:
    evidence = normalize_simulation_gate(
        check_id="buck-transient",
        domain=SimulationDomain.TRANSIENT,
        engine_status="pass",
        method=SimulationEvidenceMethod.NGSPICE,
        summary="transient checks passed",
        models=[_model(method=SimulationEvidenceMethod.NGSPICE, degraded=True)],
        tool_version="ngspice-42",
    )

    assert evidence.status == SimulationEvidenceStatus.HUMAN_REVIEW_REQUIRED
    assert evidence.live_simulation_passed is True
    assert evidence.human_review_required is True


def test_non_degraded_ngspice_pass_is_a_real_pass() -> None:
    evidence = normalize_simulation_gate(
        check_id="dc-operating-point",
        domain=SimulationDomain.DC_OPERATING_POINT,
        engine_status="pass",
        method=SimulationEvidenceMethod.NGSPICE,
        summary="DC references passed",
        models=[_model(method=SimulationEvidenceMethod.NGSPICE)],
        tool_version="ngspice-42",
    )

    assert evidence.status == SimulationEvidenceStatus.PASS
    assert evidence.live_simulation_passed is True
    assert evidence.human_review_required is False


def test_direct_ngspice_pass_requires_detected_tool_version() -> None:
    with pytest.raises(ValidationError, match="requires a detected tool version"):
        SimulationCheckEvidence(
            check_id="unidentified-solver-pass",
            domain=SimulationDomain.DC_OPERATING_POINT,
            method=SimulationEvidenceMethod.NGSPICE,
            engine_status="pass",
            status=SimulationEvidenceStatus.PASS,
            risk_class=SimulationRiskClass.LOW,
            blocking=False,
            human_review_required=False,
            summary="solver pass without tool identity",
            model_ids=["model-1"],
        )


def test_skip_is_explicit_high_risk_and_never_passes() -> None:
    evidence = normalize_simulation_gate(
        check_id="buck-transient",
        domain=SimulationDomain.TRANSIENT,
        engine_status="skipped",
        method=SimulationEvidenceMethod.NGSPICE,
        summary="ngspice unavailable",
        models=[_model(method=SimulationEvidenceMethod.NGSPICE, degraded=True)],
    )

    assert evidence.status == SimulationEvidenceStatus.SKIPPED
    assert evidence.risk_class == SimulationRiskClass.HIGH
    assert evidence.blocking is True
    assert evidence.human_review_required is True
    assert evidence.live_simulation_passed is False


def test_failed_gate_records_repair_hints() -> None:
    evidence = normalize_simulation_gate(
        check_id="buck-transient",
        domain=SimulationDomain.TRANSIENT,
        engine_status="fail",
        method=SimulationEvidenceMethod.NGSPICE,
        summary="steady-state ripple failed",
        models=[_model(method=SimulationEvidenceMethod.NGSPICE, degraded=True)],
        repair_hints=["increase output capacitance or reduce capacitor ESR"],
    )

    assert evidence.status == SimulationEvidenceStatus.FAIL
    assert evidence.blocking is True
    assert evidence.repair_hints


def test_family_report_is_hash_bound_and_counts_evidence() -> None:
    checks = [
        normalize_simulation_gate(
            check_id="buck-transient",
            domain=SimulationDomain.TRANSIENT,
            engine_status="pass",
            method=SimulationEvidenceMethod.NGSPICE,
            summary="transient checks passed",
            models=[_model(method=SimulationEvidenceMethod.NGSPICE, degraded=True)],
            tool_version="ngspice-42",
        ),
        normalize_simulation_gate(
            check_id="regulator-margin",
            domain=SimulationDomain.THERMAL,
            engine_status="pass",
            method=SimulationEvidenceMethod.ANALYTICAL,
            summary="regulator margins pass",
            models=[],
        ),
    ]
    report = SimulationFamilyReport.build(
        family_id="switching_regulator_module",
        title="Switching regulator module",
        design_state_hash="b" * 64,
        models=[_model(method=SimulationEvidenceMethod.NGSPICE, degraded=True)],
        checks=checks,
        assumptions=["fixture is family-bound rather than extracted from a selected device model"],
    )

    assert report.check_count == 2
    assert report.live_simulation_pass_count == 1
    assert report.human_review_required is True
    assert report.report_sha256 == report.compute_sha256()
    report.assumptions.append("tampered")
    assert report.report_sha256 != report.compute_sha256()


def test_report_writer_rejects_path_escape(tmp_path: Path) -> None:
    from zaptrace.analysis.simulation_signoff import write_simulation_family_report

    trusted = tmp_path / "trusted"
    trusted.mkdir()
    report = SimulationFamilyReport.build(
        family_id="f",
        title="F",
        design_state_hash="b" * 64,
        models=[],
        checks=[],
        assumptions=[],
    )
    with pytest.raises(ValueError, match="escapes trusted root"):
        write_simulation_family_report(report, tmp_path / "outside.json", trusted_root=trusted)


def test_solver_pass_without_model_provenance_is_explicit_skip() -> None:
    evidence = normalize_simulation_gate(
        check_id="unbound-solver",
        domain=SimulationDomain.TRANSIENT,
        engine_status="pass",
        method=SimulationEvidenceMethod.NGSPICE,
        summary="solver ran without governed model provenance",
        models=[],
    )
    assert evidence.status == SimulationEvidenceStatus.SKIPPED
    assert evidence.risk_class == SimulationRiskClass.HIGH
    assert evidence.blocking is True
    assert evidence.human_review_required is True
    assert evidence.live_simulation_passed is False


def test_solver_pass_with_model_but_without_tool_version_is_explicit_skip() -> None:
    evidence = normalize_simulation_gate(
        check_id="unidentified-solver",
        domain=SimulationDomain.TRANSIENT,
        engine_status="pass",
        method=SimulationEvidenceMethod.NGSPICE,
        summary="solver passed but version detection failed",
        models=[_model(method=SimulationEvidenceMethod.NGSPICE)],
    )
    assert evidence.status == SimulationEvidenceStatus.SKIPPED
    assert evidence.risk_class == SimulationRiskClass.HIGH
    assert evidence.blocking is True
    assert evidence.live_simulation_passed is False


def test_tool_version_is_retained_for_solver_evidence() -> None:
    evidence = normalize_simulation_gate(
        check_id="solver-version",
        domain=SimulationDomain.TRANSIENT,
        engine_status="pass",
        method=SimulationEvidenceMethod.NGSPICE,
        summary="solver passed",
        models=[_model(method=SimulationEvidenceMethod.NGSPICE)],
        tool_version="ngspice-42",
    )
    assert evidence.tool_version == "ngspice-42"


def test_normalized_gate_decision_covers_all_status_classes() -> None:
    assert _normalized_gate_decision(
        "pass",
        SimulationEvidenceMethod.NGSPICE,
        degraded=False,
        missing_solver_identity=False,
    ) == (SimulationEvidenceStatus.PASS, SimulationRiskClass.LOW, False, False)
    assert _normalized_gate_decision(
        "pass",
        SimulationEvidenceMethod.ANALYTICAL,
        degraded=False,
        missing_solver_identity=False,
    ) == (
        SimulationEvidenceStatus.HUMAN_REVIEW_REQUIRED,
        SimulationRiskClass.MODERATE,
        False,
        True,
    )
    assert _normalized_gate_decision(
        "error",
        SimulationEvidenceMethod.NGSPICE,
        degraded=False,
        missing_solver_identity=False,
    ) == (SimulationEvidenceStatus.FAIL, SimulationRiskClass.CRITICAL, True, True)
    assert _normalized_gate_decision(
        "skipped",
        SimulationEvidenceMethod.NGSPICE,
        degraded=False,
        missing_solver_identity=False,
    ) == (SimulationEvidenceStatus.SKIPPED, SimulationRiskClass.HIGH, True, True)
    assert _normalized_gate_decision(
        "review",
        SimulationEvidenceMethod.NGSPICE,
        degraded=False,
        missing_solver_identity=False,
    ) == (
        SimulationEvidenceStatus.HUMAN_REVIEW_REQUIRED,
        SimulationRiskClass.MODERATE,
        False,
        True,
    )
    assert _normalized_gate_decision(
        "unknown",
        SimulationEvidenceMethod.NGSPICE,
        degraded=False,
        missing_solver_identity=False,
    ) == (
        SimulationEvidenceStatus.HUMAN_REVIEW_REQUIRED,
        SimulationRiskClass.HIGH,
        False,
        True,
    )
