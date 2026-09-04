#!/usr/bin/env python3
"""Exercise the packaged REST and MCP HTTP services through Docker Compose."""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.example"
ARTIFACT_DIR = ROOT / "artifacts" / "compose-smoke"
SUMMARY_PATH = ARTIFACT_DIR / "summary.json"
LOG_PATH = ARTIFACT_DIR / "compose.log"
_MAX_LOG_BYTES = 128 * 1024
_OAUTH_PUBLIC_BASE_URL = "https://mcp.example.com"
_OAUTH_RESOURCE_URI = "https://mcp.example.com/mcp"
_OAUTH_AUTHORIZATION_SERVER = "https://auth.example.com/"
_OAUTH_JWKS_URI = "https://auth.example.com/.well-known/jwks.json"
_MCP_PROTOCOL_VERSION = "2026-07-28"


def generate_token() -> str:
    """Return an ephemeral bearer token used only by the local smoke run."""
    return secrets.token_urlsafe(48)


def find_free_port() -> int:
    """Reserve and return a currently free host-loopback TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def bounded_log(text: str, *, secrets: tuple[str, ...], limit: int = _MAX_LOG_BYTES) -> str:
    """Redact known secrets and bound UTF-8 log output."""
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    encoded = redacted.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return redacted
    prefix = encoded[:limit].decode("utf-8", errors="ignore")
    return f"{prefix}\n...[truncated]\n"


def package_version() -> str:
    """Read the authoritative package version without importing the project."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(config["project"]["version"])


def compose(
    args: list[str],
    *,
    env: dict[str, str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a fixed Docker Compose subcommand in the repository root."""
    command = ["docker", "compose", "--env-file", str(ENV_FILE), *args]
    completed = subprocess.run(  # noqa: S603
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=900,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = (completed.stdout + "\n" + completed.stderr).strip()
        raise RuntimeError(f"docker compose {' '.join(args)} failed ({completed.returncode}): {detail}")
    return completed


def startup_failure_evidence(service: str, completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Validate the expected missing-authentication startup failure."""
    diagnostic = f"{completed.stdout}\n{completed.stderr}".strip()
    if completed.returncode == 0:
        raise RuntimeError(f"{service} unexpectedly started without its required authentication token")
    if "refuses non-loopback bind" not in diagnostic or "without authentication" not in diagnostic:
        raise RuntimeError(f"{service} failed without the expected authentication diagnostic: {diagnostic}")
    return {
        "passed": True,
        "service": service,
        "returncode": completed.returncode,
        "diagnostic": diagnostic[-2048:],
    }


def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: bytes | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    """Perform one bounded smoke request and return HTTP error responses normally."""
    request = urllib.request.Request(url, data=payload, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            return response.status, response.read(1024 * 1024), response_headers
    except urllib.error.HTTPError as exc:
        response_headers = {key.lower(): value for key, value in exc.headers.items()}
        return exc.code, exc.read(1024 * 1024), response_headers


def mcp_discover_payload(client_name: str) -> bytes:
    """Return one modern MCP server/discover request body."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": _MCP_PROTOCOL_VERSION,
                    "io.modelcontextprotocol/clientInfo": {"name": client_name, "version": "1"},
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
            },
        },
        separators=(",", ":"),
    ).encode()


def mcp_protocol_headers() -> dict[str, str]:
    """Return headers required by the modern streamable-HTTP protocol path."""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": _MCP_PROTOCOL_VERSION,
        "Mcp-Method": "server/discover",
    }


def parse_mcp_discover_response(payload: bytes) -> dict[str, str]:
    """Extract server identity from a modern server/discover response."""
    try:
        message = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("MCP response did not contain a successful server/discover result") from exc
    result = message.get("result") if isinstance(message, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError("MCP response did not contain a successful server/discover result")
    supported = result.get("supportedVersions")
    metadata = result.get("_meta")
    server_info = metadata.get("io.modelcontextprotocol/serverInfo") if isinstance(metadata, dict) else None
    if not isinstance(supported, list) or _MCP_PROTOCOL_VERSION not in supported or not isinstance(server_info, dict):
        raise RuntimeError("MCP response did not contain a successful server/discover result")
    return {
        "protocol_version": _MCP_PROTOCOL_VERSION,
        "server_name": str(server_info.get("name", "")),
        "server_version": str(server_info.get("version", "")),
    }


def _missing_token_probe(service: str, token_name: str, env: dict[str, str]) -> dict[str, Any]:
    probe_env = dict(env)
    probe_env[token_name] = ""
    completed = compose(["run", "--rm", "--no-deps", service], env=probe_env, check=False)
    return startup_failure_evidence(service, completed)


def oauth_smoke_environment(env: dict[str, str]) -> dict[str, str]:
    """Return a public-configuration-only OAuth profile environment for Compose smoke."""
    oauth_env = dict(env)
    oauth_env.update(
        {
            "ZAPTRACE_MCP_HTTP_TOKEN": "",
            "ZAPTRACE_MCP_TOKEN_SUBJECT": "",
            "ZAPTRACE_MCP_AUTH_CONFIG_VERSION": "1",
            "ZAPTRACE_MCP_AUTH_PROFILE": "oauth-jwt",
            "ZAPTRACE_MCP_PUBLIC_BASE_URL": _OAUTH_PUBLIC_BASE_URL,
            "ZAPTRACE_MCP_AUTH_RESOURCE_URI": _OAUTH_RESOURCE_URI,
            "ZAPTRACE_MCP_AUTHORIZATION_SERVER": _OAUTH_AUTHORIZATION_SERVER,
            "ZAPTRACE_MCP_AUTH_JWKS_URI": _OAUTH_JWKS_URI,
        }
    )
    return oauth_env


def mcp_oauth_profile_checks(port: int) -> dict[str, Any]:
    """Probe packaged OAuth discovery and missing-bearer denial without signing material."""
    base = f"http://127.0.0.1:{port}"
    discovery_status, discovery_body, _ = http_request(f"{base}/.well-known/oauth-protected-resource/mcp")
    metadata = json.loads(discovery_body)
    if (
        discovery_status != 200
        or metadata.get("resource") != _OAUTH_RESOURCE_URI
        or metadata.get("authorization_servers") != [_OAUTH_AUTHORIZATION_SERVER]
        or "zaptrace:read" not in metadata.get("scopes_supported", [])
    ):
        raise RuntimeError(f"MCP OAuth discovery returned unexpected response: {discovery_status} {metadata}")

    discover = mcp_discover_payload("zaptrace-oauth-compose-smoke")
    missing_status, missing_body, missing_headers = http_request(
        f"{base}/mcp",
        method="POST",
        headers=mcp_protocol_headers(),
        payload=discover,
    )
    missing = json.loads(missing_body)
    challenge = missing_headers.get("www-authenticate", "")
    if (
        missing_status != 401
        or missing.get("error", {}).get("code") != "AUTH_REQUIRED"
        or "resource_metadata=" not in challenge
        or 'scope="zaptrace:read"' not in challenge
    ):
        raise RuntimeError(
            "MCP OAuth missing-bearer smoke returned unexpected response: "
            f"status={missing_status}, body={missing}, challenge={challenge!r}"
        )

    return {
        "passed": True,
        "profile": "oauth-jwt",
        "provider_type": "RemoteAuthProvider/JWTVerifier",
        "algorithm": "RS256",
        "configuration_identity": {
            "resource": _OAUTH_RESOURCE_URI,
            "authorization_server": _OAUTH_AUTHORIZATION_SERVER,
            "jwks_uri": _OAUTH_JWKS_URI,
        },
        "discovery_status": discovery_status,
        "missing_token_status": missing_status,
        "denial_cases": ["missing_authorization_header"],
    }


def _api_checks(port: int, token: str) -> dict[str, Any]:
    base = f"http://127.0.0.1:{port}"
    health_status, health_body, _ = http_request(f"{base}/health")
    health = json.loads(health_body)
    if health_status != 200 or health.get("status") != "ok" or health.get("version") != package_version():
        raise RuntimeError(f"REST health check returned unexpected response: {health_status} {health}")

    missing_status, _, _ = http_request(f"{base}/api/v1/library/categories")
    invalid_status, _, _ = http_request(
        f"{base}/api/v1/library/categories",
        headers={"Authorization": "Bearer invalid-token"},
    )
    valid_status, valid_body, _ = http_request(
        f"{base}/api/v1/library/categories",
        headers={"Authorization": f"Bearer {token}"},
    )
    if (missing_status, invalid_status, valid_status) != (401, 401, 200):
        raise RuntimeError(
            "REST authorization smoke returned unexpected statuses: "
            f"missing={missing_status}, invalid={invalid_status}, valid={valid_status}"
        )
    return {
        "passed": True,
        "health_status": health_status,
        "version": str(health["version"]),
        "missing_token_status": missing_status,
        "invalid_token_status": invalid_status,
        "valid_token_status": valid_status,
        "valid_response_bytes": len(valid_body),
    }


def _mcp_checks(port: int, token: str) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}/mcp"
    payload = mcp_discover_payload("zaptrace-compose-smoke")
    protocol_headers = mcp_protocol_headers()
    missing_status, _, _ = http_request(url, method="POST", headers=protocol_headers, payload=payload)
    invalid_status, _, _ = http_request(
        url,
        method="POST",
        headers={**protocol_headers, "Authorization": "Bearer invalid"},
        payload=payload,
    )
    valid_status, valid_body, valid_headers = http_request(
        url,
        method="POST",
        headers={**protocol_headers, "Authorization": f"Bearer {token}"},
        payload=payload,
    )
    if (missing_status, invalid_status, valid_status) != (401, 401, 200):
        raise RuntimeError(
            "MCP authorization smoke returned unexpected statuses: "
            f"missing={missing_status}, invalid={invalid_status}, valid={valid_status}"
        )
    if "mcp-session-id" in valid_headers:
        raise RuntimeError("Modern MCP response unexpectedly returned a transport session header")
    identity = parse_mcp_discover_response(valid_body)
    if identity["server_name"] != "zaptrace" or identity["server_version"] != package_version():
        raise RuntimeError(f"MCP server/discover returned unexpected server identity: {identity}")

    return {
        "passed": True,
        "missing_token_status": missing_status,
        "invalid_token_status": invalid_status,
        "valid_token_status": valid_status,
        "transport_session_header_present": False,
        **identity,
    }


def _write_report(report: dict[str, Any]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def execute() -> dict[str, Any]:
    """Run the complete Compose smoke lifecycle and always retain bounded evidence."""
    api_token = generate_token()
    mcp_token = generate_token()
    secrets_to_redact = (api_token, mcp_token)
    api_port = find_free_port()
    mcp_port = find_free_port()
    if mcp_port == api_port:
        mcp_port = api_port + 1 if api_port < 65535 else api_port - 1

    env = dict(os.environ)
    env.update(
        {
            "COMPOSE_PROJECT_NAME": f"zaptrace-ci-{os.getpid()}",
            "ZAPTRACE_API_TOKEN": api_token,
            "ZAPTRACE_MCP_HTTP_TOKEN": mcp_token,
            "ZAPTRACE_API_PUBLISHED_PORT": str(api_port),
            "ZAPTRACE_MCP_HTTP_PUBLISHED_PORT": str(mcp_port),
        }
    )
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "gate_id": "compose-runtime-smoke-v1",
        "passed": False,
        "package_version": package_version(),
        "services": ["zaptrace-api", "zaptrace-mcp-http"],
        "published_ports": {"api": api_port, "mcp_http": mcp_port},
        "checks": {},
    }

    try:
        compose(["build"], env=env)
        report["checks"]["api_missing_token_startup"] = _missing_token_probe("zaptrace-api", "ZAPTRACE_API_TOKEN", env)
        report["checks"]["mcp_missing_token_startup"] = _missing_token_probe(
            "zaptrace-mcp-http", "ZAPTRACE_MCP_HTTP_TOKEN", env
        )
        compose(
            [
                "up",
                "--detach",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "240",
                "zaptrace-api",
                "zaptrace-mcp-http",
            ],
            env=env,
        )
        compose(["--profile", "smoke", "run", "--rm", "zaptrace-ready"], env=env)
        report["checks"]["rest"] = _api_checks(api_port, api_token)
        report["checks"]["mcp_http"] = _mcp_checks(mcp_port, mcp_token)

        compose(["stop", "zaptrace-mcp-http"], env=env)
        oauth_env = oauth_smoke_environment(env)
        compose(
            [
                "up",
                "--detach",
                "--no-build",
                "--no-deps",
                "--force-recreate",
                "--wait",
                "--wait-timeout",
                "120",
                "zaptrace-mcp-http",
            ],
            env=oauth_env,
        )
        report["checks"]["mcp_oauth_profile"] = mcp_oauth_profile_checks(mcp_port)
        report["passed"] = True
    except Exception as exc:  # noqa: BLE001 - CI boundary converts all failures into evidence
        report["error"] = bounded_log(str(exc), secrets=secrets_to_redact, limit=4096).strip()
    finally:
        try:
            logs = compose(["logs", "--no-color", "--timestamps"], env=env, check=False)
            combined_logs = f"{logs.stdout}\n{logs.stderr}".strip()
            ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
            LOG_PATH.write_text(
                bounded_log(combined_logs, secrets=secrets_to_redact) + "\n",
                encoding="utf-8",
            )
            report["logs_returncode"] = logs.returncode
        except Exception as exc:  # noqa: BLE001 - evidence capture must not skip teardown
            report["logs_error"] = bounded_log(str(exc), secrets=secrets_to_redact, limit=2048).strip()
        try:
            cleanup = compose(["down", "--volumes", "--remove-orphans"], env=env, check=False)
            report["cleanup_returncode"] = cleanup.returncode
            if cleanup.returncode != 0:
                report["passed"] = False
        except Exception as exc:  # noqa: BLE001 - preserve the original failure and report cleanup
            report["cleanup_error"] = bounded_log(str(exc), secrets=secrets_to_redact, limit=2048).strip()
            report["passed"] = False
        _write_report(report)

    return report


def main() -> int:
    report = execute()
    passed = report.get("passed") is True
    print(
        json.dumps(
            {
                "gate_id": "compose-runtime-smoke-v1",
                "passed": passed,
                "summary_path": SUMMARY_PATH.relative_to(ROOT).as_posix(),
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
