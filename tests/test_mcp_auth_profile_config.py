from __future__ import annotations

from pathlib import Path

import pytest
import uvicorn

from zaptrace.mcp.auth_config import resolve_mcp_http_auth_configuration
from zaptrace.mcp.server import run_http

_AUTH_ENV_VARS = (
    "ZAPTRACE_MCP_AUTH_CONFIG_VERSION",
    "ZAPTRACE_MCP_AUTH_PROFILE",
    "ZAPTRACE_MCP_HTTP_TOKEN",
    "ZAPTRACE_MCP_TOKEN_SUBJECT",
    "ZAPTRACE_MCP_CAPABILITIES",
    "ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS",
    "ZAPTRACE_MCP_PUBLIC_BASE_URL",
    "ZAPTRACE_MCP_AUTH_RESOURCE_URI",
    "ZAPTRACE_MCP_AUTHORIZATION_SERVER",
    "ZAPTRACE_MCP_AUTH_JWKS_URI",
)


@pytest.fixture(autouse=True)
def _clean_auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _capture_uvicorn(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append({"app": app, **kwargs}))
    return calls


def _set_explicit_profile(monkeypatch: pytest.MonkeyPatch, profile: str) -> None:
    monkeypatch.setenv("ZAPTRACE_MCP_AUTH_CONFIG_VERSION", "1")
    monkeypatch.setenv("ZAPTRACE_MCP_AUTH_PROFILE", profile)


def _set_valid_oauth_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_explicit_profile(monkeypatch, "oauth-jwt")
    monkeypatch.setenv("ZAPTRACE_MCP_PUBLIC_BASE_URL", "https://mcp.example.com")
    monkeypatch.setenv("ZAPTRACE_MCP_AUTH_RESOURCE_URI", "https://mcp.example.com/mcp")
    monkeypatch.setenv("ZAPTRACE_MCP_AUTHORIZATION_SERVER", "https://auth.example.com/")
    monkeypatch.setenv("ZAPTRACE_MCP_AUTH_JWKS_URI", "https://auth.example.com/.well-known/jwks.json")


def test_explicit_auth_profile_requires_contract_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPTRACE_MCP_AUTH_PROFILE", "oauth-jwt")
    _capture_uvicorn(monkeypatch)

    with pytest.raises(RuntimeError, match="ZAPTRACE_MCP_AUTH_CONFIG_VERSION.*required"):
        run_http(host="127.0.0.1", port=18090)


def test_contract_version_requires_explicit_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPTRACE_MCP_AUTH_CONFIG_VERSION", "1")
    _capture_uvicorn(monkeypatch)

    with pytest.raises(RuntimeError, match="ZAPTRACE_MCP_AUTH_PROFILE.*required"):
        run_http(host="127.0.0.1", port=18090)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("ZAPTRACE_MCP_AUTH_CONFIG_VERSION", "2", "unsupported.*version"),
        ("ZAPTRACE_MCP_AUTH_PROFILE", "unknown", "unsupported.*profile"),
    ],
)
def test_unknown_contract_selection_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    _set_explicit_profile(monkeypatch, "local")
    monkeypatch.setenv(name, value)
    _capture_uvicorn(monkeypatch)

    with pytest.raises(RuntimeError, match=message):
        run_http(host="127.0.0.1", port=18090)


def test_legacy_loopback_inference_remains_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_uvicorn(monkeypatch)

    run_http(host="127.0.0.1", port=18090)

    assert len(calls) == 1
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 18090


def test_legacy_static_bearer_inference_remains_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPTRACE_MCP_HTTP_TOKEN", "controlled-token")
    calls = _capture_uvicorn(monkeypatch)

    run_http(host="0.0.0.0", port=18090)

    assert len(calls) == 1
    assert calls[0]["host"] == "0.0.0.0"


def test_explicit_local_profile_allows_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_explicit_profile(monkeypatch, "local")
    calls = _capture_uvicorn(monkeypatch)

    run_http(host="127.0.0.1", port=18090)

    assert len(calls) == 1


def test_explicit_local_profile_rejects_non_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_explicit_profile(monkeypatch, "local")
    _capture_uvicorn(monkeypatch)

    with pytest.raises(RuntimeError, match="local.*loopback"):
        run_http(host="0.0.0.0", port=18090)


@pytest.mark.parametrize(
    ("legacy_variable", "value"),
    [
        ("ZAPTRACE_MCP_HTTP_TOKEN", "must-not-be-ignored"),
        ("ZAPTRACE_MCP_TOKEN_SUBJECT", "must-not-be-ignored"),
        ("ZAPTRACE_MCP_CAPABILITIES", "release-export"),
    ],
)
def test_explicit_local_profile_rejects_legacy_settings(
    monkeypatch: pytest.MonkeyPatch,
    legacy_variable: str,
    value: str,
) -> None:
    _set_explicit_profile(monkeypatch, "local")
    monkeypatch.setenv(legacy_variable, value)
    _capture_uvicorn(monkeypatch)

    with pytest.raises(RuntimeError, match=f"local.*{legacy_variable}"):
        run_http(host="127.0.0.1", port=18090)


def test_explicit_static_bearer_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_explicit_profile(monkeypatch, "static-bearer")
    _capture_uvicorn(monkeypatch)

    with pytest.raises(RuntimeError, match="static-bearer.*ZAPTRACE_MCP_HTTP_TOKEN"):
        run_http(host="127.0.0.1", port=18090)


def test_explicit_static_bearer_allows_non_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_explicit_profile(monkeypatch, "static-bearer")
    monkeypatch.setenv("ZAPTRACE_MCP_HTTP_TOKEN", "controlled-token")
    calls = _capture_uvicorn(monkeypatch)

    run_http(host="0.0.0.0", port=18090)

    assert len(calls) == 1


def test_legacy_inference_rejects_oauth_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPTRACE_MCP_PUBLIC_BASE_URL", "https://mcp.example.com")
    _capture_uvicorn(monkeypatch)

    with pytest.raises(RuntimeError, match="requires explicit.*oauth-jwt"):
        run_http(host="127.0.0.1", port=18090)


@pytest.mark.parametrize(
    ("profile", "oauth_variable"),
    [
        (profile, oauth_variable)
        for profile in ("local", "static-bearer")
        for oauth_variable in (
            "ZAPTRACE_MCP_PUBLIC_BASE_URL",
            "ZAPTRACE_MCP_AUTH_RESOURCE_URI",
            "ZAPTRACE_MCP_AUTHORIZATION_SERVER",
            "ZAPTRACE_MCP_AUTH_JWKS_URI",
        )
    ],
)
def test_non_oauth_profiles_reject_oauth_settings(
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    oauth_variable: str,
) -> None:
    _set_explicit_profile(monkeypatch, profile)
    if profile == "static-bearer":
        monkeypatch.setenv("ZAPTRACE_MCP_HTTP_TOKEN", "controlled-token")
    monkeypatch.setenv(oauth_variable, "https://example.com/value")
    _capture_uvicorn(monkeypatch)

    with pytest.raises(RuntimeError, match=f"{profile}.*{oauth_variable}"):
        run_http(host="127.0.0.1", port=18090)


@pytest.mark.parametrize(
    "required_variable",
    [
        "ZAPTRACE_MCP_PUBLIC_BASE_URL",
        "ZAPTRACE_MCP_AUTH_RESOURCE_URI",
        "ZAPTRACE_MCP_AUTHORIZATION_SERVER",
        "ZAPTRACE_MCP_AUTH_JWKS_URI",
    ],
)
def test_oauth_profile_requires_complete_configuration(
    monkeypatch: pytest.MonkeyPatch,
    required_variable: str,
) -> None:
    _set_valid_oauth_configuration(monkeypatch)
    monkeypatch.delenv(required_variable)
    _capture_uvicorn(monkeypatch)

    with pytest.raises(RuntimeError, match=f"oauth-jwt.*{required_variable}"):
        run_http(host="0.0.0.0", port=18090)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("ZAPTRACE_MCP_PUBLIC_BASE_URL", "http://mcp.example.com"),
        ("ZAPTRACE_MCP_AUTH_RESOURCE_URI", "https://user@mcp.example.com/mcp"),
        ("ZAPTRACE_MCP_AUTHORIZATION_SERVER", "https://auth.example.com?tenant=one"),
        ("ZAPTRACE_MCP_AUTH_JWKS_URI", "https://auth.example.com/jwks#fragment"),
    ],
)
def test_oauth_profile_rejects_unsafe_urls(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
) -> None:
    _set_valid_oauth_configuration(monkeypatch)
    monkeypatch.setenv(variable, value)
    _capture_uvicorn(monkeypatch)

    error_pattern = f"{variable}.*HTTPS|{variable}.*credentials|{variable}.*query|{variable}.*fragment"
    with pytest.raises(RuntimeError, match=error_pattern):
        run_http(host="0.0.0.0", port=18090)


def test_oauth_resource_must_share_public_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_valid_oauth_configuration(monkeypatch)
    monkeypatch.setenv("ZAPTRACE_MCP_AUTH_RESOURCE_URI", "https://other.example.com/mcp")
    _capture_uvicorn(monkeypatch)

    with pytest.raises(RuntimeError, match="resource.*same origin"):
        run_http(host="0.0.0.0", port=18090)


@pytest.mark.parametrize(
    ("legacy_variable", "value"),
    [
        ("ZAPTRACE_MCP_HTTP_TOKEN", "legacy-token"),
        ("ZAPTRACE_MCP_TOKEN_SUBJECT", "legacy-subject"),
        ("ZAPTRACE_MCP_CAPABILITIES", "release-export"),
    ],
)
def test_oauth_profile_rejects_legacy_grant_settings(
    monkeypatch: pytest.MonkeyPatch,
    legacy_variable: str,
    value: str,
) -> None:
    _set_valid_oauth_configuration(monkeypatch)
    monkeypatch.setenv(legacy_variable, value)
    _capture_uvicorn(monkeypatch)

    with pytest.raises(RuntimeError, match=f"oauth-jwt.*{legacy_variable}"):
        run_http(host="0.0.0.0", port=18090)


def test_oauth_profile_runs_supported_listener_after_denial_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_valid_oauth_configuration(monkeypatch)
    calls = _capture_uvicorn(monkeypatch)
    built: list[object] = []
    app = object()
    monkeypatch.setattr(
        "zaptrace.mcp.server.create_oauth_http_app",
        lambda configuration: built.append(configuration) or app,
    )

    run_http(host="0.0.0.0", port=18090)

    assert len(built) == 1
    assert calls == [{"app": app, "host": "0.0.0.0", "port": 18090}]


def test_resolved_static_configuration_redacts_token_from_repr() -> None:
    configuration = resolve_mcp_http_auth_configuration(
        host="0.0.0.0",
        environ={
            "ZAPTRACE_MCP_AUTH_CONFIG_VERSION": "1",
            "ZAPTRACE_MCP_AUTH_PROFILE": "static-bearer",
            "ZAPTRACE_MCP_HTTP_TOKEN": "sensitive-controlled-token",
        },
    )

    assert configuration.profile == "static-bearer"
    assert configuration.explicit is True
    assert configuration.contract_version == "1"
    assert configuration.authentication_configured is True
    assert "sensitive-controlled-token" not in repr(configuration)


def test_resolved_oauth_configuration_retains_public_identity_only() -> None:
    configuration = resolve_mcp_http_auth_configuration(
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

    assert configuration.profile == "oauth-jwt"
    assert configuration.resource_uri == "https://mcp.example.com/mcp"
    assert configuration.authorization_server == "https://auth.example.com/"
    assert configuration.static_token == ""


def test_environment_example_documents_profile_names_without_credentials() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")

    assert "# ZAPTRACE_MCP_AUTH_CONFIG_VERSION=1" in example
    assert "# ZAPTRACE_MCP_AUTH_PROFILE=static-bearer" in example
    assert "# ZAPTRACE_MCP_AUTH_PROFILE=oauth-jwt" in example
    assert "# ZAPTRACE_MCP_PUBLIC_BASE_URL=https://mcp.example.com" in example
    assert "# ZAPTRACE_MCP_AUTH_RESOURCE_URI=https://mcp.example.com/mcp" in example
    assert "# ZAPTRACE_MCP_AUTHORIZATION_SERVER=https://auth.example.com/" in example
    assert "# ZAPTRACE_MCP_AUTH_JWKS_URI=https://auth.example.com/.well-known/jwks.json" in example
    assert "client_secret" not in example
    assert "request authentication remains disabled" not in example
    assert "PRIVATE_KEY" not in example


@pytest.mark.parametrize(
    ("legacy_variable", "value"),
    [
        ("ZAPTRACE_MCP_TOKEN_SUBJECT", "compose-mcp"),
        ("ZAPTRACE_MCP_CAPABILITIES", "read"),
    ],
)
def test_legacy_missing_token_preserves_non_loopback_auth_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    legacy_variable: str,
    value: str,
) -> None:
    monkeypatch.setenv(legacy_variable, value)
    _capture_uvicorn(monkeypatch)

    with pytest.raises(RuntimeError, match="refuses non-loopback bind.*without authentication"):
        run_http(host="0.0.0.0", port=18090)
