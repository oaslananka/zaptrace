"""Guardrails for fabrication and production-readiness claims.

ZapTrace proof and export artifacts may contain evidence, but evidence is not a
fabrication guarantee. Public/generated text must not claim manufacturing,
production, or no-review readiness unless an explicit release policy permits it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .signoff import AutonomousSignoffStatus

FORBIDDEN_FABRICATION_CLAIMS: tuple[str, ...] = (
    "generates manufacturing-ready",
    "produces manufacturing-ready",
    "manufacturing-ready output",
    "fabrication-ready output",
    "fabrication-ready by default",
    "production-ready output",
    "one command to production",
    "ready for fabrication",
    "ready to fabricate",
    "ready for manufacturing",
    "manufacturer-approved",
    "no-human-review",
    "no human review required",
)


class FabricationClaimViolation(BaseModel):
    """One unapproved fabrication/readiness claim found in generated text."""

    claim: str = Field(description="Matched forbidden claim phrase")
    context: str = Field(description="Small surrounding snippet for diagnostics")


def _context(text: str, start: int, end: int, *, radius: int = 48) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return " ".join(text[left:right].split())


def find_unapproved_fabrication_claims(
    text: str,
    *,
    signoff_status: AutonomousSignoffStatus | str = AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED,
    release_policy_allows_fabrication_claims: bool = False,
) -> list[FabricationClaimViolation]:
    """Return forbidden claims unless release policy explicitly allows them.

    Even an ``autonomous-pass`` design is not allowed to use fabrication-ready or
    production-ready language by default. A caller must pass both an
    autonomous-pass status and an explicit release-policy permission.
    """
    status = AutonomousSignoffStatus(signoff_status)
    if release_policy_allows_fabrication_claims and status == AutonomousSignoffStatus.AUTONOMOUS_PASS:
        return []

    haystack = text.lower()
    violations: list[FabricationClaimViolation] = []
    for claim in FORBIDDEN_FABRICATION_CLAIMS:
        start = haystack.find(claim)
        if start >= 0:
            violations.append(
                FabricationClaimViolation(
                    claim=claim,
                    context=_context(text, start, start + len(claim)),
                )
            )
    return violations


def assert_no_unapproved_fabrication_claims(
    text: str,
    *,
    signoff_status: AutonomousSignoffStatus | str = AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED,
    release_policy_allows_fabrication_claims: bool = False,
) -> None:
    """Raise ValueError if generated text makes an unapproved readiness claim."""
    violations = find_unapproved_fabrication_claims(
        text,
        signoff_status=signoff_status,
        release_policy_allows_fabrication_claims=release_policy_allows_fabrication_claims,
    )
    if violations:
        claims = ", ".join(v.claim for v in violations)
        raise ValueError(f"Unapproved fabrication/manufacturing readiness claim(s): {claims}")
