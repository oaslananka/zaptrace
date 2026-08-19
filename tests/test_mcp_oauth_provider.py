from __future__ import annotations

import logging
from typing import cast

import pytest
from fastmcp.server.auth import RemoteAuthProvider, TokenVerifier
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.jwt import JWTVerifier
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.testclient import TestClient

from zaptrace.mcp.auth_config import MCPHTTPAuthConfiguration, resolve_mcp_http_auth_configuration
from zaptrace.mcp.oauth_provider import (
    OAUTH_SUPPORTED_SCOPES,
    build_mcp_oauth_provider,
)
from zaptrace.mcp.server import create_oauth_http_app


def _configuration(
    *,
    resource_uri: str = "https://mcp.example.com/mcp",
    authorization_server: str = "https://auth.example.com/",
) -> MCPHTTPAuthConfiguration:
    return resolve_mcp_http_auth_configuration(
        host="0.0.0.0",
        environ={
            "ZAPTRACE_MCP_AUTH_CONFIG_VERSION": "1",
            "ZAPTRACE_MCP_AUTH_PROFILE": "oauth-jwt",
            "ZAPTRACE_MCP_PUBLIC_BASE_URL": "https://mcp.example.com",
            "ZAPTRACE_MCP_AUTH_RESOURCE_URI": resource_uri,
            "ZAPTRACE_MCP_AUTHORIZATION_SERVER": authorization_server,
            "ZAPTRACE_MCP_AUTH_JWKS_URI": "https://auth.example.com/.well-known/jwks.json",
        },
    )


def test_remote_provider_binds_exact_jwt_resource_contract() -> None:
    provider = build_mcp_oauth_provider(_configuration())

    assert isinstance(provider, RemoteAuthProvider)
    verifier = provider.token_verifier
    assert isinstance(verifier, JWTVerifier)
    assert verifier.jwks_uri == "https://auth.example.com/.well-known/jwks.json"
    assert verifier.issuer == "https://auth.example.com/"
    assert verifier.audience == "https://mcp.example.com/mcp"
    assert verifier.algorithm == "RS256"
    assert verifier.required_scopes == []
    assert list(provider._scopes_supported or []) == list(OAUTH_SUPPORTED_SCOPES)
    assert [str(item) for item in provider.authorization_servers] == ["https://auth.example.com/"]
    assert str(provider.authorization_servers[0]) == verifier.issuer
    assert str(provider.base_url).rstrip("/") == "https://mcp.example.com"
    assert str(provider.resource_base_url).rstrip("/") == "https://mcp.example.com"


def test_provider_rejects_noncanonical_authorization_server_identity() -> None:
    configuration = _configuration(authorization_server="https://auth.example.com")

    with pytest.raises(RuntimeError, match="authorization server.*canonical"):
        build_mcp_oauth_provider(configuration)


def test_provider_fails_closed_when_resource_uri_does_not_match_mcp_path() -> None:
    configuration = _configuration(resource_uri="https://mcp.example.com/alternate")

    with pytest.raises(RuntimeError, match=r"resource URI.*public base URL.*/mcp"):
        build_mcp_oauth_provider(configuration)


def test_oauth_metadata_and_missing_bearer_challenge_match_contract() -> None:
    app = create_oauth_http_app(_configuration())

    with TestClient(app) as client:
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")
        missing = client.get("/mcp")
        query_only = client.get("/mcp?access_token=must-not-authorize")
        client.cookies.set("access_token", "must-not-authorize")
        cookie_only = client.get("/mcp")
        custom_header_only = client.get("/mcp", headers={"X-Access-Token": "must-not-authorize"})

    assert metadata.status_code == 200
    payload = metadata.json()
    assert payload["resource"] == "https://mcp.example.com/mcp"
    assert payload["authorization_servers"] == ["https://auth.example.com/"]
    assert payload["scopes_supported"] == list(OAUTH_SUPPORTED_SCOPES)
    assert payload["bearer_methods_supported"] == ["header"]
    assert payload["resource_name"] == "ZapTrace MCP"

    for response in (missing, query_only, cookie_only, custom_header_only):
        assert response.status_code == 401
        assert response.json() == {
            "ok": False,
            "error": {
                "code": "AUTH_REQUIRED",
                "message": "Bearer authentication is required",
                "details": {},
            },
        }
        challenge = response.headers["www-authenticate"]
        assert challenge.startswith("Bearer ")
        assert 'resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"' in challenge
        assert 'scope="zaptrace:read"' in challenge
        assert "invalid_token" not in challenge


def test_invalid_bearer_is_redacted_and_uses_stable_invalid_token_contract(caplog: pytest.LogCaptureFixture) -> None:
    marker = "must-never-appear-in-logs-or-response"
    app = create_oauth_http_app(_configuration())

    with caplog.at_level(logging.DEBUG), TestClient(app) as client:
        response = client.get("/mcp", headers={"Authorization": f"Bearer {marker}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID_TOKEN"
    assert response.json()["error"]["message"] == "Bearer token is invalid"
    challenge = response.headers["www-authenticate"]
    assert 'error="invalid_token"' in challenge
    assert 'scope="zaptrace:read"' in challenge
    assert marker not in response.text
    assert marker not in caplog.text


class _AcceptingVerifier(TokenVerifier):
    def __init__(self) -> None:
        super().__init__()

    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(
            token=token,
            client_id="client-test",
            scopes=["zaptrace:read"],
            claims={"iss": "https://auth.example.com/", "sub": "subject-test"},
        )


def test_valid_oauth_token_reaches_bounded_app_after_principal_slice(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = RemoteAuthProvider(
        token_verifier=_AcceptingVerifier(),
        authorization_servers=[AnyHttpUrl("https://auth.example.com/")],
        base_url="https://mcp.example.com",
        resource_base_url="https://mcp.example.com",
        scopes_supported=list(OAUTH_SUPPORTED_SCOPES),
        resource_name="ZapTrace MCP",
    )
    monkeypatch.setattr("zaptrace.mcp.server.build_mcp_oauth_provider", lambda _config: provider)
    app = create_oauth_http_app(_configuration())
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "oauth-slice3-test", "version": "1"},
        },
    }
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer [REDACTED]",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json=payload,
        )
    assert response.status_code == 200
    assert "AUTHORIZATION_PROFILE_INCOMPLETE" not in response.text
    assert "valid-test-token" not in response.text


def test_oauth_server_view_preserves_registered_tool_and_resource_surface() -> None:
    import asyncio

    from zaptrace.mcp.server import server

    app = cast(Starlette, create_oauth_http_app(_configuration()))
    oauth_server = app.state.fastmcp_server

    async def compare() -> tuple[set[str], set[str], set[str], set[str]]:
        original_tools = {item.name for item in await server.list_tools()}
        oauth_tools = {item.name for item in await oauth_server.list_tools()}
        original_resources = {str(item.uri) for item in await server.list_resources()}
        oauth_resources = {str(item.uri) for item in await oauth_server.list_resources()}
        return original_tools, oauth_tools, original_resources, oauth_resources

    original_tools, oauth_tools, original_resources, oauth_resources = asyncio.run(compare())
    assert len(original_tools) == 96
    assert oauth_tools == original_tools
    assert len(original_resources) == 7
    assert oauth_resources == original_resources
