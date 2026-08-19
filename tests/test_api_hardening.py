from __future__ import annotations

from fastapi.testclient import TestClient

from zaptrace.api.server import create_app

WRITE_HEADERS = {
    "X-ZapTrace-Session-Id": "api-hardening-session",
    "X-ZapTrace-Capabilities": "preview-write",
    "X-ZapTrace-Actor": "pytest",
    "X-ZapTrace-Reason": "artifact lifecycle test",
}
SANDBOX_HEADERS = {
    "X-ZapTrace-Session-Id": "api-hardening-session",
    "X-ZapTrace-Capabilities": "sandbox-write",
    "X-ZapTrace-Actor": "pytest",
}


def test_optional_bearer_auth_is_enforced_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("ZAPTRACE_API_TOKEN", "secret-token")
    client = TestClient(create_app())

    denied = client.get("/api/v1/library/categories")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "AUTH_REQUIRED"

    allowed = client.get("/api/v1/library/categories", headers={"Authorization": "Bearer secret-token"})
    assert allowed.status_code == 200


def test_openapi_schema_exposes_hardened_artifact_lifecycle(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ZAPTRACE_API_TOKEN", raising=False)
    monkeypatch.setenv("ZAPTRACE_API_ARTIFACT_ROOT", str(tmp_path))
    client = TestClient(create_app())

    schema = client.get("/openapi.json").json()

    assert "/api/v1/artifacts" in schema["paths"]
    assert "/api/v1/artifacts/{artifact_id}" in schema["paths"]
    assert "/api/v1/artifacts/expired" in schema["paths"]
    assert "/api/v1/artifacts/config" in schema["paths"]
    assert "/api/v1/agent/sessions" in schema["paths"]
    assert "/api/v1/agent/sessions/{session_id}/access" in schema["paths"]
    assert "/api/v1/agent/sessions/{session_id}/delegates/{delegate_principal}" in schema["paths"]


def test_artifact_lifecycle_store_list_delete_and_cleanup(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ZAPTRACE_API_TOKEN", raising=False)
    monkeypatch.setenv("ZAPTRACE_API_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ZAPTRACE_API_ARTIFACT_RETENTION_SECONDS", "0")
    client = TestClient(create_app())

    config = client.get("/api/v1/artifacts/config")
    assert config.status_code == 200
    assert config.json()["artifact_root"] == str(tmp_path.resolve())

    created = client.post(
        "/api/v1/artifacts",
        json={"filename": "report.md", "kind": "proof-report", "content": "# Proof\n"},
        headers=WRITE_HEADERS,
    )
    assert created.status_code == 200
    artifact = created.json()["artifact"]
    assert artifact["filename"] == "report.md"
    assert artifact["kind"] == "proof-report"
    assert artifact["size_bytes"] == len(b"# Proof\n")
    assert len(artifact["sha256"]) == 64

    listed = client.get("/api/v1/artifacts", headers={"X-ZapTrace-Session-Id": "api-hardening-session"})
    assert listed.status_code == 200
    assert listed.json()["count"] == 1

    cleanup = client.delete("/api/v1/artifacts/expired", headers=SANDBOX_HEADERS)
    assert cleanup.status_code == 200
    assert cleanup.json()["deleted_count"] == 1

    created_again = client.post(
        "/api/v1/artifacts",
        json={"filename": "report.md", "kind": "proof-report", "content": "# Proof\n"},
        headers=WRITE_HEADERS,
    ).json()["artifact"]
    deleted = client.delete(f"/api/v1/artifacts/{created_again['artifact_id']}", headers=SANDBOX_HEADERS)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"]["artifact_id"] == created_again["artifact_id"]


def test_bearer_token_scopes_override_spoofed_capability_header(monkeypatch) -> None:
    monkeypatch.setenv("ZAPTRACE_API_TOKEN", "scoped-token")
    monkeypatch.delenv("ZAPTRACE_API_TOKEN_SCOPES", raising=False)
    client = TestClient(create_app())

    denied = client.post(
        "/api/v1/designs/parse/str",
        params={"yaml_content": "meta:\n  name: TokenScopeDenied\n"},
        headers={
            "Authorization": "Bearer scoped-token",
            "X-ZapTrace-Session-Id": "token-scope-session",
            "X-ZapTrace-Capabilities": "preview-write release-export",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "OPERATION_NOT_AUTHORIZED"


def test_bearer_token_scope_audience_and_session_are_enforced(monkeypatch) -> None:
    monkeypatch.setenv("ZAPTRACE_API_TOKEN", "scoped-token")
    monkeypatch.setenv("ZAPTRACE_API_TOKEN_SCOPES", "preview-write")
    monkeypatch.setenv("ZAPTRACE_API_TOKEN_AUDIENCE", "zaptrace-api")
    monkeypatch.setenv("ZAPTRACE_API_TOKEN_SUBJECT", "ci-bot")
    monkeypatch.setenv("ZAPTRACE_API_TOKEN_SESSIONS", "allowed-session")
    client = TestClient(create_app())

    wrong_audience = client.get(
        "/api/v1/library/categories",
        headers={"Authorization": "Bearer scoped-token", "X-ZapTrace-Audience": "other"},
    )
    assert wrong_audience.status_code == 403
    assert wrong_audience.json()["error"]["code"] == "AUTH_AUDIENCE_MISMATCH"

    wrong_session = client.post(
        "/api/v1/designs/parse/str",
        params={"yaml_content": "meta:\n  name: WrongSession\n"},
        headers={
            "Authorization": "Bearer scoped-token",
            "X-ZapTrace-Audience": "zaptrace-api",
            "X-ZapTrace-Session-Id": "other-session",
        },
    )
    assert wrong_session.status_code == 403
    assert wrong_session.json()["detail"]["code"] == "OBJECT_NOT_AUTHORIZED"

    allowed = client.post(
        "/api/v1/designs/parse/str",
        params={"yaml_content": "meta:\n  name: AllowedTokenDesign\n"},
        headers={
            "Authorization": "Bearer scoped-token",
            "X-ZapTrace-Audience": "zaptrace-api",
            "X-ZapTrace-Session-Id": "allowed-session",
        },
    )
    assert allowed.status_code == 200
