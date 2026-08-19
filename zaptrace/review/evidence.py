"""Normalize state-bound Review Studio decisions for proof and release evidence."""

from __future__ import annotations

from zaptrace.review.storage import review_sessions_for_design_session
from zaptrace.review.workflow import (
    _REVIEW_SESSIONS,
    DecisionType,
    ReviewDecision,
    ReviewSession,
    ReviewStatus,
)


def _decision_evidence(
    session: ReviewSession,
    decision: ReviewDecision,
    *,
    status: str,
    current: bool,
    approval_id_matched: bool,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": status,
        "review_session_id": session.session_id,
        "decision_id": decision.decision_id,
        "decision": decision.decision.value,
        "reviewer_id": decision.decided_by,
        "decided_at": decision.decided_at,
        "reason": decision.reason,
        "waiver_notes": decision.waiver_notes,
        "design_state_hash": decision.design_state_hash,
        "approval_id": decision.approval_id,
        "current": current,
        "approval_id_matched": approval_id_matched,
        "checklist_results": {key: value.value for key, value in decision.checklist_results.items()},
    }


def _default_evidence(design_state_hash: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": ReviewStatus.PENDING.value,
        "review_session_id": "",
        "decision_id": "",
        "decision": "",
        "reviewer_id": "",
        "decided_at": "",
        "reason": "No current matching engineering review approval was supplied.",
        "waiver_notes": "",
        "design_state_hash": design_state_hash,
        "approval_id": "",
        "current": False,
        "approval_id_matched": False,
        "checklist_results": {},
    }


def _terminal_sessions(design_session_id: str, design_name: str) -> list[ReviewSession]:
    sessions = [
        session
        for session in review_sessions_for_design_session(design_session_id, _REVIEW_SESSIONS)
        if session.design_name == design_name and session.latest_decision is not None
    ]
    sessions.sort(key=lambda item: item.latest_decision.decided_at if item.latest_decision else "", reverse=True)
    return sessions


def resolve_engineering_review_evidence(
    design_session_id: str,
    design_name: str,
    design_state_hash: str,
    approval_id: str,
) -> dict[str, object]:
    """Resolve current human review evidence without conflating external approvals."""
    sessions = _terminal_sessions(design_session_id, design_name)
    current_sessions = [
        session
        for session in sessions
        if session.latest_decision is not None and session.latest_decision.design_state_hash == design_state_hash
    ]

    if current_sessions:
        session = current_sessions[0]
        decision = session.latest_decision
        assert decision is not None
        blocking_status = {
            DecisionType.REJECT: ReviewStatus.REJECTED.value,
            DecisionType.REQUEST_REPAIR: ReviewStatus.REPAIR_REQUESTED.value,
            DecisionType.ROLLBACK: ReviewStatus.ROLLED_BACK.value,
        }.get(decision.decision)
        if blocking_status is not None:
            return _decision_evidence(
                session,
                decision,
                status=blocking_status,
                current=True,
                approval_id_matched=False,
            )

    normalized_approval = approval_id.strip()
    matching_sessions = [
        session
        for session in sessions
        if session.latest_decision is not None
        and session.latest_decision.approval_id
        and session.latest_decision.approval_id == normalized_approval
    ]
    if matching_sessions:
        session = matching_sessions[0]
        decision = session.latest_decision
        assert decision is not None
        current = decision.design_state_hash == design_state_hash
        status = _matched_review_status(decision, current=current)
        return _decision_evidence(
            session,
            decision,
            status=status,
            current=current,
            approval_id_matched=True,
        )

    if current_sessions:
        session = current_sessions[0]
        decision = session.latest_decision
        assert decision is not None
        return _decision_evidence(
            session,
            decision,
            status=ReviewStatus.PENDING.value,
            current=True,
            approval_id_matched=False,
        )
    return _default_evidence(design_state_hash)


def _matched_review_status(decision: ReviewDecision, *, current: bool) -> str:
    if not current:
        return "stale-review"
    if decision.decision == DecisionType.APPROVE:
        return ReviewStatus.HUMAN_APPROVED.value
    return ReviewStatus.RISK_ACCEPTED.value
