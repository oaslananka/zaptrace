"""REST API routes for session ownership, sandbox management, and replay."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from zaptrace.agent._tool_impls import _get_session
from zaptrace.api.routes._session import (
    authorize_request_capability,
    authorize_target_session,
    current_request_id,
    current_request_principal,
)
from zaptrace.security.objects import (
    ObjectAccessDeniedError,
    RequestPrincipal,
    authorize_object,
    delegate_object_access,
    generate_secure_object_id,
    get_object_access,
    revoke_object_access,
)
from zaptrace.security.replay import get_replay
from zaptrace.security.sandbox import (
    emergency_reset,
    emergency_stop,
    reset_sandbox,
    sandbox_status,
)

router = APIRouter()

_FORBIDDEN_RESPONSE: dict[int | str, dict[str, Any]] = {403: {"description": "Forbidden"}}
_NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {404: {"description": "Not found"}}

_CREATE_SESSION_AUTH = authorize_request_capability("session_create", required_capability="preview-write")
_READ_SESSION_ACCESS = authorize_target_session("read-session-access")
_DELEGATE_SESSION = authorize_target_session(
    "delegate-session", tool_name="session_delegate", required_capability="approved-commit"
)
_REVOKE_SESSION_DELEGATE = authorize_target_session(
    "revoke-session-delegate", tool_name="session_delegate", required_capability="approved-commit"
)
_SANDBOX_STATUS = authorize_target_session("sandbox-status")
_SANDBOX_STOP = authorize_target_session("sandbox-stop", tool_name="sandbox_stop", required_capability="sandbox-write")
_SANDBOX_RESET = authorize_target_session(
    "sandbox-reset", tool_name="sandbox_reset", required_capability="sandbox-write"
)
_SANDBOX_CLEAR = authorize_target_session(
    "sandbox-clear", tool_name="sandbox_clear", required_capability="sandbox-write"
)
_REPLAY_READ = authorize_target_session("replay-read")


@router.post("/sessions")
def api_create_session(
    request: Request,
    principal: RequestPrincipal = Depends(_CREATE_SESSION_AUTH),  # noqa: B008
) -> dict[str, Any]:
    """Create and claim a cryptographically strong API session ID."""
    session_id = generate_secure_object_id("api")
    access = authorize_object(
        object_type="session",
        object_id=session_id,
        principal=principal,
        action="create-session",
        request_id=current_request_id(request),
        allow_claim=True,
    )
    _get_session(session_id)
    return {"ok": True, "session_id": session_id, "access": access.to_dict()}


@router.get("/sessions/{session_id}/access", responses=_FORBIDDEN_RESPONSE)
def api_session_access(
    session_id: str,
    _authorized_session: str = Depends(_READ_SESSION_ACCESS),
) -> dict[str, Any]:
    """Return ownership and delegation metadata for an authorized session."""
    access = get_object_access("session", session_id)
    if access is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "OBJECT_NOT_AUTHORIZED", "message": "Principal is not authorized for the target object"},
        )
    return {"ok": True, "access": access.to_dict()}


@router.post("/sessions/{session_id}/delegates/{delegate_principal}", responses=_FORBIDDEN_RESPONSE)
def api_delegate_session(
    session_id: str,
    delegate_principal: str,
    request: Request,
    _authorized_session: str = Depends(_DELEGATE_SESSION),
) -> dict[str, Any]:
    """Delegate session access; only the owner or object administrator may grant it."""
    try:
        access = delegate_object_access(
            object_type="session",
            object_id=session_id,
            principal=current_request_principal(request),
            delegate_principal=delegate_principal,
            request_id=current_request_id(request),
        )
    except (ObjectAccessDeniedError, ValueError) as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "OBJECT_NOT_AUTHORIZED", "message": str(exc)},
        ) from exc
    return {"ok": True, "access": access.to_dict()}


@router.delete("/sessions/{session_id}/delegates/{delegate_principal}", responses=_FORBIDDEN_RESPONSE)
def api_revoke_session_delegate(
    session_id: str,
    delegate_principal: str,
    request: Request,
    _authorized_session: str = Depends(_REVOKE_SESSION_DELEGATE),
) -> dict[str, Any]:
    """Revoke delegated session access; only owner/admin may revoke it."""
    try:
        access = revoke_object_access(
            object_type="session",
            object_id=session_id,
            principal=current_request_principal(request),
            delegate_principal=delegate_principal,
            request_id=current_request_id(request),
        )
    except (ObjectAccessDeniedError, ValueError) as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "OBJECT_NOT_AUTHORIZED", "message": str(exc)},
        ) from exc
    return {"ok": True, "access": access.to_dict()}


@router.get("/sandbox/{session_id}/status", responses=_NOT_FOUND_RESPONSE)
def api_sandbox_status(
    session_id: str,
    _authorized_session: str = Depends(_SANDBOX_STATUS),
) -> dict[str, Any]:
    """Get sandbox status for an authorized session."""
    try:
        return sandbox_status(session_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sandbox/{session_id}/stop")
def api_sandbox_stop(
    session_id: str,
    reason: str = "",
    _authorized_session: str = Depends(_SANDBOX_STOP),
) -> dict[str, Any]:
    """Emergency-stop an authorized session."""
    emergency_stop(session_id, reason)
    return {"session_id": session_id, "emergency_stopped": True}


@router.post("/sandbox/{session_id}/reset")
def api_sandbox_reset(
    session_id: str,
    _authorized_session: str = Depends(_SANDBOX_RESET),
) -> dict[str, Any]:
    """Reset emergency stop for an authorized session."""
    emergency_reset(session_id)
    status = sandbox_status(session_id)
    return {"session_id": session_id, "emergency_stopped": status["emergency_stopped"]}


@router.post("/sandbox/{session_id}/clear")
def api_sandbox_clear(
    session_id: str,
    _authorized_session: str = Depends(_SANDBOX_CLEAR),
) -> dict[str, Any]:
    """Clear counters and budgets for an authorized session."""
    reset_sandbox(session_id)
    return {"session_id": session_id, "reset": True}


@router.get("/replay/{session_id}", responses=_NOT_FOUND_RESPONSE)
def api_replay_log(
    session_id: str,
    _authorized_session: str = Depends(_REPLAY_READ),
) -> dict[str, Any]:
    """Get replay metadata for an authorized session."""
    log = get_replay(session_id)
    if log is None:
        raise HTTPException(status_code=404, detail=f"No replay log for session '{session_id}'")
    return {
        "session_id": log.session_id,
        "entry_count": log.entry_count,
        "total_duration_ms": round(log.total_duration_ms, 1),
        "digest": log.digest,
    }
