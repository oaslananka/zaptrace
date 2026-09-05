"""Trust-aware component governance and deterministic library audit reports.

Schema validation answers whether a component record is structurally honest.
Release eligibility is a separate decision: metadata density never upgrades an
unverified family template into fabrication evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.library.schema import (
    ComponentField,
    ComponentTrustTier,
    FieldProvenance,
    HumanReviewApproval,
    ProvenanceConfidence,
    ProvenanceSourceType,
    ReviewScope,
    has_exact_provenance_identity,
)


class ComponentGovernanceSeverity(StrEnum):
    """Severity for governed component findings."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class GovernedPin(BaseModel):
    """One pin entry in the governed component view."""

    model_config = ConfigDict(extra="forbid", strict=False)

    name: str
    type: str = ""
    description: str = ""
    function: str = ""
    electrical_type: str = ""


class GovernedComponentV2(BaseModel):
    """Normalized governed component contract, schema version 2.0."""

    model_config = ConfigDict(extra="forbid", strict=False)

    schema_version: str = "2.0"
    id: str
    name: str
    category: str
    mpn: str
    manufacturer: str
    datasheet: str
    lifecycle: str
    package: str
    footprint: str
    pins: dict[str, GovernedPin]
    package_pin_map: dict[str, str] = Field(default_factory=dict)
    electrical_limits: dict[str, Any] = Field(default_factory=dict)
    sourcing: dict[str, Any] = Field(default_factory=dict)
    compliance: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    trust_tier: ComponentTrustTier = ComponentTrustTier.HEURISTIC
    field_provenance: dict[ComponentField, FieldProvenance] = Field(default_factory=dict)
    human_review: HumanReviewApproval | None = None


# Backwards-compatible import name. The value is now schema v2.
GovernedComponentV1 = GovernedComponentV2


class ComponentGovernanceFinding(BaseModel):
    """One validation finding for one component."""

    component_id: str
    field: str
    severity: ComponentGovernanceSeverity
    message: str


class ComponentGovernanceValidation(BaseModel):
    """Validation and trust decision for one component."""

    component_id: str
    schema_version: str = "2.0"
    valid: bool
    reviewed_ready: bool
    release_eligible: bool = False
    human_review_required: bool = True
    trust_tier: ComponentTrustTier = ComponentTrustTier.HEURISTIC
    missing_provenance_fields: list[ComponentField] = Field(default_factory=list)
    findings: list[ComponentGovernanceFinding] = Field(default_factory=list)
    coverage_score: float = 0.0


class RepeatedPinSignature(BaseModel):
    """A pin/type signature reused across multiple part-specific records."""

    signature_sha256: str
    count: int
    component_ids: list[str]
    categories: list[str]
    packages: list[str]


class ComponentLoadFinding(BaseModel):
    """A component file rejected before governance conversion."""

    path: str
    reason: str


class ComponentGovernanceReport(BaseModel):
    """Machine-readable repository-wide component audit."""

    schema_version: str = "2.0"
    historical_snapshot: bool = True
    evidence_status: str = "historical-governance-snapshot"
    component_count: int
    valid_count: int
    reviewed_ready_count: int
    release_eligible_count: int = 0
    blocked_component_count: int = 0
    human_review_required_count: int = 0
    error_count: int
    warning_count: int
    load_error_count: int = 0
    mean_coverage_score: float
    trust_tier_counts: dict[str, int] = Field(default_factory=dict)
    missing_field_counts: dict[str, int] = Field(default_factory=dict)
    provenance_source_counts: dict[str, int] = Field(default_factory=dict)
    repeated_pin_signatures: list[RepeatedPinSignature] = Field(default_factory=list)
    load_errors: list[ComponentLoadFinding] = Field(default_factory=list)
    validations: list[ComponentGovernanceValidation]

    @property
    def valid(self) -> bool:
        return self.error_count == 0 and self.load_error_count == 0


@dataclass(frozen=True)
class GovernedComponentSchema:
    """Required field policy for governed component schema v2."""

    required_identity_fields: tuple[str, ...] = ("id", "name", "category", "mpn", "manufacturer")
    required_traceability_fields: tuple[str, ...] = ("datasheet", "package", "footprint", "pins")
    required_governance_sections: tuple[str, ...] = (
        "electrical_limits",
        "sourcing",
        "compliance",
        "provenance",
    )

    @property
    def all_fields(self) -> tuple[str, ...]:
        return self.required_identity_fields + self.required_traceability_fields + self.required_governance_sections


SCHEMA_V2 = GovernedComponentSchema()
SCHEMA_V1 = SCHEMA_V2


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _field(spec: Any, name: str, default: Any = "") -> Any:
    return getattr(spec, name, default)


def _pin_map(raw_pins: dict[str, Any]) -> dict[str, GovernedPin]:
    pins: dict[str, GovernedPin] = {}
    for pin_name, pin_data in raw_pins.items():
        if isinstance(pin_data, dict):
            pins[str(pin_name)] = GovernedPin(name=str(pin_name), **pin_data)
        else:
            pins[str(pin_name)] = GovernedPin(name=str(pin_name), description=str(pin_data))
    return pins


def _derived_electrical_limits(spec: Any) -> dict[str, Any]:
    properties = _as_dict(_field(spec, "properties", {}))
    result = _as_dict(_field(spec, "electrical_limits", {})).copy()
    if _field(spec, "voltage_supply", "") and "voltage_supply" not in result:
        result["voltage_supply"] = _field(spec, "voltage_supply")
    for key in (
        "rated_power_w",
        "max_voltage_v",
        "voltage_rating_v",
        "current_rating_a",
        "frequency_mhz",
        "temperature_range",
    ):
        if key in properties and key not in result:
            result[key] = properties[key]
    return result


def governed_component_from_spec(spec: Any) -> GovernedComponentV2:
    """Convert a loader ``ComponentSpec``-like object into schema v2."""

    properties = _as_dict(_field(spec, "properties", {}))
    sourcing = _as_dict(_field(spec, "sourcing", {})).copy()
    if _field(spec, "mpn", "") and "mpn" not in sourcing:
        sourcing["mpn"] = _field(spec, "mpn")
    if _field(spec, "manufacturer", "") and "manufacturer" not in sourcing:
        sourcing["manufacturer"] = _field(spec, "manufacturer")
    compliance = _as_dict(_field(spec, "compliance", {})).copy()
    if "rohs" in properties and "rohs" not in compliance:
        compliance["rohs"] = properties["rohs"]
    provenance = _as_dict(_field(spec, "provenance", {})).copy()
    if _field(spec, "datasheet", "") and "datasheet" not in provenance:
        provenance["datasheet"] = _field(spec, "datasheet")
    return GovernedComponentV2(
        id=_field(spec, "id"),
        name=_field(spec, "name"),
        category=_field(spec, "category"),
        mpn=_field(spec, "mpn", ""),
        manufacturer=_field(spec, "manufacturer", ""),
        datasheet=_field(spec, "datasheet", ""),
        lifecycle=_field(spec, "lifecycle", ""),
        package=_field(spec, "package", ""),
        footprint=_field(spec, "footprint", ""),
        pins=_pin_map(_as_dict(_field(spec, "pins", {}))),
        package_pin_map={str(k): str(v) for k, v in _as_dict(_field(spec, "package_pin_map", {})).items()},
        electrical_limits=_derived_electrical_limits(spec),
        sourcing=sourcing,
        compliance=compliance,
        provenance=provenance,
        trust_tier=_field(spec, "trust_tier", ComponentTrustTier.HEURISTIC),
        field_provenance=dict(_field(spec, "field_provenance", {})),
        human_review=_field(spec, "human_review", None),
    )


def _finding(
    component_id: str,
    field: str,
    severity: ComponentGovernanceSeverity,
    message: str,
) -> ComponentGovernanceFinding:
    return ComponentGovernanceFinding(
        component_id=component_id,
        field=field,
        severity=severity,
        message=message,
    )


def _approval_covers_release(approval: HumanReviewApproval | None) -> bool:
    if approval is None:
        return False
    return {ReviewScope.RELEASE, ReviewScope.FABRICATION}.issubset(approval.scopes)


_VERIFIED_SOURCES = {
    ProvenanceSourceType.MANUFACTURER_DOCUMENT,
    ProvenanceSourceType.MANUFACTURER_WEB,
    ProvenanceSourceType.AUTHORIZED_DISTRIBUTOR,
}


def _verified_evidence_gaps(evidence: FieldProvenance) -> list[str]:
    requirements = (
        (evidence.source_type in _VERIFIED_SOURCES, "authoritative manufacturer/distributor source"),
        (bool(evidence.source_identity), "source identity"),
        (has_exact_provenance_identity(evidence), "source SHA-256"),
        (bool(evidence.source_version), "source version"),
        (evidence.extracted_at is not None, "extraction date"),
        (bool(evidence.reviewed_by and evidence.reviewed_at), "field review metadata"),
        (evidence.confidence is ProvenanceConfidence.HIGH, "high confidence"),
    )
    return [message for passed, message in requirements if not passed]


def _verified_evidence_findings(component: GovernedComponentV2) -> list[ComponentGovernanceFinding]:
    findings: list[ComponentGovernanceFinding] = []
    if not component.package_pin_map:
        findings.append(
            _finding(
                component.id,
                "package_pin_map",
                ComponentGovernanceSeverity.ERROR,
                "verified trust tier requires an exact physical package pin map",
            )
        )
    for field_name, evidence in component.field_provenance.items():
        failures = _verified_evidence_gaps(evidence)
        if failures:
            findings.append(
                _finding(
                    component.id,
                    f"field_provenance.{field_name.value}",
                    ComponentGovernanceSeverity.ERROR,
                    "verified trust tier requires " + ", ".join(failures),
                )
            )
    if not _approval_covers_release(component.human_review):
        findings.append(
            _finding(
                component.id,
                "human_review",
                ComponentGovernanceSeverity.ERROR,
                "verified trust tier requires release and fabrication review scopes",
            )
        )
    return findings


def validate_governed_component(
    spec: Any, *, schema: GovernedComponentSchema = SCHEMA_V2
) -> ComponentGovernanceValidation:
    """Validate schema completeness and compute release eligibility."""

    component = governed_component_from_spec(spec)
    findings: list[ComponentGovernanceFinding] = []
    populated = 0
    for field_name in schema.all_fields:
        value = getattr(component, field_name)
        if value:
            populated += 1
            continue
        severity = (
            ComponentGovernanceSeverity.ERROR
            if field_name in schema.required_identity_fields + schema.required_traceability_fields
            else ComponentGovernanceSeverity.WARNING
        )
        findings.append(
            _finding(
                component.id,
                field_name,
                severity,
                f"governed component schema v2 requires {field_name}",
            )
        )

    missing_provenance = sorted(set(ComponentField) - set(component.field_provenance), key=lambda field: field.value)
    findings.extend(
        _finding(
            component.id,
            f"field_provenance.{field_name.value}",
            ComponentGovernanceSeverity.ERROR,
            f"schema v2 requires provenance for {field_name.value}",
        )
        for field_name in missing_provenance
    )

    if component.trust_tier is ComponentTrustTier.VERIFIED:
        findings.extend(_verified_evidence_findings(component))
    elif component.trust_tier is ComponentTrustTier.PLACEHOLDER:
        findings.append(
            _finding(
                component.id,
                "trust_tier",
                ComponentGovernanceSeverity.INFO,
                "placeholder records are never release or fabrication eligible",
            )
        )
    elif not _approval_covers_release(component.human_review):
        findings.append(
            _finding(
                component.id,
                "trust_tier",
                ComponentGovernanceSeverity.INFO,
                f"{component.trust_tier.value} record requires policy-approved human review for release",
            )
        )

    errors = [finding for finding in findings if finding.severity is ComponentGovernanceSeverity.ERROR]
    warnings = [finding for finding in findings if finding.severity is ComponentGovernanceSeverity.WARNING]
    valid = not errors
    approval_override = _approval_covers_release(component.human_review)
    release_eligible = valid and (
        component.trust_tier is ComponentTrustTier.VERIFIED
        or (component.trust_tier in {ComponentTrustTier.CURATED, ComponentTrustTier.HEURISTIC} and approval_override)
    )
    human_review_required = not release_eligible
    return ComponentGovernanceValidation(
        component_id=component.id,
        valid=valid,
        reviewed_ready=valid and not warnings and release_eligible,
        release_eligible=release_eligible,
        human_review_required=human_review_required,
        trust_tier=component.trust_tier,
        missing_provenance_fields=missing_provenance,
        findings=findings,
        coverage_score=round(populated / len(schema.all_fields), 3),
    )


def _pin_signature(spec: Any) -> str:
    pins = _as_dict(_field(spec, "pins", {}))
    normalized = []
    for name, raw in sorted(pins.items(), key=lambda item: str(item[0])):
        pin = raw if isinstance(raw, dict) else {"description": str(raw)}
        normalized.append((str(name), str(pin.get("type", "")), str(pin.get("electrical_type", ""))))
    payload = json.dumps(normalized, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _repeated_pin_signatures(specs: dict[str, Any]) -> list[RepeatedPinSignature]:
    grouped: dict[str, list[Any]] = {}
    for key in sorted(specs):
        spec = specs[key]
        if _field(spec, "category", "") == "passive":
            continue
        signature = _pin_signature(spec)
        grouped.setdefault(signature, []).append(spec)

    findings: list[RepeatedPinSignature] = []
    for signature, group in sorted(grouped.items()):
        if len(group) < 3:
            continue
        findings.append(
            RepeatedPinSignature(
                signature_sha256=signature,
                count=len(group),
                component_ids=sorted(str(_field(spec, "id")) for spec in group),
                categories=sorted({str(_field(spec, "category")) for spec in group}),
                packages=sorted({str(_field(spec, "package")) for spec in group}),
            )
        )
    findings.sort(key=lambda row: (-row.count, row.signature_sha256))
    return findings


def _load_findings(load_errors: Iterable[Any] | None) -> list[ComponentLoadFinding]:
    return [
        ComponentLoadFinding(path=str(_field(error, "path")), reason=str(_field(error, "reason")))
        for error in (load_errors or [])
    ]


def _finding_count(validations: list[ComponentGovernanceValidation], severity: ComponentGovernanceSeverity) -> int:
    return sum(1 for row in validations for finding in row.findings if finding.severity is severity)


def _mean_coverage(validations: list[ComponentGovernanceValidation]) -> float:
    return round(sum(row.coverage_score for row in validations) / len(validations), 3) if validations else 0.0


def _trust_and_source_counts(specs: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    trust_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for spec in specs.values():
        tier = _field(spec, "trust_tier", ComponentTrustTier.HEURISTIC)
        tier_value = tier.value if isinstance(tier, ComponentTrustTier) else str(tier)
        trust_counts[tier_value] = trust_counts.get(tier_value, 0) + 1
        for evidence in dict(_field(spec, "field_provenance", {})).values():
            source_type = _field(evidence, "source_type", "")
            value = source_type.value if isinstance(source_type, ProvenanceSourceType) else str(source_type)
            if value:
                source_counts[value] = source_counts.get(value, 0) + 1
    return dict(sorted(trust_counts.items())), dict(sorted(source_counts.items()))


def _missing_field_counts(validations: list[ComponentGovernanceValidation]) -> dict[str, int]:
    counts: dict[str, int] = {}
    reportable = {ComponentGovernanceSeverity.ERROR, ComponentGovernanceSeverity.WARNING}
    for row in validations:
        for finding in row.findings:
            if finding.severity in reportable:
                counts[finding.field] = counts.get(finding.field, 0) + 1
    return dict(sorted(counts.items()))


def validate_component_library(
    specs: dict[str, Any], *, load_errors: Iterable[Any] | None = None
) -> ComponentGovernanceReport:
    """Validate all loaded specs and return deterministic trust evidence."""

    validations = [validate_governed_component(specs[key]) for key in sorted(specs)]
    load_findings = _load_findings(load_errors)
    trust_counts, source_counts = _trust_and_source_counts(specs)
    release_count = sum(1 for row in validations if row.release_eligible)
    inspected_count = len(validations) + len(load_findings)
    return ComponentGovernanceReport(
        component_count=inspected_count,
        valid_count=sum(1 for row in validations if row.valid),
        reviewed_ready_count=sum(1 for row in validations if row.reviewed_ready),
        release_eligible_count=release_count,
        blocked_component_count=inspected_count - release_count,
        human_review_required_count=sum(1 for row in validations if row.human_review_required),
        error_count=_finding_count(validations, ComponentGovernanceSeverity.ERROR) + len(load_findings),
        warning_count=_finding_count(validations, ComponentGovernanceSeverity.WARNING),
        load_error_count=len(load_findings),
        mean_coverage_score=_mean_coverage(validations),
        trust_tier_counts=trust_counts,
        missing_field_counts=_missing_field_counts(validations),
        provenance_source_counts=source_counts,
        repeated_pin_signatures=_repeated_pin_signatures(specs),
        load_errors=load_findings,
        validations=validations,
    )


def write_component_governance_report(
    specs: dict[str, Any], output_path: str | Path, *, load_errors: Iterable[Any] | None = None
) -> Path:
    """Write a machine-readable component governance report."""

    out = Path(output_path)
    if out.suffix.lower() != ".json":
        raise ValueError(f"unexpected governance report suffix: {out.suffix}")
    report = validate_component_library(specs, load_errors=load_errors)
    resolved = out.resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return resolved
