"""Human review workflow — checklist, approve/reject, waiver, rollback.

Review Studio uses a checklist-based approval workflow where each review
item must be explicitly acknowledged before approve, reject, request-repair,
or accept-risk can be recorded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from secrets import token_urlsafe

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.review.storage import (
    hydrate_review_session,
    persist_review_session,
)
from zaptrace.review.storage import (
    review_sessions_for_design_session as load_review_sessions_for_design_session,
)


class ChecklistStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WAIVED = "waived"


class DecisionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_REPAIR = "request-repair"
    ACCEPT_RISK = "accept-risk"
    ROLLBACK = "rollback"


class ReviewStatus(StrEnum):
    PENDING = "human-review-required"
    HUMAN_APPROVED = "human-approved"
    REJECTED = "rejected"
    REPAIR_REQUESTED = "repair-requested"
    RISK_ACCEPTED = "risk-accepted"
    ROLLED_BACK = "rolled-back"


class ReviewTransitionError(ValueError):
    """Raised when a review mutation violates the decision state machine."""


class HumanChecklistItem(BaseModel):
    """One review checklist item — a gate that a human must explicitly address."""

    model_config = ConfigDict(strict=False)

    item_id: str
    panel_id: str
    label: str
    description: str = ""
    status: ChecklistStatus = ChecklistStatus.PENDING
    decided_by: str = ""
    decided_at: str = ""
    reason: str = ""
    waiver_notes: str = ""
    is_blocking: bool = True


class ReviewDecision(BaseModel):
    """Record of a human review decision on an entire design review."""

    model_config = ConfigDict(strict=False)

    decision_id: str
    review_session_id: str
    design_name: str
    design_state_hash: str
    transaction_id: str = ""
    decision: DecisionType
    decided_by: str
    decided_at: str = ""
    reason: str = ""
    waiver_notes: str = ""
    checklist_results: dict[str, ChecklistStatus] = Field(default_factory=dict)
    approval_id: str = ""


class ReviewSession(BaseModel):
    """A mutable review session in progress — tracks checklist and decisions."""

    model_config = ConfigDict(strict=False)

    session_id: str
    design_name: str
    design_state_hash: str = ""
    design_session_id: str = ""
    owner_principal: str = ""
    checklist: dict[str, HumanChecklistItem] = Field(default_factory=dict)
    decisions: list[ReviewDecision] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    finalized_at: str = ""

    @property
    def all_approved(self) -> bool:
        """True when all blocking checklist items are approved or waived."""
        return all(
            item.status in (ChecklistStatus.APPROVED, ChecklistStatus.WAIVED)
            for item in self.checklist.values()
            if item.is_blocking
        )

    @property
    def any_rejected(self) -> bool:
        """True when any checklist item is rejected."""
        return any(item.status == ChecklistStatus.REJECTED for item in self.checklist.values())

    @property
    def latest_decision(self) -> ReviewDecision | None:
        """Return the immutable terminal decision, when present."""
        return self.decisions[-1] if self.decisions else None

    @property
    def finalized(self) -> bool:
        """True once a terminal decision has been recorded."""
        return bool(self.finalized_at or self.decisions)

    @property
    def status(self) -> ReviewStatus:
        """Expose human review status separately from autonomous sign-off."""
        latest = self.latest_decision
        if latest is None:
            return ReviewStatus.PENDING
        return {
            DecisionType.APPROVE: ReviewStatus.HUMAN_APPROVED,
            DecisionType.REJECT: ReviewStatus.REJECTED,
            DecisionType.REQUEST_REPAIR: ReviewStatus.REPAIR_REQUESTED,
            DecisionType.ACCEPT_RISK: ReviewStatus.RISK_ACCEPTED,
            DecisionType.ROLLBACK: ReviewStatus.ROLLED_BACK,
        }[latest.decision]


# ---------------------------------------------------------------------------
# In-memory store (session-local, ephemeral)
# ---------------------------------------------------------------------------

_REVIEW_SESSIONS: dict[str, ReviewSession] = {}


def _utc_now_str() -> str:
    return datetime.now(UTC).isoformat()


def _generate_id(prefix: str = "rev") -> str:
    return f"{prefix}-{token_urlsafe(24)}"


def _ensure_mutable(session: ReviewSession) -> None:
    if session.finalized:
        raise ReviewTransitionError("review session is finalized and cannot be mutated")


def _require_identity_and_reason(*, decided_by: str, reason: str) -> tuple[str, str]:
    actor = decided_by.strip()
    rationale = reason.strip()
    if not actor:
        raise ReviewTransitionError("authenticated reviewer identity is required")
    if not rationale:
        raise ReviewTransitionError("review decision rationale is required")
    return actor, rationale


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_review_session(
    design_name: str,
    design_state_hash: str = "",
    *,
    panel_ids: list[str] | None = None,
    design_session_id: str = "",
    owner_principal: str = "",
) -> ReviewSession:
    """Create a new review session with a default checklist.

    Args:
        design_name: Name of the design under review.
        design_state_hash: Deterministic design state hash for provenance.
        panel_ids: Panel IDs to create checklist items for; ``None`` builds for all.
        design_session_id: Parent design-session object identifier.
        owner_principal: Principal that owns the review object.

    Returns:
        A new :class:`ReviewSession` with checklist items for each panel.
    """
    session_id = _generate_id("session")
    now = _utc_now_str()
    checklist: dict[str, HumanChecklistItem] = {}
    ids = panel_ids or [
        "requirements",
        "assumptions",
        "erc",
        "drc",
        "dfm",
        "bom",
        "supply",
        "manufacturing",
        "simulation",
        "proof_pack",
        "benchmark",
        "decision_log",
    ]
    for pid in ids:
        item_id = f"{pid}-review"
        checklist[item_id] = HumanChecklistItem(
            item_id=item_id,
            panel_id=pid,
            label=f"Review {pid.replace('_', ' ').title()}",
            description=f"Human must inspect {pid} panel evidence and confirm acceptability.",
            is_blocking=(pid not in ("decision_log", "simulation")),
        )
    session = ReviewSession(
        session_id=session_id,
        design_name=design_name,
        design_state_hash=design_state_hash,
        design_session_id=design_session_id,
        owner_principal=owner_principal,
        checklist=checklist,
        created_at=now,
        updated_at=now,
    )
    _REVIEW_SESSIONS[session_id] = session
    persist_review_session(session)
    return session


def get_review_session(session_id: str, *, design_session_id: str = "") -> ReviewSession | None:
    """Look up a review session, hydrating its durable parent-scoped record on cache miss."""
    cached = _REVIEW_SESSIONS.get(session_id)
    if cached is not None:
        return cached
    return hydrate_review_session(session_id, design_session_id, _REVIEW_SESSIONS)


def remove_review_sessions_for_design_session(design_session_id: str) -> list[str]:
    """Remove cached review objects and report durable children before parent deletion."""
    sessions = load_review_sessions_for_design_session(design_session_id, _REVIEW_SESSIONS)
    removed = sorted(session.session_id for session in sessions)
    for session_id in removed:
        _REVIEW_SESSIONS.pop(session_id, None)
    return removed


def approve_checklist_item(
    session: ReviewSession,
    item_id: str,
    *,
    decided_by: str = "",
    reason: str = "",
) -> HumanChecklistItem:
    """Mark a checklist item as approved.

    Raises:
        KeyError: if *item_id* is not in the checklist.
    """
    _ensure_mutable(session)
    item = session.checklist.get(item_id)
    if item is None:
        raise KeyError(f"Checklist item not found: {item_id}")
    item.status = ChecklistStatus.APPROVED
    item.decided_by = decided_by
    item.decided_at = _utc_now_str()
    item.reason = reason
    session.updated_at = _utc_now_str()
    persist_review_session(session)
    return item


def reject_checklist_item(
    session: ReviewSession,
    item_id: str,
    *,
    decided_by: str = "",
    reason: str = "",
) -> HumanChecklistItem:
    """Mark a checklist item as rejected.

    Raises:
        KeyError: if *item_id* is not in the checklist.
    """
    _ensure_mutable(session)
    item = session.checklist.get(item_id)
    if item is None:
        raise KeyError(f"Checklist item not found: {item_id}")
    item.status = ChecklistStatus.REJECTED
    item.decided_by = decided_by
    item.decided_at = _utc_now_str()
    item.reason = reason
    session.updated_at = _utc_now_str()
    persist_review_session(session)
    return item


def add_waiver(
    session: ReviewSession,
    item_id: str,
    *,
    decided_by: str = "",
    reason: str = "",
    waiver_notes: str = "",
) -> HumanChecklistItem:
    """Waive a checklist item (non-blocking override).

    Raises:
        KeyError: if *item_id* is not in the checklist.
    """
    _ensure_mutable(session)
    item = session.checklist.get(item_id)
    if item is None:
        raise KeyError(f"Checklist item not found: {item_id}")
    item.status = ChecklistStatus.WAIVED
    item.decided_by = decided_by
    item.decided_at = _utc_now_str()
    item.reason = reason
    item.waiver_notes = waiver_notes
    session.updated_at = _utc_now_str()
    persist_review_session(session)
    return item


def resolve_decision(
    session: ReviewSession,
    decision: DecisionType,
    *,
    decided_by: str = "",
    reason: str = "",
    waiver_notes: str = "",
) -> ReviewDecision:
    """Record one immutable, state-bound terminal engineering review decision."""
    _ensure_mutable(session)
    actor, rationale = _require_identity_and_reason(decided_by=decided_by, reason=reason)

    if decision == DecisionType.APPROVE:
        if session.any_rejected or not session.all_approved:
            raise ReviewTransitionError("all blocking checklist items must be approved or waived before approval")
    elif decision == DecisionType.ACCEPT_RISK:
        if session.any_rejected or not session.all_approved:
            raise ReviewTransitionError("all blocking checklist items must be resolved before accepting risk")
        if not any(item.status == ChecklistStatus.WAIVED for item in session.checklist.values()):
            raise ReviewTransitionError("accept-risk requires at least one explicit waiver")

    decision_id = _generate_id("decision")
    now = _utc_now_str()
    approval_id = _generate_id("approval") if decision in (DecisionType.APPROVE, DecisionType.ACCEPT_RISK) else ""
    checklist_results = {item_id: item.status for item_id, item in session.checklist.items()}
    rec = ReviewDecision(
        decision_id=decision_id,
        review_session_id=session.session_id,
        design_name=session.design_name,
        design_state_hash=session.design_state_hash,
        decision=decision,
        decided_by=actor,
        decided_at=now,
        reason=rationale,
        waiver_notes=waiver_notes.strip(),
        checklist_results=checklist_results,
        approval_id=approval_id,
    )
    session.decisions.append(rec)
    session.updated_at = now
    session.finalized_at = now
    persist_review_session(session)
    return rec
