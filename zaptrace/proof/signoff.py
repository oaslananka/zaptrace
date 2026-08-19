"""Autonomous sign-off policy primitives.

This module defines the small, explicit status vocabulary used to decide whether
ZapTrace evidence can support an autonomous pass, requires human engineering
review, is blocked by missing/failing evidence, is outside the supported domain,
or is unsafe to fabricate.

The policy is deliberately conservative: unknown, skipped, or missing required
evidence is never treated as a pass.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class AutonomousSignoffStatus(StrEnum):
    """Top-level status for a generated design or proof pack."""

    AUTONOMOUS_PASS = "autonomous-pass"
    HUMAN_REVIEW_REQUIRED = "human-review-required"
    BLOCKED_INSUFFICIENT_EVIDENCE = "blocked-insufficient-evidence"
    UNSUPPORTED_DOMAIN = "unsupported-domain"
    UNSAFE_TO_FABRICATE = "unsafe-to-fabricate"


class SignoffCheckStatus(StrEnum):
    """Normalized status of one evidence item consumed by sign-off policy."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"


class SignoffEvidence(BaseModel):
    """One machine-checkable item used by autonomous sign-off policy."""

    name: str = Field(description="Stable evidence/check name")
    status: SignoffCheckStatus = Field(description="Normalized evidence status")
    source: str = Field(default="zaptrace", description="Evidence producer: zaptrace, kicad, fab_profile, external")
    summary: str = Field(default="", description="Human-readable explanation")
    release_blocking: bool = Field(default=True, description="Whether this evidence can block autonomous-pass")
    evidence_required: bool = Field(
        default=True, description="Whether missing/skipped/unknown evidence blocks sign-off"
    )
    human_review_required: bool = Field(default=False, description="Whether this evidence requires human review")
    unsupported: bool = Field(
        default=False, description="Whether this evidence marks the design outside supported domain"
    )
    unsafe: bool = Field(default=False, description="Whether this evidence marks a safety/fabrication hazard")
    approval_id: str = Field(default="", description="Human approval or waiver identifier, if any")

    @property
    def is_missing_required_evidence(self) -> bool:
        """True when required evidence is absent or inconclusive."""
        return self.evidence_required and self.status in {SignoffCheckStatus.SKIPPED, SignoffCheckStatus.UNKNOWN}

    @property
    def is_release_blocking_failure(self) -> bool:
        """True when this item blocks release/autonomous-pass by failing."""
        return self.release_blocking and self.status == SignoffCheckStatus.FAIL

    @property
    def requires_human_review(self) -> bool:
        """True when this item is not blocking but still needs engineering review."""
        return self.human_review_required or self.status == SignoffCheckStatus.WARNING


class AutonomousSignoffDecision(BaseModel):
    """Result of applying an autonomous sign-off policy."""

    status: AutonomousSignoffStatus = Field(description="Top-level sign-off status")
    summary: str = Field(description="One-line explanation of the decision")
    evidence: list[SignoffEvidence] = Field(default_factory=list, description="Input evidence used for the decision")
    blocking_checks: list[str] = Field(
        default_factory=list, description="Checks that blocked due to failure/missing evidence"
    )
    human_review_checks: list[str] = Field(
        default_factory=list, description="Checks that require human engineering review"
    )
    unsupported_checks: list[str] = Field(default_factory=list, description="Checks that mark the design unsupported")
    unsafe_checks: list[str] = Field(default_factory=list, description="Checks that mark the design unsafe")

    @property
    def autonomous_pass(self) -> bool:
        return self.status == AutonomousSignoffStatus.AUTONOMOUS_PASS

    @property
    def blocks_autonomous_pass(self) -> bool:
        return self.status != AutonomousSignoffStatus.AUTONOMOUS_PASS

    def to_evidence_record(self) -> dict[str, object]:
        """Return a compact JSON-serializable proof-pack record."""
        return {
            "status": self.status.value,
            "summary": self.summary,
            "blocking_checks": self.blocking_checks,
            "human_review_checks": self.human_review_checks,
            "unsupported_checks": self.unsupported_checks,
            "unsafe_checks": self.unsafe_checks,
            "evidence_count": len(self.evidence),
        }


class AutonomousSignoffPolicy(BaseModel):
    """Conservative policy for classifying generated design evidence."""

    require_at_least_one_evidence_item: bool = Field(
        default=True,
        description="If true, empty evidence produces blocked-insufficient-evidence",
    )

    def evaluate(self, evidence: list[SignoffEvidence]) -> AutonomousSignoffDecision:
        """Evaluate evidence and return the most conservative sign-off status.

        Precedence is intentionally strict:
        unsafe > unsupported > blocking/missing evidence > human review > pass.
        """
        if self.require_at_least_one_evidence_item and not evidence:
            return AutonomousSignoffDecision(
                status=AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE,
                summary="No sign-off evidence was provided.",
                evidence=[],
                blocking_checks=["missing-signoff-evidence"],
            )

        unsafe = [item.name for item in evidence if item.unsafe]
        unsupported = [item.name for item in evidence if item.unsupported]
        blocking = [
            item.name for item in evidence if item.is_release_blocking_failure or item.is_missing_required_evidence
        ]
        human_review = [
            item.name
            for item in evidence
            if item.requires_human_review
            and item.name not in blocking
            and item.name not in unsafe
            and item.name not in unsupported
        ]

        if unsafe:
            return AutonomousSignoffDecision(
                status=AutonomousSignoffStatus.UNSAFE_TO_FABRICATE,
                summary=f"Unsafe-to-fabricate evidence present: {', '.join(unsafe)}.",
                evidence=evidence,
                unsafe_checks=unsafe,
                unsupported_checks=unsupported,
                blocking_checks=blocking,
                human_review_checks=human_review,
            )
        if unsupported:
            return AutonomousSignoffDecision(
                status=AutonomousSignoffStatus.UNSUPPORTED_DOMAIN,
                summary=f"Design is outside the supported autonomous domain: {', '.join(unsupported)}.",
                evidence=evidence,
                unsupported_checks=unsupported,
                blocking_checks=blocking,
                human_review_checks=human_review,
            )
        if blocking:
            return AutonomousSignoffDecision(
                status=AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE,
                summary=f"Required sign-off evidence failed or is missing: {', '.join(blocking)}.",
                evidence=evidence,
                blocking_checks=blocking,
                human_review_checks=human_review,
            )
        if human_review:
            return AutonomousSignoffDecision(
                status=AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED,
                summary=f"Human engineering review is required for: {', '.join(human_review)}.",
                evidence=evidence,
                human_review_checks=human_review,
            )

        return AutonomousSignoffDecision(
            status=AutonomousSignoffStatus.AUTONOMOUS_PASS,
            summary="All required sign-off evidence passed for the supported autonomous domain.",
            evidence=evidence,
        )
