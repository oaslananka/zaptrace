"""Guardrails for public manufacturing/readiness claims."""

from __future__ import annotations

from pathlib import Path

from zaptrace.proof.claims import (
    FORBIDDEN_FABRICATION_CLAIMS,
    assert_no_unapproved_fabrication_claims,
    find_unapproved_fabrication_claims,
)
from zaptrace.proof.signoff import AutonomousSignoffStatus

_POSITIVE_CLAIMS = (
    "generates manufacturing-ready",
    "produces manufacturing-ready",
    "one command to production",
    "fabrication-ready by default",
)


def test_no_positive_manufacturing_ready_claims_remain() -> None:
    roots = [Path("README.md"), Path("zaptrace"), Path("docs"), Path("benchmarks")]
    offenders: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if path == Path("zaptrace/proof/claims.py"):
                continue
            if path.is_file() and path.suffix.lower() in {".py", ".md", ".txt"}:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
                for claim in _POSITIVE_CLAIMS:
                    if claim in text:
                        offenders.append(f"{path}: {claim}")
    assert offenders == []


def test_forbidden_claims_are_centrally_defined() -> None:
    assert "one command to production" in FORBIDDEN_FABRICATION_CLAIMS
    assert "ready for fabrication" in FORBIDDEN_FABRICATION_CLAIMS
    assert "manufacturer-approved" in FORBIDDEN_FABRICATION_CLAIMS


def test_generated_text_claim_is_rejected_without_release_policy() -> None:
    violations = find_unapproved_fabrication_claims(
        "This proof pack is ready for fabrication.",
        signoff_status=AutonomousSignoffStatus.AUTONOMOUS_PASS,
    )

    assert [v.claim for v in violations] == ["ready for fabrication"]


def test_generated_text_claim_requires_autonomous_pass_and_release_permission() -> None:
    assert_no_unapproved_fabrication_claims(
        "This bundle is ready for manufacturing.",
        signoff_status=AutonomousSignoffStatus.AUTONOMOUS_PASS,
        release_policy_allows_fabrication_claims=True,
    )


def test_generated_text_claim_still_fails_when_status_is_not_autonomous_pass() -> None:
    try:
        assert_no_unapproved_fabrication_claims(
            "This bundle is ready for manufacturing.",
            signoff_status=AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED,
            release_policy_allows_fabrication_claims=True,
        )
    except ValueError as exc:
        assert "ready for manufacturing" in str(exc)
    else:  # pragma: no cover - defensive clarity
        raise AssertionError("expected fabrication claim guard to reject non-autonomous-pass status")
