"""Strict component record schema and trust vocabulary.

Schema v2 is the validation boundary for committed component YAML.  It rejects
unknown structural keys, keeps ``properties`` as the single documented domain
extension bag, and records provenance for every field that can affect sourcing,
pin mapping, package/footprint selection, electrical checks, or release safety.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class ComponentTrustTier(StrEnum):
    """Declared evidence strength for one component record."""

    VERIFIED = "verified"
    CURATED = "curated"
    HEURISTIC = "heuristic"
    PLACEHOLDER = "placeholder"


class ComponentField(StrEnum):
    """Critical fields that require independent provenance entries."""

    MPN = "mpn"
    DATASHEET = "datasheet"
    PIN_MAP = "pin_map"
    PACKAGE = "package"
    FOOTPRINT = "footprint"
    ELECTRICAL_LIMITS = "electrical_limits"
    LIFECYCLE = "lifecycle"
    SOURCING = "sourcing"


class ProvenanceSourceType(StrEnum):
    """Supported evidence source classes."""

    MANUFACTURER_DOCUMENT = "manufacturer_document"
    MANUFACTURER_WEB = "manufacturer_web"
    AUTHORIZED_DISTRIBUTOR = "authorized_distributor"
    INTERNAL_MANIFEST = "internal_manifest"
    FAMILY_TEMPLATE = "family_template"
    MANUAL_ENTRY = "manual_entry"


class ProvenanceConfidence(StrEnum):
    """Confidence assigned to one field claim."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReviewScope(StrEnum):
    """Actions covered by a policy-approved human review."""

    RELEASE = "release"
    FABRICATION = "fabrication"


class StrictSchemaModel(BaseModel):
    """Base model that rejects undeclared keys while allowing YAML coercion."""

    model_config = ConfigDict(extra="forbid", strict=False)


class ComponentPin(StrictSchemaModel):
    """One strict pin-map entry."""

    type: str = ""
    description: str = ""
    function: str = ""
    electrical_type: str = ""


class ElectricalLimits(StrictSchemaModel):
    """Governed electrical-limit keys used by the committed library."""

    review_note: str = ""
    max_power_w: float | None = None
    voltage_supply: str = ""
    rated_voltage_v: float | None = None
    frequency_mhz: float | None = None
    current_rating_a: float | None = None
    temperature_range: str | list[float] = ""
    max_voltage_v: float | None = None
    rated_power_w: float | None = None
    capacitance_uf: float | None = None


class SourcingMetadata(StrictSchemaModel):
    """Part sourcing identity and review status."""

    mpn: str = ""
    manufacturer: str = ""
    status: str = ""
    production_note: str = ""
    authorized_distributors: list[str] = Field(default_factory=list)


class ComplianceMetadata(StrictSchemaModel):
    """Regulatory metadata without implying certification."""

    rohs: bool | str | None = None
    reach: bool | str | None = None
    production_note: str = ""


class LegacyProvenanceMetadata(StrictSchemaModel):
    """Record-level legacy provenance retained alongside field evidence."""

    source: str = ""
    reviewed_by: str = ""
    generation: str = ""
    review_status: str = ""
    production_note: str = ""
    datasheet_reference_type: str = ""
    datasheet: str = ""
    datasheet_sha256: str = ""
    source_sha256: str = ""


class FieldProvenance(StrictSchemaModel):
    """Evidence for one critical component field."""

    source_type: ProvenanceSourceType
    source_locator: str = Field(min_length=1)
    source_identity: str = ""
    source_sha256: str = ""
    source_capture_path: str = ""
    source_capture_sha256: str = ""
    source_version: str = ""
    extraction_method: str = Field(min_length=1)
    extracted_at: date | None = None
    reviewed_by: str = ""
    reviewed_at: date | None = None
    confidence: ProvenanceConfidence

    @model_validator(mode="after")
    def validate_capture_identity(self) -> FieldProvenance:
        capture_fields = bool(self.source_capture_path), bool(self.source_capture_sha256)
        if any(capture_fields) and not all(capture_fields):
            raise ValueError("source capture path and SHA-256 must be provided together")
        if self.source_capture_sha256 and not _SHA256_RE.fullmatch(self.source_capture_sha256):
            raise ValueError("source capture SHA-256 must be a lowercase SHA-256 digest")
        if all(capture_fields):
            if self.source_type not in {
                ProvenanceSourceType.MANUFACTURER_WEB,
                ProvenanceSourceType.AUTHORIZED_DISTRIBUTOR,
            }:
                raise ValueError("source capture identity is only valid for mutable authoritative web evidence")
            if self.source_sha256:
                raise ValueError("source capture identity must not be combined with raw source SHA-256")
        return self


class HumanReviewApproval(StrictSchemaModel):
    """Policy-scoped human approval that can unlock bounded release use."""

    approval_id: str = Field(min_length=1)
    reviewed_by: str = Field(min_length=1)
    reviewed_at: date
    scopes: set[ReviewScope] = Field(min_length=1)
    policy: str = Field(default="component-trust-v1", min_length=1)


_CURATED_SOURCES = {
    ProvenanceSourceType.MANUFACTURER_DOCUMENT,
    ProvenanceSourceType.MANUFACTURER_WEB,
    ProvenanceSourceType.AUTHORIZED_DISTRIBUTOR,
    ProvenanceSourceType.MANUAL_ENTRY,
}
_VERIFIED_SOURCES = {
    ProvenanceSourceType.MANUFACTURER_DOCUMENT,
    ProvenanceSourceType.MANUFACTURER_WEB,
    ProvenanceSourceType.AUTHORIZED_DISTRIBUTOR,
}


def has_exact_provenance_identity(evidence: FieldProvenance) -> bool:
    """Return whether provenance is bound to exact source bytes or a mutable-web capture."""

    if _SHA256_RE.fullmatch(evidence.source_sha256):
        return True
    return (
        evidence.source_type in {ProvenanceSourceType.MANUFACTURER_WEB, ProvenanceSourceType.AUTHORIZED_DISTRIBUTOR}
        and bool(evidence.source_capture_path)
        and bool(_SHA256_RE.fullmatch(evidence.source_capture_sha256))
    )


def _failed_requirements(requirements: tuple[tuple[bool, str], ...]) -> list[str]:
    return [message for passed, message in requirements if not passed]


def _curated_field_failures(field_name: ComponentField, evidence: FieldProvenance) -> list[str]:
    prefix = field_name.value
    requirements = (
        (evidence.source_type in _CURATED_SOURCES, f"{prefix}: part-specific source type"),
        (bool(evidence.source_identity and evidence.source_version), f"{prefix}: source identity/version"),
        (bool(evidence.extracted_at and evidence.extraction_method), f"{prefix}: extraction metadata"),
        (bool(evidence.reviewed_by and evidence.reviewed_at), f"{prefix}: review metadata"),
        (evidence.confidence is not ProvenanceConfidence.LOW, f"{prefix}: confidence must be medium or high"),
    )
    return _failed_requirements(requirements)


def _verified_field_failures(field_name: ComponentField, evidence: FieldProvenance) -> list[str]:
    prefix = field_name.value
    requirements = (
        (evidence.source_type in _VERIFIED_SOURCES, f"{prefix}: non-authoritative source type"),
        (bool(evidence.source_identity), f"{prefix}: source identity"),
        (has_exact_provenance_identity(evidence), f"{prefix}: source SHA-256"),
        (bool(evidence.source_version), f"{prefix}: source version"),
        (bool(evidence.extraction_method and evidence.extracted_at), f"{prefix}: extraction metadata"),
        (bool(evidence.reviewed_by and evidence.reviewed_at), f"{prefix}: review metadata"),
        (evidence.confidence is ProvenanceConfidence.HIGH, f"{prefix}: confidence must be high"),
    )
    return _failed_requirements(requirements)


class ComponentRecordV2(StrictSchemaModel):
    """Strict versioned component YAML contract."""

    schema_version: Literal["2.0"]
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    manufacturer: str = ""
    mpn: str = ""
    description: str = ""
    datasheet: str = ""
    package: str = ""
    footprint: str = ""
    lifecycle: str = "active"
    voltage_supply: str = ""
    pins: dict[str, ComponentPin] = Field(default_factory=dict)
    package_pin_map: dict[str, str] = Field(default_factory=dict)
    electrical_limits: ElectricalLimits = Field(default_factory=ElectricalLimits)
    sourcing: SourcingMetadata = Field(default_factory=SourcingMetadata)
    compliance: ComplianceMetadata = Field(default_factory=ComplianceMetadata)
    provenance: LegacyProvenanceMetadata = Field(default_factory=LegacyProvenanceMetadata)
    properties: dict[str, Any] = Field(default_factory=dict)
    trust_tier: ComponentTrustTier
    field_provenance: dict[ComponentField, FieldProvenance]
    human_review: HumanReviewApproval | None = None

    def _validate_package_pin_map(self) -> None:
        if not self.package_pin_map:
            return
        if any(not pin_id.strip() or not logical_pin.strip() for pin_id, logical_pin in self.package_pin_map.items()):
            raise ValueError("package pin map cannot contain empty pin ids or logical pin names")
        unknown = sorted(set(self.package_pin_map.values()) - set(self.pins))
        if unknown:
            raise ValueError("package pin map references unknown logical pin(s): " + ", ".join(unknown))
        if self.trust_tier is ComponentTrustTier.VERIFIED:
            uncovered = sorted(set(self.pins) - set(self.package_pin_map.values()))
            if uncovered:
                raise ValueError(
                    "verified package pin map does not cover declared logical pins: " + ", ".join(uncovered)
                )

    @model_validator(mode="after")
    def validate_critical_provenance(self) -> ComponentRecordV2:
        self._validate_package_pin_map()
        missing = set(ComponentField) - set(self.field_provenance)
        unexpected = set(self.field_provenance) - set(ComponentField)
        if missing or unexpected:
            details: list[str] = []
            if missing:
                details.append("missing " + ", ".join(sorted(field.value for field in missing)))
            if unexpected:
                details.append("unexpected " + ", ".join(sorted(str(field) for field in unexpected)))
            raise ValueError("critical field provenance mismatch: " + "; ".join(details))

        if self.trust_tier is ComponentTrustTier.VERIFIED:
            self._validate_verified_claim()
        elif self.trust_tier is ComponentTrustTier.CURATED:
            self._validate_curated_claim()
        return self

    def _validate_curated_claim(self) -> None:
        if self.human_review is None:
            raise ValueError("curated component requires human review metadata")
        failures = [
            failure
            for field_name, evidence in self.field_provenance.items()
            for failure in _curated_field_failures(field_name, evidence)
        ]
        if failures:
            raise ValueError("curated component evidence is incomplete: " + "; ".join(failures))

    def _validate_verified_claim(self) -> None:
        if not self.package_pin_map:
            raise ValueError("verified component requires physical package pin map")
        approval = self.human_review
        required_scopes = {ReviewScope.RELEASE, ReviewScope.FABRICATION}
        if approval is None or not required_scopes.issubset(approval.scopes):
            raise ValueError("verified component requires release and fabrication human review approval")
        failures = [
            failure
            for field_name, evidence in self.field_provenance.items()
            for failure in _verified_field_failures(field_name, evidence)
        ]
        if failures:
            raise ValueError("verified component evidence is incomplete: " + "; ".join(failures))


def validate_component_record(raw: dict[str, Any]) -> ComponentRecordV2:
    """Validate one raw YAML mapping against strict component schema v2."""

    return ComponentRecordV2.model_validate(raw)
