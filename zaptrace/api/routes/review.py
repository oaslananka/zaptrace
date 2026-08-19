"""Review Studio REST API routes.

Provides endpoints for:
- Review bundle (aggregated panels)
- Individual review panels
- Review session management (checklist, approve/reject/waive)
- Candidate comparison
- Static review bundle generation
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from zaptrace.agent._tool_impls import _get_session
from zaptrace.api.routes._session import (
    authorize_object_or_403,
    authorize_tool,
    current_request_principal,
    resolve_session_id,
)
from zaptrace.core.diff import diff_designs
from zaptrace.review.panels import collect_panels, collect_review_bundle
from zaptrace.review.workflow import (
    DecisionType,
    ReviewSession,
    ReviewTransitionError,
    add_waiver,
    approve_checklist_item,
    create_review_session,
    get_review_session,
    reject_checklist_item,
    resolve_decision,
)

router = APIRouter()

_NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {404: {"description": "Not found"}}
_DIFF_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"description": "Invalid design comparison"},
    404: {"description": "Design not found"},
}


def _authorize_review_object(request: Request, review_session_id: str, action: str) -> None:
    authorize_object_or_403(
        request,
        object_type="review-session",
        object_id=review_session_id,
        action=action,
    )


def _get_design_or_404(name: str, session: str = "api-default") -> Any:
    sess = _get_session(session)
    design = sess.get("designs", {}).get(name)
    if design is None:
        raise HTTPException(404, f"Design '{name}' not found")
    return design


def _review_session_payload(session: Any) -> dict[str, Any]:
    return {
        **session.model_dump(mode="json"),
        "review_status": session.status.value,
        "finalized": session.finalized,
    }


def _get_review_or_404(session_id: str, design_session_id: str) -> ReviewSession:
    review = get_review_session(session_id, design_session_id=design_session_id)
    if review is None:
        raise HTTPException(404, f"Review session '{session_id}' not found")
    return review


# ---------------------------------------------------------------------------
# Review bundle
# ---------------------------------------------------------------------------


@router.get("/bundle/{design_name}", responses=_NOT_FOUND_RESPONSE)
def review_bundle(
    design_name: str,
    baseline_name: str | None = Query(None),
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """Full review bundle — all aggregated panels for a design.

    Args:
        design_name: Name of the design under review.
        baseline_name: Optional baseline design name for semantic diff.

    Returns:
        ``ReviewPanelBundle`` as JSON dict.
    """
    design = _get_design_or_404(design_name, session)
    baseline = _get_design_or_404(baseline_name, session) if baseline_name else None
    bundle = collect_review_bundle(design, baseline=baseline)
    return {"ok": True, "bundle": bundle.model_dump(mode="json")}


@router.get("/bundle/{design_name}/panels", responses=_NOT_FOUND_RESPONSE)
def list_review_panels(
    design_name: str,
    panel_ids: str | None = Query(None, description="Comma-separated panel IDs"),
    baseline_name: str | None = Query(None),
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """List specific review panels for a design.

    Args:
        design_name: Name of the design.
        panel_ids: Comma-separated subset of panel IDs (e.g. ``erc,drc,bom``).
        baseline_name: Optional baseline for semantic diff.

    Returns:
        ``{panel_id: ReviewPanel}`` as JSON dict.
    """
    design = _get_design_or_404(design_name, session)
    baseline = _get_design_or_404(baseline_name, session) if baseline_name else None
    pid_list = [p.strip() for p in panel_ids.split(",") if p.strip()] if panel_ids else None
    panels = collect_panels(design, baseline=baseline, panel_ids=pid_list)
    return {
        "ok": True,
        "design_name": design_name,
        "panels": {pid: p.model_dump(mode="json") for pid, p in panels.items()},
    }


# ---------------------------------------------------------------------------
# Candidate diff / compare
# ---------------------------------------------------------------------------


@router.get("/diff/{design_a}/{design_b}", responses=_DIFF_ERROR_RESPONSES)
def review_diff(
    design_a: str,
    design_b: str,
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """Semantic diff between two designs for candidate comparison.

    Args:
        design_a: Reference (baseline) design name.
        design_b: New (candidate) design name.

    Returns:
        Diff entries as JSON.
    """
    da = _get_design_or_404(design_a, session)
    db = _get_design_or_404(design_b, session)
    try:
        changes = diff_designs(da, db)
        items = []
        for c in changes:
            d = getattr(c, "model_dump", lambda mode="json", _c=c: {"message": str(_c)})()
            items.append(d if isinstance(d, dict) else {"message": str(c)})
        return {"ok": True, "design_a": design_a, "design_b": design_b, "changes": items, "count": len(items)}
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e)) from e


# ---------------------------------------------------------------------------
# Review session (checklist + decisions)
# ---------------------------------------------------------------------------


@router.post("/session/{design_name}", responses=_NOT_FOUND_RESPONSE)
def start_review_session(
    design_name: str,
    request: Request,
    session: str = Depends(authorize_tool("review_start")),
) -> dict[str, Any]:
    """Start a new review session for *design_name*.

    Returns the session with a generated checklist.
    """
    design = _get_design_or_404(design_name, session)
    from zaptrace.security.release import release_design_state_hash

    state_hash = release_design_state_hash(design)
    principal = current_request_principal(request)
    rs = create_review_session(
        design_name,
        state_hash,
        design_session_id=session,
        owner_principal=principal.principal_id,
    )
    authorize_object_or_403(
        request,
        object_type="review-session",
        object_id=rs.session_id,
        action="create-review-session",
        allow_claim=True,
        parent_object_type="session",
        parent_object_id=session,
    )
    return {"ok": True, "session": _review_session_payload(rs)}


@router.get("/session/{session_id}", responses=_NOT_FOUND_RESPONSE)
def get_review_session_route(
    session_id: str,
    request: Request,
    _session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """Get review session state by ID."""
    _authorize_review_object(request, session_id, "read-review-session")
    rs = _get_review_or_404(session_id, _session)
    return {"ok": True, "session": _review_session_payload(rs)}


@router.post(
    "/session/{session_id}/checklist/{item_id}/approve",
    responses={
        404: {"description": "Review session or checklist item not found"},
        409: {"description": "Review session is finalized"},
    },
)
def approve_checklist_route(
    session_id: str,
    request: Request,
    item_id: str,
    reason: str = "",
    _session: str = Depends(authorize_tool("review_approve")),
) -> dict[str, Any]:
    """Approve a single checklist item in a review session."""
    _authorize_review_object(request, session_id, "approve-review-item")
    rs = _get_review_or_404(session_id, _session)
    try:
        item = approve_checklist_item(
            rs,
            item_id,
            decided_by=current_request_principal(request).principal_id,
            reason=reason,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ReviewTransitionError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "item": item.model_dump(mode="json")}


@router.post(
    "/session/{session_id}/checklist/{item_id}/reject",
    responses={
        404: {"description": "Review session or checklist item not found"},
        409: {"description": "Review session is finalized"},
    },
)
def reject_checklist_route(
    session_id: str,
    request: Request,
    item_id: str,
    reason: str = "",
    _session: str = Depends(authorize_tool("review_reject")),
) -> dict[str, Any]:
    """Reject a single checklist item in a review session."""
    _authorize_review_object(request, session_id, "reject-review-item")
    rs = _get_review_or_404(session_id, _session)
    try:
        item = reject_checklist_item(
            rs,
            item_id,
            decided_by=current_request_principal(request).principal_id,
            reason=reason,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ReviewTransitionError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "item": item.model_dump(mode="json")}


@router.post(
    "/session/{session_id}/checklist/{item_id}/waive",
    responses={
        404: {"description": "Review session or checklist item not found"},
        409: {"description": "Review session is finalized"},
    },
)
def waive_checklist_route(
    session_id: str,
    request: Request,
    item_id: str,
    reason: str = "",
    waiver_notes: str = "",
    _session: str = Depends(authorize_tool("review_waive")),
) -> dict[str, Any]:
    """Waive a checklist item (non-blocking override)."""
    _authorize_review_object(request, session_id, "waive-review-item")
    rs = _get_review_or_404(session_id, _session)
    try:
        item = add_waiver(
            rs,
            item_id,
            decided_by=current_request_principal(request).principal_id,
            reason=reason,
            waiver_notes=waiver_notes,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ReviewTransitionError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "item": item.model_dump(mode="json")}


@router.post(
    "/session/{session_id}/decide",
    responses={
        400: {"description": "Invalid decision type"},
        404: {"description": "Review session not found"},
        409: {"description": "Review transition preconditions were not met"},
    },
)
def decide_review_route(
    session_id: str,
    request: Request,
    decision: Annotated[
        str,
        Query(description="One of: approve, reject, request-repair, accept-risk, rollback"),
    ],
    _session: Annotated[str, Depends(authorize_tool("review_decide"))],
    reason: str = "",
    waiver_notes: str = "",
) -> dict[str, Any]:
    """Finalize a review session with an authenticated engineering decision."""
    _authorize_review_object(request, session_id, "decide-review-session")
    rs = _get_review_or_404(session_id, _session)
    try:
        dt = DecisionType(decision.lower())
    except ValueError as e:
        raise HTTPException(
            400,
            f"Invalid decision '{decision}'. Use: approve, reject, request-repair, accept-risk, rollback",
        ) from e
    try:
        rec = resolve_decision(
            rs,
            dt,
            decided_by=current_request_principal(request).principal_id,
            reason=reason,
            waiver_notes=waiver_notes,
        )
    except ReviewTransitionError as e:
        raise HTTPException(409, str(e)) from e
    return {
        "ok": True,
        "decision": rec.model_dump(mode="json"),
        "all_approved": rs.all_approved,
        "review_status": rs.status.value,
    }
