from __future__ import annotations

import json

import pytest
from fastmcp import Client
from starlette.testclient import TestClient

from zaptrace.agent._tool_impls import _sessions
from zaptrace.mcp.server import create_http_app, server
from zaptrace.security.objects import reset_object_authorization_state

_PROTOCOL_VERSION = "2026-07-28"
_META = {
    "io.modelcontextprotocol/protocolVersion": _PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientInfo": {"name": "zaptrace-conformance", "version": "1"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


@pytest.fixture(autouse=True)
def _reset_mcp_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _sessions.clear()
    reset_object_authorization_state()
    monkeypatch.delenv("ZAPTRACE_MCP_HTTP_TOKEN", raising=False)
    monkeypatch.delenv("ZAPTRACE_MCP_TOKEN_SUBJECT", raising=False)
    monkeypatch.delenv("ZAPTRACE_MCP_CAPABILITIES", raising=False)
    monkeypatch.delenv("ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS", raising=False)
    yield
    _sessions.clear()
    reset_object_authorization_state()


def _headers(method: str, *, name: str | None = None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": _PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return headers


def _request(request_id: int, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    merged_params = dict(params or {})
    merged_params["_meta"] = dict(_META)
    payload["params"] = merged_params
    return payload


def _structured_result(response) -> dict[str, object]:
    payload = response.json()
    result = payload["result"]
    structured = result["structuredContent"]
    assert isinstance(structured, dict)
    return structured


def test_server_instructions_make_protocol_and_application_state_boundary_explicit() -> None:
    instructions = server.instructions or ""

    assert _PROTOCOL_VERSION in instructions
    assert "application-level" in instructions.lower()
    assert "Mcp-Session-Id" in instructions


def test_modern_http_request_does_not_bypass_static_bearer_boundary() -> None:
    app = create_http_app(token="controlled-modern-token")

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            headers=_headers("server/discover"),
            json=_request(1, "server/discover"),
        )

    assert response.status_code == 401
    assert "mcp-session-id" not in response.headers
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_modern_server_discovery_is_stateless_over_real_http_app() -> None:
    app = create_http_app(token="")

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            headers=_headers("server/discover"),
            json=_request(1, "server/discover"),
        )

    assert response.status_code == 200
    assert "mcp-session-id" not in response.headers
    result = response.json()["result"]
    assert result["supportedVersions"] == [_PROTOCOL_VERSION]
    assert result["capabilities"]["tools"]["listChanged"] is False
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "zaptrace"


def test_modern_requests_thread_zaptrace_application_handle_without_transport_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS", "true")
    app = create_http_app(token="")

    with TestClient(app) as client:
        created = client.post(
            "/mcp",
            headers=_headers("tools/call", name="session_create"),
            json=_request(
                1,
                "tools/call",
                {"name": "session_create", "arguments": {"capabilities": "preview-write"}},
            ),
        )
        assert created.status_code == 200
        assert "mcp-session-id" not in created.headers
        session_id = str(_structured_result(created)["data"]["session_id"])

        design_yaml = """meta:\n  name: ModernState\ncomponents:\n  r1:\n    ref: R1\n    type: resistor\n"""
        parsed = client.post(
            "/mcp",
            headers=_headers("tools/call", name="design_parse_str"),
            json=_request(
                2,
                "tools/call",
                {
                    "name": "design_parse_str",
                    "arguments": {"session_id": session_id, "yaml_content": design_yaml},
                },
            ),
        )
        listed = client.post(
            "/mcp",
            headers=_headers("tools/call", name="session_list"),
            json=_request(3, "tools/call", {"name": "session_list", "arguments": {}}),
        )

    assert parsed.status_code == 200
    assert "mcp-session-id" not in parsed.headers
    parsed_data = _structured_result(parsed)
    assert parsed_data["ok"] is True
    assert parsed_data["data"]["design_name"] == "ModernState"

    listed_data = _structured_result(listed)
    assert listed_data["ok"] is True
    sessions = listed_data["data"]["sessions"]
    assert {item["session_id"]: item["design_count"] for item in sessions} == {session_id: 1}


@pytest.mark.asyncio
async def test_same_server_supports_modern_and_legacy_client_modes() -> None:
    observations: dict[str, tuple[int, dict[str, object]]] = {}

    for mode in (_PROTOCOL_VERSION, "legacy"):
        async with Client(server, mode=mode) as client:
            tools = await client.list_tools()
            result = await client.call_tool("session_list")
            observations[mode] = (len(tools), result.structured_content or {})

    assert observations[_PROTOCOL_VERSION][0] == 96
    assert observations["legacy"][0] == 96
    assert observations[_PROTOCOL_VERSION][1] == {"ok": True, "data": {"sessions": []}}
    assert observations["legacy"][1] == observations[_PROTOCOL_VERSION][1]
