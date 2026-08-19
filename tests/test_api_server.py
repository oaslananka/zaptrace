"""Tests for FastAPI REST API server."""

from __future__ import annotations

from fastapi.testclient import TestClient

from zaptrace import __version__
from zaptrace.api.server import app

client = TestClient(app)

PREVIEW_HEADERS = {
    "X-ZapTrace-Session-Id": "api-test-session",
    "X-ZapTrace-Capabilities": "preview-write",
    "X-ZapTrace-Actor": "pytest",
    "X-ZapTrace-Reason": "test preview-write operation",
}
SANDBOX_HEADERS = {
    "X-ZapTrace-Session-Id": "api-test-session",
    "X-ZapTrace-Capabilities": "release-export",
    "X-ZapTrace-Actor": "pytest",
    "X-ZapTrace-Reason": "test release-export operation",
}
APPROVED_HEADERS = {
    "X-ZapTrace-Session-Id": "api-tx-session",
    "X-ZapTrace-Capabilities": "approved-commit",
    "X-ZapTrace-Actor": "pytest",
    "X-ZapTrace-Reason": "test approved transaction commit",
}


class TestHealth:
    def test_health_ok(self) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == __version__


class TestDesigns:
    def test_parse_str(self) -> None:
        yaml = """meta:
  name: APITest
components:
  r1:
    ref: R1
    type: resistor
"""
        resp = client.post("/api/v1/designs/parse/str", params={"yaml_content": yaml}, headers=PREVIEW_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["design_name"] == "APITest"

    def test_inspect_not_found(self) -> None:
        resp = client.get("/api/v1/designs/nonexistent")
        assert resp.status_code == 404


class TestERC:
    def test_list_rules(self) -> None:
        resp = client.get("/api/v1/erc/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert "rules" in data
        assert len(data["rules"]) >= 20


class TestLibrary:
    def test_search(self) -> None:
        resp = client.get("/api/v1/library/search", params={"query": "esp32"})
        assert resp.status_code == 200

    def test_categories(self) -> None:
        resp = client.get("/api/v1/library/categories")
        assert resp.status_code == 200


class TestPipeline:
    def test_templates(self) -> None:
        resp = client.get("/api/v1/pipeline/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 8

    def test_synthesize(self) -> None:
        resp = client.post(
            "/api/v1/pipeline/synthesize", params={"intent": "esp32 i2c sensor"}, headers=PREVIEW_HEADERS
        )
        assert resp.status_code == 200


class TestSecurityPolicy:
    def test_missing_session_blocks_mutating_request(self) -> None:
        resp = client.post("/api/v1/designs/parse/str", params={"yaml_content": "meta:\n  name: MissingSession\n"})
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "SESSION_REQUIRED"

    def test_missing_capability_blocks_write_request_and_records_audit(self) -> None:
        headers = {"X-ZapTrace-Session-Id": "api-denied-session", "X-ZapTrace-Actor": "pytest"}
        resp = client.post(
            "/api/v1/designs/parse/str",
            params={"yaml_content": "meta:\n  name: DeniedDesign\n"},
            headers=headers,
        )
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == "OPERATION_NOT_AUTHORIZED"
        assert detail["required_capability"] == "preview-write"

        audit = client.get("/api/v1/audit/events", headers={"X-ZapTrace-Session-Id": "api-denied-session"})
        assert audit.status_code == 200
        events = audit.json()["events"]
        assert events[-1]["decision"] == "deny"
        assert events[-1]["tool"] == "design_parse_str"

    def test_path_traversal_parse_file_is_rejected(self) -> None:
        resp = client.post(
            "/api/v1/designs/parse/file",
            params={"path": "../../../etc/passwd"},
            headers=PREVIEW_HEADERS,
        )
        assert resp.status_code == 400
        assert "Path outside workspace" in resp.json()["detail"] or "Path not found" in resp.json()["detail"]

    def test_unsafe_release_export_path_is_rejected(self) -> None:
        yaml = """meta:
  name: ExportPolicyTest
components:
  r1:
    ref: R1
    type: resistor
"""
        parsed = client.post("/api/v1/designs/parse/str", params={"yaml_content": yaml}, headers=PREVIEW_HEADERS)
        assert parsed.status_code == 200
        resp = client.post(
            "/api/v1/export/ExportPolicyTest/kicad",
            params={"output_dir": "../../../tmp/zaptrace-escape", "approval_id": "path-test-approval"},
            headers=SANDBOX_HEADERS,
        )
        assert resp.status_code == 400
        assert "Path outside workspace" in resp.json()["detail"]

    def test_allowed_mutation_records_allow_audit_event(self) -> None:
        headers = {
            "X-ZapTrace-Session-Id": "api-allowed-session",
            "X-ZapTrace-Capabilities": "preview-write",
            "X-ZapTrace-Actor": "pytest",
            "X-ZapTrace-Reason": "audit allow example",
        }
        resp = client.post(
            "/api/v1/designs/parse/str",
            params={"yaml_content": "meta:\n  name: AllowedDesign\n"},
            headers=headers,
        )
        assert resp.status_code == 200
        audit = client.get("/api/v1/audit/events", headers={"X-ZapTrace-Session-Id": "api-allowed-session"})
        assert audit.status_code == 200
        events = audit.json()["events"]
        assert events[-1]["decision"] == "allow"
        assert events[-1]["actor"] == "pytest"
        assert events[-1]["reason"] == "audit allow example"


class TestTransactions:
    def test_rest_transaction_preview_validate_commit_flow(self) -> None:
        yaml = """meta:
  name: RestTx
components:
  r1:
    ref: R1
    type: resistor
    value: 10k
"""
        preview_headers = {
            "X-ZapTrace-Session-Id": "api-tx-session",
            "X-ZapTrace-Capabilities": "preview-write",
            "X-ZapTrace-Actor": "pytest",
        }
        sandbox_headers = {
            "X-ZapTrace-Session-Id": "api-tx-session",
            "X-ZapTrace-Capabilities": "sandbox-write",
            "X-ZapTrace-Actor": "pytest",
        }

        parsed = client.post("/api/v1/designs/parse/str", params={"yaml_content": yaml}, headers=preview_headers)
        assert parsed.status_code == 200

        preview = client.post(
            "/api/v1/designs/RestTx/transactions/preview",
            json={"operation": "board_update", "params": {"width_mm": 125}, "reason": "try wider board"},
            headers=preview_headers,
        )
        assert preview.status_code == 200
        preview_data = preview.json()
        assert preview_data["state"] == "previewed"
        assert preview_data["semantic_diff"][0]["type"] == "board_changed"

        tx_id = preview_data["transaction_id"]
        validated = client.post(f"/api/v1/designs/transactions/{tx_id}/validate", headers=sandbox_headers)
        assert validated.status_code == 200
        assert validated.json()["state"] == "validated"

        committed = client.post(
            f"/api/v1/designs/transactions/{tx_id}/commit",
            json={"approval_id": "approval-rest-1"},
            headers=APPROVED_HEADERS,
        )
        assert committed.status_code == 200
        assert committed.json()["state"] == "committed"

        inspected = client.get("/api/v1/designs/RestTx", headers={"X-ZapTrace-Session-Id": "api-tx-session"})
        assert inspected.status_code == 200
        assert inspected.json()["board"]["width_mm"] == 125

    def test_rest_transaction_commit_without_approval_is_rejected(self) -> None:
        yaml = "meta:\n  name: RestTxReject\ncomponents: {}\n"
        preview_headers = {"X-ZapTrace-Session-Id": "api-tx-reject", "X-ZapTrace-Capabilities": "preview-write"}
        sandbox_headers = {"X-ZapTrace-Session-Id": "api-tx-reject", "X-ZapTrace-Capabilities": "sandbox-write"}
        approved_headers = {"X-ZapTrace-Session-Id": "api-tx-reject", "X-ZapTrace-Capabilities": "approved-commit"}
        assert (
            client.post("/api/v1/designs/parse/str", params={"yaml_content": yaml}, headers=preview_headers).status_code
            == 200
        )
        preview = client.post(
            "/api/v1/designs/RestTxReject/transactions/preview",
            json={"operation": "board_update", "params": {"layers": 4}},
            headers=preview_headers,
        )
        tx_id = preview.json()["transaction_id"]
        assert client.post(f"/api/v1/designs/transactions/{tx_id}/validate", headers=sandbox_headers).status_code == 200
        resp = client.post(
            f"/api/v1/designs/transactions/{tx_id}/commit",
            json={"approval_id": ""},
            headers=approved_headers,
        )
        assert resp.status_code == 400
        assert "approval_id is required" in resp.json()["detail"]
