from __future__ import annotations

import importlib.util
import json
import secrets
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_compose_smoke.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_compose_smoke_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evidence_paths_are_fixed_inside_artifacts() -> None:
    module = _module()

    assert module.SUMMARY_PATH == ROOT / "artifacts" / "compose-smoke" / "summary.json"
    assert module.LOG_PATH == ROOT / "artifacts" / "compose-smoke" / "compose.log"


def test_bounded_log_redacts_tokens_and_truncates() -> None:
    module = _module()
    secret_value = secrets.token_urlsafe(32)

    bounded = module.bounded_log(
        f"before {secret_value} " + "x" * 200,
        secrets=(secret_value,),
        limit=64,
    )

    assert secret_value not in bounded
    assert "[REDACTED]" in bounded
    assert bounded.endswith("\n...[truncated]\n")
    assert len(bounded.encode("utf-8")) <= 96


def test_parse_mcp_discover_response_returns_server_identity() -> None:
    module = _module()
    payload = (
        b'{"jsonrpc":"2.0","id":1,"result":{"supportedVersions":["2026-07-28"],'
        b'"_meta":{"io.modelcontextprotocol/serverInfo":{"name":"zaptrace","version":"0.3.0"}},'
        b'"resultType":"complete"}}'
    )

    result = module.parse_mcp_discover_response(payload)

    assert result == {
        "protocol_version": "2026-07-28",
        "server_name": "zaptrace",
        "server_version": "0.3.0",
    }


def test_parse_mcp_discover_response_rejects_error_payload() -> None:
    module = _module()

    with pytest.raises(RuntimeError, match="successful server/discover result"):
        module.parse_mcp_discover_response(b'{"jsonrpc":"2.0","id":1,"error":{"code":-1}}')


def test_execute_always_collects_logs_and_tears_down(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _module()
    calls: list[tuple[str, ...]] = []
    secret_value = secrets.token_urlsafe(32)

    monkeypatch.setattr(module, "SUMMARY_PATH", tmp_path / "summary.json")
    monkeypatch.setattr(module, "LOG_PATH", tmp_path / "compose.log")
    monkeypatch.setattr(module, "find_free_port", lambda: 18080 if not calls else 18090)

    def fake_compose(args: list[str], *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(args))
        if args == ["build"]:
            raise RuntimeError(f"build failed with {secret_value}")
        if args == ["logs", "--no-color", "--timestamps"]:
            return subprocess.CompletedProcess(args, 0, f"service log {secret_value}", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(module, "compose", fake_compose)
    monkeypatch.setattr(module, "generate_token", lambda: secret_value)

    report = module.execute()

    assert report["passed"] is False
    assert ("logs", "--no-color", "--timestamps") in calls
    assert ("down", "--volumes", "--remove-orphans") in calls
    assert secret_value not in module.SUMMARY_PATH.read_text(encoding="utf-8")
    assert secret_value not in module.LOG_PATH.read_text(encoding="utf-8")


def test_startup_failure_requires_nonzero_and_auth_diagnostic() -> None:
    module = _module()
    expected = subprocess.CompletedProcess(
        ["docker", "compose"],
        1,
        "",
        "ZapTrace REST API refuses non-loopback bind '0.0.0.0' without authentication",
    )

    assert module.startup_failure_evidence("zaptrace-api", expected)["passed"] is True

    unexpected_success = subprocess.CompletedProcess([], 0, "", "")
    with pytest.raises(RuntimeError, match="unexpectedly started"):
        module.startup_failure_evidence("zaptrace-api", unexpected_success)


def test_oauth_smoke_environment_is_public_configuration_only() -> None:
    module = _module()
    environment = module.oauth_smoke_environment(
        {
            "ZAPTRACE_MCP_HTTP_TOKEN": "static-secret",
            "ZAPTRACE_MCP_TOKEN_SUBJECT": "legacy-subject",
            "UNCHANGED": "yes",
        }
    )

    assert environment["ZAPTRACE_MCP_HTTP_TOKEN"] == ""
    assert environment["ZAPTRACE_MCP_TOKEN_SUBJECT"] == ""
    assert environment["ZAPTRACE_MCP_AUTH_CONFIG_VERSION"] == "1"
    assert environment["ZAPTRACE_MCP_AUTH_PROFILE"] == "oauth-jwt"
    assert environment["ZAPTRACE_MCP_PUBLIC_BASE_URL"] == "https://mcp.example.com"
    assert environment["ZAPTRACE_MCP_AUTH_RESOURCE_URI"] == "https://mcp.example.com/mcp"
    assert environment["ZAPTRACE_MCP_AUTHORIZATION_SERVER"] == "https://auth.example.com/"
    assert environment["ZAPTRACE_MCP_AUTH_JWKS_URI"] == "https://auth.example.com/.well-known/jwks.json"
    assert environment["UNCHANGED"] == "yes"
    assert "static-secret" not in repr(environment)
    assert "legacy-subject" not in repr(environment)


def test_mcp_oauth_profile_checks_validate_discovery_and_missing_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    calls: list[tuple[str, str]] = []

    def fake_http_request(
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        payload: bytes | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        del headers, payload
        calls.append((method, url))
        if url.endswith("/.well-known/oauth-protected-resource/mcp"):
            return (
                200,
                b'{"resource":"https://mcp.example.com/mcp","authorization_servers":["https://auth.example.com/"],"scopes_supported":["zaptrace:read"]}',
                {},
            )
        return (
            401,
            b'{"ok":false,"error":{"code":"AUTH_REQUIRED"}}',
            {
                "www-authenticate": (
                    'Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp", '
                    'scope="zaptrace:read"'
                )
            },
        )

    monkeypatch.setattr(module, "http_request", fake_http_request)
    result = module.mcp_oauth_profile_checks(18090)

    assert result["passed"] is True
    assert result["provider_type"] == "RemoteAuthProvider/JWTVerifier"
    assert result["profile"] == "oauth-jwt"
    assert result["discovery_status"] == 200
    assert result["missing_token_status"] == 401
    assert result["denial_cases"] == ["missing_authorization_header"]
    assert calls == [
        ("GET", "http://127.0.0.1:18090/.well-known/oauth-protected-resource/mcp"),
        ("POST", "http://127.0.0.1:18090/mcp"),
    ]


def test_main_prints_only_bounded_evidence_pointer(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    sentinel = "must-not-reach-console"
    monkeypatch.setattr(
        module,
        "execute",
        lambda: {
            "gate_id": "compose-runtime-smoke-v1",
            "passed": False,
            "error": sentinel,
            "checks": {"diagnostic": sentinel},
        },
    )

    assert module.main() == 1
    output = capsys.readouterr().out
    assert sentinel not in output
    assert json.loads(output) == {
        "gate_id": "compose-runtime-smoke-v1",
        "passed": False,
        "summary_path": "artifacts/compose-smoke/summary.json",
    }
