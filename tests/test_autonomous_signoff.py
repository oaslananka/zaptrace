from __future__ import annotations

from zaptrace.proof.signoff import (
    AutonomousSignoffPolicy,
    AutonomousSignoffStatus,
    SignoffCheckStatus,
    SignoffEvidence,
)


def test_status_vocabulary_matches_autonomy_contract() -> None:
    assert {status.value for status in AutonomousSignoffStatus} == {
        "autonomous-pass",
        "human-review-required",
        "blocked-insufficient-evidence",
        "unsupported-domain",
        "unsafe-to-fabricate",
    }


def test_policy_returns_autonomous_pass_when_all_required_evidence_passes() -> None:
    decision = AutonomousSignoffPolicy().evaluate(
        [
            SignoffEvidence(name="requirements-coverage", status=SignoffCheckStatus.PASS),
            SignoffEvidence(name="kicad-drc", status=SignoffCheckStatus.PASS, source="kicad"),
        ]
    )

    assert decision.status == AutonomousSignoffStatus.AUTONOMOUS_PASS
    assert decision.autonomous_pass is True
    assert decision.blocking_checks == []


def test_policy_requires_human_review_for_warning_or_review_flag() -> None:
    decision = AutonomousSignoffPolicy().evaluate(
        [
            SignoffEvidence(name="kicad-drc", status=SignoffCheckStatus.PASS, source="kicad"),
            SignoffEvidence(name="rf-layout-risk", status=SignoffCheckStatus.WARNING),
            SignoffEvidence(
                name="datasheet-low-confidence",
                status=SignoffCheckStatus.PASS,
                human_review_required=True,
            ),
        ]
    )

    assert decision.status == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert decision.human_review_checks == ["rf-layout-risk", "datasheet-low-confidence"]
    assert decision.blocks_autonomous_pass is True


def test_policy_blocks_failed_release_evidence() -> None:
    decision = AutonomousSignoffPolicy().evaluate(
        [
            SignoffEvidence(name="requirements-coverage", status=SignoffCheckStatus.PASS),
            SignoffEvidence(name="kicad-erc", status=SignoffCheckStatus.FAIL, source="kicad"),
        ]
    )

    assert decision.status == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert decision.blocking_checks == ["kicad-erc"]


def test_policy_blocks_missing_required_evidence() -> None:
    decision = AutonomousSignoffPolicy().evaluate(
        [SignoffEvidence(name="kicad-oracle", status=SignoffCheckStatus.SKIPPED, source="kicad")]
    )

    assert decision.status == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert decision.blocking_checks == ["kicad-oracle"]


def test_policy_marks_unsupported_domain_before_generic_blocking() -> None:
    decision = AutonomousSignoffPolicy().evaluate(
        [
            SignoffEvidence(name="mains-safety-domain", status=SignoffCheckStatus.FAIL, unsupported=True),
            SignoffEvidence(name="requirements-coverage", status=SignoffCheckStatus.UNKNOWN),
        ]
    )

    assert decision.status == AutonomousSignoffStatus.UNSUPPORTED_DOMAIN
    assert decision.unsupported_checks == ["mains-safety-domain"]
    assert "requirements-coverage" in decision.blocking_checks


def test_policy_marks_unsafe_to_fabricate_with_highest_precedence() -> None:
    decision = AutonomousSignoffPolicy().evaluate(
        [
            SignoffEvidence(name="battery-thermal-runaway", status=SignoffCheckStatus.FAIL, unsafe=True),
            SignoffEvidence(name="unknown-domain", status=SignoffCheckStatus.FAIL, unsupported=True),
        ]
    )

    assert decision.status == AutonomousSignoffStatus.UNSAFE_TO_FABRICATE
    assert decision.unsafe_checks == ["battery-thermal-runaway"]
    assert decision.unsupported_checks == ["unknown-domain"]


def test_empty_evidence_blocks_by_default() -> None:
    decision = AutonomousSignoffPolicy().evaluate([])

    assert decision.status == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert decision.blocking_checks == ["missing-signoff-evidence"]


def test_decision_exports_compact_evidence_record() -> None:
    decision = AutonomousSignoffPolicy().evaluate(
        [SignoffEvidence(name="kicad-drc", status=SignoffCheckStatus.FAIL, source="kicad")]
    )

    record = decision.to_evidence_record()
    assert record["status"] == "blocked-insufficient-evidence"
    assert record["blocking_checks"] == ["kicad-drc"]
    assert record["evidence_count"] == 1
