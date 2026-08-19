from __future__ import annotations

from zaptrace.security.sandbox import emergency_reset, emergency_stop, reset_sandbox, sandbox_status


def test_emergency_stop_reason_is_exposed_and_reset() -> None:
    session_id = "sandbox-emergency-reason"
    reset_sandbox(session_id)

    emergency_stop(session_id, "operator requested stop")
    stopped = sandbox_status(session_id)
    assert stopped["emergency_stopped"] is True
    assert stopped["emergency_reason"] == "operator requested stop"

    emergency_reset(session_id)
    resumed = sandbox_status(session_id)
    assert resumed["emergency_stopped"] is False
    assert resumed["emergency_reason"] == ""
