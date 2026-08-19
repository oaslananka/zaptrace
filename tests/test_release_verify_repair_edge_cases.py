"""Fail-closed edge cases for release verify/repair evidence and output handling."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from zaptrace.benchmark import release_convergence
from zaptrace.core.models import Component, Design, DesignMeta
from zaptrace.core.state import design_state_hash
from zaptrace.pipeline import verify_repair
from zaptrace.pipeline.verify_repair import VerifyRepairContext
from zaptrace.pipeline.verify_repair_models import (
    FailureEvidence,
    FailureSeverity,
    GateDomain,
    GateEvidence,
    GateVerdict,
    Repairability,
    VerifyRepairPolicy,
    VerifyRepairStopReason,
    release_verify_repair_report_json,
    resolve_verify_repair_output_path,
)
from zaptrace.proof import ProofManifest, attach_verify_repair_evidence


def _design(*, footprint: str = "0402") -> Design:
    design = Design(meta=DesignMeta(name="verify-repair-edge"))
    design.components["R1"] = Component(
        id="R1",
        ref="R1",
        type="resistor",
        value="10k",
        footprint=footprint,
    )
    return design


def _policy(*domains: GateDomain) -> VerifyRepairPolicy:
    return VerifyRepairPolicy(
        policy_version="edge-policy",
        max_iterations=1,
        enabled_domains=list(domains or (GateDomain.ERC,)),
    )


def _context(*domains: GateDomain) -> VerifyRepairContext:
    return VerifyRepairContext(policy=_policy(*domains))


def _finding(
    *,
    domain: GateDomain = GateDomain.ERC,
    verdict: GateVerdict = GateVerdict.BLOCKED,
    repairability: Repairability = Repairability.NON_REPAIRABLE,
) -> FailureEvidence:
    return FailureEvidence(
        failure_id=f"{domain.value}:fixture",
        domain=domain,
        rule_id="fixture",
        severity=FailureSeverity.ERROR,
        verdict=verdict,
        repairability=repairability,
        message="fixture finding",
        requires_human_review=verdict != GateVerdict.WARNING,
    )


def test_gate_error_builds_critical_state_bound_evidence() -> None:
    design = _design()
    state_hash = design_state_hash(design)

    evidence = verify_repair._gate_error(GateDomain.ERC, state_hash, "gate failed")

    assert evidence.verdict == GateVerdict.ERROR
    assert evidence.findings[0].severity == FailureSeverity.CRITICAL
    assert evidence.design_state_hash == state_hash


@pytest.mark.parametrize("variant", ["missing", "raises", "wrong-domain", "wrong-hash"])
def test_run_gates_fails_closed_for_invalid_adapters(variant: str) -> None:
    design = _design()
    state_hash = design_state_hash(design)
    adapters = {}
    if variant == "raises":
        adapters[GateDomain.ERC] = lambda _design, _context: (_ for _ in ()).throw(RuntimeError("boom"))
    elif variant == "wrong-domain":
        adapters[GateDomain.ERC] = lambda _design, _context: GateEvidence.pass_result(
            GateDomain.DRC,
            state_hash,
        )
    elif variant == "wrong-hash":
        adapters[GateDomain.ERC] = lambda _design, _context: GateEvidence.pass_result(
            GateDomain.ERC,
            "0" * 64,
        )

    evidence = verify_repair._run_gates(design, _context(), adapters)[0]

    assert evidence.verdict == GateVerdict.ERROR
    assert evidence.findings[-1].rule_id == "gate-execution"


def test_replace_gate_with_repair_error_appends_missing_domain() -> None:
    design = _design()
    state_hash = design_state_hash(design)
    existing = GateEvidence.pass_result(GateDomain.DRC, state_hash)

    result = verify_repair._replace_gate_with_repair_error(
        [existing],
        domain=GateDomain.ERC,
        state_hash=state_hash,
        message="repair failed",
    )

    assert [gate.domain for gate in result] == [GateDomain.DRC, GateDomain.ERC]
    assert result[-1].verdict == GateVerdict.ERROR


def test_terminal_reason_handles_gate_error_and_empty_failures() -> None:
    state_hash = design_state_hash(_design())
    error_gate = GateEvidence.from_findings(
        domain=GateDomain.ERC,
        design_state_hash=state_hash,
        findings=[_finding(verdict=GateVerdict.ERROR)],
    )
    pass_gate = GateEvidence.pass_result(GateDomain.ERC, state_hash)

    assert verify_repair._terminal_reason_before_repair([error_gate]) == VerifyRepairStopReason.GATE_EXECUTION_ERROR
    assert verify_repair._terminal_reason_before_repair([pass_gate]) is None


def test_untyped_repair_mutation_is_rolled_back() -> None:
    def gate(design: Design, _context: VerifyRepairContext) -> GateEvidence:
        state_hash = design_state_hash(design)
        if design.components["R1"].footprint:
            return GateEvidence.pass_result(GateDomain.ERC, state_hash)
        return GateEvidence.from_findings(
            domain=GateDomain.ERC,
            design_state_hash=state_hash,
            findings=[
                _finding(
                    verdict=GateVerdict.WARNING,
                    repairability=Repairability.AUTO_REPAIRABLE,
                )
            ],
        )

    def untyped_mutation(design: Design, _failures: list[FailureEvidence], _context: VerifyRepairContext) -> None:
        design.components["R1"].footprint = "0402"
        return None

    outcome = verify_repair.run_verify_repair(
        _design(footprint=""),
        policy=_policy(),
        gate_adapters={GateDomain.ERC: gate},
        repair_adapters=[untyped_mutation],
    )

    assert outcome.design.components["R1"].footprint == ""
    assert outcome.report.stop_reason == VerifyRepairStopReason.REPAIR_EXECUTION_ERROR


def test_resolve_adapters_fills_each_omitted_registry() -> None:
    gate_adapters, default_repairs = verify_repair._resolve_adapters({}, None)
    default_gates, repair_adapters = verify_repair._resolve_adapters(None, [])

    assert gate_adapters == {}
    assert default_repairs
    assert default_gates
    assert repair_adapters == []


def test_gate_evidence_passed_and_fallback_verdicts() -> None:
    state_hash = design_state_hash(_design())
    passed = GateEvidence.pass_result(GateDomain.ERC, state_hash)
    blocked = GateEvidence.from_findings(
        domain=GateDomain.ERC,
        design_state_hash=state_hash,
        findings=[_finding()],
    )
    skipped = GateEvidence.from_findings(
        domain=GateDomain.ERC,
        design_state_hash=state_hash,
        findings=[_finding(verdict=GateVerdict.SKIPPED)],
    )
    empty = GateEvidence.from_findings(
        domain=GateDomain.ERC,
        design_state_hash=state_hash,
        findings=[],
    )

    assert passed.passed is True
    assert blocked.passed is False
    assert skipped.verdict == GateVerdict.SKIPPED
    assert empty.verdict == GateVerdict.PASS


@pytest.mark.parametrize("domains", [[], [GateDomain.ERC, GateDomain.ERC]])
def test_policy_rejects_empty_or_duplicate_domains(domains: list[GateDomain]) -> None:
    kwargs = {
        "policy_version": "invalid",
        "max_iterations": 1,
        "enabled_domains": domains,
    }
    with pytest.raises(ValidationError):
        VerifyRepairPolicy(**kwargs)


def test_relative_output_path_resolves_inside_trusted_root(tmp_path: Path) -> None:
    resolved = resolve_verify_repair_output_path("reports/result.json", trusted_root=tmp_path, require_json=True)
    assert resolved == tmp_path / "reports" / "result.json"


def _passing_outcome() -> verify_repair.VerifyRepairOutcome:
    return verify_repair.run_verify_repair(
        _design(),
        policy=_policy(),
        gate_adapters={
            GateDomain.ERC: lambda design, _context: GateEvidence.pass_result(
                GateDomain.ERC,
                design_state_hash(design),
            )
        },
        repair_adapters=[],
    )


def test_report_json_finalizes_missing_digest_and_rejects_tampering() -> None:
    report = _passing_outcome().report
    report.report_sha256 = ""

    payload = release_verify_repair_report_json(report)

    assert report.report_sha256
    assert '"report_sha256"' in payload
    report.design_name = "tampered"
    with pytest.raises(ValueError, match="hash does not match"):
        release_verify_repair_report_json(report)


def test_proof_attachment_rejects_unfinalized_report() -> None:
    report = _passing_outcome().report
    report.report_sha256 = ""
    manifest = ProofManifest(name="edge-proof", design_path="design.yaml")

    with pytest.raises(ValueError, match="finalized and hash-valid"):
        attach_verify_repair_evidence(manifest, report, report_path="verify-repair.json")


def test_remove_benchmark_owned_children_keeps_marker(tmp_path: Path) -> None:
    marker = tmp_path / release_convergence._OUTPUT_MARKER
    marker.write_text("owned\n", encoding="utf-8")
    stale_file = tmp_path / "stale.json"
    stale_file.write_text("stale", encoding="utf-8")
    stale_dir = tmp_path / "stale-dir"
    stale_dir.mkdir()
    (stale_dir / "child").write_text("stale", encoding="utf-8")

    release_convergence._remove_benchmark_owned_children(tmp_path, marker)

    assert marker.exists()
    assert not stale_file.exists()
    assert not stale_dir.exists()


def test_prepare_existing_output_rejects_file_and_unowned_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("fixture", encoding="utf-8")
    file_marker = file_path / release_convergence._OUTPUT_MARKER
    with pytest.raises(ValueError, match="not a directory"):
        release_convergence._prepare_existing_output_dir(file_path, file_marker)

    unowned = tmp_path / "unowned"
    unowned.mkdir()
    (unowned / "foreign.txt").write_text("foreign", encoding="utf-8")
    unowned_marker = unowned / release_convergence._OUTPUT_MARKER
    with pytest.raises(ValueError, match="not benchmark-owned"):
        release_convergence._prepare_existing_output_dir(unowned, unowned_marker)


def test_prepare_output_dir_rejects_root_and_cleans_owned_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe release convergence output"):
        release_convergence._prepare_output_dir(tmp_path, trusted_root=tmp_path)

    owned = tmp_path / "owned"
    owned.mkdir()
    marker = owned / release_convergence._OUTPUT_MARKER
    marker.write_text("owned\n", encoding="utf-8")
    (owned / "stale.txt").write_text("stale", encoding="utf-8")

    resolved = release_convergence._prepare_output_dir(owned, trusted_root=tmp_path)

    assert resolved == owned
    assert marker.exists()
    assert not (owned / "stale.txt").exists()
