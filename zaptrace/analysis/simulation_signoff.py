"""Unified, state-bound simulation and analytical sign-off evidence.

This module normalizes existing DC, transient, AC, power, thermal, current-
density, and SI/PI evidence without pretending that analytical or degraded
models are equivalent to solver-backed, device-accurate validation.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class SimulationEvidenceStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"
    HUMAN_REVIEW_REQUIRED = "human-review-required"


class SimulationEvidenceMethod(StrEnum):
    NGSPICE = "ngspice"
    HYBRID = "hybrid"
    ANALYTICAL = "analytical"
    HEURISTIC = "heuristic"


class SimulationRiskClass(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class SimulationDomain(StrEnum):
    DC_OPERATING_POINT = "dc-operating-point"
    TRANSIENT = "transient"
    AC = "ac"
    POWER_INTEGRITY = "power-integrity"
    SIGNAL_INTEGRITY = "signal-integrity"
    THERMAL = "thermal"
    CURRENT_DENSITY = "current-density"


class SimulationModelEvidence(BaseModel):
    """Governed input model and provenance used by a simulation gate."""

    model_config = ConfigDict(strict=False)

    model_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    version: str = Field(min_length=1)
    model_sha256: str = Field(pattern=_SHA256_PATTERN)
    method: SimulationEvidenceMethod
    binding: str = Field(min_length=1)
    degraded: bool
    confidence: float = Field(ge=0.0, le=1.0)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    artifact_path: str = ""
    netlist_path: str = ""
    netlist_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")


class SimulationCheckEvidence(BaseModel):
    """One normalized gate result with explicit risk and repair guidance."""

    model_config = ConfigDict(strict=False)

    check_id: str = Field(min_length=1)
    domain: SimulationDomain
    method: SimulationEvidenceMethod
    engine_status: str = Field(min_length=1)
    tool_version: str = ""
    status: SimulationEvidenceStatus
    risk_class: SimulationRiskClass
    blocking: bool
    human_review_required: bool
    live_simulation_passed: bool = False
    summary: str = Field(min_length=1)
    model_ids: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    repair_hints: list[str] = Field(default_factory=list)
    raw_result: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def failed_checks_have_repair_guidance(self) -> SimulationCheckEvidence:
        if self.status == SimulationEvidenceStatus.FAIL and not self.repair_hints:
            raise ValueError("failed simulation evidence requires at least one repair hint")
        if self.status == SimulationEvidenceStatus.PASS and self.engine_status.lower() != "pass":
            raise ValueError("simulation evidence cannot pass when the engine did not pass")
        if self.live_simulation_passed and (
            self.method != SimulationEvidenceMethod.NGSPICE
            or self.engine_status.lower() != "pass"
            or not self.tool_version
        ):
            raise ValueError("live_simulation_passed requires an identified ngspice engine pass")
        if (
            self.status == SimulationEvidenceStatus.PASS
            and self.method == SimulationEvidenceMethod.NGSPICE
            and not self.tool_version
        ):
            raise ValueError("ngspice pass evidence requires a detected tool version")
        return self


def _normalized_gate_decision(
    normalized: str,
    method: SimulationEvidenceMethod,
    *,
    degraded: bool,
    missing_solver_identity: bool,
) -> tuple[SimulationEvidenceStatus, SimulationRiskClass, bool, bool]:
    if missing_solver_identity or normalized in {"skipped", "no-reference", "missing", "unsupported"}:
        return SimulationEvidenceStatus.SKIPPED, SimulationRiskClass.HIGH, True, True
    if normalized in {"fail", "error", "blocked"}:
        risk = SimulationRiskClass.CRITICAL if normalized == "error" else SimulationRiskClass.HIGH
        return SimulationEvidenceStatus.FAIL, risk, True, True
    if normalized in {"human-review-required", "review"}:
        return SimulationEvidenceStatus.HUMAN_REVIEW_REQUIRED, SimulationRiskClass.MODERATE, False, True
    if normalized == "pass":
        if method == SimulationEvidenceMethod.NGSPICE and not degraded:
            return SimulationEvidenceStatus.PASS, SimulationRiskClass.LOW, False, False
        return SimulationEvidenceStatus.HUMAN_REVIEW_REQUIRED, SimulationRiskClass.MODERATE, False, True
    return SimulationEvidenceStatus.HUMAN_REVIEW_REQUIRED, SimulationRiskClass.HIGH, False, True


def normalize_simulation_gate(
    *,
    check_id: str,
    domain: SimulationDomain,
    engine_status: str,
    method: SimulationEvidenceMethod,
    summary: str,
    models: list[SimulationModelEvidence],
    tool_version: str = "",
    metrics: dict[str, Any] | None = None,
    repair_hints: list[str] | None = None,
    raw_result: dict[str, Any] | None = None,
) -> SimulationCheckEvidence:
    """Normalize one producer result without collapsing skips or weak models into pass."""
    normalized = engine_status.strip().lower().replace("_", "-")
    degraded = any(model.degraded or model.confidence < 0.8 for model in models)
    solver_method = method in {SimulationEvidenceMethod.NGSPICE, SimulationEvidenceMethod.HYBRID}
    missing_solver_identity = normalized == "pass" and solver_method and (not models or not tool_version)
    live_pass = normalized == "pass" and method == SimulationEvidenceMethod.NGSPICE and not missing_solver_identity
    status, risk, blocking, review = _normalized_gate_decision(
        normalized,
        method,
        degraded=degraded,
        missing_solver_identity=missing_solver_identity,
    )

    return SimulationCheckEvidence(
        check_id=check_id,
        domain=domain,
        method=method,
        engine_status=normalized,
        tool_version=tool_version,
        status=status,
        risk_class=risk,
        blocking=blocking,
        human_review_required=review,
        live_simulation_passed=live_pass,
        summary=summary,
        model_ids=[model.model_id for model in models],
        metrics=metrics or {},
        repair_hints=repair_hints or [],
        raw_result=raw_result or {},
    )


class SimulationFamilyReport(BaseModel):
    """Hash-bound simulation/analysis sign-off evidence for one board family."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    policy_version: str = "1.0"
    family_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    design_state_hash: str = Field(pattern=_SHA256_PATTERN)
    models: list[SimulationModelEvidence] = Field(default_factory=list)
    checks: list[SimulationCheckEvidence] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    check_count: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    human_review_count: int = Field(ge=0)
    live_simulation_pass_count: int = Field(ge=0)
    blocked: bool
    human_review_required: bool
    repair_hints: list[str] = Field(default_factory=list)
    report_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_internal_consistency(self) -> SimulationFamilyReport:
        model_ids = [model.model_id for model in self.models]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("simulation model ids must be unique within a family report")
        check_ids = [check.check_id for check in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("simulation check ids must be unique within a family report")
        unknown_model_ids = sorted({model_id for check in self.checks for model_id in check.model_ids} - set(model_ids))
        if unknown_model_ids:
            raise ValueError("simulation checks reference unknown model ids: " + ", ".join(unknown_model_ids))
        expected = {
            "check_count": len(self.checks),
            "pass_count": sum(check.status == SimulationEvidenceStatus.PASS for check in self.checks),
            "fail_count": sum(check.status == SimulationEvidenceStatus.FAIL for check in self.checks),
            "skipped_count": sum(check.status == SimulationEvidenceStatus.SKIPPED for check in self.checks),
            "human_review_count": sum(
                check.status == SimulationEvidenceStatus.HUMAN_REVIEW_REQUIRED for check in self.checks
            ),
            "live_simulation_pass_count": sum(check.live_simulation_passed for check in self.checks),
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"{field_name} does not match simulation checks")
        if self.blocked != any(check.blocking for check in self.checks):
            raise ValueError("blocked does not match simulation checks")
        if self.human_review_required != any(check.human_review_required for check in self.checks):
            raise ValueError("human_review_required does not match simulation checks")
        expected_hints = list(dict.fromkeys(hint for check in self.checks for hint in check.repair_hints))
        if self.repair_hints != expected_hints:
            raise ValueError("repair_hints do not match simulation checks")
        if self.report_sha256 and self.report_sha256 != self.compute_sha256():
            raise ValueError("simulation family report hash does not match report contents")
        return self

    @classmethod
    def build(
        cls,
        *,
        family_id: str,
        title: str,
        design_state_hash: str,
        models: list[SimulationModelEvidence],
        checks: list[SimulationCheckEvidence],
        assumptions: list[str],
    ) -> SimulationFamilyReport:
        hints = list(dict.fromkeys(hint for check in checks for hint in check.repair_hints))
        report = cls(
            family_id=family_id,
            title=title,
            design_state_hash=design_state_hash,
            models=models,
            checks=checks,
            assumptions=assumptions,
            check_count=len(checks),
            pass_count=sum(check.status == SimulationEvidenceStatus.PASS for check in checks),
            fail_count=sum(check.status == SimulationEvidenceStatus.FAIL for check in checks),
            skipped_count=sum(check.status == SimulationEvidenceStatus.SKIPPED for check in checks),
            human_review_count=sum(check.status == SimulationEvidenceStatus.HUMAN_REVIEW_REQUIRED for check in checks),
            live_simulation_pass_count=sum(check.live_simulation_passed for check in checks),
            blocked=any(check.blocking for check in checks),
            human_review_required=any(check.human_review_required for check in checks),
            repair_hints=hints,
        )
        report.report_sha256 = report.compute_sha256()
        return report

    def compute_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"report_sha256"})
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def resolve_simulation_output_path(
    path: str | Path,
    *,
    trusted_root: str | Path | None = None,
    require_json: bool = False,
) -> Path:
    """Resolve an output path inside a trusted root before filesystem mutation."""
    root = Path(trusted_root or Path.cwd()).resolve(strict=True)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"simulation sign-off output escapes trusted root: {resolved}") from exc
    if require_json and resolved.suffix.lower() != ".json":
        raise ValueError("simulation sign-off report output must be JSON")
    return resolved


def simulation_family_report_json(report: SimulationFamilyReport) -> str:
    if not report.report_sha256 or report.report_sha256 != report.compute_sha256():
        raise ValueError("simulation sign-off report must be finalized and hash-valid")
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_simulation_family_report(
    report: SimulationFamilyReport,
    output_path: str | Path,
    *,
    trusted_root: str | Path | None = None,
) -> Path:
    resolved = resolve_simulation_output_path(output_path, trusted_root=trusted_root, require_json=True)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(simulation_family_report_json(report), encoding="utf-8")
    return resolved


__all__ = [
    "SimulationCheckEvidence",
    "SimulationDomain",
    "SimulationEvidenceMethod",
    "SimulationEvidenceStatus",
    "SimulationFamilyReport",
    "SimulationModelEvidence",
    "SimulationRiskClass",
    "normalize_simulation_gate",
    "resolve_simulation_output_path",
    "simulation_family_report_json",
    "write_simulation_family_report",
]
