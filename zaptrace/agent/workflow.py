"""Checkpoint, resume, and recovery contracts for long-running agent workflows."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.security.policy import record_audit_event


class WorkflowStatus(StrEnum):
    """Workflow lifecycle states."""

    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    ABORTED = "aborted"
    COMPLETED = "completed"


class StepStatus(StrEnum):
    """Per-step lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FailureKind(StrEnum):
    """Recoverable workflow failure categories."""

    TOOL_ERROR = "tool_error"
    TIMEOUT = "timeout"
    VALIDATION_GATE = "validation_gate"
    USER_ABORT = "user_abort"


class RecoveryDecision(StrEnum):
    """Recovery decision kinds recorded in checkpoint and audit logs."""

    RESUME = "resume"
    ROLLBACK = "rollback"
    ABORT = "abort"
    RETRY = "retry"


class WorkflowStepRecord(BaseModel):
    """A serializable workflow step record."""

    model_config = ConfigDict(strict=False)

    step_id: str
    name: str
    tool: str = ""
    mutates_design: bool = False
    status: StepStatus = StepStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    transaction_id: str = ""
    diff_summary: str = ""
    rollback_id: str = ""
    rollback_available: bool = False
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    failure_kind: FailureKind | None = None
    error: str = ""


class WorkflowRecoveryEvent(BaseModel):
    """A serializable recovery decision."""

    model_config = ConfigDict(strict=False)

    timestamp: str
    decision: RecoveryDecision
    reason: str
    step_id: str = ""
    rollback_id: str = ""
    audit_event_id: str = ""


class WorkflowCheckpoint(BaseModel):
    """Checkpoint schema for resumable long-running agent workflows."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    workflow_id: str
    design_name: str
    status: WorkflowStatus = WorkflowStatus.RUNNING
    current_step_index: int = Field(default=0, ge=0)
    resume_count: int = Field(default=0, ge=0)
    steps: list[WorkflowStepRecord] = Field(default_factory=list)
    recovery_events: list[WorkflowRecoveryEvent] = Field(default_factory=list)
    proof_evidence: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def step(self, step_id: str) -> WorkflowStepRecord:
        """Return one step by ID or raise a clear error."""
        for item in self.steps:
            if item.step_id == step_id:
                return item
        raise ValueError(f"unknown workflow step: {step_id}")

    def save(self, path: str | Path) -> None:
        """Persist the checkpoint as stable JSON."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")


class WorkflowStepSpec(BaseModel):
    """Input spec used to create a checkpoint."""

    model_config = ConfigDict(strict=False)

    step_id: str
    name: str
    tool: str = ""
    mutates_design: bool = False


def load_checkpoint(path: str | Path) -> WorkflowCheckpoint:
    """Load a checkpoint JSON file."""
    return WorkflowCheckpoint.model_validate_json(Path(path).read_text(encoding="utf-8"))


def create_checkpoint(
    workflow_id: str, design_name: str, steps: Iterable[WorkflowStepSpec | dict[str, Any]]
) -> WorkflowCheckpoint:
    """Create a new running checkpoint without executing workflow steps."""
    records = [
        WorkflowStepRecord.model_validate(step.model_dump(mode="json") if isinstance(step, WorkflowStepSpec) else step)
        for step in steps
    ]
    return WorkflowCheckpoint(workflow_id=workflow_id, design_name=design_name, steps=records)


def begin_step(checkpoint: WorkflowCheckpoint, step_id: str) -> WorkflowCheckpoint:
    """Mark a step as running and increment its attempt count."""
    step = checkpoint.step(step_id)
    step.status = StepStatus.RUNNING
    step.attempts += 1
    checkpoint.status = WorkflowStatus.RUNNING
    checkpoint.current_step_index = checkpoint.steps.index(step)
    _touch(checkpoint)
    return checkpoint


def complete_step(
    checkpoint: WorkflowCheckpoint,
    step_id: str,
    *,
    evidence: dict[str, Any] | None = None,
    transaction_id: str = "",
    diff_summary: str = "",
    rollback_id: str = "",
) -> WorkflowCheckpoint:
    """Mark a step as passed while preserving transaction/diff/rollback lineage."""
    step = checkpoint.step(step_id)
    step.status = StepStatus.PASSED
    if evidence is not None:
        step.evidence.append(evidence)
        checkpoint.proof_evidence.append({"step_id": step_id, **evidence})
    if transaction_id:
        step.transaction_id = transaction_id
    if diff_summary:
        step.diff_summary = diff_summary
    if rollback_id:
        step.rollback_id = rollback_id
        step.rollback_available = True
    checkpoint.current_step_index = min(len(checkpoint.steps), checkpoint.steps.index(step) + 1)
    if checkpoint.current_step_index >= len(checkpoint.steps):
        checkpoint.status = WorkflowStatus.COMPLETED
    _touch(checkpoint)
    return checkpoint


def fail_step(
    checkpoint: WorkflowCheckpoint,
    step_id: str,
    *,
    kind: FailureKind,
    error: str,
    evidence: dict[str, Any] | None = None,
) -> WorkflowCheckpoint:
    """Mark a workflow step as failed without discarding prior evidence."""
    step = checkpoint.step(step_id)
    step.status = StepStatus.FAILED
    step.failure_kind = kind
    step.error = error
    if evidence is not None:
        step.evidence.append(evidence)
        checkpoint.proof_evidence.append({"step_id": step_id, **evidence})
    checkpoint.status = WorkflowStatus.ABORTED if kind == FailureKind.USER_ABORT else WorkflowStatus.FAILED
    checkpoint.current_step_index = checkpoint.steps.index(step)
    _touch(checkpoint)
    return checkpoint


def resume_workflow(
    checkpoint: WorkflowCheckpoint,
    *,
    reason: str,
    audit_session: dict[str, Any] | None = None,
    session_id: str = "agent-workflow",
    actor: str = "agent-runtime",
) -> WorkflowCheckpoint:
    """Resume a failed/paused workflow and record the recovery decision."""
    if checkpoint.status not in {WorkflowStatus.FAILED, WorkflowStatus.PAUSED}:
        raise ValueError(f"workflow cannot resume from {checkpoint.status}")
    checkpoint.resume_count += 1
    checkpoint.status = WorkflowStatus.RUNNING
    event = _record_recovery(
        checkpoint,
        decision=RecoveryDecision.RESUME,
        reason=reason,
        audit_session=audit_session,
        session_id=session_id,
        actor=actor,
    )
    checkpoint.recovery_events.append(event)
    _touch(checkpoint)
    return checkpoint


def abort_workflow(
    checkpoint: WorkflowCheckpoint,
    *,
    reason: str,
    audit_session: dict[str, Any] | None = None,
    session_id: str = "agent-workflow",
    actor: str = "agent-runtime",
) -> WorkflowCheckpoint:
    """Abort a workflow with an auditable recovery decision."""
    checkpoint.status = WorkflowStatus.ABORTED
    event = _record_recovery(
        checkpoint,
        decision=RecoveryDecision.ABORT,
        reason=reason,
        audit_session=audit_session,
        session_id=session_id,
        actor=actor,
    )
    checkpoint.recovery_events.append(event)
    _touch(checkpoint)
    return checkpoint


def rollback_after_resume(
    checkpoint: WorkflowCheckpoint,
    step_id: str,
    *,
    reason: str,
    audit_session: dict[str, Any] | None = None,
    session_id: str = "agent-workflow",
    actor: str = "agent-runtime",
) -> WorkflowCheckpoint:
    """Record that a previously preserved rollback handle was used after resume."""
    step = checkpoint.step(step_id)
    if not step.rollback_available or not step.rollback_id:
        raise ValueError(f"rollback is not available for step: {step_id}")
    event = _record_recovery(
        checkpoint,
        decision=RecoveryDecision.ROLLBACK,
        reason=reason,
        audit_session=audit_session,
        session_id=session_id,
        actor=actor,
        step_id=step_id,
        rollback_id=step.rollback_id,
    )
    checkpoint.recovery_events.append(event)
    _touch(checkpoint)
    return checkpoint


def _record_recovery(
    checkpoint: WorkflowCheckpoint,
    *,
    decision: RecoveryDecision,
    reason: str,
    audit_session: dict[str, Any] | None,
    session_id: str,
    actor: str,
    step_id: str = "",
    rollback_id: str = "",
) -> WorkflowRecoveryEvent:
    audit_event_id = ""
    if audit_session is not None:
        audit = record_audit_event(
            audit_session,
            surface="agent-runtime",
            session_id=session_id,
            actor=actor,
            tool="workflow_recovery",
            capability="sandbox-write",
            decision=decision.value,
            reason=reason,
            metadata={
                "workflow_id": checkpoint.workflow_id,
                "design_name": checkpoint.design_name,
                "status": checkpoint.status.value,
                "step_id": step_id or checkpoint.steps[checkpoint.current_step_index].step_id,
                "rollback_id": rollback_id,
                "resume_count": checkpoint.resume_count,
            },
        )
        audit_event_id = str(audit.get("event_id", ""))
    return WorkflowRecoveryEvent(
        timestamp=datetime.now(UTC).isoformat(),
        decision=decision,
        reason=reason,
        step_id=step_id or checkpoint.steps[checkpoint.current_step_index].step_id,
        rollback_id=rollback_id,
        audit_event_id=audit_event_id,
    )


def _touch(checkpoint: WorkflowCheckpoint) -> None:
    checkpoint.updated_at = datetime.now(UTC).isoformat()
