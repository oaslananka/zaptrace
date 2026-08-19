from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "security" / "mcp-http-authorization-contract.md"


def _contract() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def test_contract_is_versioned_and_selects_remote_jwt_resource_server() -> None:
    text = _contract()
    assert "Contract version: `1`" in text
    assert "`RemoteAuthProvider` composed with `JWTVerifier`" in text
    assert "Repository-owned JWT/OAuth implementation | Rejected" in text
    assert "OAuth/OIDC proxy | Deferred" in text


def test_contract_defines_fail_closed_profiles_and_scope_mapping() -> None:
    text = _contract()
    for profile in ("`local`", "`static-bearer`", "`oauth-jwt`"):
        assert profile in text
    for scope, capability in (
        ("zaptrace:read", "`read`"),
        ("zaptrace:preview-write", "`preview-write`"),
        ("zaptrace:sandbox-write", "`sandbox-write`"),
        ("zaptrace:approved-commit", "`approved-commit`"),
        ("zaptrace:release-export", "`release-export`"),
    ):
        assert f"`{scope}` | {capability}" in text
    assert "Unknown scopes grant nothing" in text
    assert "ZAPTRACE_MCP_AUTH_CONFIG_VERSION" in text
    assert "ZAPTRACE_MCP_AUTH_RESOURCE_URI" in text


def test_contract_defines_discovery_challenges_and_negative_evidence() -> None:
    text = _contract()
    assert "/.well-known/oauth-protected-resource/mcp" in text
    assert 'error="invalid_token"' in text
    assert 'error="insufficient_scope"' in text
    assert "wrong issuer" in text
    assert "wrong audience/resource" in text
    assert "principal A attempting to access principal B's session" in text


def test_threat_model_and_navigation_reference_contract() -> None:
    threat_model = (ROOT / "docs" / "security" / "agent-runtime-threat-model.md").read_text(encoding="utf-8")
    nav = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    for threat in (
        "Token passthrough",
        "Audience confusion",
        "Scope escalation",
        "Client mix-up",
        "Bearer replay",
        "Cross-session object access",
    ):
        assert threat in threat_model
    assert "security/mcp-http-authorization-contract.md" in nav


def test_contract_contains_no_committed_credentials() -> None:
    text = _contract()
    forbidden = (
        "BEGIN " + "PRIVATE" + " KEY",
        "client_secret=",
        "ZAPTRACE_MCP_HTTP_TOKEN=ey",
        "Authorization: Bearer ey",
    )
    assert all(value not in text for value in forbidden)


def test_slice4_documents_supported_oauth_denial_and_object_audit_boundary() -> None:
    contract = _contract()
    deployment = (ROOT / "docs" / "mcp-http-deployment.md").read_text(encoding="utf-8")
    network = (ROOT / "docs" / "security" / "network-transport-authentication.md").read_text(encoding="utf-8")

    assert "Slice 2" in contract
    assert "provider construction, RFC 9728 discovery, and stable `401` challenges" in contract
    assert "Slice 3" in contract
    assert "validated `AccessToken.scopes`" in contract
    assert "`(iss, sub)`" in contract
    assert "environment/session capability grants" in contract
    assert "unknown scopes grant nothing" in contract.lower()
    assert "Slice 4" in contract
    assert "`403 insufficient_scope`" in contract
    assert "`OBJECT_NOT_AUTHORIZED`" in contract
    assert "redacted authorization audit" in contract
    assert "AUTHORIZATION_PROFILE_INCOMPLETE" not in contract
    assert "supported `oauth-jwt`" in deployment
    assert "per-request" in deployment
    assert "supported `oauth-jwt`" in network
    assert "public multi-tenant" in deployment


def test_slice5_documents_e2e_jwt_evidence_and_compose_migration() -> None:
    contract = _contract()
    deployment = (ROOT / "docs" / "mcp-http-deployment.md").read_text(encoding="utf-8")

    assert "Slice 5" in contract
    assert "end-to-end evidence and migration — complete" in contract.lower()
    assert "tests/test_mcp_oauth_jwt_e2e.py" in contract
    assert "ephemeral asymmetric" in contract.lower()
    assert "not-yet-valid" in contract
    assert "artifacts/compose-smoke/summary.json" in deployment
    assert "compose-runtime-smoke" in deployment
    assert "signing material" in deployment
    assert "ZAPTRACE_MCP_AUTH_PROFILE=oauth-jwt" in deployment
