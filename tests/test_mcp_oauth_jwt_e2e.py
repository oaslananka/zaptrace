from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Mapping

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from starlette.testclient import TestClient

import zaptrace.mcp.server as mcp_server
from zaptrace.agent._tool_impls import _sessions
from zaptrace.mcp.auth_config import MCPHTTPAuthConfiguration, resolve_mcp_http_auth_configuration
from zaptrace.mcp.oauth_provider import build_mcp_oauth_provider
from zaptrace.security.objects import remove_object_access, reset_object_authorization_state

_ISSUER = "https://auth.example.com/"
_RESOURCE = "https://mcp.example.com/mcp"
_JWKS_URI = "https://auth.example.com/.well-known/jwks.json"
_KID = "ephemeral-test-key"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _uint_b64url(value: int) -> str:
    return _b64url(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def _unsupported_algorithm_jwt(claims: Mapping[str, object], algorithm: str) -> str:
    header = {"alg": algorithm, "kid": _KID, "typ": "JWT"}
    encoded_header = _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    encoded_claims = _b64url(json.dumps(dict(claims), separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    if algorithm == "none":
        signature = ""
    elif algorithm == "HS256":
        signature = _b64url(hmac.new(b"ephemeral-test-hmac", signing_input, hashlib.sha256).digest())
    else:
        raise AssertionError(f"unsupported test algorithm: {algorithm}")
    return f"{encoded_header}.{encoded_claims}.{signature}"


def _jwt(private_key: rsa.RSAPrivateKey, claims: Mapping[str, object], *, kid: str = _KID) -> str:
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    encoded_header = _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    encoded_claims = _b64url(json.dumps(dict(claims), separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{encoded_header}.{encoded_claims}.{_b64url(signature)}"


def _jwks(private_key: rsa.RSAPrivateKey) -> dict[str, object]:
    numbers = private_key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": _KID,
                "n": _uint_b64url(numbers.n),
                "e": _uint_b64url(numbers.e),
            }
        ]
    }


def _configuration() -> MCPHTTPAuthConfiguration:
    return resolve_mcp_http_auth_configuration(
        host="0.0.0.0",
        environ={
            "ZAPTRACE_MCP_AUTH_CONFIG_VERSION": "1",
            "ZAPTRACE_MCP_AUTH_PROFILE": "oauth-jwt",
            "ZAPTRACE_MCP_PUBLIC_BASE_URL": "https://mcp.example.com",
            "ZAPTRACE_MCP_AUTH_RESOURCE_URI": _RESOURCE,
            "ZAPTRACE_MCP_AUTHORIZATION_SERVER": _ISSUER,
            "ZAPTRACE_MCP_AUTH_JWKS_URI": _JWKS_URI,
        },
    )


def _claims(
    *,
    subject: str | None = "subject-a",
    issuer: str = _ISSUER,
    audience: str = _RESOURCE,
    scope: str = "zaptrace:read",
    exp_offset: int = 600,
    nbf_offset: int = -5,
) -> dict[str, object]:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": issuer,
        "aud": audience,
        "scope": scope,
        "iat": now,
        "nbf": now + nbf_offset,
        "exp": now + exp_offset,
    }
    if subject is not None:
        claims["sub"] = subject
    return claims


def _real_provider(
    monkeypatch: pytest.MonkeyPatch,
    private_key: rsa.RSAPrivateKey,
) -> RemoteAuthProvider:
    provider = build_mcp_oauth_provider(_configuration())
    verifier = provider.token_verifier
    assert isinstance(verifier, JWTVerifier)

    async def fetch_jwks() -> dict[str, object]:
        return _jwks(private_key)

    monkeypatch.setattr(verifier, "_fetch_jwks", fetch_jwks)
    return provider


def _real_app(monkeypatch: pytest.MonkeyPatch, private_key: rsa.RSAPrivateKey):
    provider = _real_provider(monkeypatch, private_key)
    monkeypatch.setattr(mcp_server, "build_mcp_oauth_provider", lambda _configuration: provider)
    return mcp_server.create_oauth_http_app(_configuration())


def _headers(token: str | None = None, session_id: str | None = None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    return headers


def _initialize_payload(request_id: int) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "oauth-rs256-e2e", "version": "1"},
        },
    }


def _initialize(client: TestClient, token: str, request_id: int) -> str:
    response = client.post("/mcp", headers=_headers(token), json=_initialize_payload(request_id))
    assert response.status_code == 200
    session_id = response.headers["mcp-session-id"]
    acknowledged = client.post(
        "/mcp",
        headers=_headers(token, session_id),
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert acknowledged.status_code == 202
    return session_id


def _sse_message(response) -> dict[str, object]:
    for line in response.text.splitlines():
        if line.startswith("data:"):
            payload = json.loads(line.removeprefix("data:").strip())
            if isinstance(payload, dict):
                return payload
    raise AssertionError(f"response did not contain an SSE JSON message: {response.text!r}")


@pytest.fixture
def rsa_keys() -> tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey]:
    return (
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
    )


@pytest.mark.asyncio
async def test_real_rs256_verifier_accepts_token_without_optional_not_before(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_keys
    provider = _real_provider(monkeypatch, private_key)
    verifier = provider.token_verifier
    claims = _claims(subject="no-not-before-subject")
    claims.pop("nbf")
    token = _jwt(private_key, claims)

    access_token = await verifier.verify_token(token)

    assert access_token is not None
    assert access_token.claims["sub"] == "no-not-before-subject"


@pytest.mark.asyncio
async def test_real_rs256_verifier_rejects_not_yet_valid_token(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_keys
    provider = _real_provider(monkeypatch, private_key)
    verifier = provider.token_verifier
    token = _jwt(private_key, _claims(subject="future-subject", nbf_offset=300))

    assert await verifier.verify_token(token) is None


def test_real_rs256_valid_token_initializes_mcp_without_token_leak(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_keys
    token = _jwt(private_key, _claims())
    app = _real_app(monkeypatch, private_key)

    with TestClient(app) as client:
        response = client.post("/mcp", headers=_headers(token), json=_initialize_payload(1))

    assert response.status_code == 200
    assert token not in response.text
    assert response.headers.get("mcp-session-id")


@pytest.mark.parametrize(
    "case",
    [
        "malformed-jwt",
        "alg-none",
        "symmetric-hmac",
        "invalid-signature",
        "unknown-kid",
        "expired",
        "missing-expiration",
        "not-yet-valid",
        "invalid-not-before",
        "wrong-issuer",
        "wrong-audience",
        "missing-subject",
    ],
)
def test_real_rs256_negative_credentials_return_stable_401_without_token_leak(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_key, other_key = rsa_keys
    claims = _claims()
    signing_key = private_key
    kid = _KID
    if case == "malformed-jwt":
        token = "malformed-jwt-marker"
    elif case == "alg-none":
        token = _unsupported_algorithm_jwt(claims, "none")
    elif case == "symmetric-hmac":
        token = _unsupported_algorithm_jwt(claims, "HS256")
    else:
        if case == "invalid-signature":
            signing_key = other_key
        elif case == "unknown-kid":
            kid = "unknown-test-key"
        elif case == "expired":
            claims = _claims(exp_offset=-60)
        elif case == "missing-expiration":
            claims.pop("exp")
        elif case == "not-yet-valid":
            claims = _claims(nbf_offset=300)
        elif case == "invalid-not-before":
            claims["nbf"] = "not-a-numeric-date"
        elif case == "wrong-issuer":
            claims = _claims(issuer="https://other-auth.example.com/")
        elif case == "wrong-audience":
            claims = _claims(audience="https://other-service.example.com/mcp")
        elif case == "missing-subject":
            claims = _claims(subject=None)
        token = _jwt(signing_key, claims, kid=kid)

    app = _real_app(monkeypatch, private_key)
    with caplog.at_level(logging.DEBUG), TestClient(app) as client:
        response = client.post("/mcp", headers=_headers(token), json=_initialize_payload(10))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID_TOKEN"
    assert 'error="invalid_token"' in response.headers["www-authenticate"]
    assert token not in response.text
    assert token not in caplog.text


def test_real_rs256_missing_malformed_and_query_credentials_do_not_authorize(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_keys
    token = _jwt(private_key, _claims())
    app = _real_app(monkeypatch, private_key)

    with TestClient(app) as client:
        missing = client.post("/mcp", headers=_headers(), json=_initialize_payload(20))
        malformed = client.post(
            "/mcp",
            headers={**_headers(), "Authorization": f"Basic {token}"},
            json=_initialize_payload(21),
        )
        query = client.post(f"/mcp?access_token={token}", headers=_headers(), json=_initialize_payload(22))

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "AUTH_REQUIRED"
    assert malformed.status_code == 401
    assert malformed.json()["error"]["code"] == "AUTH_INVALID_TOKEN"
    assert query.status_code == 401
    assert query.json()["error"]["code"] == "AUTH_REQUIRED"
    assert token not in missing.text + malformed.text + query.text


def test_real_rs256_unknown_scope_and_client_self_grants_cannot_escalate(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_keys
    unknown_scope_token = _jwt(private_key, _claims(scope="untrusted:admin"))
    read_token = _jwt(private_key, _claims(scope="zaptrace:read"))
    app = _real_app(monkeypatch, private_key)

    with TestClient(app) as client:
        unknown_scope = client.post(
            "/mcp",
            headers=_headers(unknown_scope_token),
            json=_initialize_payload(30),
        )
        session_id = _initialize(client, read_token, 31)
        created = client.post(
            "/mcp",
            headers={**_headers(read_token, session_id), "X-ZapTrace-Capabilities": "release-export"},
            json={
                "jsonrpc": "2.0",
                "id": 32,
                "method": "tools/call",
                "params": {
                    "name": "session_create",
                    "arguments": {"capabilities": "release-export"},
                },
            },
        )
        created_message = _sse_message(created)
        structured = created_message["result"]["structuredContent"]  # type: ignore[index]
        claimed_session_id = structured["data"]["session_id"]  # type: ignore[index]
        denied = client.post(
            "/mcp",
            headers={**_headers(read_token, session_id), "X-ZapTrace-Capabilities": "release-export"},
            json={
                "jsonrpc": "2.0",
                "id": 33,
                "method": "tools/call",
                "params": {
                    "name": "erc_validate",
                    "arguments": {"session_id": claimed_session_id, "design_name": "probe"},
                },
            },
        )

    try:
        assert unknown_scope.status_code == 403
        assert unknown_scope.json()["error"]["details"]["required_scope"] == "zaptrace:read"
        assert structured["ok"] is True  # type: ignore[index]
        assert structured["data"]["capabilities"] == []  # type: ignore[index]
        assert denied.status_code == 403
        assert denied.json()["error"]["details"]["required_scope"] == "zaptrace:sandbox-write"
    finally:
        _sessions.pop(str(claimed_session_id), None)
        remove_object_access("session", str(claimed_session_id))


def test_real_rs256_authorization_is_rechecked_on_later_mcp_request(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    private_key, _ = rsa_keys
    token = _jwt(private_key, _claims())
    app = _real_app(monkeypatch, private_key)

    with TestClient(app) as client:
        session_id = _initialize(client, token, 40)
        later = client.post(
            "/mcp",
            headers=_headers(session_id=session_id),
            json={"jsonrpc": "2.0", "id": 41, "method": "tools/list"},
        )

    assert later.status_code == 401
    assert later.json()["error"]["code"] == "AUTH_REQUIRED"


def test_real_rs256_cross_principal_session_access_remains_object_denied(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    reset_object_authorization_state()
    private_key, _ = rsa_keys
    owner_token = _jwt(private_key, _claims(subject="subject-owner"))
    other_token = _jwt(private_key, _claims(subject="subject-other"))
    app = _real_app(monkeypatch, private_key)
    claimed_session_id = ""

    with TestClient(app) as client:
        owner_transport = _initialize(client, owner_token, 50)
        created = client.post(
            "/mcp",
            headers=_headers(owner_token, owner_transport),
            json={
                "jsonrpc": "2.0",
                "id": 51,
                "method": "tools/call",
                "params": {"name": "session_create", "arguments": {}},
            },
        )
        created_message = _sse_message(created)
        created_structured = created_message["result"]["structuredContent"]  # type: ignore[index]
        claimed_session_id = str(created_structured["data"]["session_id"])  # type: ignore[index]

        other_transport = _initialize(client, other_token, 52)
        denied = client.post(
            "/mcp",
            headers=_headers(other_token, other_transport),
            json={
                "jsonrpc": "2.0",
                "id": 53,
                "method": "tools/call",
                "params": {
                    "name": "design_inspect",
                    "arguments": {"session_id": claimed_session_id, "design_name": "probe"},
                },
            },
        )

    try:
        assert denied.status_code == 200
        denied_message = _sse_message(denied)
        structured = denied_message["result"]["structuredContent"]  # type: ignore[index]
        assert structured["ok"] is False  # type: ignore[index]
        assert structured["error"]["code"] == "OBJECT_NOT_AUTHORIZED"  # type: ignore[index]
        evidence = denied.text
        assert owner_token not in evidence
        assert other_token not in evidence
    finally:
        if claimed_session_id:
            _sessions.pop(claimed_session_id, None)
            remove_object_access("session", claimed_session_id)


def test_real_rs256_bearer_is_not_forwarded_to_mutating_tool_executor(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
) -> None:
    from types import SimpleNamespace

    private_key, _ = rsa_keys
    token = _jwt(private_key, _claims(scope="zaptrace:preview-write"))
    captured: dict[str, object] = {}

    async def fake_execute_mutating_tool(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="completed", result={"parsed": True})

    monkeypatch.setattr(mcp_server, "execute_mutating_tool", fake_execute_mutating_tool)
    app = _real_app(monkeypatch, private_key)
    claimed_session_id = ""

    with TestClient(app) as client:
        transport_session = _initialize(client, token, 60)
        created = client.post(
            "/mcp",
            headers=_headers(token, transport_session),
            json={
                "jsonrpc": "2.0",
                "id": 61,
                "method": "tools/call",
                "params": {"name": "session_create", "arguments": {}},
            },
        )
        created_message = _sse_message(created)
        created_structured = created_message["result"]["structuredContent"]  # type: ignore[index]
        claimed_session_id = str(created_structured["data"]["session_id"])  # type: ignore[index]

        executed = client.post(
            "/mcp",
            headers=_headers(token, transport_session),
            json={
                "jsonrpc": "2.0",
                "id": 62,
                "method": "tools/call",
                "params": {
                    "name": "design_parse_str",
                    "arguments": {
                        "session_id": claimed_session_id,
                        "yaml_content": "meta:\n  name: PassthroughProbe\n",
                    },
                },
            },
        )

    try:
        assert executed.status_code == 200
        assert captured["tool_name"] == "design_parse_str"
        assert token not in repr(captured)
        assert "authorization" not in repr(captured).lower()
        assert "access_token" not in repr(captured).lower()
    finally:
        if claimed_session_id:
            _sessions.pop(claimed_session_id, None)
            remove_object_access("session", claimed_session_id)
