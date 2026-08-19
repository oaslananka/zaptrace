"""Versioned evidence contracts for release-grade verify/repair orchestration."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class GateDomain(StrEnum):
    """Verification domains coordinated by the release orchestrator."""

    ERC = "erc"
    DRC = "drc"
    KICAD_ORACLE = "kicad-oracle"
    DFM = "dfm"
    SIMULATION = "simulation"
    SUPPLY_CHAIN = "supply-chain"
    PROOF_PACK = "proof-pack"


class GateVerdict(StrEnum):
    """Normalized verdict for one gate or finding."""

    PASS = "pass"
    WARNING = "warning"
    BLOCKED = "blocked"
    HUMAN_REVIEW_REQUIRED = "human-review-required"
    SKIPPED = "skipped"
    ERROR = "error"


class FailureSeverity(StrEnum):
    """Normalized engineering severity."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Repairability(StrEnum):
    """Whether one failure can be handled autonomously."""

    AUTO_REPAIRABLE = "auto-repairable"
    HUMAN_REPAIRABLE = "human-repairable"
    NON_REPAIRABLE = "non-repairable"


class VerifyRepairStopReason(StrEnum):
    """Deterministic terminal reasons for a verify/repair run."""

    ALL_GATES_PASSED = "all-gates-passed"
    HUMAN_REVIEW_REQUIRED = "human-review-required"
    NON_REPAIRABLE = "non-repairable"
    NO_PROGRESS = "no-progress"
    ITERATION_BUDGET_EXHAUSTED = "iteration-budget-exhausted"
    GATE_EXECUTION_ERROR = "gate-execution-error"
    REPAIR_EXECUTION_ERROR = "repair-execution-error"


class FailureEvidence(BaseModel):
    """One normalized failure emitted by a domain gate."""

    model_config = ConfigDict(strict=False)

    failure_id: str = Field(min_length=1)
    domain: GateDomain
    rule_id: str = Field(min_length=1)
    severity: FailureSeverity
    verdict: GateVerdict
    repairability: Repairability
    message: str = Field(min_length=1)
    affected_refs: list[str] = Field(default_factory=list)
    requires_human_review: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class GateEvidence(BaseModel):
    """State-bound result from one configured verification domain."""

    model_config = ConfigDict(strict=False)

    domain: GateDomain
    verdict: GateVerdict
    design_state_hash: str = Field(pattern=_SHA256_PATTERN)
    summary: str = ""
    blocks_autonomous_release: bool = False
    human_review_required: bool = False
    findings: list[FailureEvidence] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict in {GateVerdict.PASS, GateVerdict.WARNING}

    @property
    def blocking_count(self) -> int:
        count = sum(
            item.verdict in {GateVerdict.BLOCKED, GateVerdict.HUMAN_REVIEW_REQUIRED, GateVerdict.ERROR}
            for item in self.findings
        )
        return count or int(self.blocks_autonomous_release)

    @classmethod
    def pass_result(cls, domain: GateDomain, design_state_hash: str, summary: str = "") -> GateEvidence:
        return cls(
            domain=domain,
            verdict=GateVerdict.PASS,
            design_state_hash=design_state_hash,
            summary=summary,
        )

    @classmethod
    def from_findings(
        cls,
        *,
        domain: GateDomain,
        design_state_hash: str,
        findings: list[FailureEvidence],
        summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> GateEvidence:
        verdicts = {item.verdict for item in findings}
        if GateVerdict.ERROR in verdicts:
            verdict = GateVerdict.ERROR
        elif GateVerdict.BLOCKED in verdicts:
            verdict = GateVerdict.BLOCKED
        elif GateVerdict.HUMAN_REVIEW_REQUIRED in verdicts:
            verdict = GateVerdict.HUMAN_REVIEW_REQUIRED
        elif GateVerdict.WARNING in verdicts:
            verdict = GateVerdict.WARNING
        elif GateVerdict.SKIPPED in verdicts:
            verdict = GateVerdict.SKIPPED
        else:
            verdict = GateVerdict.PASS
        human_review = (
            any(item.requires_human_review for item in findings) or verdict == GateVerdict.HUMAN_REVIEW_REQUIRED
        )
        blocks = verdict in {
            GateVerdict.BLOCKED,
            GateVerdict.HUMAN_REVIEW_REQUIRED,
            GateVerdict.SKIPPED,
            GateVerdict.ERROR,
        }
        return cls(
            domain=domain,
            verdict=verdict,
            design_state_hash=design_state_hash,
            summary=summary,
            blocks_autonomous_release=blocks,
            human_review_required=human_review,
            findings=findings,
            metadata=metadata or {},
        )


class SemanticDiffEvidence(BaseModel):
    """One semantic design change recorded for a repair."""

    model_config = ConfigDict(strict=False)

    type: str
    ref: str
    detail: str
    old_value: str | None = None
    new_value: str | None = None


class RepairApplication(BaseModel):
    """Raw result returned by one bounded repair adapter."""

    model_config = ConfigDict(strict=False)

    repair_id: str = Field(min_length=1)
    domains: list[GateDomain]
    rationale: str = Field(min_length=1)
    patches: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    human_review_required: bool = False


class RepairEvidence(BaseModel):
    """Hash-bound before/after evidence for an applied repair batch."""

    model_config = ConfigDict(strict=False)

    iteration: int = Field(ge=1)
    repair_id: str
    domains: list[GateDomain]
    rationale: str
    before_state_hash: str = Field(pattern=_SHA256_PATTERN)
    after_state_hash: str = Field(pattern=_SHA256_PATTERN)
    before_blocking_count: int = Field(ge=0)
    after_blocking_count: int = Field(ge=0)
    improved: bool
    semantic_diff: list[SemanticDiffEvidence] = Field(default_factory=list)
    patches: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    human_review_required: bool = False


class GateHistoryEntry(BaseModel):
    """One immutable snapshot of all configured gates at a design state."""

    model_config = ConfigDict(strict=False)

    iteration: int = Field(ge=0)
    phase: Literal["initial", "post-repair"]
    design_state_hash: str = Field(pattern=_SHA256_PATTERN)
    blocking_count: int = Field(ge=0)
    human_review_count: int = Field(ge=0)
    gates: list[GateEvidence]


class VerifyRepairPolicy(BaseModel):
    """Versioned orchestration policy controlling gates and repair budget."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    policy_version: str = Field(default="1.0", min_length=1)
    max_iterations: int = Field(default=3, ge=1, le=16)
    enabled_domains: list[GateDomain] = Field(default_factory=lambda: list(GateDomain))
    fab_profile: str = "jlcpcb-2layer"
    strict_simulation: bool = True
    erc_warnings_require_review: bool = True
    drc_warnings_require_review: bool = False
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "Convergence is bounded software evidence, not electrical or fabrication approval.",
            "Skipped, missing, high-risk, or unsupported evidence never becomes an autonomous pass.",
            "Physical validation and qualified human engineering review remain separate evidence domains.",
        ]
    )

    @field_validator("enabled_domains")
    @classmethod
    def domains_are_unique(cls, value: list[GateDomain]) -> list[GateDomain]:
        if not value:
            raise ValueError("at least one verify/repair domain is required")
        if len(value) != len(set(value)):
            raise ValueError("verify/repair domains must be unique")
        return value

    def identity_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def release_default(cls) -> VerifyRepairPolicy:
        return cls()

    @classmethod
    def automated_convergence(cls) -> VerifyRepairPolicy:
        """Software-only benchmark policy; deliberately not a release policy."""
        return cls(
            policy_version="1.0-automated-convergence",
            max_iterations=3,
            enabled_domains=[GateDomain.ERC],
            strict_simulation=False,
            erc_warnings_require_review=False,
            non_claims=[
                "This policy measures ERC repair convergence only.",
                "It does not run or waive release DRC, DFM, simulation, KiCad, supply-chain, or physical gates.",
                "A benchmark pass is not release, manufacturing, or fabrication readiness.",
            ],
        )


class VerifyRepairReport(BaseModel):
    """Complete machine-readable verify/repair convergence evidence."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    design_name: str
    policy_version: str
    policy_sha256: str = Field(pattern=_SHA256_PATTERN)
    enabled_domains: list[GateDomain]
    initial_design_state_hash: str = Field(pattern=_SHA256_PATTERN)
    final_design_state_hash: str = Field(pattern=_SHA256_PATTERN)
    converged: bool
    stop_reason: VerifyRepairStopReason
    blocks_autonomous_release: bool
    human_review_required: bool
    iteration_budget: int = Field(ge=1)
    iterations_used: int = Field(ge=0)
    gate_history: list[GateHistoryEntry]
    repairs: list[RepairEvidence]
    final_gates: list[GateEvidence]
    human_review_reasons: list[str] = Field(default_factory=list)
    non_claims: list[str] = Field(default_factory=list)
    report_sha256: str = ""

    def compute_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"report_sha256"})
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def finalize(self) -> VerifyRepairReport:
        self.report_sha256 = self.compute_sha256()
        return self


class VerifyRepairOutcome(BaseModel):
    """The repaired design plus its immutable evidence report."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    design: Any
    report: VerifyRepairReport


def resolve_verify_repair_output_path(
    path: str | Path,
    *,
    trusted_root: str | Path | None = None,
    require_json: bool = False,
) -> Path:
    """Resolve one output path inside an explicit trusted root before filesystem access."""
    root = Path(trusted_root or Path.cwd()).resolve(strict=True)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"verify/repair output escapes trusted root: {resolved}") from exc
    if require_json and resolved.suffix.lower() != ".json":
        raise ValueError("verify/repair report output must be JSON")
    return resolved


def release_verify_repair_report_json(report: VerifyRepairReport) -> str:
    """Return stable pretty JSON after verifying the embedded report digest."""
    if not report.report_sha256:
        report.finalize()
    if report.report_sha256 != report.compute_sha256():
        raise ValueError("verify/repair report hash does not match report contents")
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_release_verify_repair_report(
    report: VerifyRepairReport,
    output_path: str | Path,
    *,
    trusted_root: str | Path | None = None,
) -> Path:
    """Write one JSON report only after trusted-root containment validation."""
    resolved = resolve_verify_repair_output_path(
        output_path,
        trusted_root=trusted_root,
        require_json=True,
    )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(release_verify_repair_report_json(report), encoding="utf-8")
    return resolved


__all__ = [
    "FailureEvidence",
    "FailureSeverity",
    "GateDomain",
    "GateEvidence",
    "GateHistoryEntry",
    "GateVerdict",
    "RepairApplication",
    "RepairEvidence",
    "Repairability",
    "SemanticDiffEvidence",
    "VerifyRepairOutcome",
    "VerifyRepairPolicy",
    "VerifyRepairReport",
    "VerifyRepairStopReason",
    "release_verify_repair_report_json",
    "resolve_verify_repair_output_path",
    "write_release_verify_repair_report",
]
