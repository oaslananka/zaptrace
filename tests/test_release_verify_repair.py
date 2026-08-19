"""Release-grade verify/repair orchestration contracts for issue #245."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from zaptrace.core.models import Component, Design, DesignMeta
from zaptrace.core.state import design_state_hash
from zaptrace.pipeline.verify_repair import run_verify_repair
from zaptrace.pipeline.verify_repair_models import (
    FailureEvidence,
    FailureSeverity,
    GateDomain,
    GateEvidence,
    GateVerdict,
    Repairability,
    RepairApplication,
    VerifyRepairPolicy,
    VerifyRepairStopReason,
    release_verify_repair_report_json,
    write_release_verify_repair_report,
)


def _design(*, footprint: str = "") -> Design:
    design = Design(meta=DesignMeta(name="verify-repair-test"))
    design.components["R1"] = Component(
        id="R1",
        ref="R1",
        type="resistor",
        value="10k",
        footprint=footprint,
    )
    return design


def _footprint_gate(design: Design, _context) -> GateEvidence:
    component = design.components["R1"]
    if component.footprint:
        return GateEvidence.pass_result(GateDomain.ERC, design_state_hash(design), "footprint assigned")
    finding = FailureEvidence(
        failure_id="erc:ERC020:R1",
        domain=GateDomain.ERC,
        rule_id="ERC020",
        severity=FailureSeverity.ERROR,
        verdict=GateVerdict.BLOCKED,
        repairability=Repairability.AUTO_REPAIRABLE,
        message="R1 has no footprint",
        affected_refs=["R1"],
    )
    return GateEvidence.from_findings(
        domain=GateDomain.ERC,
        design_state_hash=design_state_hash(design),
        findings=[finding],
        summary="missing footprint",
    )


def _footprint_repair(design: Design, failures: list[FailureEvidence], _context) -> RepairApplication | None:
    if not any(item.rule_id == "ERC020" for item in failures):
        return None
    design.components["R1"].footprint = "0402"
    return RepairApplication(
        repair_id="erc-footprint",
        domains=[GateDomain.ERC],
        rationale="assign deterministic resistor footprint",
        patches=[
            {
                "rule_id": "ERC020",
                "component_ref": "R1",
                "field": "footprint",
                "old_value": "",
                "new_value": "0402",
            }
        ],
    )


def test_release_policy_is_versioned_and_enables_every_required_domain() -> None:
    policy = VerifyRepairPolicy.release_default()

    assert policy.max_iterations == 3
    assert set(policy.enabled_domains) == set(GateDomain)
    assert len(policy.identity_sha256()) == 64
    assert policy.identity_sha256() == VerifyRepairPolicy.release_default().identity_sha256()


def test_orchestrator_repairs_a_copy_and_records_hash_bound_semantic_diff() -> None:
    original = _design()
    original_hash = design_state_hash(original)
    policy = VerifyRepairPolicy(
        policy_version="test-1",
        max_iterations=2,
        enabled_domains=[GateDomain.ERC],
    )

    outcome = run_verify_repair(
        original,
        policy=policy,
        gate_adapters={GateDomain.ERC: _footprint_gate},
        repair_adapters=[_footprint_repair],
    )

    assert outcome.report.stop_reason == VerifyRepairStopReason.ALL_GATES_PASSED
    assert outcome.report.converged is True
    assert outcome.design.components["R1"].footprint == "0402"
    assert original.components["R1"].footprint == ""
    assert design_state_hash(original) == original_hash
    assert outcome.report.initial_design_state_hash == original_hash
    assert outcome.report.final_design_state_hash == design_state_hash(outcome.design)
    assert len(outcome.report.repairs) == 1
    repair = outcome.report.repairs[0]
    assert repair.before_state_hash == original_hash
    assert repair.after_state_hash == outcome.report.final_design_state_hash
    assert repair.improved is True
    assert any(item.type == "footprint_changed" and item.ref == "R1" for item in repair.semantic_diff)
    assert [item.phase for item in outcome.report.gate_history] == ["initial", "post-repair"]


def test_non_repairable_high_risk_failure_stops_with_human_review_evidence() -> None:
    def unsafe_gate(design: Design, _context) -> GateEvidence:
        finding = FailureEvidence(
            failure_id="simulation:unsafe-rail",
            domain=GateDomain.SIMULATION,
            rule_id="rail-overvoltage",
            severity=FailureSeverity.CRITICAL,
            verdict=GateVerdict.BLOCKED,
            repairability=Repairability.NON_REPAIRABLE,
            message="simulated rail exceeds absolute maximum",
            requires_human_review=True,
        )
        return GateEvidence.from_findings(
            domain=GateDomain.SIMULATION,
            design_state_hash=design_state_hash(design),
            findings=[finding],
            summary="unsafe rail",
        )

    outcome = run_verify_repair(
        _design(footprint="0402"),
        policy=VerifyRepairPolicy(
            policy_version="test-unsafe",
            max_iterations=2,
            enabled_domains=[GateDomain.SIMULATION],
        ),
        gate_adapters={GateDomain.SIMULATION: unsafe_gate},
        repair_adapters=[],
    )

    assert outcome.report.stop_reason == VerifyRepairStopReason.NON_REPAIRABLE
    assert outcome.report.converged is False
    assert outcome.report.blocks_autonomous_release is True
    assert outcome.report.human_review_required is True
    assert outcome.report.human_review_reasons == ["simulated rail exceeds absolute maximum"]
    assert outcome.report.repairs == []


def test_repair_that_changes_state_without_reducing_blockers_stops_no_progress() -> None:
    def ineffective_repair(design: Design, _failures, _context) -> RepairApplication:
        design.components["R1"].value = "11k"
        return RepairApplication(
            repair_id="ineffective",
            domains=[GateDomain.ERC],
            rationale="changes an unrelated value",
            patches=[{"field": "value", "old_value": "10k", "new_value": "11k"}],
        )

    outcome = run_verify_repair(
        _design(),
        policy=VerifyRepairPolicy(
            policy_version="test-no-progress",
            max_iterations=3,
            enabled_domains=[GateDomain.ERC],
        ),
        gate_adapters={GateDomain.ERC: _footprint_gate},
        repair_adapters=[ineffective_repair],
    )

    assert outcome.report.stop_reason == VerifyRepairStopReason.NO_PROGRESS
    assert outcome.report.iterations_used == 1
    assert outcome.report.repairs[0].improved is False
    assert outcome.report.repairs[0].before_blocking_count == outcome.report.repairs[0].after_blocking_count


def test_iteration_budget_is_a_hard_cap_with_deterministic_stop_reason() -> None:
    def countdown_gate(design: Design, _context) -> GateEvidence:
        count = int(design.meta.revision)
        if count == 0:
            return GateEvidence.pass_result(GateDomain.ERC, design_state_hash(design), "countdown complete")
        findings = [
            FailureEvidence(
                failure_id=f"erc:remaining:{index}",
                domain=GateDomain.ERC,
                rule_id="COUNTDOWN",
                severity=FailureSeverity.ERROR,
                verdict=GateVerdict.BLOCKED,
                repairability=Repairability.AUTO_REPAIRABLE,
                message=f"{count} repair rounds remain",
            )
            for index in range(count)
        ]
        return GateEvidence.from_findings(
            domain=GateDomain.ERC,
            design_state_hash=design_state_hash(design),
            findings=findings,
            summary="countdown",
        )

    def decrement(design: Design, _failures, _context) -> RepairApplication:
        before = design.meta.revision
        design.meta.revision -= 1
        return RepairApplication(
            repair_id=f"decrement-{before}",
            domains=[GateDomain.ERC],
            rationale="bounded synthetic progress",
            patches=[{"field": "meta.revision", "old_value": before, "new_value": design.meta.revision}],
        )

    design = _design(footprint="0402")
    design.meta.revision = 3
    policy = VerifyRepairPolicy(
        policy_version="test-budget",
        max_iterations=2,
        enabled_domains=[GateDomain.ERC],
    )

    first = run_verify_repair(
        design,
        policy=policy,
        gate_adapters={GateDomain.ERC: countdown_gate},
        repair_adapters=[decrement],
    )
    second = run_verify_repair(
        deepcopy(design),
        policy=policy,
        gate_adapters={GateDomain.ERC: countdown_gate},
        repair_adapters=[decrement],
    )

    assert first.report.stop_reason == VerifyRepairStopReason.ITERATION_BUDGET_EXHAUSTED
    assert first.report.iterations_used == 2
    assert first.report.final_design_state_hash == second.report.final_design_state_hash
    assert first.report.report_sha256 == second.report.report_sha256


def test_report_json_and_writer_preserve_report_identity(tmp_path: Path) -> None:
    outcome = run_verify_repair(
        _design(),
        policy=VerifyRepairPolicy(
            policy_version="test-json",
            max_iterations=1,
            enabled_domains=[GateDomain.ERC],
        ),
        gate_adapters={GateDomain.ERC: _footprint_gate},
        repair_adapters=[_footprint_repair],
    )

    rendered = release_verify_repair_report_json(outcome.report)
    path = write_release_verify_repair_report(outcome.report, tmp_path / "verify-repair.json", trusted_root=tmp_path)

    assert path.read_text(encoding="utf-8") == rendered
    assert outcome.report.report_sha256 in rendered
    with pytest.raises(ValueError, match="JSON"):
        write_release_verify_repair_report(outcome.report, tmp_path / "verify-repair.txt", trusted_root=tmp_path)


def test_default_adapter_registry_covers_every_release_domain() -> None:
    from zaptrace.pipeline.verify_repair_gates import default_gate_adapters

    assert set(default_gate_adapters()) == set(GateDomain)


def test_default_erc_adapter_uses_real_repair_registry() -> None:
    from zaptrace.pipeline.verify_repair_gates import default_gate_adapters, default_repair_adapters

    original = _design()
    outcome = run_verify_repair(
        original,
        policy=VerifyRepairPolicy(
            policy_version="real-erc",
            max_iterations=2,
            enabled_domains=[GateDomain.ERC],
            erc_warnings_require_review=False,
        ),
        gate_adapters=default_gate_adapters(),
        repair_adapters=default_repair_adapters(),
    )

    assert outcome.report.stop_reason == VerifyRepairStopReason.ALL_GATES_PASSED
    assert outcome.design.components["R1"].footprint == "0402"
    assert original.components["R1"].footprint == ""
    assert outcome.report.repairs[0].patches[0]["rule_id"] == "ERC020"
    assert outcome.report.repairs[0].semantic_diff[0].type == "footprint_changed"


def test_strict_simulation_skip_is_human_review_required(monkeypatch) -> None:
    from types import SimpleNamespace

    import zaptrace.pipeline.verify_repair_gates as gates

    monkeypatch.setattr(
        gates,
        "run_simulation_gate",
        lambda *_args, **_kwargs: SimpleNamespace(
            status=SimpleNamespace(value="skipped"),
            blocking=True,
            strict=True,
            reason="ngspice unavailable",
            checks=[],
            node_voltages={},
            to_dict=lambda: {
                "status": "skipped",
                "blocking": True,
                "strict": True,
                "reason": "ngspice unavailable",
                "checks": [],
                "node_voltages": {},
            },
        ),
    )

    outcome = run_verify_repair(
        _design(footprint="0402"),
        policy=VerifyRepairPolicy(
            policy_version="strict-sim",
            max_iterations=1,
            enabled_domains=[GateDomain.SIMULATION],
            strict_simulation=True,
        ),
        gate_adapters={GateDomain.SIMULATION: gates.simulation_gate},
        repair_adapters=[],
    )

    assert outcome.report.stop_reason == VerifyRepairStopReason.NON_REPAIRABLE
    gate = outcome.report.final_gates[0]
    assert gate.verdict == GateVerdict.HUMAN_REVIEW_REQUIRED
    assert gate.blocks_autonomous_release is True
    assert gate.findings[0].requires_human_review is True


def test_drc_errors_are_never_silently_auto_repaired() -> None:
    from zaptrace.core.models import Net, NetNode
    from zaptrace.pipeline.verify_repair_gates import drc_gate

    design = _design(footprint="0402")
    design.components["R2"] = Component(
        id="R2",
        ref="R2",
        type="resistor",
        value="10k",
        footprint="0402",
    )
    design.nets["SIGNAL"] = Net(
        id="SIGNAL",
        name="SIGNAL",
        nodes=[NetNode(component_ref="R1", pin_name="1"), NetNode(component_ref="R2", pin_name="1")],
    )

    outcome = run_verify_repair(
        design,
        policy=VerifyRepairPolicy(
            policy_version="real-drc",
            max_iterations=1,
            enabled_domains=[GateDomain.DRC],
        ),
        gate_adapters={GateDomain.DRC: drc_gate},
        repair_adapters=[],
    )

    assert outcome.report.stop_reason == VerifyRepairStopReason.HUMAN_REVIEW_REQUIRED
    assert outcome.report.repairs == []
    assert any(item.domain == GateDomain.DRC for item in outcome.report.final_gates[0].findings)
    assert all(item.repairability == Repairability.HUMAN_REPAIRABLE for item in outcome.report.final_gates[0].findings)


def test_proof_gate_returns_state_bound_evidence() -> None:
    from zaptrace.pipeline.verify_repair import VerifyRepairContext
    from zaptrace.pipeline.verify_repair_gates import proof_pack_gate

    design = _design(footprint="0402")
    evidence = proof_pack_gate(
        design,
        VerifyRepairContext(
            policy=VerifyRepairPolicy(
                policy_version="proof-gate",
                max_iterations=1,
                enabled_domains=[GateDomain.PROOF_PACK],
            )
        ),
    )

    assert evidence.domain == GateDomain.PROOF_PACK
    assert evidence.design_state_hash == design_state_hash(design)
    assert evidence.metadata["check_count"] > 0
    assert evidence.verdict in {GateVerdict.PASS, GateVerdict.WARNING, GateVerdict.BLOCKED}


def test_proof_manifest_binds_verify_repair_report_and_blocks_nonconvergence(tmp_path: Path) -> None:
    from zaptrace.proof import CheckDefinition, CheckResult, CheckStatus, ProofManifest, ProofPack
    from zaptrace.proof.signoff import AutonomousSignoffStatus
    from zaptrace.proof.verify_repair import attach_verify_repair_evidence

    outcome = run_verify_repair(
        _design(footprint="0402"),
        policy=VerifyRepairPolicy(
            policy_version="proof-blocked",
            max_iterations=1,
            enabled_domains=[GateDomain.SIMULATION],
        ),
        gate_adapters={
            GateDomain.SIMULATION: lambda design, _context: GateEvidence.from_findings(
                domain=GateDomain.SIMULATION,
                design_state_hash=design_state_hash(design),
                findings=[
                    FailureEvidence(
                        failure_id="simulation:missing",
                        domain=GateDomain.SIMULATION,
                        rule_id="missing-simulation-evidence",
                        severity=FailureSeverity.ERROR,
                        verdict=GateVerdict.HUMAN_REVIEW_REQUIRED,
                        repairability=Repairability.NON_REPAIRABLE,
                        message="simulation evidence is missing",
                        requires_human_review=True,
                    )
                ],
                summary="simulation missing",
            )
        },
        repair_adapters=[],
    )
    report_path = write_release_verify_repair_report(
        outcome.report, tmp_path / "verify-repair.json", trusted_root=tmp_path
    )
    manifest = ProofManifest(name="VerifyRepairBlocked", design_path="design.yaml")

    evidence = attach_verify_repair_evidence(manifest, outcome.report, report_path=report_path)
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    assert evidence.report_sha256 == outcome.report.report_sha256
    assert evidence.policy_sha256 == outcome.report.policy_sha256
    assert evidence.final_design_state_hash == outcome.report.final_design_state_hash
    assert evidence.stop_reason == VerifyRepairStopReason.NON_REPAIRABLE
    assert evidence.gate_history_count == len(outcome.report.gate_history)
    assert evidence.blocks_autonomous_release is True
    assert manifest.references["verify-repair.json"] == str(report_path)
    assert pack.autonomous_signoff.status == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert "verify-repair" in pack.autonomous_signoff.blocking_checks
    assert "verify-repair-human-review" in pack.autonomous_signoff.human_review_checks


def test_converged_verify_repair_evidence_allows_otherwise_passing_proof() -> None:
    from zaptrace.proof import CheckDefinition, CheckResult, CheckStatus, ProofManifest, ProofPack
    from zaptrace.proof.signoff import AutonomousSignoffStatus
    from zaptrace.proof.verify_repair import attach_verify_repair_evidence

    outcome = run_verify_repair(
        _design(),
        policy=VerifyRepairPolicy(
            policy_version="proof-pass",
            max_iterations=1,
            enabled_domains=[GateDomain.ERC],
        ),
        gate_adapters={GateDomain.ERC: _footprint_gate},
        repair_adapters=[_footprint_repair],
    )
    manifest = ProofManifest(name="VerifyRepairPass", design_path="design.yaml")
    attach_verify_repair_evidence(manifest, outcome.report, report_path="verify-repair.json")
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    assert manifest.verify_repair is not None
    assert manifest.verify_repair.converged is True
    assert pack.autonomous_signoff.status == AutonomousSignoffStatus.AUTONOMOUS_PASS


def test_safe_repairs_are_recorded_before_remaining_nonrepairable_handoff() -> None:
    def nonrepairable_gate(design: Design, _context) -> GateEvidence:
        return GateEvidence.from_findings(
            domain=GateDomain.SIMULATION,
            design_state_hash=design_state_hash(design),
            findings=[
                FailureEvidence(
                    failure_id="simulation:missing",
                    domain=GateDomain.SIMULATION,
                    rule_id="missing-evidence",
                    severity=FailureSeverity.ERROR,
                    verdict=GateVerdict.HUMAN_REVIEW_REQUIRED,
                    repairability=Repairability.NON_REPAIRABLE,
                    message="simulation evidence is missing",
                    requires_human_review=True,
                )
            ],
            summary="simulation missing",
        )

    outcome = run_verify_repair(
        _design(),
        policy=VerifyRepairPolicy(
            policy_version="mixed-repair-handoff",
            max_iterations=2,
            enabled_domains=[GateDomain.ERC, GateDomain.SIMULATION],
        ),
        gate_adapters={GateDomain.ERC: _footprint_gate, GateDomain.SIMULATION: nonrepairable_gate},
        repair_adapters=[_footprint_repair],
    )

    assert outcome.design.components["R1"].footprint == "0402"
    assert len(outcome.report.repairs) == 1
    assert outcome.report.repairs[0].improved is True
    assert outcome.report.stop_reason == VerifyRepairStopReason.NON_REPAIRABLE
    assert outcome.report.human_review_reasons == ["simulation evidence is missing"]


def test_orchestrator_rejects_output_directory_outside_trusted_root(tmp_path: Path) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    outside = tmp_path / "outside"

    design = _design(footprint="0402")
    policy = VerifyRepairPolicy(
        policy_version="safe-output",
        max_iterations=1,
        enabled_domains=[GateDomain.ERC],
    )
    gate_adapters = {GateDomain.ERC: _footprint_gate}

    with pytest.raises(ValueError, match="escapes trusted root"):
        run_verify_repair(
            design,
            policy=policy,
            gate_adapters=gate_adapters,
            repair_adapters=[],
            output_dir=outside,
            trusted_output_root=trusted_root,
        )


def test_report_writer_rejects_path_outside_trusted_root(tmp_path: Path) -> None:
    outcome = run_verify_repair(
        _design(footprint="0402"),
        policy=VerifyRepairPolicy(
            policy_version="safe-report",
            max_iterations=1,
            enabled_domains=[GateDomain.ERC],
        ),
        gate_adapters={GateDomain.ERC: _footprint_gate},
        repair_adapters=[],
    )
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()

    with pytest.raises(ValueError, match="escapes trusted root"):
        write_release_verify_repair_report(
            outcome.report,
            tmp_path / "outside.json",
            trusted_root=trusted_root,
        )


def test_verify_repair_proof_types_are_public_api() -> None:
    from zaptrace.proof import VerifyRepairProofEvidence, attach_verify_repair_evidence

    assert VerifyRepairProofEvidence.__name__ == "VerifyRepairProofEvidence"
    assert callable(attach_verify_repair_evidence)


def test_repair_adapter_exception_is_atomic_and_has_deterministic_stop_reason() -> None:
    original = _design()
    original_hash = design_state_hash(original)

    def exploding_repair(design: Design, _failures, _context) -> RepairApplication:
        design.components["R1"].footprint = "BROKEN"
        raise RuntimeError("repair engine failed")

    outcome = run_verify_repair(
        original,
        policy=VerifyRepairPolicy(
            policy_version="repair-error",
            max_iterations=2,
            enabled_domains=[GateDomain.ERC],
        ),
        gate_adapters={GateDomain.ERC: _footprint_gate},
        repair_adapters=[exploding_repair],
    )

    assert outcome.report.stop_reason == VerifyRepairStopReason.REPAIR_EXECUTION_ERROR
    assert outcome.report.iterations_used == 1
    assert outcome.report.blocks_autonomous_release is True
    assert outcome.report.human_review_required is True
    assert outcome.design.components["R1"].footprint == ""
    assert design_state_hash(outcome.design) == original_hash
    assert design_state_hash(original) == original_hash
    assert outcome.report.repairs == []
    assert outcome.report.gate_history[-1].phase == "post-repair"
    assert any("repair engine failed" in reason for reason in outcome.report.human_review_reasons)
