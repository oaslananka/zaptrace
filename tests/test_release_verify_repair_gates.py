"""Focused branch coverage for release verify/repair gate adapters."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from zaptrace.core.models import Component, Design, DesignMeta, DRCSeverity
from zaptrace.erc.models import ERCSeverity
from zaptrace.pipeline import verify_repair_gates as gates
from zaptrace.pipeline.verify_repair import VerifyRepairContext
from zaptrace.pipeline.verify_repair_models import (
    FailureEvidence,
    FailureSeverity,
    GateDomain,
    GateVerdict,
    Repairability,
    VerifyRepairPolicy,
)
from zaptrace.security.release import ReleaseEvidenceStatus


def _design() -> Design:
    design = Design(meta=DesignMeta(name="gate-adapter-test"))
    design.components["R1"] = Component(id="R1", ref="R1", type="resistor", value="10k", footprint="0402")
    return design


def _context(tmp_path: Path | None = None, **policy_overrides: Any) -> VerifyRepairContext:
    policy = VerifyRepairPolicy(
        policy_version="gate-test",
        max_iterations=1,
        enabled_domains=[GateDomain.ERC],
        **policy_overrides,
    )
    return VerifyRepairContext(policy=policy, output_dir=tmp_path)


def _erc_result(violations: list[Any]) -> Any:
    return SimpleNamespace(
        active_violations=violations,
        total_errors=sum(item.severity.value == "error" for item in violations),
        total_warnings=sum(item.severity.value == "warning" for item in violations),
        total_info=sum(item.severity.value == "info" for item in violations),
        checks_run=[object()],
        coverage_gaps=["fixture gap"],
        coverage_summary=lambda: "fixture ERC coverage",
    )


def _violation(*, severity: str, rule_id: str = "ERC999") -> Any:
    return SimpleNamespace(
        rule_id=rule_id,
        severity=ERCSeverity(severity),
        message=f"{severity} finding",
        component_refs=["R1"],
        net_refs=["N1"],
        patch_suggestion="review fixture",
    )


def test_failure_severity_covers_critical_and_info() -> None:
    assert gates._failure_severity("critical") == FailureSeverity.CRITICAL
    assert gates._failure_severity("other") == FailureSeverity.INFO


def test_erc_handler_exception_is_not_auto_repairable(monkeypatch: pytest.MonkeyPatch) -> None:
    def exploding_handler(_design: Design, _violations: list[Any]) -> list[Any]:
        raise RuntimeError("handler failed")

    monkeypatch.setattr(gates.REPAIR_REGISTRY, "get_handler", lambda _rule: exploding_handler)
    assert gates._erc_handler_can_apply(_design(), _violation(severity="warning")) is False


@pytest.mark.parametrize(
    ("severity", "review_warnings", "expected_verdict", "expected_review"),
    [
        ("error", False, GateVerdict.BLOCKED, True),
        ("warning", True, GateVerdict.HUMAN_REVIEW_REQUIRED, True),
        ("warning", False, GateVerdict.WARNING, False),
    ],
)
def test_erc_gate_classifies_unhandled_findings(
    monkeypatch: pytest.MonkeyPatch,
    severity: str,
    review_warnings: bool,
    expected_verdict: GateVerdict,
    expected_review: bool,
) -> None:
    result = _erc_result([_violation(severity=severity)])
    monkeypatch.setattr(gates, "ERCRunner", lambda: SimpleNamespace(run=lambda _design: result))
    monkeypatch.setattr(gates, "_erc_handler_can_apply", lambda _design, _violation: False)

    evidence = gates.erc_gate(_design(), _context(erc_warnings_require_review=review_warnings))

    assert evidence.findings[0].verdict == expected_verdict
    assert evidence.findings[0].requires_human_review is expected_review


def test_erc_gate_passes_without_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _erc_result([])
    monkeypatch.setattr(gates, "ERCRunner", lambda: SimpleNamespace(run=lambda _design: result))

    evidence = gates.erc_gate(_design(), _context())

    assert evidence.verdict == GateVerdict.PASS
    assert evidence.summary == "fixture ERC coverage"


def test_erc_registry_repair_returns_none_without_applicable_failure() -> None:
    failure = FailureEvidence(
        failure_id="drc:1",
        domain=GateDomain.DRC,
        rule_id="DRC-001",
        severity=FailureSeverity.ERROR,
        verdict=GateVerdict.BLOCKED,
        repairability=Repairability.HUMAN_REPAIRABLE,
        message="manual repair",
    )
    assert gates.erc_registry_repair(_design(), [failure], _context()) is None


def test_erc_registry_repair_returns_none_for_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = FailureEvidence(
        failure_id="erc:1",
        domain=GateDomain.ERC,
        rule_id="ERC020",
        severity=FailureSeverity.WARNING,
        verdict=GateVerdict.WARNING,
        repairability=Repairability.AUTO_REPAIRABLE,
        message="missing footprint",
    )
    monkeypatch.setattr(
        gates,
        "repair_design",
        lambda _design, max_iterations: SimpleNamespace(patches=[], decisions=[], remaining=[]),
    )
    assert gates.erc_registry_repair(_design(), [failure], _context()) is None


def _drc_violation(severity: str) -> Any:
    return SimpleNamespace(
        rule_id="DRC-X",
        severity=DRCSeverity(severity),
        message=f"{severity} DRC",
        component_id="R1",
        net_id="N1",
        location="(1, 2)",
    )


@pytest.mark.parametrize(
    ("violations", "review_warnings", "expected"),
    [([], False, GateVerdict.PASS), ([_drc_violation("warning")], True, GateVerdict.HUMAN_REVIEW_REQUIRED)],
)
def test_drc_gate_pass_and_warning_review(
    monkeypatch: pytest.MonkeyPatch,
    violations: list[Any],
    review_warnings: bool,
    expected: GateVerdict,
) -> None:
    result = SimpleNamespace(
        violations=violations,
        errors=0,
        warnings=len(violations),
        info=0,
        total_violations=len(violations),
    )
    monkeypatch.setattr(gates, "DRCEngine", lambda: SimpleNamespace(run=lambda _design: result))

    evidence = gates.drc_gate(_design(), _context(drc_warnings_require_review=review_warnings))

    assert evidence.verdict == expected


def _dfm_violation(severity: str) -> Any:
    return SimpleNamespace(
        rule_id="dfm-x",
        severity=severity,
        message=f"{severity} DFM",
        location="R1",
        actual="0.1",
        expected="0.2",
    )


@pytest.mark.parametrize(
    ("severity", "expected_verdict", "expected_repairability"),
    [
        ("error", GateVerdict.BLOCKED, Repairability.HUMAN_REPAIRABLE),
        ("human-review-required", GateVerdict.HUMAN_REVIEW_REQUIRED, Repairability.NON_REPAIRABLE),
        ("warning", GateVerdict.WARNING, Repairability.HUMAN_REPAIRABLE),
    ],
)
def test_dfm_gate_classifies_findings(
    monkeypatch: pytest.MonkeyPatch,
    severity: str,
    expected_verdict: GateVerdict,
    expected_repairability: Repairability,
) -> None:
    profile = SimpleNamespace(name="fixture-fab")
    result = SimpleNamespace(
        violations=[_dfm_violation(severity)],
        readiness_status=SimpleNamespace(value="fixture-status"),
        to_dict=lambda: {"status": "fixture-status"},
    )
    monkeypatch.setattr(gates, "load_profile", lambda _name: profile)
    monkeypatch.setattr(gates, "DFMChecker", lambda _profile: SimpleNamespace(check=lambda _design: result))

    evidence = gates.dfm_gate(_design(), _context())

    assert evidence.findings[0].verdict == expected_verdict
    assert evidence.findings[0].repairability == expected_repairability


def test_dfm_gate_passes_without_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = SimpleNamespace(name="fixture-fab")
    result = SimpleNamespace(violations=[])
    monkeypatch.setattr(gates, "load_profile", lambda _name: profile)
    monkeypatch.setattr(gates, "DFMChecker", lambda _profile: SimpleNamespace(check=lambda _design: result))

    evidence = gates.dfm_gate(_design(), _context())

    assert evidence.verdict == GateVerdict.PASS


@pytest.mark.parametrize(
    ("status", "blocking", "expected_verdict", "expected_review"),
    [
        ("pass", False, GateVerdict.PASS, False),
        ("skipped", False, GateVerdict.WARNING, False),
        ("no_reference", True, GateVerdict.HUMAN_REVIEW_REQUIRED, True),
        ("fail", True, GateVerdict.BLOCKED, True),
    ],
)
def test_simulation_gate_classifies_status(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    blocking: bool,
    expected_verdict: GateVerdict,
    expected_review: bool,
) -> None:
    result = SimpleNamespace(
        status=SimpleNamespace(value=status),
        blocking=blocking,
        reason=f"simulation {status}",
        to_dict=lambda: {"status": status, "blocking": blocking},
    )
    monkeypatch.setattr(gates, "run_simulation_gate", lambda _design, strict: result)

    evidence = gates.simulation_gate(_design(), _context(strict_simulation=True))

    assert evidence.verdict == expected_verdict
    assert evidence.human_review_required is expected_review


def test_supply_chain_gate_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gates,
        "build_component_coverage",
        lambda _design: {"status": SimpleNamespace(value=ReleaseEvidenceStatus.PASS.value)},
    )

    evidence = gates.supply_chain_gate(_design(), _context())

    assert evidence.verdict == GateVerdict.PASS


def test_supply_chain_gate_emits_grouped_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gates,
        "build_component_coverage",
        lambda _design: {
            "status": "human-review-required",
            "unresolved_components": [{"component_ref": "R1"}],
            "placement_missing_components": [{"ref": "R2"}],
            "blocked_components": [{"component_id": "R3"}],
        },
    )

    evidence = gates.supply_chain_gate(_design(), _context())

    assert [item.rule_id for item in evidence.findings] == [
        "unresolved-component",
        "placement-missing",
        "release-blocked-component",
    ]


def test_supply_chain_gate_fails_closed_without_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gates, "build_component_coverage", lambda _design: {"status": "missing-evidence"})

    evidence = gates.supply_chain_gate(_design(), _context())

    assert evidence.findings[0].repairability == Repairability.NON_REPAIRABLE


def test_kicad_oracle_requires_output_dir() -> None:
    evidence = gates.kicad_oracle_gate(_design(), _context())
    assert evidence.findings[0].rule_id == "missing-output-dir"


def test_kicad_oracle_reports_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import zaptrace.kicad.oracle as oracle_module

    monkeypatch.setattr(oracle_module, "detect_kicad", lambda: SimpleNamespace(available=False))

    evidence = gates.kicad_oracle_gate(_design(), _context(tmp_path))

    assert evidence.findings[0].rule_id == "oracle-unavailable"


def _oracle_result(*, passed: bool, name: str) -> Any:
    return SimpleNamespace(
        passed=passed,
        message=f"{name} result",
        errors=0 if passed else 1,
        warnings=0,
        report_path=f"{name}.json",
        report_sha256="a" * 64,
    )


@pytest.mark.parametrize("passed", [True, False])
def test_kicad_oracle_available_pass_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    passed: bool,
) -> None:
    import zaptrace.export.kicad as export_module
    import zaptrace.kicad.oracle as oracle_module

    project = tmp_path / "fixture.kicad_pro"
    pcb = tmp_path / "fixture.kicad_pcb"
    project.write_text("fixture", encoding="utf-8")
    pcb.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(export_module, "export_kicad", lambda _design, _dir: {"project": project, "pcb": pcb})
    oracle = SimpleNamespace(
        available=True,
        version="9.0",
        run_erc=lambda *_args, **_kwargs: _oracle_result(passed=passed, name="erc"),
        run_drc=lambda *_args, **_kwargs: _oracle_result(passed=passed, name="drc"),
    )
    monkeypatch.setattr(oracle_module, "detect_kicad", lambda: oracle)

    evidence = gates.kicad_oracle_gate(_design(), _context(tmp_path))

    assert evidence.verdict == (GateVerdict.PASS if passed else GateVerdict.BLOCKED)


def _proof_result(status: Any, *, name: str = "fixture") -> Any:
    check = SimpleNamespace(name=name, severity=SimpleNamespace(value="error"))
    return SimpleNamespace(
        status=status,
        check=check,
        message=f"{name} message",
        to_dict=lambda: {"name": name, "status": str(status)},
    )


@pytest.mark.parametrize("status_name", ["pass", "fail", "error", "skip"])
def test_proof_pack_gate_classifies_results(monkeypatch: pytest.MonkeyPatch, status_name: str) -> None:
    import zaptrace.synthesis.proof as proof_module
    from zaptrace.proof.checker import CheckStatus, ProofRunner

    status = CheckStatus(status_name)
    monkeypatch.setattr(proof_module, "_baseline_checks", lambda _design: [object()])
    monkeypatch.setattr(ProofRunner, "run_checks", lambda _self, _checks: [_proof_result(status)])

    evidence = gates.proof_pack_gate(_design(), _context())

    expected = (
        GateVerdict.PASS
        if status == CheckStatus.PASS
        else (GateVerdict.BLOCKED if status in {CheckStatus.FAIL, CheckStatus.ERROR} else GateVerdict.WARNING)
    )
    assert evidence.verdict == expected
