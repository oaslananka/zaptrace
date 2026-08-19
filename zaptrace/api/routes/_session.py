"""REST principal, session, capability, and object-authorization helpers."""

from __future__ import annotations

from collections.abc import Callable
from secrets import token_urlsafe
from typing import Any

from fastapi import Depends, Header, HTTPException, Request

from zaptrace.agent._tool_impls import _get_session, _sessions
from zaptrace.security.network import environment_flag
from zaptrace.security.objects import (
    ObjectAccessDeniedError,
    RequestPrincipal,
    authorize_object,
    get_object_access,
    object_authorization_events,
)
from zaptrace.security.policy import (
    authorize_capability,
    granted_capabilities_from_header,
    record_audit_event,
    required_operation_capability,
)


def _request_id(request: Request, supplied: str | None = None) -> str:
    existing = getattr(request.state, "zaptrace_request_id", None)
    if existing:
        return str(existing)
    request_id = (supplied or "").strip() or f"req-{token_urlsafe(12)}"
    request.state.zaptrace_request_id = request_id
    return request_id


def resolve_request_principal(
    request: Request,
    *,
    actor_header: str | None = None,
    capability_header: str | None = None,
    request_id_header: str | None = None,
) -> RequestPrincipal:
    """Resolve and cache the authorization principal for a request."""
    existing = getattr(request.state, "zaptrace_principal", None)
    if isinstance(existing, RequestPrincipal):
        _request_id(request, request_id_header)
        return existing

    auth = getattr(request.state, "zaptrace_auth", None)
    if isinstance(auth, dict):
        actor = str(auth.get("actor") or "api-token")
        principal = RequestPrincipal(
            principal_id=actor,
            actor=actor,
            scopes=frozenset(str(scope).lower() for scope in auth.get("scopes", set())),
            authenticated=True,
        )
    elif environment_flag("ZAPTRACE_API_ALLOW_LOCAL_CAPABILITY_HEADERS"):
        principal = RequestPrincipal(
            principal_id="local-development",
            actor=actor_header or "local-rest-client",
            scopes=frozenset(granted_capabilities_from_header(capability_header)),
            local_development=True,
        )
    else:
        principal = RequestPrincipal(
            principal_id="loopback-read-only",
            actor="unauthenticated-rest-client",
        )

    request.state.zaptrace_principal = principal
    _request_id(request, request_id_header)
    return principal


def current_request_principal(request: Request) -> RequestPrincipal:
    """Return the cached principal after a route dependency resolved it."""
    principal = getattr(request.state, "zaptrace_principal", None)
    if not isinstance(principal, RequestPrincipal):
        principal = resolve_request_principal(request)
    return principal


def current_request_id(request: Request) -> str:
    """Return the stable correlation ID for the current request."""
    return _request_id(request)


def _check_token_session_allowlist(request: Request, session_id: str, principal: RequestPrincipal) -> None:
    auth = getattr(request.state, "zaptrace_auth", None)
    allowed_sessions = set(auth.get("allowed_sessions", {"*"})) if isinstance(auth, dict) else {"*"}
    if not principal.is_admin and "*" not in allowed_sessions and session_id not in allowed_sessions:
        raise HTTPException(
            status_code=403,
            detail={"code": "OBJECT_NOT_AUTHORIZED", "message": "Principal is not authorized for the target object"},
        )


def authorize_object_or_403(
    request: Request,
    *,
    object_type: str,
    object_id: str,
    action: str,
    allow_claim: bool = False,
    parent_object_type: str = "",
    parent_object_id: str = "",
) -> None:
    """Apply central object ACL policy and translate denials to stable HTTP errors."""
    principal = current_request_principal(request)
    effective_allow_claim = allow_claim
    if object_type == "session" and get_object_access(object_type, object_id) is None and object_id in _sessions:
        effective_allow_claim = False
    try:
        authorize_object(
            object_type=object_type,
            object_id=object_id,
            principal=principal,
            action=action,
            request_id=current_request_id(request),
            allow_claim=effective_allow_claim,
            parent_object_type=parent_object_type,
            parent_object_id=parent_object_id,
        )
    except ObjectAccessDeniedError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "OBJECT_NOT_AUTHORIZED", "message": "Principal is not authorized for the target object"},
        ) from exc


def resolve_session_id(
    request: Request,
    x_zaptrace_session_id: str | None = Header(None),
    x_zaptrace_actor: str | None = Header(None),
    x_zaptrace_capabilities: str | None = Header(None),
    x_request_id: str | None = Header(None, alias="X-Request-ID"),
) -> str:
    """Resolve and authorize a session selector for read operations."""
    principal = resolve_request_principal(
        request,
        actor_header=x_zaptrace_actor,
        capability_header=x_zaptrace_capabilities,
        request_id_header=x_request_id,
    )
    if principal.authenticated and not x_zaptrace_session_id:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "SESSION_REQUIRED",
                "message": "X-ZapTrace-Session-Id is required for authenticated session-scoped reads",
            },
        )
    session_id = x_zaptrace_session_id or "api-default"
    _check_token_session_allowlist(request, session_id, principal)
    authorize_object_or_403(
        request,
        object_type="session",
        object_id=session_id,
        action=f"read:{request.url.path}",
        allow_claim=True,
    )
    return session_id


def require_session_id(
    request: Request,
    x_zaptrace_session_id: str | None = Header(None),
    x_zaptrace_actor: str | None = Header(None),
    x_zaptrace_capabilities: str | None = Header(None),
    x_request_id: str | None = Header(None, alias="X-Request-ID"),
) -> str:
    """Require an explicit session ID for mutating REST operations."""
    if not x_zaptrace_session_id:
        raise HTTPException(
            status_code=401,
            detail={"code": "SESSION_REQUIRED", "message": "X-ZapTrace-Session-Id is required for mutating operations"},
        )
    principal = resolve_request_principal(
        request,
        actor_header=x_zaptrace_actor,
        capability_header=x_zaptrace_capabilities,
        request_id_header=x_request_id,
    )
    _check_token_session_allowlist(request, x_zaptrace_session_id, principal)
    return x_zaptrace_session_id


def _effective_capabilities(request: Request, raw_header: str | None) -> tuple[set[str], str]:
    principal = current_request_principal(request)
    if principal.authenticated:
        return set(principal.scopes), "bearer-token"
    if principal.local_development:
        return granted_capabilities_from_header(raw_header), "explicit-loopback-development"
    return set(), "capability-headers-disabled"


def _authorize_capability_for_session(
    request: Request,
    *,
    session_id: str,
    tool_name: str,
    raw_capabilities: str | None,
    reason_header: str | None,
    allow_claim: bool,
    required_capability: str | None = None,
) -> str:
    authorize_object_or_403(
        request,
        object_type="session",
        object_id=session_id,
        action=tool_name,
        allow_claim=allow_claim,
    )
    required = required_capability or required_operation_capability(tool_name)
    granted, auth_source = _effective_capabilities(request, raw_capabilities)
    allowed, reason = authorize_capability(required, granted)
    principal = current_request_principal(request)
    session = _get_session(session_id)
    record_audit_event(
        session,
        surface="rest",
        session_id=session_id,
        actor=principal.actor,
        tool=tool_name,
        capability=required,
        decision="allow" if allowed else "deny",
        reason=reason_header or reason,
        metadata={
            "method": request.method,
            "path": str(request.url.path),
            "granted_capabilities": sorted(granted),
            "auth_source": auth_source,
            "authenticated": principal.authenticated,
            "principal_id": principal.principal_id,
            "target_object_type": "session",
            "target_object_id": session_id,
            "request_id": current_request_id(request),
        },
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "OPERATION_NOT_AUTHORIZED",
                "message": reason,
                "tool": tool_name,
                "required_capability": required,
            },
        )
    return session_id


def authorize_request_capability(
    tool_name: str, *, required_capability: str | None = None
) -> Callable[..., RequestPrincipal]:
    """Build a capability dependency for operations that create their object."""

    def _dependency(
        request: Request,
        x_zaptrace_actor: str | None = Header(None),
        x_zaptrace_capabilities: str | None = Header(None),
        x_request_id: str | None = Header(None, alias="X-Request-ID"),
    ) -> RequestPrincipal:
        principal = resolve_request_principal(
            request,
            actor_header=x_zaptrace_actor,
            capability_header=x_zaptrace_capabilities,
            request_id_header=x_request_id,
        )
        required = required_capability or required_operation_capability(tool_name)
        granted, _auth_source = _effective_capabilities(request, x_zaptrace_capabilities)
        allowed, reason = authorize_capability(required, granted)
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "OPERATION_NOT_AUTHORIZED",
                    "message": reason,
                    "tool": tool_name,
                    "required_capability": required,
                },
            )
        return principal

    return _dependency


def authorize_tool(tool_name: str) -> Callable[..., str]:
    """Build a dependency enforcing session ownership and capability policy."""

    def _dependency(
        request: Request,
        session_id: str = Depends(require_session_id),
        x_zaptrace_capabilities: str | None = Header(None),
        x_zaptrace_reason: str | None = Header(None),
    ) -> str:
        return _authorize_capability_for_session(
            request,
            session_id=session_id,
            tool_name=tool_name,
            raw_capabilities=x_zaptrace_capabilities,
            reason_header=x_zaptrace_reason,
            allow_claim=True,
        )

    return _dependency


def authorize_target_session(
    action: str,
    *,
    tool_name: str | None = None,
    required_capability: str | None = None,
    allow_claim: bool = False,
) -> Callable[..., str]:
    """Build a dependency authorizing a path-selected target session."""

    def _dependency(
        session_id: str,
        request: Request,
        x_zaptrace_actor: str | None = Header(None),
        x_zaptrace_capabilities: str | None = Header(None),
        x_zaptrace_reason: str | None = Header(None),
        x_request_id: str | None = Header(None, alias="X-Request-ID"),
    ) -> str:
        principal = resolve_request_principal(
            request,
            actor_header=x_zaptrace_actor,
            capability_header=x_zaptrace_capabilities,
            request_id_header=x_request_id,
        )
        _check_token_session_allowlist(request, session_id, principal)
        if tool_name is None:
            authorize_object_or_403(
                request,
                object_type="session",
                object_id=session_id,
                action=action,
                allow_claim=allow_claim,
            )
            return session_id
        return _authorize_capability_for_session(
            request,
            session_id=session_id,
            tool_name=tool_name,
            raw_capabilities=x_zaptrace_capabilities,
            reason_header=x_zaptrace_reason,
            allow_claim=allow_claim,
            required_capability=required_capability,
        )

    return _dependency


def session_audit_events(session_id: str, limit: int = 50) -> dict[str, Any]:
    """Return capability and object-authorization events for a session."""
    session = _get_session(session_id)
    capability_events = list(session.get("audit_events", []))
    direct_object_events = object_authorization_events(object_type="session", object_id=session_id, limit=limit)
    child_object_events = object_authorization_events(
        parent_object_type="session",
        parent_object_id=session_id,
        limit=limit,
    )
    bounded_limit = max(1, limit)
    object_events = sorted(
        [*direct_object_events, *child_object_events],
        key=lambda event: str(event["timestamp"]),
    )[-bounded_limit:]
    return {
        "session_id": session_id,
        "count": len(capability_events),
        "events": capability_events[-bounded_limit:],
        "object_authorization_count": len(object_events),
        "object_authorization_events": object_events[-bounded_limit:],
    }
