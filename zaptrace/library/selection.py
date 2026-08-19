"""Deterministic, evidence-aware component selection before PCB layout.

The selector composes existing component-governance evidence and records why a
candidate was accepted or rejected.  It never upgrades heuristic metadata into
manufacturer verification or fabrication approval.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.ee.footprint_proof import FootprintProof, FootprintProofValidationReport, validate_footprint_proof
from zaptrace.library.datasheet import (
    DatasheetFactReport,
    DatasheetFactScope,
    validate_datasheet_facts,
)
from zaptrace.library.governance import validate_governed_component
from zaptrace.library.loader import ComponentSpec
from zaptrace.supply.contracts import BomProviderResult, LifecycleStatus, RiskLevel


class SelectionDiagnosticSeverity(StrEnum):
    """Severity emitted by the pre-layout component-selection gate."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class SelectionDiagnostic(BaseModel):
    """One explainable candidate-selection finding."""

    model_config = ConfigDict(extra="forbid", strict=False)

    code: str
    severity: SelectionDiagnosticSeverity
    message: str
    expected: str = ""
    observed: str = ""


class SelectionScoreDimension(BaseModel):
    """One deterministic weighted score dimension."""

    model_config = ConfigDict(extra="forbid", strict=False)

    name: str
    score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(gt=0.0, le=1.0)
    explanation: str


class ComponentSelectionRequirement(BaseModel):
    """Declared electrical, physical, and supply constraints for one position."""

    model_config = ConfigDict(extra="forbid", strict=False)

    requirement_id: str = Field(min_length=1)
    position: str = Field(min_length=1)
    category: str = Field(min_length=1)
    operating_voltage_v: float | None = Field(default=None, ge=0)
    operating_current_a: float | None = Field(default=None, ge=0)
    operating_power_w: float | None = Field(default=None, ge=0)
    voltage_utilization_max: float = Field(default=0.8, gt=0, le=1)
    current_utilization_max: float = Field(default=0.8, gt=0, le=1)
    power_utilization_max: float = Field(default=0.5, gt=0, le=1)
    allowed_packages: list[str] = Field(default_factory=list)
    required_footprint: str = ""
    required_pin_functions: dict[str, str] = Field(default_factory=dict)
    max_supply_risk: RiskLevel = RiskLevel.HIGH
    require_release_eligible: bool = False


class ComponentSelectionEvidence(BaseModel):
    """Optional evidence attached to one candidate assessment."""

    model_config = ConfigDict(extra="forbid", strict=False)

    datasheet: DatasheetFactReport | None = None
    footprint: FootprintProof | None = None
    supply: BomProviderResult | None = None


class ComponentCandidateAssessment(BaseModel):
    """Machine-readable assessment and rank input for one candidate."""

    model_config = ConfigDict(extra="forbid", strict=False)

    component_id: str
    eligible: bool
    score: float = Field(ge=0.0, le=1.0)
    score_dimensions: list[SelectionScoreDimension]
    diagnostics: list[SelectionDiagnostic] = Field(default_factory=list)
    extracted_constraints: dict[str, Any] = Field(default_factory=dict)
    trust_tier: str
    release_eligible: bool
    human_review_required: bool
    assessment_hash: str


class ComponentSelectionDecision(BaseModel):
    """Ranked selection result for one design position."""

    model_config = ConfigDict(extra="forbid", strict=False)

    schema_version: str = "1.0"
    requirement: ComponentSelectionRequirement
    selected_component_id: str = ""
    blocked: bool
    human_review_required: bool
    rationale: str
    assessments: list[ComponentCandidateAssessment]
    decision_hash: str
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "selection evidence does not prove manufacturer approval or component authenticity",
            "stock and lifecycle evidence may change after its recorded timestamp",
            "human engineering review remains required before fabrication",
        ]
    )

    def proof_evidence(self) -> dict[str, Any]:
        """Return a compact payload suitable for a proof-pack manifest."""
        selected = next(
            (item for item in self.assessments if item.component_id == self.selected_component_id),
            None,
        )
        return {
            "schema_version": self.schema_version,
            "requirement_id": self.requirement.requirement_id,
            "position": self.requirement.position,
            "selected_component_id": self.selected_component_id,
            "candidate_count": len(self.assessments),
            "blocked": self.blocked,
            "human_review_required": self.human_review_required,
            "rationale": self.rationale,
            "extracted_constraints": dict(selected.extracted_constraints) if selected is not None else {},
            "decision_hash": self.decision_hash,
            "non_claims": list(self.non_claims),
        }


def _canonical_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _error(code: str, message: str, *, expected: str = "", observed: str = "") -> SelectionDiagnostic:
    return SelectionDiagnostic(
        code=code,
        severity=SelectionDiagnosticSeverity.ERROR,
        message=message,
        expected=expected,
        observed=observed,
    )


def _warning(code: str, message: str, *, expected: str = "", observed: str = "") -> SelectionDiagnostic:
    return SelectionDiagnostic(
        code=code,
        severity=SelectionDiagnosticSeverity.WARNING,
        message=message,
        expected=expected,
        observed=observed,
    )


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _physical_diagnostics(
    requirement: ComponentSelectionRequirement,
    spec: ComponentSpec,
) -> list[SelectionDiagnostic]:
    diagnostics: list[SelectionDiagnostic] = []
    if requirement.allowed_packages and spec.package not in requirement.allowed_packages:
        diagnostics.append(
            _error(
                "package-mismatch",
                f"{spec.id} package is outside the allowed package set",
                expected=", ".join(sorted(requirement.allowed_packages)),
                observed=spec.package,
            )
        )
    if requirement.required_footprint and spec.footprint != requirement.required_footprint:
        diagnostics.append(
            _error(
                "footprint-mismatch",
                f"{spec.id} footprint does not match the required footprint",
                expected=requirement.required_footprint,
                observed=spec.footprint,
            )
        )
    for pin_id, expected_function in sorted(requirement.required_pin_functions.items()):
        raw_pin = spec.pins.get(pin_id, {})
        observed = str(raw_pin.get("function") or raw_pin.get("description") or raw_pin.get("type") or "")
        if observed.casefold() != expected_function.casefold():
            diagnostics.append(
                _error(
                    "pin-function-mismatch",
                    f"{spec.id} pin {pin_id} does not provide the required function",
                    expected=expected_function,
                    observed=observed or "missing",
                )
            )
    return diagnostics


_FACT_CONSTRAINT_KEYS: dict[tuple[str, DatasheetFactScope | None], str] = {
    ("voltage", DatasheetFactScope.ABSOLUTE_MAXIMUM): "absolute_voltage_max_v",
    ("voltage", DatasheetFactScope.RECOMMENDED_OPERATING): "recommended_voltage_max_v",
    ("voltage", None): "voltage_rating_v",
    ("current", DatasheetFactScope.ABSOLUTE_MAXIMUM): "absolute_current_max_a",
    ("current", DatasheetFactScope.RECOMMENDED_OPERATING): "recommended_current_max_a",
    ("current", None): "current_rating_a",
    ("power", DatasheetFactScope.ABSOLUTE_MAXIMUM): "absolute_power_max_w",
    ("power", DatasheetFactScope.RECOMMENDED_OPERATING): "recommended_power_max_w",
    ("power", None): "power_rating_w",
}


def _fact_constraint_key(field: str, scope: DatasheetFactScope) -> str | None:
    normalized = field.casefold()
    if "max" not in normalized:
        return None
    metric = next((name for name in ("voltage", "current", "power") if name in normalized), None)
    if metric is None:
        return None
    scoped = scope if scope in {DatasheetFactScope.ABSOLUTE_MAXIMUM, DatasheetFactScope.RECOMMENDED_OPERATING} else None
    return _FACT_CONSTRAINT_KEYS[(metric, scoped)]


def _datasheet_constraints(report: DatasheetFactReport | None) -> dict[str, float]:
    if report is None:
        return {}
    result: dict[str, float] = {}
    for fact in report.facts:
        value = _as_float(fact.value)
        key = _fact_constraint_key(fact.field, fact.scope)
        if value is not None and key is not None:
            result[key] = value
    return result


def _first_float(mapping: dict[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = _as_float(mapping.get(name))
        if value is not None:
            return value
    return None


def _rating(
    extracted: dict[str, Any],
    *,
    recommended: tuple[str, ...],
    absolute: tuple[str, ...],
    fallback: tuple[str, ...],
) -> float | None:
    return (
        _first_float(extracted, recommended) or _first_float(extracted, absolute) or _first_float(extracted, fallback)
    )


def _metric_diagnostic(
    *,
    component_id: str,
    metric: str,
    used: float | None,
    rating: float | None,
    utilization_limit: float,
) -> SelectionDiagnostic | None:
    if used is None:
        return None
    if rating is None or rating <= 0:
        return _warning(
            f"{metric}-limit-missing",
            f"{component_id} has no machine-readable {metric} rating for the declared operating point",
            observed=str(used),
        )
    allowed = rating * utilization_limit
    if used <= allowed:
        return None
    return _error(
        f"{metric}-limit-exceeded",
        f"{component_id} operating {metric} exceeds the configured derating envelope",
        expected=f"<= {allowed:.6g}",
        observed=f"{used:.6g}",
    )


def _electrical_diagnostics(
    requirement: ComponentSelectionRequirement,
    spec: ComponentSpec,
    extracted: dict[str, Any],
) -> list[SelectionDiagnostic]:
    voltage_rating = _rating(
        extracted,
        recommended=("recommended_voltage_max_v",),
        absolute=("absolute_voltage_max_v",),
        fallback=("max_voltage_v", "voltage_rating_v", "rated_voltage_v"),
    )
    current_rating = _rating(
        extracted,
        recommended=("recommended_current_max_a",),
        absolute=("absolute_current_max_a",),
        fallback=("current_rating_a", "max_current_a", "output_current_max_a"),
    )
    power_rating = _rating(
        extracted,
        recommended=("recommended_power_max_w",),
        absolute=("absolute_power_max_w",),
        fallback=("max_power_w", "rated_power_w", "power_rating_w"),
    )
    checks = (
        _metric_diagnostic(
            component_id=spec.id,
            metric="voltage",
            used=requirement.operating_voltage_v,
            rating=voltage_rating,
            utilization_limit=requirement.voltage_utilization_max,
        ),
        _metric_diagnostic(
            component_id=spec.id,
            metric="current",
            used=requirement.operating_current_a,
            rating=current_rating,
            utilization_limit=requirement.current_utilization_max,
        ),
        _metric_diagnostic(
            component_id=spec.id,
            metric="power",
            used=requirement.operating_power_w,
            rating=power_rating,
            utilization_limit=requirement.power_utilization_max,
        ),
    )
    return [item for item in checks if item is not None]


def _category_diagnostics(
    requirement: ComponentSelectionRequirement,
    spec: ComponentSpec,
) -> list[SelectionDiagnostic]:
    if spec.category == requirement.category:
        return []
    return [
        SelectionDiagnostic(
            code="category-mismatch",
            severity=SelectionDiagnosticSeverity.ERROR,
            message=f"{spec.id} category does not satisfy {requirement.position}",
            expected=requirement.category,
            observed=spec.category,
        )
    ]


def _datasheet_diagnostics(report: DatasheetFactReport | None) -> list[SelectionDiagnostic]:
    if report is None:
        return []
    validation = validate_datasheet_facts(report)
    diagnostics: list[SelectionDiagnostic] = []
    if validation.blocked:
        codes = sorted({item.code for item in validation.diagnostics if item.severity.value == "error"})
        diagnostics.append(
            _error(
                "datasheet-facts-blocked",
                "datasheet fact validation reported blocking provenance or conflicts",
                expected="valid hashed, non-conflicting facts",
                observed=", ".join(codes),
            )
        )
    if validation.human_review_required:
        diagnostics.append(
            _warning(
                "datasheet-review-required",
                f"{validation.low_confidence_count} low-confidence datasheet fact(s) require review",
            )
        )
    return diagnostics


def _validate_component_footprint(spec: ComponentSpec, proof: FootprintProof) -> FootprintProofValidationReport:
    if spec.package_pin_map:
        return validate_footprint_proof(proof, expected_physical_pins=set(spec.package_pin_map))
    return validate_footprint_proof(proof, expected_pins=set(spec.pins))


def _footprint_diagnostics(spec: ComponentSpec, proof: FootprintProof | None) -> list[SelectionDiagnostic]:
    if proof is None:
        return []
    validation = _validate_component_footprint(spec, proof)
    diagnostics: list[SelectionDiagnostic] = []
    if validation.blocked:
        codes = sorted({item.code for item in validation.diagnostics if item.severity.value == "error"})
        diagnostics.append(
            _error(
                "footprint-proof-blocked",
                "footprint proof does not match the component pin/pad contract",
                expected="complete matching pin map and footprint geometry",
                observed=", ".join(codes),
            )
        )
    if proof.package_id != spec.package or proof.footprint_name != spec.footprint:
        diagnostics.append(
            _error(
                "footprint-proof-mismatch",
                "attached footprint proof belongs to a different package or footprint",
                expected=f"{spec.package} / {spec.footprint}",
                observed=f"{proof.package_id} / {proof.footprint_name}",
            )
        )
    return diagnostics


_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


def _supply_risk(spec: ComponentSpec, supply: BomProviderResult | None) -> RiskLevel:
    if supply is None:
        return RiskLevel.MEDIUM
    if supply.lifecycle is LifecycleStatus.OBSOLETE or supply.stock == 0:
        return RiskLevel.CRITICAL
    if supply.lifecycle is LifecycleStatus.NRND:
        return RiskLevel.HIGH
    if supply.footprint and spec.footprint and supply.footprint != spec.footprint:
        return RiskLevel.HIGH
    if supply.lifecycle is LifecycleStatus.UNKNOWN or supply.stock is None:
        return RiskLevel.MEDIUM
    if supply.stock < 100 or supply.cache.stale:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _supply_diagnostics(
    requirement: ComponentSelectionRequirement,
    spec: ComponentSpec,
    supply: BomProviderResult | None,
) -> tuple[RiskLevel, list[SelectionDiagnostic]]:
    risk = _supply_risk(spec, supply)
    if _RISK_ORDER[risk] <= _RISK_ORDER[requirement.max_supply_risk]:
        return risk, []
    return (
        risk,
        [
            _error(
                "supply-risk-blocked",
                f"{spec.id} supply risk exceeds the requirement ceiling",
                expected=requirement.max_supply_risk.value,
                observed=risk.value,
            )
        ],
    )


def _release_diagnostics(
    requirement: ComponentSelectionRequirement,
    spec: ComponentSpec,
) -> list[SelectionDiagnostic]:
    governance = validate_governed_component(spec)
    if not requirement.require_release_eligible or governance.release_eligible:
        return []
    return [
        _error(
            "release-eligibility-required",
            f"{spec.id} is not eligible for release/fabrication use",
            expected="release_eligible=true",
            observed=f"trust_tier={governance.trust_tier.value}",
        )
    ]


def _extract_constraints(spec: ComponentSpec, evidence: ComponentSelectionEvidence) -> dict[str, Any]:
    extracted = dict(spec.electrical_limits)
    extracted.update(_datasheet_constraints(evidence.datasheet))
    extracted.update(
        {
            "package": spec.package,
            "footprint": spec.footprint,
            "pin_count": len(spec.pins),
            "supply_risk": _supply_risk(spec, evidence.supply).value,
        }
    )
    return extracted


def _footprint_score(spec: ComponentSpec, evidence: ComponentSelectionEvidence) -> SelectionScoreDimension:
    if evidence.footprint is not None:
        validation = _validate_component_footprint(spec, evidence.footprint)
        score = 1.0 if not validation.blocked else 0.0
        explanation = "attached footprint proof passes" if score else "attached footprint proof is blocked"
    elif spec.footprint:
        score = 0.6
        explanation = "component declares a footprint but no attached footprint proof"
    else:
        score = 0.0
        explanation = "component has no usable footprint reference"
    return SelectionScoreDimension(name="footprint", score=score, weight=0.20, explanation=explanation)


def _evidence_score(spec: ComponentSpec, evidence: ComponentSelectionEvidence) -> SelectionScoreDimension:
    governance = validate_governed_component(spec)
    scores = {"verified": 1.0, "curated": 0.8, "heuristic": 0.5, "placeholder": 0.0}
    score = scores[governance.trust_tier.value]
    if evidence.datasheet is not None and not validate_datasheet_facts(evidence.datasheet).blocked:
        score = min(1.0, score + 0.1)
    return SelectionScoreDimension(
        name="evidence",
        score=score,
        weight=0.25,
        explanation=f"component trust tier is {governance.trust_tier.value}",
    )


def _supply_score(spec: ComponentSpec, evidence: ComponentSelectionEvidence) -> SelectionScoreDimension:
    risk = _supply_risk(spec, evidence.supply)
    scores = {
        RiskLevel.LOW: 1.0,
        RiskLevel.MEDIUM: 0.6,
        RiskLevel.HIGH: 0.25,
        RiskLevel.CRITICAL: 0.0,
    }
    return SelectionScoreDimension(
        name="supply",
        score=scores[risk],
        weight=0.20,
        explanation=f"supply risk is {risk.value}",
    )


def assess_component_candidate(
    requirement: ComponentSelectionRequirement,
    spec: ComponentSpec,
    evidence: ComponentSelectionEvidence | None = None,
) -> ComponentCandidateAssessment:
    """Assess one candidate without mutating the component or design."""
    attached = evidence or ComponentSelectionEvidence()
    extracted = _extract_constraints(spec, attached)
    supply_risk, supply_diagnostics = _supply_diagnostics(requirement, spec, attached.supply)
    diagnostics = [
        *_category_diagnostics(requirement, spec),
        *_physical_diagnostics(requirement, spec),
        *_electrical_diagnostics(requirement, spec, extracted),
        *_datasheet_diagnostics(attached.datasheet),
        *_footprint_diagnostics(spec, attached.footprint),
        *supply_diagnostics,
        *_release_diagnostics(requirement, spec),
    ]
    errors = [item for item in diagnostics if item.severity is SelectionDiagnosticSeverity.ERROR]
    warnings = [item for item in diagnostics if item.severity is SelectionDiagnosticSeverity.WARNING]
    governance = validate_governed_component(spec)
    dimensions = [
        SelectionScoreDimension(
            name="constraint_fit",
            score=0.0 if errors else 1.0,
            weight=0.35,
            explanation="hard constraints failed" if errors else "declared hard constraints pass",
        ),
        _evidence_score(spec, attached),
        _footprint_score(spec, attached),
        _supply_score(spec, attached),
    ]
    score = round(sum(item.score * item.weight for item in dimensions), 6)
    human_review_required = (
        bool(errors or warnings)
        or governance.human_review_required
        or attached.datasheet is None
        or attached.footprint is None
        or attached.supply is None
        or supply_risk is not RiskLevel.LOW
    )
    payload = {
        "requirement_id": requirement.requirement_id,
        "component_id": spec.id,
        "eligible": not errors,
        "score": score,
        "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
        "extracted_constraints": extracted,
        "trust_tier": governance.trust_tier.value,
        "release_eligible": governance.release_eligible,
    }
    return ComponentCandidateAssessment(
        component_id=spec.id,
        eligible=not errors,
        score=score,
        score_dimensions=dimensions,
        diagnostics=diagnostics,
        extracted_constraints=extracted,
        trust_tier=governance.trust_tier.value,
        release_eligible=governance.release_eligible,
        human_review_required=human_review_required,
        assessment_hash=_canonical_hash(payload),
    )


def select_component(
    requirement: ComponentSelectionRequirement,
    candidates: list[ComponentSpec],
    evidence_by_component: dict[str, ComponentSelectionEvidence] | None = None,
) -> ComponentSelectionDecision:
    """Rank candidates and select the highest-scoring hard-gate-passing part."""
    evidence_map = evidence_by_component or {}
    assessments = [assess_component_candidate(requirement, spec, evidence_map.get(spec.id)) for spec in candidates]
    assessments.sort(key=lambda item: (not item.eligible, -item.score, item.component_id))
    selected = next((item for item in assessments if item.eligible), None)
    selected_id = selected.component_id if selected is not None else ""
    blocked = selected is None
    human_review_required = blocked or bool(selected and selected.human_review_required)
    rationale = (
        f"selected {selected_id} at rank 1 of {sum(item.eligible for item in assessments)} eligible candidate(s)"
        if selected is not None
        else "no candidate passed the pre-layout component-selection gate"
    )
    hash_payload = {
        "requirement": requirement.model_dump(mode="json"),
        "selected_component_id": selected_id,
        "assessments": [
            {
                "component_id": item.component_id,
                "eligible": item.eligible,
                "score": item.score,
                "assessment_hash": item.assessment_hash,
            }
            for item in assessments
        ],
    }
    return ComponentSelectionDecision(
        requirement=requirement,
        selected_component_id=selected_id,
        blocked=blocked,
        human_review_required=human_review_required,
        rationale=rationale,
        assessments=assessments,
        decision_hash=_canonical_hash(hash_payload),
    )
