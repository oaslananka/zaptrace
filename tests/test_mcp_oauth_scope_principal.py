from __future__ import annotations

import json
import re

import pytest
from fastmcp.server.auth import AccessToken, RemoteAuthProvider, TokenVerifier
from pydantic import AnyHttpUrl
from starlette.testclient import TestClient

import zaptrace.mcp.oauth_provider as oauth_provider
import zaptrace.mcp.server as mcp_server
from zaptrace.agent._tool_impls import _sessions
from zaptrace.mcp.auth_config import resolve_mcp_http_auth_configuration
from zaptrace.mcp.oauth_provider import (
    authorize_oauth_capability,
    oauth_capabilities_from_scopes,
    oauth_principal_from_access_token,
)
from zaptrace.security.objects import (
    get_object_access,
    object_authorization_events,
    remove_object_access,
    reset_object_authorization_state,
)


def _token(
    *scopes: str,
    issuer: str = "https://auth.example.com/",
    subject: str = "subject-a",
    client_id: str = "client-a",
) -> AccessToken:
    return AccessToken(
        token="raw-token-must-not-be-stored",
        client_id=client_id,
        scopes=list(scopes),
        claims={"iss": issuer, "sub": subject},
    )


def test_oauth_scope_mapping_is_exact_and_unknown_scopes_grant_nothing() -> None:
    capabilities = oauth_capabilities_from_scopes(
        [
            "zaptrace:read",
            "zaptrace:preview-write",
            "zaptrace:sandbox-write",
            "zaptrace:approved-commit",
            "zaptrace:release-export",
            "zaptrace:read:extra",
            "read",
            "object-admin",
        ]
    )

    assert capabilities == {
        "read",
        "preview-write",
        "sandbox-write",
        "approved-commit",
        "release-export",
    }


def test_oauth_scope_authorization_uses_existing_capability_ladder() -> None:
    allowed_read, _, read_scope = authorize_oauth_capability("read", ["zaptrace:release-export"])
    allowed_preview, _, preview_scope = authorize_oauth_capability("preview-write", ["zaptrace:sandbox-write"])
    denied, reason, required_scope = authorize_oauth_capability("sandbox-write", ["zaptrace:read", "untrusted:admin"])

    assert allowed_read is True
    assert read_scope == "zaptrace:read"
    assert allowed_preview is True
    assert preview_scope == "zaptrace:preview-write"
    assert denied is False
    assert required_scope == "zaptrace:sandbox-write"
    assert "zaptrace:sandbox-write" in reason


def test_oauth_read_requires_at_least_one_recognized_scope() -> None:
    allowed, reason, required_scope = authorize_oauth_capability("read", ["profile", "unknown"])

    assert allowed is False
    assert required_scope == "zaptrace:read"
    assert "zaptrace:read" in reason


def test_oauth_principal_is_stable_pair_bound_and_redacted() -> None:
    first = oauth_principal_from_access_token(_token("zaptrace:read"))
    same = oauth_principal_from_access_token(_token("zaptrace:release-export", client_id="different-client"))
    different_subject = oauth_principal_from_access_token(_token("zaptrace:read", subject="subject-b"))
    different_issuer = oauth_principal_from_access_token(_token("zaptrace:read", issuer="https://other.example.com/"))

    assert first.principal_id == same.principal_id
    assert first.principal_id != different_subject.principal_id
    assert first.principal_id != different_issuer.principal_id
    assert first.actor == first.principal_id
    assert first.authenticated is True
    assert first.local_development is False
    assert first.scopes == frozenset({"read"})
    assert re.fullmatch(r"oauth:[0-9a-f]{64}", first.principal_id)
    for secret_or_identity in (
        "raw-token-must-not-be-stored",
        "subject-a",
        "https://auth.example.com/",
        "client-a",
    ):
        assert secret_or_identity not in first.principal_id
        assert secret_or_identity not in first.actor


@pytest.mark.parametrize(
    ("issuer", "subject"),
    [
        ("", "subject-a"),
        ("https://auth.example.com/", ""),
    ],
)
def test_oauth_principal_requires_validated_issuer_and_subject(
    issuer: str,
    subject: str,
) -> None:
    token = _token("zaptrace:read", issuer=issuer, subject=subject)

    with pytest.raises(RuntimeError, match="issuer|subject"):
        oauth_principal_from_access_token(token)


def test_server_uses_validated_oauth_context_instead_of_env_or_session_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "oauth-scope-isolation"
    _sessions[session_id] = {"designs": {}, "capabilities": {"release-export"}}
    monkeypatch.setenv("ZAPTRACE_MCP_CAPABILITIES", "release-export")
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: _token("zaptrace:read"))

    try:
        principal = mcp_server._mcp_principal()
        capabilities = mcp_server._session_capabilities(session_id)
    finally:
        _sessions.pop(session_id, None)

    assert principal.authenticated is True
    assert principal.scopes == frozenset({"read"})
    assert capabilities == {"read"}


async def test_oauth_scope_denial_happens_before_object_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_object_authorization_state()
    session_id = "oauth-insufficient-scope"
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: _token("zaptrace:read"))

    def _should_not_run(session_id: str) -> dict[str, bool]:
        return {"called": True}

    wrapped = mcp_server._make_sandboxed_tool(
        "oauth-sandbox-probe",
        {
            "fn": _should_not_run,
            "params": {"session_id": {"type": "string"}},
            "capability": "sandbox-write",
        },
    )
    result = await wrapped(session_id=session_id)

    assert result["ok"] is False
    assert result["error"]["code"] == "OPERATION_NOT_AUTHORIZED"
    assert result["error"]["details"]["required_scope"] == "zaptrace:sandbox-write"
    assert session_id not in _sessions
    assert get_object_access("session", session_id) is None


def test_oauth_session_create_requires_recognized_read_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_object_authorization_state()
    existing = set(_sessions)
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: _token("profile"))

    result = mcp_server.session_create()

    assert result["ok"] is False
    assert result["error"]["code"] == "OPERATION_NOT_AUTHORIZED"
    assert result["error"]["details"]["required_scope"] == "zaptrace:read"
    assert set(_sessions) == existing


def test_oauth_session_create_claims_session_for_pair_bound_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zaptrace.security.objects import remove_object_access

    reset_object_authorization_state()
    token = _token("zaptrace:read")
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: token)
    monkeypatch.setenv("ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS", "true")

    result = mcp_server.session_create(capabilities="release-export")
    session_id = result["data"]["session_id"]
    access = get_object_access("session", session_id)

    try:
        assert result["ok"] is True
        assert result["data"]["capabilities"] == []
        assert access is not None
        assert access.owner_principal == oauth_principal_from_access_token(token).principal_id
    finally:
        _sessions.pop(session_id, None)
        remove_object_access("session", session_id)


def test_oauth_session_destroy_requires_sandbox_write_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zaptrace.security.objects import remove_object_access

    reset_object_authorization_state()
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: _token("zaptrace:read"))
    created = mcp_server.session_create()
    session_id = created["data"]["session_id"]

    try:
        denied = __import__("asyncio").run(mcp_server.session_destroy(session_id))
        assert denied["ok"] is False
        assert denied["error"]["code"] == "OPERATION_NOT_AUTHORIZED"
        assert denied["error"]["details"]["required_scope"] == "zaptrace:sandbox-write"
        assert session_id in _sessions
    finally:
        _sessions.pop(session_id, None)
        remove_object_access("session", session_id)


def test_oauth_read_resource_requires_recognized_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: _token("profile"))

    result = mcp_server.library_categories()

    assert result["ok"] is False
    assert result["error"]["code"] == "OPERATION_NOT_AUTHORIZED"
    assert result["error"]["details"]["required_scope"] == "zaptrace:read"


class _RequestVerifier(TokenVerifier):
    def __init__(self, scopes: list[str], *, subject: str = "subject-request") -> None:
        super().__init__()
        self.scopes = scopes
        self.subject = subject

    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(
            token=token,
            client_id="client-request",
            scopes=self.scopes,
            claims={"iss": "https://auth.example.com/", "sub": self.subject},
        )


def _oauth_configuration():
    return resolve_mcp_http_auth_configuration(
        host="0.0.0.0",
        environ={
            "ZAPTRACE_MCP_AUTH_CONFIG_VERSION": "1",
            "ZAPTRACE_MCP_AUTH_PROFILE": "oauth-jwt",
            "ZAPTRACE_MCP_PUBLIC_BASE_URL": "https://mcp.example.com",
            "ZAPTRACE_MCP_AUTH_RESOURCE_URI": "https://mcp.example.com/mcp",
            "ZAPTRACE_MCP_AUTHORIZATION_SERVER": "https://auth.example.com/",
            "ZAPTRACE_MCP_AUTH_JWKS_URI": "https://auth.example.com/.well-known/jwks.json",
        },
    )


def _sse_message(response) -> dict:
    for line in response.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line.removeprefix("data: "))
    raise AssertionError(f"missing SSE data message: {response.text[:200]!r}")


def test_bounded_oauth_request_context_creates_pair_owned_read_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_object_authorization_state()
    verifier = _RequestVerifier(["zaptrace:read"])
    provider = RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[AnyHttpUrl("https://auth.example.com/")],
        base_url="https://mcp.example.com",
        resource_base_url="https://mcp.example.com",
        scopes_supported=["zaptrace:read"],
        resource_name="ZapTrace MCP",
    )
    monkeypatch.setattr(mcp_server, "build_mcp_oauth_provider", lambda _config: provider)
    app = mcp_server.create_oauth_http_app(_oauth_configuration())
    headers = {
        "Authorization": "Bearer request-context-token",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    with TestClient(app) as client:
        initialized = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "slice3-context", "version": "1"},
                },
            },
        )
        transport_session = initialized.headers["mcp-session-id"]
        request_headers = {**headers, "mcp-session-id": transport_session}
        acknowledged = client.post(
            "/mcp",
            headers=request_headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        called = client.post(
            "/mcp",
            headers=request_headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "session_create", "arguments": {}},
            },
        )

    payload = _sse_message(called)
    structured = payload["result"]["structuredContent"]
    session_id = structured["data"]["session_id"]
    access = get_object_access("session", session_id)
    expected_principal = oauth_principal_from_access_token(
        AccessToken(
            token="different-token-value",
            client_id="different-client",
            scopes=["zaptrace:read"],
            claims={"iss": "https://auth.example.com/", "sub": "subject-request"},
        )
    )

    try:
        assert initialized.status_code == 200
        assert acknowledged.status_code == 202
        assert called.status_code == 200
        assert structured["ok"] is True
        assert structured["data"]["capabilities"] == []
        assert access is not None
        assert access.owner_principal == expected_principal.principal_id
        assert "request-context-token" not in called.text
        assert "subject-request" not in access.owner_principal
    finally:
        _sessions.pop(session_id, None)
        remove_object_access("session", session_id)


def test_oauth_authorization_rejects_unknown_required_capability() -> None:
    allowed, reason, required_scope = authorize_oauth_capability(
        "not-a-zaptrace-capability",
        ["zaptrace:read"],
    )

    assert allowed is False
    assert required_scope == ""
    assert reason == "unknown required capability: not-a-zaptrace-capability"


def test_oauth_capability_denial_rejects_incomplete_validated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = AccessToken(
        token="incomplete-identity-token",
        client_id="client-a",
        scopes=["zaptrace:read"],
        claims={"iss": "https://auth.example.com/"},
    )
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: incomplete)

    result = mcp_server._oauth_capability_denial(
        operation="identity-probe",
        required_capability="read",
    )

    assert result is not None
    assert result["ok"] is False
    assert result["error"]["code"] == "AUTH_INVALID_TOKEN"
    assert result["error"]["message"] == "Validated OAuth identity is incomplete"
    assert result["error"]["details"] == {"operation": "identity-probe"}
    assert "incomplete-identity-token" not in str(result)


def test_oauth_session_list_denies_token_without_recognized_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: _token("profile"))

    result = mcp_server.session_list()

    assert result["ok"] is False
    assert result["error"]["code"] == "OPERATION_NOT_AUTHORIZED"
    assert result["error"]["details"]["required_scope"] == "zaptrace:read"


@pytest.mark.parametrize(
    "resource",
    [
        mcp_server.list_designs,
        mcp_server.synthesis_templates,
        mcp_server.last_proof_result,
        mcp_server.audit_events,
        mcp_server.design_snapshots,
        mcp_server.erc_rules,
    ],
)
def test_oauth_read_resources_deny_token_without_recognized_scope(
    monkeypatch: pytest.MonkeyPatch,
    resource,
) -> None:
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: _token("profile"))

    result = resource()

    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["error"]["code"] == "OPERATION_NOT_AUTHORIZED"
    assert result["error"]["details"]["required_scope"] == "zaptrace:read"


class _TokenMapVerifier(TokenVerifier):
    def __init__(self) -> None:
        super().__init__()
        self._profiles = {
            "read-only-token": (["zaptrace:read"], "subject-read-only"),
            "sandbox-owner-token": (["zaptrace:sandbox-write"], "subject-owner"),
            "sandbox-other-token": (["zaptrace:sandbox-write"], "subject-other"),
        }

    async def verify_token(self, token: str) -> AccessToken | None:
        profile = self._profiles.get(token)
        if profile is None:
            return None
        scopes, subject = profile
        return AccessToken(
            token=token,
            client_id="client-request",
            scopes=scopes,
            claims={"iss": "https://auth.example.com/", "sub": subject},
        )


def _mapped_oauth_app(monkeypatch: pytest.MonkeyPatch):
    provider = RemoteAuthProvider(
        token_verifier=_TokenMapVerifier(),
        authorization_servers=[AnyHttpUrl("https://auth.example.com/")],
        base_url="https://mcp.example.com",
        resource_base_url="https://mcp.example.com",
        scopes_supported=[
            "zaptrace:read",
            "zaptrace:preview-write",
            "zaptrace:sandbox-write",
            "zaptrace:approved-commit",
            "zaptrace:release-export",
        ],
        resource_name="ZapTrace MCP",
    )
    monkeypatch.setattr(mcp_server, "build_mcp_oauth_provider", lambda _config: provider)
    return mcp_server.create_oauth_http_app(_oauth_configuration())


def _oauth_headers(token: str, transport_session: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if transport_session is not None:
        headers["mcp-session-id"] = transport_session
    return headers


def _initialize_transport(client: TestClient, token: str, request_id: int) -> str:
    initialized = client.post(
        "/mcp",
        headers=_oauth_headers(token),
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "slice4-test", "version": "1"},
            },
        },
    )
    assert initialized.status_code == 200
    transport_session = initialized.headers["mcp-session-id"]
    acknowledged = client.post(
        "/mcp",
        headers=_oauth_headers(token, transport_session),
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert acknowledged.status_code == 202
    return transport_session


def test_oauth_http_insufficient_scope_is_transport_403_before_tool_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_object_authorization_state()
    app = _mapped_oauth_app(monkeypatch)

    with TestClient(app) as client:
        transport_session = _initialize_transport(client, "read-only-token", 10)
        response = client.post(
            "/mcp",
            headers=_oauth_headers("read-only-token", transport_session),
            json={
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "erc_validate",
                    "arguments": {"session_id": "must-not-be-claimed", "design_name": "probe"},
                },
            },
        )

    assert response.status_code == 403
    assert response.json() == {
        "ok": False,
        "error": {
            "code": "OPERATION_NOT_AUTHORIZED",
            "message": "missing required OAuth scope: zaptrace:sandbox-write",
            "details": {
                "operation": "erc_validate",
                "required_capability": "sandbox-write",
                "required_scope": "zaptrace:sandbox-write",
            },
        },
    }
    challenge = response.headers["www-authenticate"]
    assert 'error="insufficient_scope"' in challenge
    assert 'scope="zaptrace:sandbox-write"' in challenge
    assert 'resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"' in challenge
    assert "read-only-token" not in response.text
    assert get_object_access("session", "must-not-be-claimed") is None


def test_oauth_transport_does_not_cache_authorization_between_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _mapped_oauth_app(monkeypatch)

    with TestClient(app) as client:
        transport_session = _initialize_transport(client, "read-only-token", 20)
        response = client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": transport_session,
            },
            json={"jsonrpc": "2.0", "id": 21, "method": "tools/list"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_oauth_cross_principal_object_denial_stays_mcp_structured_and_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_object_authorization_state()
    app = _mapped_oauth_app(monkeypatch)
    created_session_id = ""

    with TestClient(app) as client:
        owner_transport = _initialize_transport(client, "sandbox-owner-token", 30)
        created = client.post(
            "/mcp",
            headers=_oauth_headers("sandbox-owner-token", owner_transport),
            json={
                "jsonrpc": "2.0",
                "id": 31,
                "method": "tools/call",
                "params": {"name": "session_create", "arguments": {}},
            },
        )
        created_payload = _sse_message(created)
        created_structured = created_payload["result"]["structuredContent"]
        assert created_structured["ok"] is True
        created_session_id = created_structured["data"]["session_id"]

        other_transport = _initialize_transport(client, "sandbox-other-token", 32)
        denied = client.post(
            "/mcp",
            headers=_oauth_headers("sandbox-other-token", other_transport),
            json={
                "jsonrpc": "2.0",
                "id": 33,
                "method": "tools/call",
                "params": {
                    "name": "design_inspect",
                    "arguments": {"session_id": created_session_id, "design_name": "probe"},
                },
            },
        )

    try:
        assert denied.status_code == 200
        denied_payload = _sse_message(denied)
        structured = denied_payload["result"]["structuredContent"]
        assert structured["ok"] is False
        assert structured["error"]["code"] == "OBJECT_NOT_AUTHORIZED"

        other_principal = oauth_principal_from_access_token(
            AccessToken(
                token="different-token-value",
                client_id="ignored-client",
                scopes=["zaptrace:sandbox-write"],
                claims={"iss": "https://auth.example.com/", "sub": "subject-other"},
            )
        )
        events = object_authorization_events(
            object_type="session",
            object_id=created_session_id,
            principal_id=other_principal.principal_id,
        )
        assert any(event["decision"] == "deny" for event in events)
        evidence = repr(events) + denied.text
        for sensitive in (
            "sandbox-owner-token",
            "sandbox-other-token",
            "subject-owner",
            "subject-other",
        ):
            assert sensitive not in evidence
    finally:
        if created_session_id:
            _sessions.pop(created_session_id, None)
            remove_object_access("session", created_session_id)


async def test_oauth_mutating_audit_uses_redacted_authenticated_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from zaptrace.agent._tool_impls import TOOL_REGISTRY

    reset_object_authorization_state()
    token = _token("zaptrace:preview-write")
    expected_principal = oauth_principal_from_access_token(token)
    session_id = "oauth-audit-session"
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: token)

    async def fake_execute_mutating_tool(**_kwargs):
        return SimpleNamespace(status="completed", result={"audit_probe": True})

    monkeypatch.setattr(mcp_server, "execute_mutating_tool", fake_execute_mutating_tool)
    wrapped = mcp_server._make_sandboxed_tool("design_parse_str", TOOL_REGISTRY["design_parse_str"])

    try:
        result = await wrapped(session_id=session_id, yaml_content="meta:\n  name: AuditProbe\n")
        event = _sessions[session_id]["audit_events"][-1]

        assert result["ok"] is True
        assert event["actor"] == expected_principal.principal_id
        assert event["metadata"]["principal_id"] == expected_principal.principal_id
        assert event["metadata"]["auth_source"] == "oauth-jwt"
        assert event["metadata"]["authenticated"] is True
        evidence = repr(event)
        for sensitive in (
            token.token,
            "subject-a",
            "https://auth.example.com/",
            token.client_id,
        ):
            assert sensitive not in evidence
    finally:
        _sessions.pop(session_id, None)
        remove_object_access("session", session_id)


def test_oauth_request_requirements_treat_non_mapping_batch_items_as_read() -> None:
    requirements = oauth_provider._request_requirements(
        [None, {"method": "tools/list"}],
        lambda _tool_name: None,
    )

    assert requirements == [("mcp-request", "read"), ("tools/list", "read")]


async def test_oauth_capture_json_payload_skips_non_http_messages_and_replays_malformed_body() -> None:
    messages = iter(
        [
            {"type": "websocket.connect"},
            {"type": "http.request", "body": b"{", "more_body": False},
            {"type": "http.disconnect"},
        ]
    )

    async def receive():
        return next(messages)

    payload, replay = await oauth_provider._capture_json_payload(receive)

    assert payload is None
    assert (await replay())["type"] == "websocket.connect"
    assert (await replay())["type"] == "http.request"
    assert (await replay())["type"] == "http.disconnect"


async def test_oauth_capture_json_payload_handles_disconnect_before_request_body() -> None:
    messages = iter([{"type": "http.disconnect"}, {"type": "http.disconnect"}])

    async def receive():
        return next(messages)

    payload, replay = await oauth_provider._capture_json_payload(receive)

    assert payload is None
    assert (await replay())["type"] == "http.disconnect"


def test_oauth_authorization_rejects_validated_token_without_pair_bound_subject() -> None:
    from types import SimpleNamespace

    token = AccessToken(
        token="missing-sub-token-must-not-leak",
        client_id="client-missing-sub",
        scopes=["zaptrace:read"],
        claims={"iss": "https://auth.example.com/"},
    )
    scope = {"user": SimpleNamespace(access_token=token)}

    response = oauth_provider._oauth_authorization_response(
        scope=scope,
        payload={"jsonrpc": "2.0", "id": 90, "method": "tools/list"},
        tool_capability_resolver=lambda _tool_name: None,
        resource_metadata_url="https://mcp.example.com/.well-known/oauth-protected-resource/mcp",
    )

    assert response is not None
    assert response.status_code == 401
    payload = json.loads(response.body)
    assert payload["error"]["code"] == "AUTH_INVALID_TOKEN"
    assert token.token not in response.body.decode()
