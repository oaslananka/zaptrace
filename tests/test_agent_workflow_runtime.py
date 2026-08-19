from __future__ import annotations

import json
from pathlib import Path

import pytest

from zaptrace.agent.workflow import (
    FailureKind,
    WorkflowStatus,
    WorkflowStepSpec,
    abort_workflow,
    begin_step,
    complete_step,
    create_checkpoint,
    fail_step,
    load_checkpoint,
    resume_workflow,
    rollback_after_resume,
)


def _checkpoint():
    return create_checkpoint(
        "wf-001",
        "AgentBoard",
        [
            WorkflowStepSpec(step_id="architect", name="Architecture", tool="architect_agent"),
            WorkflowStepSpec(step_id="layout", name="Layout candidate", tool="layout_agent", mutates_design=True),
            WorkflowStepSpec(step_id="validate", name="Validation gate", tool="verification_agent"),
        ],
    )


def test_checkpoint_schema_round_trips_to_json(tmp_path: Path) -> None:
    checkpoint = _checkpoint()
    path = tmp_path / "checkpoint.json"

    checkpoint.save(path)
    loaded = load_checkpoint(path)

    assert loaded.schema_version == "1.0"
    assert loaded.workflow_id == "wf-001"
    assert loaded.steps[1].mutates_design is True
    assert json.loads(path.read_text(encoding="utf-8"))["steps"][0]["step_id"] == "architect"


def test_resume_from_failed_validation_preserves_evidence_and_rollback() -> None:
    audit_session: dict[str, object] = {}
    checkpoint = _checkpoint()
    begin_step(checkpoint, "architect")
    complete_step(checkpoint, "architect", evidence={"artifact": "requirements.json", "sha256": "a" * 64})
    begin_step(checkpoint, "layout")
    complete_step(
        checkpoint,
        "layout",
        evidence={"candidate_id": "cand-a", "score": 0.71},
        transaction_id="tx-layout-1",
        diff_summary="placed 12 components",
        rollback_id="rb-layout-1",
    )
    begin_step(checkpoint, "validate")
    fail_step(checkpoint, "validate", kind=FailureKind.VALIDATION_GATE, error="DRC gate failed")

    resumed = resume_workflow(checkpoint, reason="retry after tightening clearance", audit_session=audit_session)

    assert resumed.status == WorkflowStatus.RUNNING
    assert resumed.resume_count == 1
    assert resumed.step("layout").rollback_available is True
    assert resumed.step("layout").rollback_id == "rb-layout-1"
    assert resumed.proof_evidence[0]["artifact"] == "requirements.json"
    assert resumed.proof_evidence[1]["candidate_id"] == "cand-a"
    assert resumed.recovery_events[-1].decision == "resume"
    assert audit_session["audit_events"][-1]["tool"] == "workflow_recovery"
    assert audit_session["audit_events"][-1]["metadata"]["workflow_id"] == "wf-001"


def test_rollback_remains_available_after_resume() -> None:
    checkpoint = _checkpoint()
    begin_step(checkpoint, "layout")
    complete_step(checkpoint, "layout", rollback_id="rb-layout-1")
    fail_step(checkpoint, "validate", kind=FailureKind.TOOL_ERROR, error="oracle crashed")
    resume_workflow(checkpoint, reason="oracle restarted")

    rollback_after_resume(checkpoint, "layout", reason="discard failed candidate")

    assert checkpoint.recovery_events[-1].decision == "rollback"
    assert checkpoint.recovery_events[-1].rollback_id == "rb-layout-1"


def test_timeout_failed_tool_failed_gate_and_user_abort_paths_are_serialized() -> None:
    timeout = _checkpoint()
    fail_step(timeout, "layout", kind=FailureKind.TIMEOUT, error="layout timed out after 30s")
    assert timeout.status == WorkflowStatus.FAILED
    assert timeout.step("layout").failure_kind == FailureKind.TIMEOUT

    failed_tool = _checkpoint()
    fail_step(failed_tool, "layout", kind=FailureKind.TOOL_ERROR, error="router returned non-zero")
    assert failed_tool.status == WorkflowStatus.FAILED
    assert failed_tool.step("layout").error == "router returned non-zero"

    failed_gate = _checkpoint()
    fail_step(failed_gate, "validate", kind=FailureKind.VALIDATION_GATE, error="ERC errors remain")
    assert failed_gate.status == WorkflowStatus.FAILED
    assert failed_gate.step("validate").failure_kind == FailureKind.VALIDATION_GATE

    user_abort = _checkpoint()
    abort_workflow(user_abort, reason="user asked to stop")
    assert user_abort.status == WorkflowStatus.ABORTED
    assert user_abort.recovery_events[-1].decision == "abort"


def test_resume_rejects_completed_workflows() -> None:
    checkpoint = _checkpoint()
    checkpoint.status = WorkflowStatus.COMPLETED

    with pytest.raises(ValueError, match="cannot resume"):
        resume_workflow(checkpoint, reason="not allowed")
