"""Versioned contracts for deterministic end-to-end agent evaluations."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class AgentEvaluationOutcome(StrEnum):
    """Supported scenario outcomes."""

    SUCCESS = "success"
    BLOCKED = "blocked"
    HUMAN_REVIEW_REQUIRED = "human-review-required"
    STOP_CONDITION = "stop-condition"


class AgentEvaluationRiskClass(StrEnum):
    """Risk carried by one evaluation project brief."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class AgentEvaluationMode(StrEnum):
    """Supported harness execution modes."""

    CI = "ci"
    NIGHTLY = "nightly"


class AgentEvaluationExecutor(StrEnum):
    """Execution surface for one scenario step."""

    AGENT_TOOL = "agent-tool"
    SYNTHESIS_PROOF = "synthesis-proof"
    ENGINE_BENCHMARK = "engine-benchmark"


class AgentEvaluationScenarioRole(StrEnum):
    """How one scenario contributes to MCP surface evaluation metrics."""

    LEGACY = "legacy"
    TASK = "task"
    AUTHORIZATION_PROBE = "authorization-probe"


class AgentEvaluationStepStatus(StrEnum):
    """Observed status of one execution step."""

    PASSED = "passed"
    FAILED = "failed"
    STOPPED = "stopped"


class AgentEvaluationCallDisposition(StrEnum):
    """Why one surface-aware agent call executed, stopped, or was denied."""

    EXECUTED = "executed"
    INVALID_SURFACE_CALL = "invalid-surface-call"
    EXPECTED_POLICY_DENIAL = "expected-policy-denial"
    UNEXPECTED_POLICY_DENIAL = "unexpected-policy-denial"
    AUTHORIZATION_EXPECTATION_MISMATCH = "authorization-expectation-mismatch"
    RUNTIME_FAILURE = "runtime-failure"


class AgentEvaluationOperator(StrEnum):
    """Supported deterministic outcome-rule operators."""

    EQUALS = "equals"
    NOT_EQUALS = "not-equals"
    TRUTHY = "truthy"
    FALSY = "falsy"
    CONTAINS = "contains"
    IN = "in"


class AgentEvaluationStep(BaseModel):
    """One versioned action in a scenario tool plan."""

    model_config = ConfigDict(strict=False)

    step_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    executor: AgentEvaluationExecutor
    operation: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    captures: dict[str, str] = Field(default_factory=dict)
    on_error_outcome: AgentEvaluationOutcome | None = None
    expect_authorization_denial: bool = False
    expected_artifact_kinds: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class AgentEvaluationOutcomeRule(BaseModel):
    """Declarative rule mapping observed evidence to an outcome."""

    model_config = ConfigDict(strict=False)

    path: str = Field(min_length=1)
    operator: AgentEvaluationOperator
    value: Any = None
    outcome: AgentEvaluationOutcome
    reason: str = Field(min_length=1)


class AgentEvaluationScenario(BaseModel):
    """One realistic project brief and its expected bounded execution contract."""

    model_config = ConfigDict(strict=False)

    scenario_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    risk_class: AgentEvaluationRiskClass
    expected_outcome: AgentEvaluationOutcome
    board_family_id: str = ""
    surface: str = ""
    evaluation_role: AgentEvaluationScenarioRole = AgentEvaluationScenarioRole.LEGACY
    granted_capabilities: list[str] = Field(default_factory=list)
    modes: list[AgentEvaluationMode] = Field(
        default_factory=lambda: [AgentEvaluationMode.CI, AgentEvaluationMode.NIGHTLY]
    )
    steps: list[AgentEvaluationStep]
    outcome_rules: list[AgentEvaluationOutcomeRule] = Field(default_factory=list)
    expected_artifact_kinds: list[str]
    non_claims: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_step_ids(self) -> AgentEvaluationScenario:
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError(f"duplicate step_id in scenario {self.scenario_id}")
        return self


class AgentEvaluationCorpus(BaseModel):
    """Versioned scenario fixture corpus."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    corpus_version: str = "2026.09"
    scenarios: list[AgentEvaluationScenario]
    non_claims: list[str] = Field(default_factory=list)


class AgentEvaluationArtifact(BaseModel):
    """One generated scenario artifact and its content identity."""

    model_config = ConfigDict(strict=False)

    path: str
    kind: str
    sha256: str = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=0)
    produced_by_step: str = ""


class AgentEvaluationProofLink(BaseModel):
    """Link from an evaluation scenario to proof-pack evidence."""

    model_config = ConfigDict(strict=False)

    step_id: str
    manifest_path: str = ""
    report_path: str = ""
    manifest_sha256: str = ""
    autonomous_status: str = ""


class AgentEvaluationBenchmarkLink(BaseModel):
    """Link from an evaluation scenario to benchmark/scorecard evidence."""

    model_config = ConfigDict(strict=False)

    step_id: str
    board_family_id: str = ""
    scorecard_sha256: str = ""
    score: float | None = None
    grade: str = ""


class AgentEvaluationTraceEntry(BaseModel):
    """Normalized audit record for one harness step."""

    model_config = ConfigDict(strict=False)

    call_number: int = Field(ge=1)
    step_id: str
    executor: AgentEvaluationExecutor
    operation: str
    status: AgentEvaluationStepStatus
    surface: str = ""
    disposition: AgentEvaluationCallDisposition = AgentEvaluationCallDisposition.EXECUTED
    required_capability: str = ""
    authorization_reason: str = ""
    risk: str = "safe"
    params_sha256: str = Field(pattern=_SHA256_PATTERN)
    result_sha256: str = Field(pattern=_SHA256_PATTERN)
    duration_ms: float = Field(default=0.0, ge=0)
    timestamp: float = Field(default=0.0, ge=0)
    error_type: str = ""
    error_message: str = ""
    artifact_paths: list[str] = Field(default_factory=list)

    def normalized_dict(self) -> dict[str, Any]:
        """Return stable trace evidence without volatile timing fields."""
        return self.model_dump(mode="json", exclude={"duration_ms", "timestamp"})


def normalized_trace_sha256(entries: list[AgentEvaluationTraceEntry]) -> str:
    """Hash stable tool evidence while excluding wall-clock metadata."""
    payload = [entry.normalized_dict() for entry in entries]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AgentEvaluationScenarioResult(BaseModel):
    """Auditable result for one scenario."""

    model_config = ConfigDict(strict=False)

    scenario_id: str
    title: str
    risk_class: AgentEvaluationRiskClass
    expected_outcome: AgentEvaluationOutcome
    outcome: AgentEvaluationOutcome
    matched_expectation: bool
    stop_reason: str
    session_id: str
    tool_call_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    total_duration_ms: float = Field(default=0.0, ge=0)
    trace_sha256: str = Field(pattern=_SHA256_PATTERN)
    replay_digest: str = ""
    replay_trace_sha256: str = ""
    replay_equivalent: bool | None = None
    traces: list[AgentEvaluationTraceEntry]
    artifacts: list[AgentEvaluationArtifact]
    proof_links: list[AgentEvaluationProofLink] = Field(default_factory=list)
    benchmark_links: list[AgentEvaluationBenchmarkLink] = Field(default_factory=list)
    non_claims: list[str] = Field(default_factory=list)


class AgentEvaluationSurfaceMetrics(BaseModel):
    """Aggregate deterministic call and task evidence for one reduced MCP surface."""

    model_config = ConfigDict(strict=False)

    surface: str
    visible_tool_count: int = Field(ge=0)
    tool_contract_sha256: str = Field(pattern=_SHA256_PATTERN)
    planned_call_count: int = Field(ge=0)
    invalid_call_count: int = Field(ge=0)
    invalid_call_rate: float = Field(ge=0.0, le=1.0)
    authorization_denial_count: int = Field(ge=0)
    authorization_denial_rate: float = Field(ge=0.0, le=1.0)
    expected_policy_denial_count: int = Field(ge=0)
    unexpected_policy_denial_count: int = Field(ge=0)
    authorization_expectation_mismatch_count: int = Field(ge=0)
    runtime_failure_count: int = Field(ge=0)
    task_count: int = Field(ge=0)
    task_completion_count: int = Field(ge=0)
    task_completion_rate: float = Field(ge=0.0, le=1.0)
    task_outcome_counts: dict[str, int]
    replay_check_count: int = Field(ge=0)
    replay_equivalent_count: int = Field(ge=0)
    replay_mismatch_count: int = Field(ge=0)
    replay_equivalence_rate: float = Field(ge=0.0, le=1.0)


class AgentEvaluationReport(BaseModel):
    """Top-level CI/nightly agent evaluation evidence."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    harness_version: str = "1.0"
    corpus_version: str
    corpus_sha256: str = Field(pattern=_SHA256_PATTERN)
    protocol_version: str = "2026-07-28"
    surface_contract_sha256: str = Field(pattern=_SHA256_PATTERN)
    mode: AgentEvaluationMode
    generated_at: str
    passed: bool
    scenario_count: int = Field(ge=0)
    mismatch_count: int = Field(ge=0)
    outcome_counts: dict[str, int]
    surface_regression_count: int = Field(default=0, ge=0)
    surface_metrics: dict[str, AgentEvaluationSurfaceMetrics] = Field(default_factory=dict)
    scenarios: list[AgentEvaluationScenarioResult]
    evidence_identity: dict[str, Any] = Field(default_factory=dict)
    report_sha256: str = ""
    non_claims: list[str] = Field(default_factory=list)
