from __future__ import annotations

from secrets import token_hex

import pytest
import uvicorn
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from zaptrace.agent._tool_impls import _get_session
from zaptrace.api.server import create_app
from zaptrace.api.server import run as run_api
from zaptrace.mcp.server import MCPBearerAuthMiddleware
from zaptrace.mcp.server import run_http as run_mcp_http
from zaptrace.security.network import is_loopback_host, validate_network_auth_configuration


@pytest.mark.parametrize("host", ["127.0.0.1", "127.12.34.56", "::1", "[::1]", "localhost"])
def test_loopback_hosts_are_recognized(host: str) -> None:
    assert is_loopback_host(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "api.internal", ""])
def test_non_loopback_or_invalid_hosts_are_not_treated_as_loopback(host: str) -> None:
    assert is_loopback_host(host) is False


def test_non_loopback_configuration_requires_authentication() -> None:
    with pytest.raises(RuntimeError, match="refuses non-loopback bind"):
        validate_network_auth_configuration(surface="test", host="0.0.0.0", token="")


@pytest.mark.parametrize(
    ("token", "allow_local_development", "expected_mode"),
    [
        ("", False, "loopback-read-only"),
        ("", True, "loopback-development"),
        ("configured", False, "authenticated"),
    ],
)
def test_network_auth_configuration_mode(
    token: str,
    allow_local_development: bool,
    expected_mode: str,
) -> None:
    configuration = validate_network_auth_configuration(
        surface="test",
        host="127.0.0.1",
        token=token,
        allow_local_development=allow_local_development,
    )

    assert configuration.mode == expected_mode


def test_empty_bind_host_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="bind host must not be empty"):
        validate_network_auth_configuration(surface="test", host="", token="")


def test_local_development_override_is_rejected_for_non_loopback() -> None:
    token = token_hex(32)
    with pytest.raises(RuntimeError, match="restricted to loopback"):
        validate_network_auth_configuration(
            surface="test",
            host="0.0.0.0",
            token=token,
            allow_local_development=True,
        )


def test_rest_non_loopback_startup_fails_without_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZAPTRACE_API_TOKEN", raising=False)
    monkeypatch.delenv("ZAPTRACE_API_ALLOW_LOCAL_CAPABILITY_HEADERS", raising=False)
    called = False

    def fake_run(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(uvicorn, "run", fake_run)
    with pytest.raises(RuntimeError, match="ZapTrace REST API refuses non-loopback bind"):
        run_api(host="0.0.0.0")
    assert called is False


def test_rest_loopback_startup_allows_read_only_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZAPTRACE_API_TOKEN", raising=False)
    monkeypatch.delenv("ZAPTRACE_API_ALLOW_LOCAL_CAPABILITY_HEADERS", raising=False)
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    run_api(host="127.0.0.1", port=18080)

    assert calls == [{"host": "127.0.0.1", "port": 18080, "reload": False}]


def test_client_capability_header_cannot_self_grant_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZAPTRACE_API_TOKEN", raising=False)
    monkeypatch.delenv("ZAPTRACE_API_ALLOW_LOCAL_CAPABILITY_HEADERS", raising=False)
    session_id = "capability-escalation-denied"
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/designs/parse/str",
        params={"yaml_content": "meta:\n  name: EscalationDenied\n"},
        headers={
            "X-ZapTrace-Session-Id": session_id,
            "X-ZapTrace-Capabilities": "release-export",
            "X-ZapTrace-Actor": "spoofed-admin",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "OPERATION_NOT_AUTHORIZED"
    event = _get_session(session_id)["audit_events"][-1]
    assert event["actor"] == "unauthenticated-rest-client"
    assert event["metadata"]["granted_capabilities"] == []
    assert event["metadata"]["auth_source"] == "capability-headers-disabled"
    assert event["metadata"]["authenticated"] is False


def test_authenticated_session_scoped_read_requires_explicit_session_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_token = token_hex(32)
    monkeypatch.setenv("ZAPTRACE_API_TOKEN", api_token)
    monkeypatch.setenv("ZAPTRACE_API_TOKEN_SUBJECT", "api-reader")
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/designs/missing",
        headers={"Authorization": f"Bearer {api_token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "SESSION_REQUIRED"


def test_explicit_loopback_development_mode_allows_capability_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZAPTRACE_API_TOKEN", raising=False)
    monkeypatch.setenv("ZAPTRACE_API_ALLOW_LOCAL_CAPABILITY_HEADERS", "1")
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/designs/parse/str",
        params={"yaml_content": "meta:\n  name: LocalDevelopment\n"},
        headers={
            "X-ZapTrace-Session-Id": "local-development",
            "X-ZapTrace-Capabilities": "preview-write",
            "X-ZapTrace-Actor": "local-engineer",
        },
    )

    assert response.status_code == 200
    event = _get_session("local-development")["audit_events"][-1]
    assert event["actor"] == "local-engineer"
    assert event["metadata"]["auth_source"] == "explicit-loopback-development"


def test_mcp_non_loopback_startup_fails_without_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZAPTRACE_MCP_HTTP_TOKEN", raising=False)
    monkeypatch.delenv("ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS", raising=False)
    called = False

    def fake_run(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(uvicorn, "run", fake_run)
    with pytest.raises(RuntimeError, match="ZapTrace MCP HTTP refuses non-loopback bind"):
        run_mcp_http(host="0.0.0.0")
    assert called is False


def test_mcp_non_loopback_startup_uses_bearer_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPTRACE_MCP_HTTP_TOKEN", "mcp-secret")
    monkeypatch.delenv("ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS", raising=False)
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append({"app": app, **kwargs}))
    run_mcp_http(host="0.0.0.0", port=18090)

    assert len(calls) == 1
    assert calls[0]["host"] == "0.0.0.0"
    assert calls[0]["port"] == 18090


def test_mcp_bearer_middleware_rejects_missing_and_invalid_credentials() -> None:
    def endpoint(_request: object) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route("/", endpoint)],
        middleware=[Middleware(MCPBearerAuthMiddleware, token="mcp-secret")],
    )
    client = TestClient(app)

    missing = client.get("/")
    invalid = client.get("/", headers={"Authorization": "Bearer wrong"})
    allowed = client.get("/", headers={"Authorization": "Bearer mcp-secret"})

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert allowed.status_code == 200


def test_rest_multi_worker_memory_rate_limit_fails_before_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPTRACE_API_WORKERS", "2")
    monkeypatch.setenv("ZAPTRACE_API_RATE_LIMIT_BACKEND", "memory")
    called = False

    def fake_run(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(uvicorn, "run", fake_run)
    with pytest.raises(RuntimeError, match="multi-worker.*shared rate-limit backend"):
        run_api(host="127.0.0.1")
    assert called is False
