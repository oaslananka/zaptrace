"""Fail-closed FastMCP OAuth/JWT resource-server construction."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Collection
from hashlib import sha256

from fastmcp.server.auth import AccessToken, RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from mcp.server.auth.routes import build_resource_metadata_url
from pydantic import AnyHttpUrl
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from zaptrace.mcp.auth_config import MCPHTTPAuthConfiguration
from zaptrace.security.objects import RequestPrincipal
from zaptrace.security.policy import authorize_capability

MCP_HTTP_PATH = "/mcp"
OAUTH_SUPPORTED_SCOPES = (
    "zaptrace:read",
    "zaptrace:preview-write",
    "zaptrace:sandbox-write",
    "zaptrace:approved-commit",
    "zaptrace:release-export",
)
OAUTH_SCOPE_TO_CAPABILITY = {
    "zaptrace:read": "read",
    "zaptrace:preview-write": "preview-write",
    "zaptrace:sandbox-write": "sandbox-write",
    "zaptrace:approved-commit": "approved-commit",
    "zaptrace:release-export": "release-export",
}
OAUTH_CAPABILITY_TO_SCOPE = {capability: scope for scope, capability in OAUTH_SCOPE_TO_CAPABILITY.items()}
_INITIAL_SCOPE = OAUTH_SUPPORTED_SCOPES[0]


def oauth_capabilities_from_scopes(scopes: Collection[str]) -> set[str]:
    """Map only the contract-approved OAuth scopes to ZapTrace capabilities."""
    return {OAUTH_SCOPE_TO_CAPABILITY[scope] for scope in scopes if scope in OAUTH_SCOPE_TO_CAPABILITY}


def authorize_oauth_capability(
    required_capability: str,
    scopes: Collection[str],
) -> tuple[bool, str, str]:
    """Authorize one capability using validated OAuth scopes only."""
    required_scope = OAUTH_CAPABILITY_TO_SCOPE.get(required_capability, "")
    if not required_scope:
        return False, f"unknown required capability: {required_capability}", ""
    capabilities = oauth_capabilities_from_scopes(scopes)
    if not capabilities:
        return False, f"missing required OAuth scope: {required_scope}", required_scope
    allowed, _ = authorize_capability(required_capability, capabilities)
    if not allowed:
        return False, f"missing required OAuth scope: {required_scope}", required_scope
    return True, f"validated OAuth scope satisfies {required_capability}", required_scope


def oauth_principal_from_access_token(token: AccessToken) -> RequestPrincipal:
    """Derive a redacted stable principal from validated ``(iss, sub)`` claims."""
    issuer = token.claims.get("iss")
    subject = token.claims.get("sub")
    if not isinstance(issuer, str) or not issuer.strip():
        raise RuntimeError("validated OAuth token is missing issuer identity")
    if not isinstance(subject, str) or not subject.strip():
        raise RuntimeError("validated OAuth token is missing subject identity")
    digest = sha256(f"{issuer}\0{subject}".encode()).hexdigest()
    principal_id = f"oauth:{digest}"
    return RequestPrincipal(
        principal_id=principal_id,
        actor=principal_id,
        scopes=frozenset(oauth_capabilities_from_scopes(token.scopes)),
        authenticated=True,
    )


class ZapTraceJWTVerifier(JWTVerifier):
    """FastMCP JWT verifier with the contract-required ``exp`` and ``nbf`` validation."""

    async def verify_token(self, token: str) -> AccessToken | None:
        access_token = await super().verify_token(token)
        if access_token is None:
            return None
        expires_at = access_token.claims.get("exp")
        if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
            self.logger.info("Bearer token rejected: missing or invalid expiration claim")
            return None
        not_before = access_token.claims.get("nbf")
        if not_before is None:
            return access_token
        if isinstance(not_before, bool) or not isinstance(not_before, (int, float)):
            self.logger.info("Bearer token rejected: invalid not-before claim")
            return None
        if not_before > time.time():
            self.logger.info("Bearer token rejected: token is not active yet")
            return None
        return access_token


def _require_oauth_configuration(configuration: MCPHTTPAuthConfiguration) -> tuple[str, str, str, str]:
    if configuration.profile != "oauth-jwt":
        raise RuntimeError("OAuth provider construction requires the oauth-jwt MCP auth profile")
    values = (
        configuration.public_base_url,
        configuration.resource_uri,
        configuration.authorization_server,
        configuration.jwks_uri,
    )
    if any(value is None for value in values):
        raise RuntimeError("oauth-jwt MCP auth profile is missing validated provider configuration")
    public_base_url, resource_uri, authorization_server, jwks_uri = (str(value) for value in values)
    canonical_authorization_server = str(AnyHttpUrl(authorization_server))
    if canonical_authorization_server != authorization_server:
        raise RuntimeError("oauth-jwt authorization server URL must use canonical FastMCP form")
    expected_resource = f"{public_base_url.rstrip('/')}{MCP_HTTP_PATH}"
    if resource_uri != expected_resource:
        raise RuntimeError(
            f"oauth-jwt resource URI must equal the public base URL plus {MCP_HTTP_PATH}; "
            f"expected {expected_resource!r}"
        )
    return public_base_url, resource_uri, authorization_server, jwks_uri


def build_mcp_oauth_provider(configuration: MCPHTTPAuthConfiguration) -> RemoteAuthProvider:
    """Construct the reviewed FastMCP JWT resource-server provider."""
    public_base_url, resource_uri, authorization_server, jwks_uri = _require_oauth_configuration(configuration)
    verifier = ZapTraceJWTVerifier(
        jwks_uri=jwks_uri,
        issuer=authorization_server,
        audience=resource_uri,
        algorithm="RS256",
    )
    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[AnyHttpUrl(authorization_server)],
        base_url=public_base_url,
        resource_base_url=public_base_url,
        scopes_supported=list(OAUTH_SUPPORTED_SCOPES),
        resource_name="ZapTrace MCP",
    )


def oauth_resource_metadata_url(configuration: MCPHTTPAuthConfiguration) -> str:
    """Return the exact RFC 9728 metadata URL advertised by FastMCP."""
    _, resource_uri, _, _ = _require_oauth_configuration(configuration)
    return str(build_resource_metadata_url(AnyHttpUrl(resource_uri)))


def _authorization_header(scope: Scope) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == b"authorization":
            return value.decode("latin-1")
    return ""


def _oauth_error_response(*, missing: bool, resource_metadata_url: str) -> JSONResponse:
    code = "AUTH_REQUIRED" if missing else "AUTH_INVALID_TOKEN"
    message = "Bearer authentication is required" if missing else "Bearer token is invalid"
    parts = [f'resource_metadata="{resource_metadata_url}"', f'scope="{_INITIAL_SCOPE}"']
    if not missing:
        parts.insert(0, 'error="invalid_token"')
    return JSONResponse(
        status_code=401,
        content={"ok": False, "error": {"code": code, "message": message, "details": {}}},
        headers={"WWW-Authenticate": f"Bearer {', '.join(parts)}"},
    )


ToolCapabilityResolver = Callable[[str], str | None]


def _oauth_scope_error_response(
    *,
    operation: str,
    required_capability: str,
    required_scope: str,
    resource_metadata_url: str,
) -> JSONResponse:
    challenge = (
        f'Bearer error="insufficient_scope", scope="{required_scope}", resource_metadata="{resource_metadata_url}"'
    )
    return JSONResponse(
        status_code=403,
        content={
            "ok": False,
            "error": {
                "code": "OPERATION_NOT_AUTHORIZED",
                "message": f"missing required OAuth scope: {required_scope}",
                "details": {
                    "operation": operation,
                    "required_capability": required_capability,
                    "required_scope": required_scope,
                },
            },
        },
        headers={"WWW-Authenticate": challenge},
    )


def _validated_scope_token(scope: Scope) -> AccessToken | None:
    token = getattr(scope.get("user"), "access_token", None)
    return token if isinstance(token, AccessToken) else None


def _request_requirements(
    payload: object | None,
    tool_capability_resolver: ToolCapabilityResolver,
) -> list[tuple[str, str]]:
    messages = payload if isinstance(payload, list) else [payload]
    requirements: list[tuple[str, str]] = []
    for item in messages:
        if not isinstance(item, dict):
            requirements.append(("mcp-request", "read"))
            continue
        method = item.get("method")
        params = item.get("params")
        if method == "tools/call" and isinstance(params, dict):
            tool_name = params.get("name")
            if isinstance(tool_name, str):
                capability = tool_capability_resolver(tool_name)
                if capability is not None:
                    requirements.append((tool_name, capability))
                    continue
        requirements.append((method if isinstance(method, str) else "mcp-request", "read"))
    return requirements or [("mcp-request", "read")]


def _replay_receive(messages: list[Message], receive: Receive) -> Receive:
    index = 0

    async def replay() -> Message:
        nonlocal index
        if index < len(messages):
            message = messages[index]
            index += 1
            return message
        return await receive()

    return replay


async def _capture_json_payload(receive: Receive) -> tuple[object | None, Receive]:
    messages: list[Message] = []
    body_parts: list[bytes] = []
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] == "http.disconnect":
            break
        if message["type"] != "http.request":
            continue
        body_parts.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    try:
        payload = json.loads(b"".join(body_parts)) if body_parts else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    return payload, _replay_receive(messages, receive)


def _oauth_authorization_response(
    *,
    scope: Scope,
    payload: object | None,
    tool_capability_resolver: ToolCapabilityResolver,
    resource_metadata_url: str,
) -> JSONResponse | None:
    token = _validated_scope_token(scope)
    if token is None:
        return None
    try:
        oauth_principal_from_access_token(token)
    except RuntimeError:
        return _oauth_error_response(missing=False, resource_metadata_url=resource_metadata_url)
    for operation, required_capability in _request_requirements(payload, tool_capability_resolver):
        allowed, _, required_scope = authorize_oauth_capability(required_capability, token.scopes)
        if not allowed:
            return _oauth_scope_error_response(
                operation=operation,
                required_capability=required_capability,
                required_scope=required_scope,
                resource_metadata_url=resource_metadata_url,
            )
    return None


class MCPOAuthBoundaryMiddleware:
    """Normalize bearer errors and enforce per-request OAuth scope requirements."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        resource_metadata_url: str,
        tool_capability_resolver: ToolCapabilityResolver,
    ) -> None:
        self.app = app
        self.resource_metadata_url = resource_metadata_url
        self.tool_capability_resolver = tool_capability_resolver

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != MCP_HTTP_PATH:
            await self.app(scope, receive, send)
            return
        payload: object | None = None
        if scope.get("method") == "POST" and _validated_scope_token(scope) is not None:
            payload, receive = await _capture_json_payload(receive)
        denial = _oauth_authorization_response(
            scope=scope,
            payload=payload,
            tool_capability_resolver=self.tool_capability_resolver,
            resource_metadata_url=self.resource_metadata_url,
        )
        if denial is not None:
            await denial(scope, receive, send)
            return
        await self.app(scope, receive, self._normalizing_send(scope, receive, send))

    def _normalizing_send(self, scope: Scope, receive: Receive, send: Send) -> Send:
        replace_response = False

        async def normalize(message: Message) -> None:
            nonlocal replace_response
            if message["type"] == "http.response.start":
                replace_response = int(message.get("status", 0)) == 401
                if not replace_response:
                    await send(message)
                return
            if replace_response and message["type"] == "http.response.body":
                if message.get("more_body", False):
                    return
                response = _oauth_error_response(
                    missing=not bool(_authorization_header(scope)),
                    resource_metadata_url=self.resource_metadata_url,
                )
                await response(scope, receive, send)
                return
            await send(message)

        return normalize
