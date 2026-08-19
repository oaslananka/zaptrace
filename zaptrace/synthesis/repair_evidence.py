"""Repair proposal evidence for audited auto-repair workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.synthesis.repair import Patch, RepairResult


class RepairAlternative(BaseModel):
    """One possible response to a repairable problem."""

    model_config = ConfigDict(strict=False)

    label: str
    change_summary: str
    risk: str = "medium"
    selected: bool = False


class RepairVerificationResult(BaseModel):
    """Before/after verification attached to a proposal."""

    model_config = ConfigDict(strict=False)

    violations_before: int = Field(ge=0)
    violations_after: int = Field(ge=0)
    improved: bool
    verification: str = "erc-rerun"


class RepairProposal(BaseModel):
    """Machine-readable evidence for one selected repair change."""

    model_config = ConfigDict(strict=False)

    proposal_id: str
    rule_id: str
    problem: str
    affected_refs: list[str]
    alternatives: list[RepairAlternative]
    selected_change: str
    confidence: float = Field(ge=0, le=1)
    verification: RepairVerificationResult
    human_review_required: bool = False


class RepairProposalReport(BaseModel):
    """Auditable report for repair proposals and silent-repair policy."""

    schema_version: str = "1.0"
    proposal_count: int = Field(ge=0)
    verified_count: int = Field(ge=0)
    silent_repair_count: int = Field(ge=0)
    human_review_required: bool
    blocked: bool
    proposals: list[RepairProposal]
    remaining: list[dict[str, Any]] = Field(default_factory=list)


def _problem_for_patch(patch: Patch) -> str:
    return f"{patch.rule_id} on {patch.component_ref}: {patch.rationale}"


def _proposal_id(index: int, patch: Patch) -> str:
    return f"repair-{index:03d}-{patch.rule_id}-{patch.component_ref}-{patch.field}"


def _proposal_from_patch(index: int, patch: Patch, before: int, after: int) -> RepairProposal:
    selected = f"Set {patch.component_ref}.{patch.field} from {patch.old_value!r} to {patch.new_value!r}"
    return RepairProposal(
        proposal_id=_proposal_id(index, patch),
        rule_id=patch.rule_id,
        problem=_problem_for_patch(patch),
        affected_refs=[patch.component_ref],
        alternatives=[
            RepairAlternative(
                label="leave-for-human-review",
                change_summary="Do not mutate the design; keep violation in remaining list for review.",
                risk="low",
                selected=False,
            ),
            RepairAlternative(
                label="apply-selected-patch",
                change_summary=selected,
                risk="medium" if patch.confidence < 1.0 else "low",
                selected=True,
            ),
        ],
        selected_change=selected,
        confidence=patch.confidence,
        verification=RepairVerificationResult(
            violations_before=before,
            violations_after=after,
            improved=after < before,
        ),
        human_review_required=patch.confidence < 1.0,
    )


def build_repair_proposal_report(repair: RepairResult) -> RepairProposalReport:
    """Build proposal evidence from a RepairResult.

    Any patch not attached to an iteration is considered a silent repair and
    blocks autonomous sign-off until proposal evidence is supplied.
    """
    proposals: list[RepairProposal] = []
    seen: set[int] = set()
    counter = 1
    for iteration in repair.iterations:
        for patch in iteration.patches:
            seen.add(id(patch))
            proposals.append(
                _proposal_from_patch(counter, patch, iteration.violations_before, iteration.violations_after)
            )
            counter += 1
    silent = [patch for patch in repair.patches if id(patch) not in seen]
    verified = sum(1 for proposal in proposals if proposal.verification.improved)
    human_review = bool(repair.remaining) or any(proposal.human_review_required for proposal in proposals)
    blocked = bool(silent) or any(not proposal.verification.improved for proposal in proposals)
    return RepairProposalReport(
        proposal_count=len(proposals),
        verified_count=verified,
        silent_repair_count=len(silent),
        human_review_required=human_review,
        blocked=blocked,
        proposals=proposals,
        remaining=repair.remaining,
    )


def write_repair_proposal_report(report: RepairProposalReport, output_path: str | Path) -> Path:
    out = Path(output_path)
    if out.suffix.lower() != ".json":
        raise ValueError(f"unexpected repair proposal report suffix: {out.suffix}")
    resolved = out.resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    # nosemgrep: python.lang.security.audit.path-traversal.path-traversal-write
    resolved.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return resolved
