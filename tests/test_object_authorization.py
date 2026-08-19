"""Integration tests for object-level session authorization."""

from __future__ import annotations

import json
from pathlib import Path
from secrets import token_hex

import pytest
from fastapi.testclient import TestClient

import zaptrace.mcp.server as mcp_server
from zaptrace.agent._tool_impls import _sessions
from zaptrace.api.server import create_app
from zaptrace.api.storage import ArtifactStore
from zaptrace.review.workflow import _REVIEW_SESSIONS, create_review_session
from zaptrace.security.objects import (
    ObjectAccessDeniedError,
    ObjectAccessRecord,
    RequestPrincipal,
    _direct_access_decision,
    authorize_object,
    delegate_object_access,
    get_object_access,
    object_authorization_events,
    remove_object_access,
    reset_object_authorization_state,
    revoke_object_access,
)
from zaptrace.security.replay import _session_logs, record_tool_call
from zaptrace.security.sandbox import _sandboxes


@pytest.fixture
def authorized_api(monkeypatch: pytest.MonkeyPatch, tmp_path):
    reset_object_authorization_state()
    _sessions.clear()
    _REVIEW_SESSIONS.clear()
    _sandboxes.clear()
    _session_logs.clear()

    api_token = token_hex(32)
    monkeypatch.setenv("ZAPTRACE_API_TOKEN", api_token)
    monkeypatch.setenv("ZAPTRACE_API_TOKEN_SESSIONS", "*")
    monkeypatch.setenv("ZAPTRACE_API_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    return TestClient(create_app()), api_token


def _identity(
    monkeypatch: pytest.MonkeyPatch,
    *,
    actor: str,
    scopes: str,
) -> None:
    monkeypatch.setenv("ZAPTRACE_API_TOKEN_SUBJECT", actor)
    monkeypatch.setenv("ZAPTRACE_API_TOKEN_SCOPES", scopes)


def _auth_headers(api_token: str, *, session_id: str | None = None, request_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_token}"}
    if session_id is not None:
        headers["X-ZapTrace-Session-Id"] = session_id
    if request_id is not None:
        headers["X-Request-ID"] = request_id
    return headers


def _create_session(client: TestClient, api_token: str) -> str:
    response = client.post("/api/v1/agent/sessions", headers=_auth_headers(api_token))
    assert response.status_code == 200, response.text
    return str(response.json()["session_id"])


def _load_design(client: TestClient, api_token: str, session_id: str, name: str = "OwnedDesign") -> None:
    response = client.post(
        "/api/v1/designs/parse/str",
        params={"yaml_content": f"meta:\n  name: {name}\n"},
        headers=_auth_headers(api_token, session_id=session_id),
    )
    assert response.status_code == 200, response.text


def test_api_session_ids_are_opaque_and_unique(authorized_api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, api_token = authorized_api
    _identity(monkeypatch, actor="owner-a", scopes="preview-write")

    first = _create_session(client, api_token)
    second = _create_session(client, api_token)

    assert first.startswith("api-")
    assert second.startswith("api-")
    assert len(first) > 30
    assert first != second


def test_review_session_ids_are_opaque_and_unique() -> None:
    first = create_review_session("FirstReview")
    second = create_review_session("SecondReview")

    assert first.session_id.startswith("session-")
    assert second.session_id.startswith("session-")
    assert len(first.session_id) > 30
    assert first.session_id != second.session_id


def test_artifact_store_isolates_normalized_session_selector_collisions(tmp_path) -> None:
    store = ArtifactStore(root=tmp_path)
    first = store.store_text("team/a", filename="proof.txt", kind="proof", content="first")
    second = store.store_text("team-a", filename="proof.txt", kind="proof", content="second")

    assert first.path != second.path
    assert [record.sha256 for record in store.list_artifacts("team/a")] == [first.sha256]
    assert [record.sha256 for record in store.list_artifacts("team-a")] == [second.sha256]


def test_artifact_store_rejects_manifest_with_mismatched_session_id(tmp_path) -> None:
    store = ArtifactStore(root=tmp_path)
    record = store.store_text("owned-session", filename="proof.txt", kind="proof", content="evidence")
    manifest_path = tmp_path / Path(record.path).parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["session_id"] = "other-session"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert store.list_artifacts("owned-session") == []
    assert store.delete_artifact("owned-session", record.artifact_id) is None
    assert manifest_path.exists()


def test_guessed_session_id_cannot_read_or_mutate_sandbox(authorized_api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, api_token = authorized_api
    _identity(monkeypatch, actor="owner-a", scopes="preview-write sandbox-write")
    session_id = _create_session(client, api_token)

    owner_status = client.get(f"/api/v1/agent/sandbox/{session_id}/status", headers=_auth_headers(api_token))
    assert owner_status.status_code == 200

    _identity(monkeypatch, actor="intruder-b", scopes="preview-write sandbox-write")
    for method, path in [
        ("get", f"/api/v1/agent/sandbox/{session_id}/status"),
        ("post", f"/api/v1/agent/sandbox/{session_id}/stop"),
        ("post", f"/api/v1/agent/sandbox/{session_id}/reset"),
        ("post", f"/api/v1/agent/sandbox/{session_id}/clear"),
    ]:
        response = getattr(client, method)(path, headers=_auth_headers(api_token))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "OBJECT_NOT_AUTHORIZED"


def test_owner_can_stop_reset_and_clear_own_sandbox(authorized_api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, api_token = authorized_api
    _identity(monkeypatch, actor="owner-a", scopes="preview-write sandbox-write")
    session_id = _create_session(client, api_token)

    stopped = client.post(f"/api/v1/agent/sandbox/{session_id}/stop", headers=_auth_headers(api_token))
    reset = client.post(f"/api/v1/agent/sandbox/{session_id}/reset", headers=_auth_headers(api_token))
    cleared = client.post(f"/api/v1/agent/sandbox/{session_id}/clear", headers=_auth_headers(api_token))

    assert stopped.status_code == 200
    assert reset.status_code == 200
    assert cleared.status_code == 200


def test_session_delegation_requires_approved_commit_capability(
    authorized_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, api_token = authorized_api
    _identity(monkeypatch, actor="owner-a", scopes="preview-write")
    session_id = _create_session(client, api_token)

    denied = client.post(
        f"/api/v1/agent/sessions/{session_id}/delegates/reviewer-b",
        headers=_auth_headers(api_token),
    )

    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "OPERATION_NOT_AUTHORIZED"


def test_session_delegation_is_inherited_by_review_objects(authorized_api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, api_token = authorized_api
    _identity(monkeypatch, actor="owner-a", scopes="preview-write sandbox-write approved-commit")
    owner_session = _create_session(client, api_token)
    _load_design(client, api_token, owner_session)

    review = client.post(
        "/api/v1/review/session/OwnedDesign",
        headers=_auth_headers(api_token, session_id=owner_session),
    )
    assert review.status_code == 200, review.text
    review_id = review.json()["session"]["session_id"]

    delegated = client.post(
        f"/api/v1/agent/sessions/{owner_session}/delegates/reviewer-b",
        headers=_auth_headers(api_token),
    )
    assert delegated.status_code == 200, delegated.text

    _identity(monkeypatch, actor="reviewer-b", scopes="sandbox-write")
    read_review = client.get(
        f"/api/v1/review/session/{review_id}",
        headers=_auth_headers(api_token, session_id=owner_session),
    )
    assert read_review.status_code == 200, read_review.text

    item_id = next(iter(read_review.json()["session"]["checklist"]))
    approved = client.post(
        f"/api/v1/review/session/{review_id}/checklist/{item_id}/approve",
        headers=_auth_headers(api_token, session_id=owner_session),
    )
    assert approved.status_code == 200, approved.text


def test_session_audit_includes_linked_review_object_decisions(authorized_api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, api_token = authorized_api
    _identity(monkeypatch, actor="owner-a", scopes="preview-write sandbox-write")
    session_id = _create_session(client, api_token)
    _load_design(client, api_token, session_id, name="AuditReviewDesign")
    review = client.post(
        "/api/v1/review/session/AuditReviewDesign",
        headers=_auth_headers(api_token, session_id=session_id),
    )
    assert review.status_code == 200, review.text
    review_id = review.json()["session"]["session_id"]
    item_id = next(iter(review.json()["session"]["checklist"]))

    approved = client.post(
        f"/api/v1/review/session/{review_id}/checklist/{item_id}/approve",
        headers=_auth_headers(api_token, session_id=session_id),
    )
    assert approved.status_code == 200, approved.text

    audit = client.get(
        "/api/v1/audit/events",
        headers=_auth_headers(api_token, session_id=session_id),
    )
    assert audit.status_code == 200, audit.text
    object_events = audit.json()["object_authorization_events"]
    assert any(
        event["object_type"] == "review-session"
        and event["object_id"] == review_id
        and event["parent_object_type"] == "session"
        and event["parent_object_id"] == session_id
        and event["action"] == "approve-review-item"
        and event["decision"] == "allow"
        for event in object_events
    )


def test_review_access_requires_linked_design_session_authorization(
    authorized_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, api_token = authorized_api
    _identity(monkeypatch, actor="owner-a", scopes="preview-write sandbox-write")
    owner_session = _create_session(client, api_token)
    _load_design(client, api_token, owner_session)
    review = client.post(
        "/api/v1/review/session/OwnedDesign",
        headers=_auth_headers(api_token, session_id=owner_session),
    )
    review_id = review.json()["session"]["session_id"]

    _identity(monkeypatch, actor="intruder-b", scopes="preview-write sandbox-write")
    intruder_session = _create_session(client, api_token)
    denied = client.get(
        f"/api/v1/review/session/{review_id}",
        headers=_auth_headers(api_token, session_id=intruder_session),
    )

    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "OBJECT_NOT_AUTHORIZED"


def test_delegate_cannot_grant_access_to_another_principal(authorized_api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, api_token = authorized_api
    _identity(monkeypatch, actor="owner-a", scopes="preview-write approved-commit")
    session_id = _create_session(client, api_token)
    owner_grant = client.post(
        f"/api/v1/agent/sessions/{session_id}/delegates/delegate-b",
        headers=_auth_headers(api_token),
    )
    assert owner_grant.status_code == 200

    _identity(monkeypatch, actor="delegate-b", scopes="approved-commit")
    denied = client.post(
        f"/api/v1/agent/sessions/{session_id}/delegates/third-party-c",
        headers=_auth_headers(api_token),
    )

    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "OBJECT_NOT_AUTHORIZED"


def test_object_admin_can_override_session_ownership(authorized_api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, api_token = authorized_api
    _identity(monkeypatch, actor="owner-a", scopes="preview-write")
    session_id = _create_session(client, api_token)

    _identity(monkeypatch, actor="security-admin", scopes="object-admin sandbox-write")
    status = client.get(f"/api/v1/agent/sandbox/{session_id}/status", headers=_auth_headers(api_token))
    stopped = client.post(f"/api/v1/agent/sandbox/{session_id}/stop", headers=_auth_headers(api_token))

    assert status.status_code == 200
    assert stopped.status_code == 200


def test_design_reads_and_transaction_routes_enforce_session_owner(
    authorized_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, api_token = authorized_api
    _identity(monkeypatch, actor="owner-a", scopes="preview-write sandbox-write")
    session_id = _create_session(client, api_token)
    _load_design(client, api_token, session_id, name="TransactionDesign")

    preview = client.post(
        "/api/v1/designs/TransactionDesign/transactions/preview",
        json={"operation": "board_update", "params": {"width_mm": 75.0}, "reason": "authorization test"},
        headers=_auth_headers(api_token, session_id=session_id),
    )
    assert preview.status_code == 200, preview.text
    transaction = preview.json()
    assert transaction["transaction_id"].startswith("tx-")
    assert len(transaction["transaction_id"]) > 30
    assert transaction["session_id"] == session_id

    _identity(monkeypatch, actor="intruder-b", scopes="preview-write sandbox-write")
    inspected = client.get(
        "/api/v1/designs/TransactionDesign",
        headers=_auth_headers(api_token, session_id=session_id),
    )
    transactions = client.get(
        "/api/v1/designs/transactions/list",
        headers=_auth_headers(api_token, session_id=session_id),
    )

    assert inspected.status_code == 403
    assert transactions.status_code == 403
    assert inspected.json()["detail"]["code"] == "OBJECT_NOT_AUTHORIZED"
    assert transactions.json()["detail"]["code"] == "OBJECT_NOT_AUTHORIZED"


def test_artifact_list_and_delete_enforce_session_owner(authorized_api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, api_token = authorized_api
    _identity(monkeypatch, actor="owner-a", scopes="preview-write sandbox-write")
    session_id = _create_session(client, api_token)
    created = client.post(
        "/api/v1/artifacts",
        json={"filename": "evidence.txt", "kind": "proof", "content": "owned evidence"},
        headers=_auth_headers(api_token, session_id=session_id),
    )
    assert created.status_code == 200, created.text
    artifact = created.json()["artifact"]
    assert artifact["owner_principal"] == "owner-a"

    _identity(monkeypatch, actor="intruder-b", scopes="sandbox-write")
    listed = client.get("/api/v1/artifacts", headers=_auth_headers(api_token, session_id=session_id))
    deleted = client.delete(
        f"/api/v1/artifacts/{artifact['artifact_id']}",
        headers=_auth_headers(api_token, session_id=session_id),
    )

    assert listed.status_code == 403
    assert deleted.status_code == 403


def test_artifact_cleanup_is_scoped_to_current_session(authorized_api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, api_token = authorized_api
    monkeypatch.setenv("ZAPTRACE_API_ARTIFACT_RETENTION_SECONDS", "0")
    _identity(monkeypatch, actor="owner-a", scopes="preview-write sandbox-write")
    first_session = _create_session(client, api_token)
    second_session = _create_session(client, api_token)
    for session_id in (first_session, second_session):
        created = client.post(
            "/api/v1/artifacts",
            json={"filename": f"{session_id}.txt", "kind": "proof", "content": session_id},
            headers=_auth_headers(api_token, session_id=session_id),
        )
        assert created.status_code == 200

    cleaned = client.delete(
        "/api/v1/artifacts/expired",
        headers=_auth_headers(api_token, session_id=first_session),
    )
    remaining = client.get(
        "/api/v1/artifacts",
        headers=_auth_headers(api_token, session_id=second_session),
    )

    assert cleaned.status_code == 200
    assert cleaned.json()["deleted_count"] == 1
    assert remaining.status_code == 200
    assert remaining.json()["count"] == 1


def test_replay_log_requires_session_authorization(authorized_api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, api_token = authorized_api
    _identity(monkeypatch, actor="owner-a", scopes="preview-write")
    session_id = _create_session(client, api_token)
    record_tool_call(session_id, "design_inspect", {}, {"ok": True}, 1.0)

    _identity(monkeypatch, actor="intruder-b", scopes="read")
    denied = client.get(f"/api/v1/agent/replay/{session_id}", headers=_auth_headers(api_token))
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "OBJECT_NOT_AUTHORIZED"


def test_object_authorization_audit_records_principal_target_and_request_id(
    authorized_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, api_token = authorized_api
    _identity(monkeypatch, actor="owner-a", scopes="preview-write")
    session_id = _create_session(client, api_token)

    _identity(monkeypatch, actor="intruder-b", scopes="read")
    request_id = "object-access-attempt"
    denied = client.get(
        f"/api/v1/agent/sandbox/{session_id}/status",
        headers=_auth_headers(api_token, request_id=request_id),
    )
    assert denied.status_code == 403

    event = object_authorization_events(object_type="session", object_id=session_id)[-1]
    assert event["principal_id"] == "intruder-b"
    assert event["object_type"] == "session"
    assert event["object_id"] == session_id
    assert event["action"] == "sandbox-status"
    assert event["decision"] == "deny"
    assert event["request_id"] == request_id


async def test_mcp_session_ids_are_secure_and_cross_principal_destroy_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_object_authorization_state()
    _sessions.clear()
    monkeypatch.setattr(mcp_server, "_HTTP_AUTH_ACTIVE", True)
    monkeypatch.setattr(mcp_server, "_HTTP_AUTH_ACTOR", "mcp-owner")

    created = mcp_server.session_create()
    session_id = created["data"]["session_id"]
    assert session_id.startswith("mcp-")
    assert len(session_id) > 30

    monkeypatch.setattr(mcp_server, "_HTTP_AUTH_ACTOR", "mcp-intruder")
    denied = await mcp_server.session_destroy(session_id)
    assert denied["error"]["code"] == "OBJECT_NOT_AUTHORIZED"


def _principal(principal_id: str, *scopes: str) -> RequestPrincipal:
    return RequestPrincipal(
        principal_id=principal_id,
        actor=principal_id,
        scopes=frozenset(scopes),
        authenticated=True,
    )


def test_object_policy_rejects_empty_ids_and_unregistered_delegation() -> None:
    reset_object_authorization_state()
    owner = _principal("owner-a")

    with pytest.raises(ObjectAccessDeniedError):
        authorize_object(
            object_type="session",
            object_id=" ",
            principal=owner,
            action="read",
            request_id="empty-id",
            allow_claim=True,
        )
    with pytest.raises(ObjectAccessDeniedError):
        delegate_object_access(
            object_type="session",
            object_id="missing",
            principal=owner,
            delegate_principal="delegate-b",
            request_id="missing-delegate",
        )

    events = object_authorization_events(principal_id="owner-a", limit=10)
    assert [event["decision"] for event in events] == ["deny", "deny"]


def test_object_delegation_validates_delegate_and_revoke_authority() -> None:
    reset_object_authorization_state()
    owner = _principal("owner-a")
    delegate = _principal("delegate-b")
    authorize_object(
        object_type="session",
        object_id="owned",
        principal=owner,
        action="create",
        request_id="create",
        allow_claim=True,
    )

    with pytest.raises(ValueError, match="delegate principal is required"):
        delegate_object_access(
            object_type="session",
            object_id="owned",
            principal=owner,
            delegate_principal=" ",
            request_id="empty-delegate",
        )

    delegated = delegate_object_access(
        object_type="session",
        object_id="owned",
        principal=owner,
        delegate_principal="delegate-b",
        request_id="delegate",
    )
    assert delegated.delegates == {"delegate-b"}

    with pytest.raises(ObjectAccessDeniedError):
        revoke_object_access(
            object_type="session",
            object_id="owned",
            principal=delegate,
            delegate_principal="delegate-b",
            request_id="delegate-revoke",
        )
    with pytest.raises(ObjectAccessDeniedError):
        revoke_object_access(
            object_type="session",
            object_id="missing",
            principal=owner,
            delegate_principal="delegate-b",
            request_id="missing-revoke",
        )
    with pytest.raises(ValueError, match="delegate principal is required"):
        revoke_object_access(
            object_type="session",
            object_id="owned",
            principal=owner,
            delegate_principal=" ",
            request_id="empty-revoke",
        )

    denied_events = object_authorization_events(object_type="session", limit=20)
    assert any(
        event["action"] == "revoke-delegate"
        and event["decision"] == "deny"
        and event["request_id"] == "delegate-revoke"
        for event in denied_events
    )
    assert any(
        event["action"] == "revoke-delegate" and event["decision"] == "deny" and event["request_id"] == "missing-revoke"
        for event in denied_events
    )
    assert any(
        event["action"] == "revoke-delegate" and event["decision"] == "deny" and event["request_id"] == "empty-revoke"
        for event in denied_events
    )

    revoked = revoke_object_access(
        object_type="session",
        object_id="owned",
        principal=owner,
        delegate_principal="delegate-b",
        request_id="owner-revoke",
    )
    assert revoked.delegates == set()


def test_object_access_removal_cascades_to_child_records() -> None:
    reset_object_authorization_state()
    owner = _principal("owner-a")
    authorize_object(
        object_type="session",
        object_id="parent",
        principal=owner,
        action="create-parent",
        request_id="parent",
        allow_claim=True,
    )
    authorize_object(
        object_type="review-session",
        object_id="child",
        principal=owner,
        action="create-child",
        request_id="child",
        allow_claim=True,
        parent_object_type="session",
        parent_object_id="parent",
    )

    remove_object_access("session", "parent")

    assert get_object_access("session", "parent") is None
    assert get_object_access("review-session", "child") is None


def test_object_acl_and_delegation_survive_process_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path))
    reset_object_authorization_state()
    owner = _principal("owner-persistent")
    delegate = _principal("delegate-persistent")
    intruder = _principal("intruder-persistent")

    authorize_object(
        object_type="session",
        object_id="durable-session",
        principal=owner,
        action="create",
        request_id="claim-request",
        allow_claim=True,
    )
    delegate_object_access(
        object_type="session",
        object_id="durable-session",
        principal=owner,
        delegate_principal=delegate.principal_id,
        request_id="delegate-request",
    )

    reset_object_authorization_state()

    hydrated = get_object_access("session", "durable-session")
    assert hydrated is not None
    assert hydrated.owner_principal == owner.principal_id
    assert hydrated.delegates == {delegate.principal_id}
    assert (
        authorize_object(
            object_type="session",
            object_id="durable-session",
            principal=delegate,
            action="read-after-restart",
            request_id="delegate-read",
        ).owner_principal
        == owner.principal_id
    )
    with pytest.raises(ObjectAccessDeniedError):
        authorize_object(
            object_type="session",
            object_id="durable-session",
            principal=intruder,
            action="read-after-restart",
            request_id="intruder-read",
        )
    events = object_authorization_events(object_type="session", object_id="durable-session", limit=20)
    assert any(event["request_id"] == "intruder-read" and event["decision"] == "deny" for event in events)


def test_expired_artifact_is_retained_while_evidence_reference_is_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = tmp_path / "state"
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(state_root))
    store = ArtifactStore(root=artifact_root, retention_seconds=0)
    record = store.store_text("session-a", filename="proof.json", kind="proof", content="evidence")
    store.protect_artifact(
        "session-a",
        record.artifact_id,
        reference_id="release-evidence-1",
        reference_kind="release-evidence",
    )

    assert store.cleanup_expired(session_id="session-a") == []
    assert [item.artifact_id for item in store.last_cleanup_protected] == [record.artifact_id]
    assert store.list_artifacts("session-a")[0].artifact_id == record.artifact_id

    assert store.release_artifact_reference("session-a", record.artifact_id, "release-evidence-1") is True
    deleted = store.cleanup_expired(session_id="session-a")
    assert [item.artifact_id for item in deleted] == [record.artifact_id]


def test_persistence_disabled_keeps_acl_process_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path))
    monkeypatch.setenv("ZAPTRACE_PERSISTENCE_DISABLED", "1")
    reset_object_authorization_state()
    owner = _principal("disabled-owner")

    authorize_object(
        object_type="session",
        object_id="disabled-session",
        principal=owner,
        action="create",
        request_id="disabled-claim",
        allow_claim=True,
    )
    reset_object_authorization_state()

    assert get_object_access("session", "disabled-session") is None
    assert not (tmp_path / "zaptrace-state.sqlite3").exists()


def test_remove_object_access_deletes_durable_acl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path))
    reset_object_authorization_state()
    owner = _principal("delete-owner")
    authorize_object(
        object_type="session",
        object_id="delete-session",
        principal=owner,
        action="create",
        request_id="delete-claim",
        allow_claim=True,
    )

    remove_object_access("session", "delete-session")
    reset_object_authorization_state()

    assert get_object_access("session", "delete-session") is None


def test_direct_access_decision_explains_each_authorization_path() -> None:
    record = ObjectAccessRecord(
        object_type="session",
        object_id="decision",
        owner_principal="owner-a",
        delegates={"delegate-b"},
    )

    assert _direct_access_decision(record, _principal("admin", "object-admin")) == (
        True,
        "administrator override",
    )
    assert _direct_access_decision(record, _principal("owner-a")) == (True, "object owner")
    assert _direct_access_decision(record, _principal("delegate-b")) == (
        True,
        "delegated object access",
    )
    assert _direct_access_decision(record, _principal("intruder")) == (
        False,
        "principal is not owner, delegate, or administrator",
    )
