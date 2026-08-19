"""Characterization tests for the MCP tool-wrapper phase boundaries."""

from __future__ import annotations

import pytest

import zaptrace.mcp.server as mcp_server
from zaptrace.agent._tool_impls import _sessions
from zaptrace.security.objects import get_object_access, reset_object_authorization_state


@pytest.fixture(autouse=True)
def _reset_wrapper_state(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_object_authorization_state()
    _sessions.clear()
    monkeypatch.setattr(mcp_server, "_HTTP_AUTH_ACTIVE", False)
    monkeypatch.setattr(mcp_server, "_HTTP_AUTH_ACTOR", "mcp-client")


async def test_wrapper_rejects_invalid_parameter_before_object_claim() -> None:
    def probe(session_id: str, count: int) -> dict[str, object]:
        return {"session_id": session_id, "count": count}

    wrapped = mcp_server._make_sandboxed_tool(
        "invalid-parameter-probe",
        {
            "fn": probe,
            "params": {
                "session_id": {"type": "string"},
                "count": {"type": "integer"},
            },
            "capability": "read",
        },
    )

    result = await wrapped(session_id="invalid-parameter-session", count="not-an-int")

    assert result == {
        "ok": False,
        "error": {
            "code": "INVALID_PARAMETER",
            "message": "Parameter 'count' expected integer, got str",
            "details": {},
        },
    }
    assert get_object_access("session", "invalid-parameter-session") is None
    assert "invalid-parameter-session" not in _sessions


@pytest.mark.parametrize(
    ("raw_result", "expected_data"),
    [
        (None, {"message": "Tool 'response-probe' completed successfully"}),
        (42, {"result": "42"}),
    ],
)
async def test_wrapper_preserves_response_conversion(raw_result: object, expected_data: dict[str, str]) -> None:
    def probe(session_id: str) -> object:
        del session_id
        return raw_result

    wrapped = mcp_server._make_sandboxed_tool(
        "response-probe",
        {
            "fn": probe,
            "params": {"session_id": {"type": "string"}},
            "capability": "read",
        },
    )

    result = await wrapped(session_id="response-session")

    assert result == {"ok": True, "data": expected_data}


def test_prepare_phase_is_typed_and_preserves_default_session_contract() -> None:
    prepared_type = getattr(mcp_server, "_PreparedToolCall", None)
    prepare = getattr(mcp_server, "_prepare_tool_call", None)

    assert prepared_type is not None, "wrapper refactor must expose a typed prepared-call phase"
    assert prepare is not None, "wrapper refactor must expose a preparation phase"

    def probe(session_id: str) -> dict[str, str]:
        return {"session_id": session_id}

    tool_def = {
        "fn": probe,
        "params": {"session_id": {"type": "string"}},
        "capability": "read",
    }
    prepared = prepare("typed-phase-probe", tool_def, {}, has_session=True)

    assert isinstance(prepared, prepared_type)
    assert prepared.tool_name == "typed-phase-probe"
    assert prepared.session_id == "mcp-default-session"
    assert prepared.required_capability == "read"
    assert prepared.kwargs == {"session_id": "mcp-default-session"}


def test_authorization_phase_is_typed_and_preserves_capability_audit() -> None:
    authorized_type = getattr(mcp_server, "_AuthorizedToolCall", None)
    authorize = getattr(mcp_server, "_authorize_tool_call", None)

    assert authorized_type is not None, "wrapper refactor must expose a typed authorization phase"
    assert authorize is not None, "wrapper refactor must expose an authorization phase"

    created = mcp_server.session_create()
    session_id = created["data"]["session_id"]
    _sessions[session_id]["capabilities"] = {"sandbox-write"}

    def probe(session_id: str) -> dict[str, str]:
        return {"session_id": session_id}

    tool_def = {
        "fn": probe,
        "params": {"session_id": {"type": "string"}},
        "capability": "sandbox-write",
    }
    prepared = mcp_server._prepare_tool_call(
        "authorization-phase-probe",
        tool_def,
        {"session_id": session_id},
        has_session=True,
    )

    authorized = authorize(prepared)

    assert isinstance(authorized, authorized_type)
    assert authorized.prepared is prepared
    assert authorized.principal.principal_id == "mcp-local"
    assert authorized.granted_capabilities == frozenset({"sandbox-write"})
    assert authorized.actor == "mcp-client"
    assert authorized.auth_source == "stdio-or-loopback-development"
    event = _sessions[session_id]["audit_events"][-1]
    assert event["decision"] == "allow"
    assert event["tool"] == "authorization-phase-probe"
    assert event["metadata"]["principal_id"] == authorized.principal.principal_id
    assert event["metadata"]["request_id"] == authorized.request_id


def test_execution_audit_phase_preserves_error_then_rollback_mapping() -> None:
    entry_type = getattr(mcp_server, "_ExecutionAuditEntry", None)
    map_entries = getattr(mcp_server, "_execution_audit_entries", None)

    assert entry_type is not None, "wrapper refactor must expose typed execution audit entries"
    assert map_entries is not None, "wrapper refactor must expose execution audit mapping"

    entries = map_entries(
        "rollback",
        {"job_id": "job-1", "reason": "worker error", "exception_type": "ValueError"},
    )

    assert all(isinstance(entry, entry_type) for entry in entries)
    assert [(entry.decision, entry.reason) for entry in entries] == [
        ("error", "worker error"),
        ("rollback", "isolated worker state and staged artifacts were discarded"),
    ]
    assert entries[0].metadata["job_id"] == "job-1"
    assert entries[1].metadata["exception_type"] == "ValueError"


def test_execution_audit_phase_normalizes_cancellation_decision() -> None:
    map_entries = getattr(mcp_server, "_execution_audit_entries", None)
    assert map_entries is not None

    entries = map_entries("cancel_requested", {"job_id": "job-2"})

    assert [(entry.decision, entry.reason) for entry in entries] == [
        ("cancel", "caller cancelled isolated mutating tool execution"),
    ]


def _authorized_call_for_response_tests():
    from zaptrace.security.objects import RequestPrincipal

    def probe(session_id: str) -> dict[str, str]:
        return {"session_id": session_id}

    prepared = mcp_server._prepare_tool_call(
        "outcome-probe",
        {
            "fn": probe,
            "params": {"session_id": {"type": "string"}},
            "capability": "sandbox-write",
        },
        {"session_id": "outcome-session"},
        has_session=True,
    )
    return mcp_server._AuthorizedToolCall(
        prepared=prepared,
        principal=RequestPrincipal(
            principal_id="mcp-local",
            actor="mcp-local",
            scopes=frozenset({"sandbox-write"}),
            local_development=True,
        ),
        request_id="mcp-request-test",
        granted_capabilities=frozenset({"sandbox-write"}),
        actor="mcp-client",
        auth_source="stdio-or-loopback-development",
    )


@pytest.mark.parametrize(
    ("status", "exception_type", "expected_code"),
    [
        ("conflict", "SessionDestroyedError", "SESSION_CONFLICT"),
        ("failed", "UnsupportedExecutionPlatformError", "UNSUPPORTED_PLATFORM"),
        ("failed", "ValueError", "TOOL_ERROR"),
    ],
)
def test_mutation_outcome_response_preserves_error_codes(
    status: str,
    exception_type: str,
    expected_code: str,
) -> None:
    from zaptrace.agent.execution import ToolExecutionOutcome

    convert = getattr(mcp_server, "_mutation_outcome_response", None)
    assert convert is not None, "wrapper refactor must expose mutation outcome response conversion"
    authorized = _authorized_call_for_response_tests()
    outcome = ToolExecutionOutcome(
        status=status,
        error="execution failed",
        worker_terminated=True,
        job_id="job-1",
        duration_ms=12.5,
        exception_type=exception_type,
    )

    response = convert(authorized, outcome)

    assert response is not None
    assert response["ok"] is False
    assert response["error"]["code"] == expected_code
    assert response["error"]["details"]["job_id"] == "job-1"


def test_mutation_outcome_response_preserves_timeout_evidence() -> None:
    from zaptrace.agent.execution import ToolExecutionOutcome

    convert = getattr(mcp_server, "_mutation_outcome_response", None)
    assert convert is not None
    authorized = _authorized_call_for_response_tests()
    outcome = ToolExecutionOutcome(
        status="timeout",
        worker_terminated=True,
        job_id="job-timeout",
        duration_ms=25.25,
    )

    response = convert(authorized, outcome)

    assert response == {
        "ok": False,
        "error": {
            "code": "TOOL_TIMEOUT",
            "message": f"Tool 'outcome-probe' timed out after {authorized.prepared.timeout_s}s",
            "details": {
                "tool": "outcome-probe",
                "job_id": "job-timeout",
                "worker_terminated": True,
                "duration_ms": 25.2,
            },
        },
    }


def test_response_phase_preserves_success_conversion() -> None:
    normalize = getattr(mcp_server, "_normalize_tool_result", None)
    assert normalize is not None, "wrapper refactor must expose final response conversion"

    assert normalize("response-probe", None) == {
        "ok": True,
        "data": {"message": "Tool 'response-probe' completed successfully"},
    }
    assert normalize("response-probe", 42) == {"ok": True, "data": {"result": "42"}}
    assert normalize("response-probe", {"value": 1}) == {"ok": True, "data": {"value": 1}}


async def test_execution_phase_preserves_read_timeout_response(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    execute = getattr(mcp_server, "_execute_tool_call", None)
    assert execute is not None, "wrapper refactor must expose an execution coordination phase"
    monkeypatch.setattr(mcp_server, "_tool_timeout_seconds", lambda _name: 0.01)

    async def probe(session_id: str) -> dict[str, str]:
        await asyncio.sleep(0.05)
        return {"session_id": session_id}

    prepared = mcp_server._prepare_tool_call(
        "read-timeout-probe",
        {
            "fn": probe,
            "params": {"session_id": {"type": "string"}},
            "capability": "read",
        },
        {"session_id": "read-timeout-session"},
        has_session=True,
    )
    authorized = mcp_server._authorize_tool_call(prepared)

    with pytest.raises(mcp_server._ToolCallRejectedError) as caught:
        await execute(authorized, probe)

    assert caught.value.response == {
        "ok": False,
        "error": {
            "code": "TOOL_TIMEOUT",
            "message": "Tool 'read-timeout-probe' timed out after 0.01s",
            "details": {},
        },
    }


async def test_execution_phase_routes_mutations_through_isolated_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    from zaptrace.agent.execution import ToolExecutionOutcome

    execute = getattr(mcp_server, "_execute_tool_call", None)
    assert execute is not None
    created = mcp_server.session_create()
    session_id = created["data"]["session_id"]
    _sessions[session_id]["capabilities"] = {"sandbox-write"}
    captured: dict[str, object] = {}

    def probe(session_id: str) -> dict[str, str]:
        return {"session_id": session_id}

    tool_def = {
        "fn": probe,
        "params": {"session_id": {"type": "string"}},
        "capability": "sandbox-write",
    }
    prepared = mcp_server._prepare_tool_call(
        "mutation-phase-probe",
        tool_def,
        {"session_id": session_id},
        has_session=True,
    )
    authorized = mcp_server._authorize_tool_call(prepared)

    async def fake_execute_mutating_tool(**kwargs):
        captured.update(kwargs)
        return ToolExecutionOutcome(status="completed", result={"isolated": True})

    monkeypatch.setattr(mcp_server, "execute_mutating_tool", fake_execute_mutating_tool)

    result = await execute(authorized, probe)

    assert result == {"isolated": True}
    assert captured["tool_name"] == "mutation-phase-probe"
    assert captured["tool_def"] is tool_def
    assert captured["session_id"] == session_id
    assert callable(captured["event_sink"])


def test_wrapper_preserves_public_callable_signature() -> None:
    import inspect

    def probe(session_id: str = "default", count: int = 1) -> dict[str, object]:
        return {"session_id": session_id, "count": count}

    wrapped = mcp_server._make_sandboxed_tool(
        "signature-probe",
        {
            "fn": probe,
            "params": {
                "session_id": {"type": "string"},
                "count": {"type": "integer"},
            },
            "capability": "read",
        },
    )

    assert inspect.signature(wrapped) == inspect.signature(probe)


async def test_registered_mcp_schema_remains_compatible_for_representative_tool() -> None:
    tool = next(item for item in await mcp_server.server.list_tools() if item.name == "design_parse_str")

    assert tool.parameters == {
        "additionalProperties": False,
        "properties": {
            "yaml_content": {"type": "string"},
            "session_id": {"default": "default", "type": "string"},
        },
        "required": ["yaml_content"],
        "type": "object",
    }
    assert tool.output_schema == {"additionalProperties": True, "type": "object"}
