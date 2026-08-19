from __future__ import annotations

from zaptrace.api.server import app


def test_agent_routes_document_explicit_http_errors() -> None:
    paths = app.openapi()["paths"]
    expected = {
        ("/api/v1/agent/sessions/{session_id}/access", "get"): "403",
        ("/api/v1/agent/sessions/{session_id}/delegates/{delegate_principal}", "post"): "403",
        ("/api/v1/agent/sessions/{session_id}/delegates/{delegate_principal}", "delete"): "403",
        ("/api/v1/agent/sandbox/{session_id}/status", "get"): "404",
        ("/api/v1/agent/replay/{session_id}", "get"): "404",
    }

    for (path, method), status_code in expected.items():
        responses = paths[path][method]["responses"]
        assert status_code in responses
