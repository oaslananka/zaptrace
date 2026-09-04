"""FastMCP server exposing all agent tools as MCP tools + resources.

Hardening layer:
  - Session management: create / destroy / list sessions
  - Structured error wrapping: every tool output wrapped in a consistent envelope
  - Input validation: file path sandboxing, parameter type/bounds checks
  - Timeout protection: long-running tools get a configurable timeout
"""

from __future__ import annotations

import asyncio
import functools
import hmac
import inspect
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from zaptrace import __version__
from zaptrace.agent._tool_impls import TOOL_REGISTRY, _get_session, _sessions
from zaptrace.agent.execution import (
    ToolExecutionOutcome,
    UnsupportedExecutionPlatformError,
    execute_mutating_tool,
    is_session_destroyed,
    mark_session_destroyed,
    session_execution_lock,
)
from zaptrace.mcp.auth_config import MCPHTTPAuthConfiguration, resolve_mcp_http_auth_configuration
from zaptrace.mcp.oauth_provider import (
    MCP_HTTP_PATH,
    MCPOAuthBoundaryMiddleware,
    authorize_oauth_capability,
    build_mcp_oauth_provider,
    oauth_capabilities_from_scopes,
    oauth_principal_from_access_token,
    oauth_resource_metadata_url,
)
from zaptrace.security.network import environment_flag, resolve_network_bind
from zaptrace.security.objects import (
    ObjectAccessDeniedError,
    RequestPrincipal,
    authorize_object,
    generate_secure_object_id,
    get_object_access,
    object_authorization_events,
    remove_object_access,
)
from zaptrace.security.policy import (
    authorize_capability,
    granted_capabilities_from_header,
    record_audit_event,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_NAME = "zaptrace"
SERVER_VERSION = __version__
SESSION_ID_HEADER = "x-zaptrace-session-id"
_DEFAULT_SESSION_ID = "mcp-default-session"
_DEFAULT_TIMEOUT_S = 120  # per-tool timeout
_MAX_PATH_LENGTH = 4096
_ALLOWED_EXPORT_ROOT = Path.cwd()  # sandbox base for file exports
_HTTP_AUTH_ACTIVE = False
_HTTP_AUTH_ACTOR = "mcp-client"
_OBJECT_NOT_AUTHORIZED_MESSAGE = "Principal is not authorized for the target object"


def _tool_timeout_seconds(tool_name: str) -> float:
    """Return the bounded execution timeout for a public MCP tool."""
    slow_indicators = ("proof_", "synthesize_", "route_", "pipeline_", "export_")
    return 300.0 if any(tool_name.startswith(prefix) for prefix in slow_indicators) else float(_DEFAULT_TIMEOUT_S)


# ---------------------------------------------------------------------------
# Structured response helpers
# ---------------------------------------------------------------------------

_ERROR_SENTINEL = object()


def _ok(data: Any = None) -> dict[str, Any]:
    """Return a success envelope."""
    return {"ok": True, "data": data}


def _err(message: str, code: str = "TOOL_ERROR", details: dict | None = None) -> dict[str, Any]:
    """Return an error envelope."""
    return {
        "ok": False,
        "error": {"code": code, "message": message, "details": details or {}},
    }


def _allowed_path_root() -> Path:
    """Return the configured workspace root used by MCP path policies."""
    raw = os.environ.get("ZAPTRACE_WORKSPACE", "").strip()
    return Path(raw).resolve() if raw else _ALLOWED_EXPORT_ROOT.resolve()


def _resolve_safe_path(path: str) -> tuple[Path | None, str]:
    """Resolve a user path inside the configured workspace sandbox."""
    if not path or not path.strip():
        return None, "Path is empty"
    if len(path) > _MAX_PATH_LENGTH:
        return None, f"Path exceeds max length ({_MAX_PATH_LENGTH})"
    normalized_path = path.replace("\\", "/")
    candidate = Path(normalized_path)
    root = _allowed_path_root()
    try:
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    except (OSError, RuntimeError):
        return None, f"Cannot resolve path: {path}"
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, f"Path escapes allowed sandbox: {resolved}"
    return resolved, ""


def _is_path_safe(path: str) -> tuple[bool, str]:
    """Validate that a path is within the allowed sandbox."""
    resolved, reason = _resolve_safe_path(path)
    return resolved is not None, reason


def _parameter_type_error(name: str, value: object, parameter_type: str) -> str | None:
    """Return the existing registry type error for one parameter, if any."""
    actual_type = type(value).__name__
    if parameter_type == "string" and not isinstance(value, str):
        return f"Parameter '{name}' expected string, got {actual_type}"
    if parameter_type == "integer" and not isinstance(value, int):
        return f"Parameter '{name}' expected integer, got {actual_type}"
    if parameter_type == "number" and not isinstance(value, (int, float)):
        return f"Parameter '{name}' expected number, got {actual_type}"
    if parameter_type == "boolean" and not isinstance(value, bool):
        return f"Parameter '{name}' expected boolean, got {actual_type}"
    return None


def _parameter_path_error(name: str, value: object, spec: dict) -> str | None:
    """Return the existing sandbox path error for one parameter, if any."""
    path_policy = spec.get("path_policy")
    if path_policy is None or not isinstance(value, str):
        return None

    path_suffixes = path_policy.get("path_suffixes")
    if path_suffixes and Path(value).suffix.lower() not in path_suffixes:
        return None

    resolved, reason = _resolve_safe_path(value)
    if resolved is None:
        return f"Parameter '{name}': {reason}"
    if path_policy.get("must_exist") and not resolved.exists():
        return f"Parameter '{name}': Path not found: {value}"
    return None


def _validate_tool_params(tool_def: dict, kwargs: dict) -> list[str]:
    """Validate tool parameters against registry schema.

    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []
    param_spec = tool_def.get("params", {})
    for name, value in kwargs.items():
        if name == "session_id":
            continue
        spec = param_spec.get(name, {})
        type_error = _parameter_type_error(name, value, spec.get("type", "any"))
        if type_error is not None:
            errors.append(type_error)
        path_error = _parameter_path_error(name, value, spec)
        if path_error is not None:
            errors.append(path_error)
    return errors


@dataclass(frozen=True, slots=True)
class _PreparedToolCall:
    """Validated typed context for the remaining wrapper phases."""

    tool_name: str
    tool_def: dict[str, Any]
    kwargs: dict[str, Any]
    session_id: str
    required_capability: str
    timeout_s: float


class _ToolCallRejectedError(Exception):
    """Internal control flow for a stable public wrapper denial response."""

    def __init__(self, response: dict[str, Any]) -> None:
        super().__init__(str(response.get("error", {}).get("code", "TOOL_ERROR")))
        self.response = response


def _prepare_tool_call(
    tool_name: str,
    tool_def: dict[str, Any],
    kwargs: dict[str, Any],
    *,
    has_session: bool,
) -> _PreparedToolCall:
    """Apply defaults and validate parameters before any authorization state is touched."""
    call_kwargs = dict(kwargs)
    if has_session and "session_id" not in call_kwargs:
        call_kwargs["session_id"] = _DEFAULT_SESSION_ID
    param_errors = _validate_tool_params(tool_def, call_kwargs)
    if param_errors:
        raise _ToolCallRejectedError(_err("; ".join(param_errors), code="INVALID_PARAMETER"))
    return _PreparedToolCall(
        tool_name=tool_name,
        tool_def=tool_def,
        kwargs=call_kwargs,
        session_id=str(call_kwargs.get("session_id", _DEFAULT_SESSION_ID)),
        required_capability=str(tool_def["capability"]),
        timeout_s=_tool_timeout_seconds(tool_name),
    )


def _session_capabilities(session_id: str) -> set[str]:
    """Return effective capabilities without mixing OAuth and legacy grants."""
    access_token = get_access_token()
    if access_token is not None:
        return oauth_capabilities_from_scopes(access_token.scopes)
    session = _get_session(session_id)
    caps = set(session.get("capabilities", set()))
    caps.update(granted_capabilities_from_header(os.environ.get("ZAPTRACE_MCP_CAPABILITIES")))
    return caps


def _mcp_principal() -> RequestPrincipal:
    """Resolve the stable principal for stdio or authenticated HTTP MCP."""
    access_token = get_access_token()
    if access_token is not None:
        return oauth_principal_from_access_token(access_token)
    raw_scopes = {
        item.strip().lower()
        for item in os.environ.get("ZAPTRACE_MCP_CAPABILITIES", "").replace(",", " ").split()
        if item.strip()
    }
    if _HTTP_AUTH_ACTIVE:
        return RequestPrincipal(
            principal_id=_HTTP_AUTH_ACTOR,
            actor=_HTTP_AUTH_ACTOR,
            scopes=frozenset(raw_scopes),
            authenticated=True,
        )
    return RequestPrincipal(
        principal_id="mcp-local",
        actor="mcp-local",
        scopes=frozenset(raw_scopes),
        local_development=True,
    )


def _oauth_capability_denial(
    *,
    operation: str,
    required_capability: str,
) -> dict[str, Any] | None:
    """Return a stable OAuth scope denial before any object access."""
    access_token = get_access_token()
    if access_token is None:
        return None
    try:
        oauth_principal_from_access_token(access_token)
    except RuntimeError:
        return _err(
            "Validated OAuth identity is incomplete",
            code="AUTH_INVALID_TOKEN",
            details={"operation": operation},
        )
    allowed, reason, required_scope = authorize_oauth_capability(
        required_capability,
        access_token.scopes,
    )
    if allowed:
        return None
    return _err(
        reason,
        code="OPERATION_NOT_AUTHORIZED",
        details={
            "operation": operation,
            "required_capability": required_capability,
            "required_scope": required_scope,
        },
    )


def _authorize_mcp_session_object(
    session_id: str,
    *,
    action: str,
) -> tuple[RequestPrincipal, str]:
    """Authorize a session object for an MCP tool or resource read."""
    if is_session_destroyed(session_id):
        raise ObjectAccessDeniedError(f"Session '{session_id}' has been destroyed")
    principal = _mcp_principal()
    request_id = generate_secure_object_id("mcp-request")
    allow_claim = get_object_access("session", session_id) is None and session_id not in _sessions
    authorize_object(
        object_type="session",
        object_id=session_id,
        principal=principal,
        action=action,
        request_id=request_id,
        allow_claim=allow_claim,
    )
    return principal, request_id


@dataclass(frozen=True, slots=True)
class _AuthorizedToolCall:
    """Authorization result consumed by execution and response phases."""

    prepared: _PreparedToolCall
    principal: RequestPrincipal
    request_id: str
    granted_capabilities: frozenset[str]
    actor: str
    auth_source: str


def _authorize_tool_principal(prepared: _PreparedToolCall) -> tuple[RequestPrincipal, str]:
    """Apply OAuth scope and session-object authorization before capability checks."""
    oauth_denial = _oauth_capability_denial(
        operation=prepared.tool_name,
        required_capability=prepared.required_capability,
    )
    if oauth_denial is not None:
        raise _ToolCallRejectedError(oauth_denial)
    try:
        return _authorize_mcp_session_object(prepared.session_id, action=prepared.tool_name)
    except ObjectAccessDeniedError as exc:
        raise _ToolCallRejectedError(
            _err(
                _OBJECT_NOT_AUTHORIZED_MESSAGE,
                code="OBJECT_NOT_AUTHORIZED",
                details={"tool": prepared.tool_name, "session_id": prepared.session_id},
            )
        ) from exc


def _authorization_identity(principal: RequestPrincipal) -> tuple[str, str]:
    """Return the existing actor and audit-source identity for the current transport."""
    if get_access_token() is not None:
        return principal.actor, "oauth-jwt"
    if _HTTP_AUTH_ACTIVE:
        return _HTTP_AUTH_ACTOR, "bearer-token"
    return "mcp-client", "stdio-or-loopback-development"


def _record_capability_decision(authorized: _AuthorizedToolCall, *, allowed: bool, reason: str) -> None:
    """Record the established mutating-tool capability decision."""
    prepared = authorized.prepared
    if prepared.required_capability == "read":
        return
    record_audit_event(
        _get_session(prepared.session_id),
        surface="mcp",
        session_id=prepared.session_id,
        actor=authorized.actor,
        tool=prepared.tool_name,
        capability=prepared.required_capability,
        decision="allow" if allowed else "deny",
        reason=reason,
        metadata={
            "granted_capabilities": sorted(authorized.granted_capabilities),
            "auth_source": authorized.auth_source,
            "authenticated": authorized.principal.authenticated,
            "principal_id": authorized.principal.principal_id,
            "target_object_type": "session",
            "target_object_id": prepared.session_id,
            "request_id": authorized.request_id,
        },
    )


def _authorize_tool_call(prepared: _PreparedToolCall) -> _AuthorizedToolCall:
    """Build the typed authorization context or raise a stable denial response."""
    principal, request_id = _authorize_tool_principal(prepared)
    granted = frozenset(_session_capabilities(prepared.session_id))
    allowed, reason = authorize_capability(prepared.required_capability, set(granted))
    actor, auth_source = _authorization_identity(principal)
    authorized = _AuthorizedToolCall(
        prepared=prepared,
        principal=principal,
        request_id=request_id,
        granted_capabilities=granted,
        actor=actor,
        auth_source=auth_source,
    )
    _record_capability_decision(authorized, allowed=allowed, reason=reason)
    if not allowed:
        raise _ToolCallRejectedError(
            _err(
                reason,
                code="OPERATION_NOT_AUTHORIZED",
                details={"tool": prepared.tool_name, "required_capability": prepared.required_capability},
            )
        )
    return authorized


@dataclass(frozen=True, slots=True)
class _ExecutionAuditEntry:
    """One normalized lifecycle decision emitted by isolated execution."""

    decision: str
    reason: str
    metadata: dict[str, Any]


def _execution_audit_entries(decision: str, metadata: dict[str, Any]) -> tuple[_ExecutionAuditEntry, ...]:
    """Normalize worker lifecycle callbacks into deterministic MCP audit entries."""
    mapped_decision = "cancel" if decision == "cancel_requested" else decision
    reasons = {
        "start": "isolated mutating tool execution started",
        "timeout": "execution deadline elapsed",
        "cancel": "caller cancelled isolated mutating tool execution",
        "worker_terminated": "isolated worker termination confirmed",
        "conflict": "session was destroyed before execution",
        "rollback": "isolated worker state and staged artifacts were discarded",
        "commit": "isolated worker state and staged artifacts committed",
    }
    entries: list[_ExecutionAuditEntry] = []
    if mapped_decision == "rollback" and metadata.get("reason") in {
        "worker error",
        "coordinator error",
        "worker exited without a response",
        "tool callable is not importable",
    }:
        entries.append(
            _ExecutionAuditEntry(
                decision="error",
                reason=str(metadata.get("reason")),
                metadata=dict(metadata),
            )
        )
    entries.append(
        _ExecutionAuditEntry(
            decision=mapped_decision,
            reason=reasons.get(mapped_decision, str(metadata.get("reason") or mapped_decision)),
            metadata=dict(metadata),
        )
    )
    return tuple(entries)


def _record_execution_event(
    authorized: _AuthorizedToolCall,
    decision: str,
    event_metadata: dict[str, Any],
) -> None:
    """Record normalized isolated-execution lifecycle events for one authorized call."""
    prepared = authorized.prepared
    for entry in _execution_audit_entries(decision, event_metadata):
        metadata = {
            "execution_job_id": entry.metadata.get("job_id"),
            "principal_id": authorized.principal.principal_id,
            "request_id": authorized.request_id,
            "target_object_type": "session",
            "target_object_id": prepared.session_id,
        }
        for key in (
            "worker_terminated",
            "duration_ms",
            "timeout_s",
            "exception_type",
            "reason",
        ):
            if key in entry.metadata:
                metadata[key] = entry.metadata[key]
        record_audit_event(
            _get_session(prepared.session_id),
            surface="mcp",
            session_id=prepared.session_id,
            actor=authorized.actor,
            tool=prepared.tool_name,
            capability=prepared.required_capability,
            decision=entry.decision,
            reason=entry.reason,
            metadata=metadata,
        )


class MCPBearerAuthMiddleware:
    """Require a static bearer token for MCP HTTP requests."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.expected_authorization = f"Bearer {token}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        if not hmac.compare_digest(headers.get("authorization", ""), self.expected_authorization):
            response = JSONResponse(
                status_code=401,
                content={
                    "ok": False,
                    "error": {"code": "AUTH_REQUIRED", "message": "Valid MCP bearer token is required"},
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def create_http_app(token: str | None = None) -> ASGIApp:
    """Create the MCP HTTP app with configured bearer authentication."""
    global _HTTP_AUTH_ACTIVE, _HTTP_AUTH_ACTOR
    resolved_token = os.environ.get("ZAPTRACE_MCP_HTTP_TOKEN", "") if token is None else token
    _HTTP_AUTH_ACTIVE = bool(resolved_token)
    _HTTP_AUTH_ACTOR = os.environ.get("ZAPTRACE_MCP_TOKEN_SUBJECT", "mcp-token") if resolved_token else "mcp-client"
    middleware = [Middleware(MCPBearerAuthMiddleware, token=resolved_token)] if resolved_token else None
    return server.http_app(middleware=middleware)


_SESSION_TOOL_CAPABILITIES = {
    "session_create": "read",
    "session_destroy": "sandbox-write",
    "session_list": "read",
}


def _oauth_tool_capability(tool_name: str) -> str | None:
    """Resolve the existing server-owned capability for one public MCP tool."""
    session_capability = _SESSION_TOOL_CAPABILITIES.get(tool_name)
    if session_capability is not None:
        return session_capability
    tool_def = TOOL_REGISTRY.get(tool_name)
    return str(tool_def["capability"]) if tool_def is not None else None


def create_oauth_http_app(configuration: MCPHTTPAuthConfiguration) -> ASGIApp:
    """Build the supported OAuth resource-server app."""
    provider = build_mcp_oauth_provider(configuration)
    oauth_server = FastMCP(
        SERVER_NAME,
        instructions=server.instructions,
        version=SERVER_VERSION,
        auth=provider,
        providers=server.providers,
    )
    boundary = Middleware(
        MCPOAuthBoundaryMiddleware,
        resource_metadata_url=oauth_resource_metadata_url(configuration),
        tool_capability_resolver=_oauth_tool_capability,
    )
    return oauth_server.http_app(path=MCP_HTTP_PATH, middleware=[boundary])


# ---------------------------------------------------------------------------
# Per-session tools exposed as MCP resources
# ---------------------------------------------------------------------------


def _list_session_designs(session_id: str) -> list[dict[str, Any]]:
    """List all designs in a session (internal helper)."""
    session = _get_session(session_id)
    designs = session.get("designs", {})
    return [
        {
            "name": name,
            "component_count": len(d.components),
            "net_count": len(d.nets),
            "board": f"{d.board.width_mm}x{d.board.height_mm}mm",
        }
        for name, d in designs.items()
    ]


# ---------------------------------------------------------------------------
# Sandboxed wrapper that wraps every tool call
# ---------------------------------------------------------------------------


def _mutation_failure_code(outcome: ToolExecutionOutcome) -> str:
    """Map one isolated execution failure type to the stable public error code."""
    if outcome.exception_type == UnsupportedExecutionPlatformError.__name__:
        return "UNSUPPORTED_PLATFORM"
    if outcome.exception_type == "SessionDestroyedError":
        return "SESSION_CONFLICT"
    return "TOOL_ERROR"


def _mutation_outcome_response(
    authorized: _AuthorizedToolCall,
    outcome: ToolExecutionOutcome,
) -> dict[str, Any] | None:
    """Convert a non-success isolated execution outcome into the stable MCP envelope."""
    prepared = authorized.prepared
    if outcome.status == "completed":
        return None
    if outcome.status == "conflict":
        return _err(
            outcome.error or f"Session '{prepared.session_id}' is no longer available",
            code="SESSION_CONFLICT",
            details={
                "tool": prepared.tool_name,
                "session_id": prepared.session_id,
                "job_id": outcome.job_id,
                "exception_type": outcome.exception_type,
            },
        )
    if outcome.status == "timeout":
        return _err(
            f"Tool '{prepared.tool_name}' timed out after {prepared.timeout_s}s",
            code="TOOL_TIMEOUT",
            details={
                "tool": prepared.tool_name,
                "job_id": outcome.job_id,
                "worker_terminated": outcome.worker_terminated,
                "duration_ms": round(outcome.duration_ms, 1),
            },
        )
    return _err(
        outcome.error or f"Tool '{prepared.tool_name}' failed in isolated execution",
        code=_mutation_failure_code(outcome),
        details={
            "tool": prepared.tool_name,
            "job_id": outcome.job_id,
            "worker_terminated": outcome.worker_terminated,
            "exception_type": outcome.exception_type,
        },
    )


def _normalize_tool_result(tool_name: str, result: Any) -> dict[str, Any]:
    """Convert one successful tool return value into the stable MCP success envelope."""
    if result is None:
        return _ok({"message": f"Tool '{tool_name}' completed successfully"})
    if not isinstance(result, dict):
        return _ok({"result": str(result)})
    return _ok(result)


async def _execute_tool_call(authorized: _AuthorizedToolCall, fn: Callable[..., Any]) -> Any:
    """Execute an authorized call through the established read or isolated-mutation boundary."""
    prepared = authorized.prepared
    if prepared.required_capability != "read":
        outcome = await execute_mutating_tool(
            tool_name=prepared.tool_name,
            tool_def=prepared.tool_def,
            kwargs=prepared.kwargs,
            session_id=prepared.session_id,
            timeout_s=prepared.timeout_s,
            workspace=_allowed_path_root(),
            event_sink=functools.partial(_record_execution_event, authorized),
        )
        error_response = _mutation_outcome_response(authorized, outcome)
        if error_response is not None:
            raise _ToolCallRejectedError(error_response)
        return outcome.result

    try:
        loop = asyncio.get_running_loop()
        if inspect.iscoroutinefunction(fn):
            return await asyncio.wait_for(fn(**prepared.kwargs), timeout=prepared.timeout_s)
        return await asyncio.wait_for(
            loop.run_in_executor(None, functools.partial(fn, **prepared.kwargs)),
            timeout=prepared.timeout_s,
        )
    except TimeoutError as exc:
        raise _ToolCallRejectedError(
            _err(
                f"Tool '{prepared.tool_name}' timed out after {prepared.timeout_s}s",
                code="TOOL_TIMEOUT",
            )
        ) from exc
    except Exception as exc:
        raise _ToolCallRejectedError(_err(str(exc), code="TOOL_ERROR", details={"tool": prepared.tool_name})) from exc


def _make_sandboxed_tool(tool_name: str, tool_def: dict) -> Callable:
    """Wrap a raw tool function with authorization and cancellation-safe execution."""

    fn: Callable = tool_def["fn"]
    sig = inspect.signature(fn)
    has_session = "session_id" in sig.parameters

    @functools.wraps(fn)
    async def _sandboxed_wrapper(**kwargs: Any) -> dict[str, Any]:
        try:
            prepared = _prepare_tool_call(tool_name, tool_def, kwargs, has_session=has_session)
            authorized = _authorize_tool_call(prepared)
            result = await _execute_tool_call(authorized, fn)
        except _ToolCallRejectedError as exc:
            return exc.response
        return _normalize_tool_result(tool_name, result)

    _sandboxed_wrapper.__signature__ = sig  # type: ignore[attr-defined]
    _sandboxed_wrapper.__name__ = tool_name
    _sandboxed_wrapper.__qualname__ = tool_name
    return _sandboxed_wrapper


# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

server = FastMCP(
    SERVER_NAME,
    instructions=(
        "Agent-native electronics design assistant. "
        "Use tools to parse, synthesize, validate, place, route, "
        "and export electronics designs.\n\n"
        "All tools return a structured envelope: { ok: bool, data?: ..., error?: { code, message, details } }.\n"
        "On success ok=true with data in 'data' field. On failure ok=false with error info in 'error' field.\n"
        "Use session_create() first if you need an isolated session, otherwise a default session is used.\n"
        "Protocol compatibility: MCP 2026-07-28 is the current protocol path and legacy clients remain supported. "
        "ZapTrace session_id values are application-level handles, not MCP transport sessions; "
        "modern requests do not use Mcp-Session-Id."
    ),
    version=SERVER_VERSION,
)

# ---------------------------------------------------------------------------
# Session management (administrative tools)
# ---------------------------------------------------------------------------


@server.tool(description="Create a new isolated session and return its ID")
def session_create(capabilities: str | None = None) -> dict[str, Any]:
    oauth_denial = _oauth_capability_denial(operation="session_create", required_capability="read")
    if oauth_denial is not None:
        return oauth_denial
    session_id = generate_secure_object_id("mcp")
    principal = _mcp_principal()
    authorize_object(
        object_type="session",
        object_id=session_id,
        principal=principal,
        action="create-session",
        request_id=generate_secure_object_id("mcp-request"),
        allow_claim=True,
    )
    session = _get_session(session_id)  # initialize
    allow_local_grants = get_access_token() is None and environment_flag("ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS")
    if capabilities and allow_local_grants:
        session["capabilities"] = granted_capabilities_from_header(capabilities)
    return _ok({"session_id": session_id, "capabilities": sorted(session.get("capabilities", set()))})


@server.tool(description="Destroy a session and release its resources")
async def session_destroy(session_id: str) -> dict[str, Any]:
    oauth_denial = _oauth_capability_denial(
        operation="session_destroy",
        required_capability="sandbox-write",
    )
    if oauth_denial is not None:
        return oauth_denial
    try:
        authorize_object(
            object_type="session",
            object_id=session_id,
            principal=_mcp_principal(),
            action="destroy-session",
            request_id=generate_secure_object_id("mcp-request"),
        )
    except ObjectAccessDeniedError:
        return _err(_OBJECT_NOT_AUTHORIZED_MESSAGE, code="OBJECT_NOT_AUTHORIZED")

    if session_id not in _sessions:
        from zaptrace.agent.tool_impls.runtime import _get_state_store

        state_store = _get_state_store()
        if state_store is not None and state_store.session_exists(session_id):
            _get_session(session_id)

    async with session_execution_lock(session_id):
        if session_id not in _sessions:
            result = _err(f"Session '{session_id}' not found", code="SESSION_NOT_FOUND")
        else:
            mark_session_destroyed(session_id)
            del _sessions[session_id]
            from zaptrace.review.workflow import remove_review_sessions_for_design_session
            from zaptrace.security.replay import remove_replay
            from zaptrace.security.sandbox import remove_sandbox

            remove_sandbox(session_id)
            remove_replay(session_id)
            removed_reviews = remove_review_sessions_for_design_session(session_id)
            remove_object_access("session", session_id)
            from zaptrace.agent.tool_impls.runtime import _delete_persistent_session

            _delete_persistent_session(session_id)
            result = _ok(
                {
                    "message": f"Session '{session_id}' destroyed",
                    "removed_review_sessions": removed_reviews,
                }
            )
    return result


@server.tool(description="List all active sessions and their design counts")
def session_list() -> dict[str, Any]:
    oauth_denial = _oauth_capability_denial(operation="session_list", required_capability="read")
    if oauth_denial is not None:
        return oauth_denial
    result = []
    principal = _mcp_principal()
    for sid, session_data in _sessions.items():
        access = get_object_access("session", sid)
        if access is None or not (
            principal.is_admin
            or principal.principal_id == access.owner_principal
            or principal.principal_id in access.delegates
        ):
            continue
        designs = session_data.get("designs", {})
        result.append(
            {
                "session_id": sid,
                "design_count": len(designs),
            }
        )
    return _ok({"sessions": result})


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@server.resource("zaptrace://designs")
def list_designs() -> list[dict[str, Any]] | dict[str, Any]:
    """List all designs in the current MCP session."""
    oauth_denial = _oauth_capability_denial(operation="resource:list_designs", required_capability="read")
    if oauth_denial is not None:
        return oauth_denial
    try:
        _authorize_mcp_session_object(_DEFAULT_SESSION_ID, action="resource:list-designs")
        return _list_session_designs(_DEFAULT_SESSION_ID)
    except ObjectAccessDeniedError:
        return _err(_OBJECT_NOT_AUTHORIZED_MESSAGE, code="OBJECT_NOT_AUTHORIZED")
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


@server.resource("zaptrace://library/categories")
def library_categories() -> dict[str, Any]:
    """List component library categories."""
    oauth_denial = _oauth_capability_denial(operation="resource:library_categories", required_capability="read")
    if oauth_denial is not None:
        return oauth_denial
    try:
        from zaptrace.agent._tool_impls import tool_library_list_categories

        return _ok(tool_library_list_categories())
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


@server.resource("zaptrace://templates")
def synthesis_templates() -> dict[str, Any]:
    """List available synthesis templates."""
    oauth_denial = _oauth_capability_denial(operation="resource:synthesis_templates", required_capability="read")
    if oauth_denial is not None:
        return oauth_denial
    try:
        from zaptrace.agent._tool_impls import tool_list_synthesis_templates

        return _ok({"templates": tool_list_synthesis_templates()})
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


@server.resource("zaptrace://proof/result")
def last_proof_result() -> dict[str, Any]:
    """Show the last proof pack run result (if available)."""
    oauth_denial = _oauth_capability_denial(operation="resource:last_proof_result", required_capability="read")
    if oauth_denial is not None:
        return oauth_denial
    try:
        _authorize_mcp_session_object(_DEFAULT_SESSION_ID, action="resource:last-proof-result")
        from zaptrace.agent._tool_impls import _get_session as _gs

        session = _gs(_DEFAULT_SESSION_ID)
        result = session.get("_last_proof_result")
        if result is None:
            return _ok({"message": "No proof pack has been run in this session"})
        return _ok(result)
    except ObjectAccessDeniedError:
        return _err(_OBJECT_NOT_AUTHORIZED_MESSAGE, code="OBJECT_NOT_AUTHORIZED")
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


@server.resource("zaptrace://audit/events")
def audit_events() -> dict[str, Any]:
    """List recent audit events for the default MCP session."""
    oauth_denial = _oauth_capability_denial(operation="resource:audit_events", required_capability="read")
    if oauth_denial is not None:
        return oauth_denial
    try:
        _authorize_mcp_session_object(_DEFAULT_SESSION_ID, action="resource:audit-events")
        session = _get_session(_DEFAULT_SESSION_ID)
        events = list(session.get("audit_events", []))
        direct_object_events = object_authorization_events(
            object_type="session",
            object_id=_DEFAULT_SESSION_ID,
            limit=50,
        )
        child_object_events = object_authorization_events(
            parent_object_type="session",
            parent_object_id=_DEFAULT_SESSION_ID,
            limit=50,
        )
        object_events = sorted(
            [*direct_object_events, *child_object_events],
            key=lambda event: str(event["timestamp"]),
        )[-50:]
        return _ok(
            {
                "session_id": _DEFAULT_SESSION_ID,
                "count": len(events),
                "events": events[-50:],
                "object_authorization_count": len(object_events),
                "object_authorization_events": object_events,
            }
        )
    except ObjectAccessDeniedError:
        return _err(_OBJECT_NOT_AUTHORIZED_MESSAGE, code="OBJECT_NOT_AUTHORIZED")
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


@server.resource("zaptrace://snapshots")
def design_snapshots() -> dict[str, Any]:
    """List available snapshots for all designs."""
    oauth_denial = _oauth_capability_denial(operation="resource:design_snapshots", required_capability="read")
    if oauth_denial is not None:
        return oauth_denial
    try:
        _authorize_mcp_session_object(_DEFAULT_SESSION_ID, action="resource:snapshots")
        session = _get_session(_DEFAULT_SESSION_ID)
        all_snaps = session.get("snapshots", {})
        result = {}
        for dname, snaps in all_snaps.items():
            result[dname] = list(snaps.keys())
        return _ok({"snapshots_by_design": result})
    except ObjectAccessDeniedError:
        return _err(_OBJECT_NOT_AUTHORIZED_MESSAGE, code="OBJECT_NOT_AUTHORIZED")
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


@server.resource("zaptrace://erc/rules")
def erc_rules() -> dict[str, Any]:
    """List all registered ERC rules."""
    oauth_denial = _oauth_capability_denial(operation="resource:erc_rules", required_capability="read")
    if oauth_denial is not None:
        return oauth_denial
    try:
        from zaptrace.agent._tool_impls import tool_erc_list_rules

        rules = tool_erc_list_rules()
        return _ok(rules if isinstance(rules, dict) else {"rules": rules})
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


# ---------------------------------------------------------------------------
# Register all tools from TOOL_REGISTRY
# ---------------------------------------------------------------------------


def _register_tools() -> None:
    """Register all tools with sandboxed wrappers."""
    for tool_name, tool_def in TOOL_REGISTRY.items():
        wrapped = _make_sandboxed_tool(tool_name, tool_def)
        server.tool(
            name=tool_name,
            description=tool_def["description"],
        )(wrapped)


_register_tools()

# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def run() -> None:
    """Run the MCP server on stdio (for `zaptrace-mcp` CLI entry point)."""
    server.run()


def run_http(host: str | None = None, port: int | None = None) -> None:
    """Run the MCP server over HTTP with secure network defaults."""
    host, port = resolve_network_bind(
        surface="ZapTrace MCP HTTP",
        host=host,
        port=port,
        host_env="ZAPTRACE_MCP_HTTP_HOST",
        port_env="ZAPTRACE_MCP_HTTP_PORT",
        default_host="127.0.0.1",
        default_port=8090,
    )
    auth_configuration = resolve_mcp_http_auth_configuration(host=host)
    app = (
        create_oauth_http_app(auth_configuration)
        if auth_configuration.profile == "oauth-jwt"
        else create_http_app(auth_configuration.static_token)
    )

    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
