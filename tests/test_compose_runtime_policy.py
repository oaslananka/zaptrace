from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _compose() -> dict[str, object]:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def _scripts() -> dict[str, str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return config["project"]["scripts"]


def _service(name: str) -> dict[str, object]:
    services = _compose()["services"]
    assert isinstance(services, dict)
    service = services[name]
    assert isinstance(service, dict)
    return service


def test_compose_network_services_use_declared_console_scripts() -> None:
    scripts = _scripts()
    expected = {
        "zaptrace-api": "zaptrace-api",
        "zaptrace-mcp-http": "zaptrace-mcp-http",
    }

    for service_name, script_name in expected.items():
        service = _service(service_name)
        assert scripts[script_name]
        assert service["entrypoint"] == [script_name]
        assert "command" not in service

    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "serve --host" not in compose_text


def test_authenticated_services_fail_closed_without_tokens() -> None:
    api_environment = _service("zaptrace-api")["environment"]
    mcp_environment = _service("zaptrace-mcp-http")["environment"]
    assert isinstance(api_environment, dict)
    assert isinstance(mcp_environment, dict)

    assert api_environment["ZAPTRACE_API_TOKEN"] == "${ZAPTRACE_API_TOKEN:-}"
    assert mcp_environment["ZAPTRACE_MCP_HTTP_TOKEN"] == "${ZAPTRACE_MCP_HTTP_TOKEN:-}"
    assert api_environment["ZAPTRACE_API_HOST"] == "0.0.0.0"
    assert mcp_environment["ZAPTRACE_MCP_HTTP_HOST"] == "0.0.0.0"


def test_authenticated_ports_publish_to_host_loopback() -> None:
    assert _service("zaptrace-api")["ports"] == ["127.0.0.1:${ZAPTRACE_API_PUBLISHED_PORT:-8000}:8000"]
    assert _service("zaptrace-mcp-http")["ports"] == ["127.0.0.1:${ZAPTRACE_MCP_HTTP_PUBLISHED_PORT:-8090}:8090"]


def test_compose_health_checks_exercise_rest_and_mcp_protocols() -> None:
    api_health = _service("zaptrace-api")["healthcheck"]
    mcp_health = _service("zaptrace-mcp-http")["healthcheck"]
    assert isinstance(api_health, dict)
    assert isinstance(mcp_health, dict)

    assert "/health" in " ".join(api_health["test"])
    mcp_command = " ".join(mcp_health["test"])
    assert "/mcp" in mcp_command
    assert "initialize" in mcp_command
    assert "ZAPTRACE_MCP_HTTP_TOKEN" in mcp_command


def test_readiness_service_waits_for_both_network_services() -> None:
    ready = _service("zaptrace-ready")
    assert ready["profiles"] == ["smoke"]
    assert ready["depends_on"] == {
        "zaptrace-api": {"condition": "service_healthy"},
        "zaptrace-mcp-http": {"condition": "service_healthy"},
    }


def test_loopback_profile_is_not_published() -> None:
    for name in ("zaptrace-api-loopback", "zaptrace-mcp-loopback"):
        service = _service(name)
        assert service["profiles"] == ["loopback-development"]
        assert "ports" not in service

    assert _service("zaptrace-api-loopback")["environment"]["ZAPTRACE_API_HOST"] == "127.0.0.1"
    assert _service("zaptrace-mcp-loopback")["environment"]["ZAPTRACE_MCP_HTTP_HOST"] == "127.0.0.1"


def test_environment_example_documents_tokens_without_committing_secrets() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "ZAPTRACE_API_TOKEN=" in example
    assert "ZAPTRACE_MCP_HTTP_TOKEN=" in example
    assert "replace-with-a-long-random-secret" not in example
    assert "secret-token" not in example


def test_runtime_documentation_uses_supported_entrypoints_and_non_claims() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    api_docs = (ROOT / "docs" / "api-rest-production.md").read_text(encoding="utf-8")
    mcp_docs = (ROOT / "docs" / "mcp-http-deployment.md").read_text(encoding="utf-8")

    assert "zaptrace-mcp --http" not in readme
    assert "zaptrace-mcp-http" in readme
    assert "docker compose up --build" in api_docs
    assert "docker compose --profile loopback-development" in api_docs
    assert "TLS termination" in api_docs
    assert "ZAPTRACE_MCP_HTTP_TOKEN" in mcp_docs
    assert "public hosting certification" in mcp_docs


def test_compose_mcp_forwards_versioned_oauth_configuration() -> None:
    environment = _service("zaptrace-mcp-http")["environment"]
    assert isinstance(environment, dict)
    expected = {
        "ZAPTRACE_MCP_AUTH_CONFIG_VERSION": "${ZAPTRACE_MCP_AUTH_CONFIG_VERSION:-}",
        "ZAPTRACE_MCP_AUTH_PROFILE": "${ZAPTRACE_MCP_AUTH_PROFILE:-}",
        "ZAPTRACE_MCP_PUBLIC_BASE_URL": "${ZAPTRACE_MCP_PUBLIC_BASE_URL:-}",
        "ZAPTRACE_MCP_AUTH_RESOURCE_URI": "${ZAPTRACE_MCP_AUTH_RESOURCE_URI:-}",
        "ZAPTRACE_MCP_AUTHORIZATION_SERVER": "${ZAPTRACE_MCP_AUTHORIZATION_SERVER:-}",
        "ZAPTRACE_MCP_AUTH_JWKS_URI": "${ZAPTRACE_MCP_AUTH_JWKS_URI:-}",
    }
    for name, value in expected.items():
        assert environment[name] == value

    health_command = " ".join(_service("zaptrace-mcp-http")["healthcheck"]["test"])
    assert "oauth-jwt" in health_command
    assert "/.well-known/oauth-protected-resource/mcp" in health_command
