from __future__ import annotations

from zaptrace.agent.candidates import (
    AgentRole,
    CandidateStatus,
    ValidationStatus,
    generate_candidate_set,
    mark_verification_result,
    release_gate,
    select_best_verified_candidate,
    specialist_agent_contracts,
)


def test_specialist_agent_contracts_cover_required_roles_and_permissions() -> None:
    contracts = specialist_agent_contracts()
    roles = {contract.role for contract in contracts}

    assert roles == {
        AgentRole.ARCHITECT,
        AgentRole.SCHEMATIC,
        AgentRole.CONSTRAINT,
        AgentRole.LAYOUT,
        AgentRole.VERIFICATION,
        AgentRole.SUPPLY_CHAIN,
        AgentRole.RELEASE,
    }
    assert next(item for item in contracts if item.role == AgentRole.RELEASE).permission_level == "release-export"
    assert next(item for item in contracts if item.role == AgentRole.LAYOUT).writes == "transactional layout candidate"


def test_candidate_generation_produces_multiple_sandbox_alternatives() -> None:
    log = generate_candidate_set("req-esp32", "BaseDesign", count=3)

    assert len(log.candidates) == 3
    assert {candidate.status for candidate in log.candidates} == {CandidateStatus.SANDBOX}
    assert all(candidate.lineage.sandbox_first for candidate in log.candidates)
    assert all(candidate.lineage.rollback_id for candidate in log.candidates)
    assert all(candidate.lineage.transaction_id.startswith("tx-req-esp32") for candidate in log.candidates)


def test_candidate_scores_are_machine_readable_and_explainable() -> None:
    candidate = generate_candidate_set("req-score", "BaseDesign", count=1).candidates[0]

    assert 0.0 <= candidate.score.total <= 1.0
    dimensions = {item.name: item for item in candidate.score.dimensions}
    assert {
        "constraints",
        "manufacturability",
        "bom_risk",
        "routing_quality",
        "validation_status",
        "evidence_completeness",
    }.issubset(dimensions)
    assert all(item.explanation for item in dimensions.values())


def test_verification_agent_rejects_failed_candidate_before_human_review() -> None:
    candidate = generate_candidate_set("req-verify", "BaseDesign", count=1).candidates[0]

    mark_verification_result(candidate, passed=False, reasons=["DRC clearance violation"])

    assert candidate.validation_status == ValidationStatus.FAILED
    assert candidate.status == CandidateStatus.REJECTED
    assert candidate.rejected_reasons == ["DRC clearance violation"]


def test_release_gate_requires_validation_and_approval() -> None:
    candidate = generate_candidate_set("req-release", "BaseDesign", count=1).candidates[0]

    assert release_gate(candidate, approval_id="")["code"] == "CANDIDATE_VALIDATION_REQUIRED"
    mark_verification_result(candidate, passed=True)
    assert release_gate(candidate, approval_id="")["code"] == "CANDIDATE_APPROVAL_REQUIRED"

    allowed = release_gate(candidate, approval_id="approval-123")

    assert allowed["allowed"] is True
    assert candidate.status == CandidateStatus.RELEASE_READY
    assert candidate.human_approval_id == "approval-123"


def test_proof_evidence_contains_lineage_selection_and_rejected_reasons() -> None:
    log = generate_candidate_set("req-proof", "BaseDesign", count=2)
    mark_verification_result(log.candidates[0], passed=False, reasons=["ERC failed"])
    mark_verification_result(log.candidates[1], passed=True)

    selected = select_best_verified_candidate(log)
    evidence = log.proof_evidence()

    assert selected is not None
    assert evidence["selected_candidate_id"] == selected.candidate_id
    assert evidence["candidate_lineage"][0]["rollback_id"]
    assert evidence["scores"][selected.candidate_id]["total"] == selected.score.total
    assert evidence["rejected"][log.candidates[0].candidate_id] == ["ERC failed"]
