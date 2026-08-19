from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


def _project_scripts() -> dict[str, str]:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    return config["project"]["scripts"]


def test_project_registers_explicit_mcp_http_entrypoint() -> None:
    assert _project_scripts()["zaptrace-mcp-http"] == "zaptrace.mcp.server:run_http"


def test_api_entrypoint_uses_environment_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from zaptrace.api import server as api_server

    observed: dict[str, object] = {}
    monkeypatch.setenv("ZAPTRACE_API_HOST", "0.0.0.0")
    monkeypatch.setenv("ZAPTRACE_API_PORT", "8000")
    monkeypatch.setenv("ZAPTRACE_API_TOKEN", "api-secret")
    monkeypatch.delenv("ZAPTRACE_API_ALLOW_LOCAL_CAPABILITY_HEADERS", raising=False)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: observed.update(app=app, **kwargs))

    api_server.run()

    assert observed == {
        "app": "zaptrace.api.server:app",
        "host": "0.0.0.0",
        "port": 8000,
        "reload": False,
    }


def test_api_explicit_bind_overrides_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from zaptrace.api import server as api_server

    observed: dict[str, object] = {}
    monkeypatch.setenv("ZAPTRACE_API_HOST", "0.0.0.0")
    monkeypatch.setenv("ZAPTRACE_API_PORT", "8000")
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: observed.update(app=app, **kwargs))

    api_server.run(host="127.0.0.1", port=8181)

    assert observed["host"] == "127.0.0.1"
    assert observed["port"] == 8181


def test_api_entrypoint_rejects_empty_environment_host(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from zaptrace.api import server as api_server

    monkeypatch.setenv("ZAPTRACE_API_HOST", "   ")
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="ZAPTRACE_API_HOST.*must not be empty"):
        api_server.run()


def test_api_entrypoint_rejects_invalid_environment_port(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from zaptrace.api import server as api_server

    monkeypatch.setenv("ZAPTRACE_API_PORT", "70000")
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="ZAPTRACE_API_PORT.*1.*65535"):
        api_server.run()


def test_mcp_http_entrypoint_uses_environment_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from zaptrace.mcp import server as mcp_server

    observed: dict[str, object] = {}
    monkeypatch.setenv("ZAPTRACE_MCP_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("ZAPTRACE_MCP_HTTP_PORT", "8090")
    monkeypatch.setenv("ZAPTRACE_MCP_HTTP_TOKEN", "mcp-secret")
    monkeypatch.delenv("ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS", raising=False)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: observed.update(app=app, **kwargs))

    mcp_server.run_http()

    assert observed["host"] == "0.0.0.0"
    assert observed["port"] == 8090
    assert observed["app"] is not None


def test_mcp_http_entrypoint_rejects_non_decimal_port(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from zaptrace.mcp import server as mcp_server

    monkeypatch.setenv("ZAPTRACE_MCP_HTTP_PORT", "not-a-port")
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="ZAPTRACE_MCP_HTTP_PORT.*integer"):
        mcp_server.run_http()
