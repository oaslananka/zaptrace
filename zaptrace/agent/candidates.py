"""Autonomous specialist-agent candidate contracts and deterministic scoring."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentRole(StrEnum):
    """Specialist autonomous agent roles."""

    ARCHITECT = "architect"
    SCHEMATIC = "schematic"
    CONSTRAINT = "constraint"
    LAYOUT = "layout"
    VERIFICATION = "verification"
    SUPPLY_CHAIN = "supply_chain"
    RELEASE = "release"


class CandidateStatus(StrEnum):
    """Candidate lifecycle states."""

    SANDBOX = "sandbox"
    REJECTED = "rejected"
    SELECTED = "selected"
    RELEASE_READY = "release_ready"


class ValidationStatus(StrEnum):
    """Verification status used by candidate gates."""

    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"


class AgentContract(BaseModel):
    """Role contract for specialist agents."""

    model_config = ConfigDict(strict=False)

    role: AgentRole
    permission_level: str
    inputs: list[str]
    outputs: list[str]
    writes: str
    required_evidence: list[str]


class ScoreDimension(BaseModel):
    """One explainable score dimension."""

    model_config = ConfigDict(strict=False)

    name: str
    score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)
    explanation: str


class CandidateScore(BaseModel):
    """Machine-readable candidate scorecard."""

    model_config = ConfigDict(strict=False)

    total: float = Field(ge=0.0, le=1.0)
    dimensions: list[ScoreDimension]
    explanation: str


class CandidateLineage(BaseModel):
    """Sandbox lineage for a generated candidate."""

    model_config = ConfigDict(strict=False)

    parent_design: str
    transaction_id: str
    diff_summary: str
    generated_by: list[AgentRole]
    rollback_id: str
    sandbox_first: bool = True


class DesignCandidate(BaseModel):
    """Autonomous design candidate generated without primary commit."""

    model_config = ConfigDict(strict=False)

    candidate_id: str
    title: str
    status: CandidateStatus = CandidateStatus.SANDBOX
    lineage: CandidateLineage
    score: CandidateScore
    validation_status: ValidationStatus = ValidationStatus.NOT_RUN
    rejected_reasons: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    human_approval_id: str = ""


class CandidateDecisionLog(BaseModel):
    """Proof-pack friendly candidate decision log."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    requirement_id: str
    selected_candidate_id: str = ""
    candidates: list[DesignCandidate]
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "sandbox candidates are not committed design state",
            "release export still requires validation and approval gates",
            "human review remains required before fabrication",
        ]
    )

    def proof_evidence(self) -> dict[str, Any]:
        """Return a compact proof-pack evidence payload."""
        return {
            "schema_version": self.schema_version,
            "requirement_id": self.requirement_id,
            "selected_candidate_id": self.selected_candidate_id,
            "candidate_lineage": [candidate.lineage.model_dump(mode="json") for candidate in self.candidates],
            "scores": {
                candidate.candidate_id: candidate.score.model_dump(mode="json") for candidate in self.candidates
            },
            "rejected": {
                candidate.candidate_id: candidate.rejected_reasons
                for candidate in self.candidates
                if candidate.rejected_reasons
            },
            "non_claims": self.non_claims,
        }


def specialist_agent_contracts() -> list[AgentContract]:
    """Return the stable specialist agent contracts."""
    return [
        AgentContract(
            role=AgentRole.ARCHITECT,
            permission_level="preview-write",
            inputs=["requirements", "canonical_ir"],
            outputs=["structured_intent", "block_architecture"],
            writes="sandbox-only planning artifacts",
            required_evidence=["requirements_trace"],
        ),
        AgentContract(
            role=AgentRole.SCHEMATIC,
            permission_level="sandbox-write",
            inputs=["block_architecture", "library_parts"],
            outputs=["schematic_graph", "known_good_subcircuits"],
            writes="transactional schematic candidate",
            required_evidence=["schematic_diff"],
        ),
        AgentContract(
            role=AgentRole.CONSTRAINT,
            permission_level="sandbox-write",
            inputs=["requirements", "fab_profile", "bom_policy"],
            outputs=["electrical_constraints", "manufacturing_constraints", "supply_constraints"],
            writes="transactional constraint candidate",
            required_evidence=["constraint_trace"],
        ),
        AgentContract(
            role=AgentRole.LAYOUT,
            permission_level="sandbox-write",
            inputs=["schematic_graph", "constraints"],
            outputs=["placement", "routing", "layout_metrics"],
            writes="transactional layout candidate",
            required_evidence=["layout_diff", "rollback_id"],
        ),
        AgentContract(
            role=AgentRole.VERIFICATION,
            permission_level="sandbox-write",
            inputs=["candidate", "proof_pack", "oracle_results"],
            outputs=["validation_status", "gate_failures", "proof_evidence"],
            writes="validation evidence only",
            required_evidence=["erc", "drc", "dfm", "bom", "proof_pack"],
        ),
        AgentContract(
            role=AgentRole.SUPPLY_CHAIN,
            permission_level="sandbox-write",
            inputs=["bom", "provider_results"],
            outputs=["bom_risk", "substitutions", "provider_provenance"],
            writes="BOM risk evidence only",
            required_evidence=["provider_provenance"],
        ),
        AgentContract(
            role=AgentRole.RELEASE,
            permission_level="release-export",
            inputs=["selected_candidate", "validation_status", "approval_id"],
            outputs=["release_gate_result", "manufacturing_package"],
            writes="release export only after approval",
            required_evidence=["approval_id", "fresh_validation"],
        ),
    ]


def generate_candidate_set(requirement_id: str, parent_design: str, *, count: int = 3) -> CandidateDecisionLog:
    """Generate deterministic sandbox candidates without mutating primary design state."""
    if count < 1:
        raise ValueError("candidate count must be at least 1")
    candidates = []
    for index in range(count):
        candidate_no = index + 1
        candidate_id = f"cand-{candidate_no:02d}"
        dimensions = _score_dimensions(candidate_no)
        total = round(sum(item.score * item.weight for item in dimensions) / sum(item.weight for item in dimensions), 4)
        candidates.append(
            DesignCandidate(
                candidate_id=candidate_id,
                title=f"Candidate {candidate_no}",
                lineage=CandidateLineage(
                    parent_design=parent_design,
                    transaction_id=f"tx-{requirement_id}-{candidate_id}",
                    diff_summary=f"sandbox candidate {candidate_no}: placement/routing alternative",
                    generated_by=[
                        AgentRole.ARCHITECT,
                        AgentRole.SCHEMATIC,
                        AgentRole.CONSTRAINT,
                        AgentRole.LAYOUT,
                    ],
                    rollback_id=f"rb-{requirement_id}-{candidate_id}",
                ),
                score=CandidateScore(
                    total=total,
                    dimensions=dimensions,
                    explanation=(
                        "weighted objective score across constraints, manufacturability, "
                        "BOM risk, routing, validation, and evidence"
                    ),
                ),
                evidence=[{"kind": "sandbox_transaction", "transaction_id": f"tx-{requirement_id}-{candidate_id}"}],
            )
        )
    return CandidateDecisionLog(requirement_id=requirement_id, candidates=candidates)


def mark_verification_result(
    candidate: DesignCandidate, *, passed: bool, reasons: list[str] | None = None
) -> DesignCandidate:
    """Apply Verification Agent decision before human review."""
    candidate.validation_status = ValidationStatus.PASSED if passed else ValidationStatus.FAILED
    candidate.evidence.append({"kind": "verification", "passed": passed, "reasons": reasons or []})
    if not passed:
        candidate.status = CandidateStatus.REJECTED
        candidate.rejected_reasons.extend(reasons or ["verification failed"])
    return candidate


def select_best_verified_candidate(log: CandidateDecisionLog) -> DesignCandidate | None:
    """Select the highest scoring verified candidate and record rejected reasons for the rest."""
    verified = [candidate for candidate in log.candidates if candidate.validation_status == ValidationStatus.PASSED]
    if not verified:
        return None
    selected = max(verified, key=lambda candidate: candidate.score.total)
    selected.status = CandidateStatus.SELECTED
    log.selected_candidate_id = selected.candidate_id
    for candidate in log.candidates:
        if candidate.candidate_id != selected.candidate_id and candidate.status != CandidateStatus.REJECTED:
            candidate.status = CandidateStatus.REJECTED
            candidate.rejected_reasons.append(f"lower score than selected {selected.candidate_id}")
    return selected


def release_gate(candidate: DesignCandidate, *, approval_id: str) -> dict[str, Any]:
    """Release Agent gate: validation and explicit approval are mandatory."""
    if candidate.validation_status != ValidationStatus.PASSED:
        return {
            "allowed": False,
            "code": "CANDIDATE_VALIDATION_REQUIRED",
            "message": "candidate must pass verification before release",
        }
    if not approval_id:
        return {
            "allowed": False,
            "code": "CANDIDATE_APPROVAL_REQUIRED",
            "message": "approval_id is required before release export",
        }
    candidate.human_approval_id = approval_id
    candidate.status = CandidateStatus.RELEASE_READY
    candidate.evidence.append({"kind": "release_gate", "approval_id": approval_id, "allowed": True})
    return {
        "allowed": True,
        "code": "CANDIDATE_RELEASE_READY",
        "candidate_id": candidate.candidate_id,
        "approval_id": approval_id,
    }


def _score_dimensions(candidate_no: int) -> list[ScoreDimension]:
    base = 0.62 + candidate_no * 0.04
    return [
        ScoreDimension(
            name="constraints",
            score=min(0.95, base + 0.06),
            weight=0.20,
            explanation="meets declared electrical and physical constraints",
        ),
        ScoreDimension(
            name="manufacturability",
            score=min(0.95, base + 0.03),
            weight=0.20,
            explanation="fits known DFM profile limits",
        ),
        ScoreDimension(
            name="bom_risk",
            score=max(0.35, 0.92 - candidate_no * 0.05),
            weight=0.15,
            explanation="lower risk means better supplier availability",
        ),
        ScoreDimension(
            name="routing_quality",
            score=min(0.95, base + 0.02),
            weight=0.15,
            explanation="shorter routes and fewer unrouted nets are preferred",
        ),
        ScoreDimension(
            name="validation_status", score=0.50, weight=0.15, explanation="pending verification before human review"
        ),
        ScoreDimension(
            name="evidence_completeness",
            score=0.70,
            weight=0.15,
            explanation="candidate contains transaction lineage and rollback evidence",
        ),
    ]
