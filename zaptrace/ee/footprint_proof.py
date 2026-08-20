"""Footprint proof schema and builders.

A footprint proof is machine-readable evidence that records where a land pattern
came from and what geometric/pin-mapping assumptions it carries. Validation of
those proofs is implemented by later gates; this module defines the contract.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from zaptrace import __version__
from zaptrace.core.models import FootprintDef, Pad


class FootprintSourceType(StrEnum):
    GENERATED = "generated"
    VENDORED = "vendored"
    IMPORTED = "imported"
    UNKNOWN = "unknown"


class FootprintSourceProvenance(BaseModel):
    """Source provenance for a footprint proof."""

    model_config = ConfigDict(strict=False)

    source_type: FootprintSourceType
    source_name: str = ""
    source_path: str = ""
    source_sha256: str = ""
    generator: str = ""
    generator_version: str = ""
    attribution: str = ""


class FootprintPadProof(BaseModel):
    """Pad geometry evidence captured from a FootprintDef."""

    model_config = ConfigDict(strict=False)

    pad_id: str
    layer: str
    shape: str
    position_mm: tuple[float, float]
    size_mm: tuple[float, float]
    drill_mm: float | None = None
    plated: bool = True
    solder_paste: bool = True
    solder_mask: bool = True


class FootprintPin1Evidence(BaseModel):
    """Evidence that identifies pin/pad 1 orientation in the footprint."""

    present: bool = False
    pad_id: str = ""
    method: str = ""
    message: str = ""


class FootprintProof(BaseModel):
    """Proof schema for generated/imported/vendored footprints."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    package_id: str
    footprint_name: str
    source: FootprintSourceProvenance
    pad_count: int = Field(ge=0)
    pin_count: int = Field(ge=0)
    pin_map: dict[str, str] = Field(description="Pin name/id -> pad id mapping")
    pads: list[FootprintPadProof]
    courtyard_mm: tuple[float, float]
    paste_enabled_pad_count: int = Field(ge=0)
    paste_disabled_pad_count: int = Field(ge=0)
    solder_mask_policy: str = "mask opening assumed for all pads unless explicitly modeled"
    thermal_pads: list[str] = Field(default_factory=list)
    pin1: FootprintPin1Evidence = Field(default_factory=FootprintPin1Evidence)
    notes: list[str] = Field(default_factory=list)


def file_sha256(path: str | Path) -> str:
    """Return SHA-256 for a footprint source file."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pad_to_proof(pad: Pad) -> FootprintPadProof:
    return FootprintPadProof(
        pad_id=pad.id,
        layer=pad.layer.value,
        shape=pad.shape.value,
        position_mm=pad.position,
        size_mm=pad.size,
        drill_mm=pad.drill,
        plated=pad.plated,
        solder_paste=pad.solder_paste,
        solder_mask=True,
    )


def _pin1_evidence(pads: list[Pad]) -> FootprintPin1Evidence:
    ids = {pad.id for pad in pads}
    for candidate in ("1", "A1", "P1"):
        if candidate in ids:
            return FootprintPin1Evidence(
                present=True,
                pad_id=candidate,
                method="explicit-pad-id",
                message=f"Pin-1 evidence found via pad id {candidate}",
            )
    return FootprintPin1Evidence(
        present=False,
        method="not-found",
        message="No explicit pin-1 pad id found",
    )


def _default_source(
    source_type: FootprintSourceType, source_name: str, source_path: str = ""
) -> FootprintSourceProvenance:
    digest = file_sha256(source_path) if source_path and Path(source_path).exists() else ""
    return FootprintSourceProvenance(
        source_type=source_type,
        source_name=source_name,
        source_path=source_path,
        source_sha256=digest,
        generator="zaptrace.ee.footprints" if source_type == FootprintSourceType.GENERATED else "",
        generator_version=__version__ if source_type == FootprintSourceType.GENERATED else "",
    )


def build_footprint_proof(
    package_id: str,
    footprint: FootprintDef,
    *,
    footprint_name: str = "",
    source: FootprintSourceProvenance | None = None,
    source_type: FootprintSourceType = FootprintSourceType.GENERATED,
    source_path: str = "",
    expected_pin_count: int | None = None,
    pin_map: dict[str, str] | None = None,
) -> FootprintProof:
    """Build a footprint proof from a FootprintDef."""
    resolved_source = source or _default_source(source_type, footprint.source or package_id, source_path)
    thermal = set(footprint.thermal_pads or [])
    mapping = pin_map or {pad.id: pad.id for pad in footprint.pads if pad.id not in thermal}
    pin_count = expected_pin_count if expected_pin_count is not None else len(mapping)
    paste_enabled = sum(1 for pad in footprint.pads if pad.solder_paste)
    paste_disabled = len(footprint.pads) - paste_enabled
    notes: list[str] = []
    if not footprint.courtyard or footprint.courtyard == (0.0, 0.0):
        notes.append("courtyard is missing or zero-sized")
    return FootprintProof(
        package_id=package_id,
        footprint_name=footprint_name or footprint.description or package_id,
        source=resolved_source,
        pad_count=len(footprint.pads),
        pin_count=pin_count,
        pin_map=mapping,
        pads=[_pad_to_proof(pad) for pad in footprint.pads],
        courtyard_mm=footprint.courtyard,
        paste_enabled_pad_count=paste_enabled,
        paste_disabled_pad_count=paste_disabled,
        thermal_pads=sorted(thermal),
        pin1=_pin1_evidence(footprint.pads),
        notes=notes,
    )


class FootprintProofSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class FootprintProofDiagnostic(BaseModel):
    """Actionable diagnostic emitted by footprint proof validation."""

    model_config = ConfigDict(strict=False)

    package_id: str
    code: str
    severity: FootprintProofSeverity
    message: str
    expected: str = ""
    observed: str = ""


class FootprintProofValidationReport(BaseModel):
    """Validation report for one or more footprint proofs."""

    schema_version: str = "1.0"
    proof_count: int
    blocked: bool
    error_count: int
    warning_count: int
    diagnostics: list[FootprintProofDiagnostic]


RISKY_PACKAGE_FAMILIES: tuple[str, ...] = (
    "ESP32-C3-MINI",
    "ESP32-MINI",
    "MODULE",
    "CASTELLATED",
    "AQFN",
    "BGA",
    "DFN",
    "LGA",
    "QFN",
    "RJ45",
    "USB-C",
    "USB_C",
)

DATASHEET_BACKED_RISKY_FAMILIES: tuple[str, ...] = (
    "ESP32-C3-MINI",
    "ESP32-MINI",
    "MODULE",
    "CASTELLATED",
    "AQFN",
    "DFN",
    "LGA",
    "RJ45",
    "USB-C",
)


class RiskyPackagePolicyResult(BaseModel):
    """Risk policy result for a footprint proof."""

    schema_version: str = "1.0"
    package_id: str
    risky: bool
    family: str = ""
    reviewed: bool = False
    approval_id: str = ""
    blocked: bool
    required_evidence: list[str] = Field(default_factory=list)
    diagnostics: list[FootprintProofDiagnostic] = Field(default_factory=list)


def classify_risky_package(package_id: str, footprint_name: str = "") -> str:
    """Return risky package family, or empty string when not in policy scope."""
    text = f"{package_id} {footprint_name}".upper().replace("_", "-")
    for family in RISKY_PACKAGE_FAMILIES:
        if family.replace("_", "-") in text:
            return family.replace("_", "-")
    return ""


def validate_risky_package_policy(
    proof: FootprintProof,
    *,
    reviewed: bool = False,
    approval_id: str = "",
) -> RiskyPackagePolicyResult:
    """Enforce stricter provenance/review policy for risky package families."""
    family = classify_risky_package(proof.package_id, proof.footprint_name)
    required = [
        "human-reviewed footprint proof",
        "datasheet-backed, vendored, or imported source for high-risk part-specific packages",
        "source SHA-256 or generator version",
        "pin-1 evidence",
        "non-zero courtyard",
        "complete pin_map",
    ]
    diagnostics: list[FootprintProofDiagnostic] = []
    if not family:
        return RiskyPackagePolicyResult(package_id=proof.package_id, risky=False, blocked=False)
    if not reviewed and not approval_id:
        diagnostics.append(
            FootprintProofDiagnostic(
                package_id=proof.package_id,
                code="unreviewed-risky-package",
                severity=FootprintProofSeverity.ERROR,
                message=f"{family} package requires human-reviewed footprint proof or approval_id",
                expected="reviewed=true or approval_id",
                observed="unreviewed",
            )
        )
    if not proof.source.source_sha256 and not proof.source.generator_version:
        diagnostics.append(
            FootprintProofDiagnostic(
                package_id=proof.package_id,
                code="risky-package-missing-source-provenance",
                severity=FootprintProofSeverity.ERROR,
                message=f"{family} package requires source hash or generator version provenance",
                expected="source_sha256 or generator_version",
                observed="missing",
            )
        )
    if family in DATASHEET_BACKED_RISKY_FAMILIES and proof.source.source_type == FootprintSourceType.GENERATED:
        diagnostics.append(
            FootprintProofDiagnostic(
                package_id=proof.package_id,
                code="risky-package-requires-datasheet-backed-source",
                severity=FootprintProofSeverity.ERROR,
                message=f"{family} package requires datasheet-backed, vendored, or imported footprint evidence",
                expected="vendored/imported source with source_sha256 or reviewed datasheet-derived proof",
                observed=proof.source.source_type.value,
            )
        )
    if not proof.pin1.present:
        diagnostics.append(
            FootprintProofDiagnostic(
                package_id=proof.package_id,
                code="risky-package-missing-pin1",
                severity=FootprintProofSeverity.ERROR,
                message=f"{family} package requires explicit pin-1 evidence",
            )
        )
    if proof.courtyard_mm == (0.0, 0.0):
        diagnostics.append(
            FootprintProofDiagnostic(
                package_id=proof.package_id,
                code="risky-package-missing-courtyard",
                severity=FootprintProofSeverity.ERROR,
                message=f"{family} package requires non-zero courtyard evidence",
            )
        )
    return RiskyPackagePolicyResult(
        package_id=proof.package_id,
        risky=True,
        family=family,
        reviewed=reviewed,
        approval_id=approval_id,
        blocked=bool(diagnostics),
        required_evidence=required,
        diagnostics=diagnostics,
    )


def _physical_pin_contract_diagnostic(
    proof: FootprintProof, expected_physical_pins: set[str], thermal: set[str]
) -> FootprintProofDiagnostic | None:
    actual = set(proof.pin_map) | thermal
    missing = expected_physical_pins - actual
    unexpected = actual - expected_physical_pins
    if not missing and not unexpected:
        return None
    return FootprintProofDiagnostic(
        package_id=proof.package_id,
        code="physical-pin-mismatch",
        severity=FootprintProofSeverity.ERROR,
        message="signal and thermal pad identities do not match the expected physical package pins",
        expected=", ".join(sorted(expected_physical_pins)),
        observed=", ".join(sorted(actual)),
    )


def _pad_count_diagnostic(proof: FootprintProof) -> FootprintProofDiagnostic | None:
    if proof.pad_count == len(proof.pads):
        return None
    return FootprintProofDiagnostic(
        package_id=proof.package_id,
        code="pad-count-field-mismatch",
        severity=FootprintProofSeverity.ERROR,
        message="pad_count does not match the number of pad records",
        expected=str(len(proof.pads)),
        observed=str(proof.pad_count),
    )


def _pad_pin_count_diagnostic(proof: FootprintProof, signal_pad_ids: set[str]) -> FootprintProofDiagnostic | None:
    if len(signal_pad_ids) == proof.pin_count:
        return None
    return FootprintProofDiagnostic(
        package_id=proof.package_id,
        code="pad-pin-count-mismatch",
        severity=FootprintProofSeverity.ERROR,
        message="signal pad count does not match expected pin count",
        expected=str(proof.pin_count),
        observed=str(len(signal_pad_ids)),
    )


def _pin_map_count_diagnostic(proof: FootprintProof) -> FootprintProofDiagnostic | None:
    if len(proof.pin_map) == proof.pin_count:
        return None
    return FootprintProofDiagnostic(
        package_id=proof.package_id,
        code="pin-map-count-mismatch",
        severity=FootprintProofSeverity.ERROR,
        message="pin_map entry count does not match expected pin count",
        expected=str(proof.pin_count),
        observed=str(len(proof.pin_map)),
    )


def _pin_map_pad_missing_diagnostic(
    proof: FootprintProof, pad_ids: set[str], mapped_pads: set[str]
) -> FootprintProofDiagnostic | None:
    missing_pads = sorted(mapped_pads - pad_ids)
    if not missing_pads:
        return None
    return FootprintProofDiagnostic(
        package_id=proof.package_id,
        code="pin-map-pad-missing",
        severity=FootprintProofSeverity.ERROR,
        message="pin_map references pad ids not present in the footprint",
        expected="existing pad id",
        observed=", ".join(missing_pads),
    )


def _unmapped_signal_pad_diagnostic(
    proof: FootprintProof, signal_pad_ids: set[str], mapped_pads: set[str]
) -> FootprintProofDiagnostic | None:
    unmapped_signal_pads = sorted(signal_pad_ids - mapped_pads)
    if not unmapped_signal_pads:
        return None
    return FootprintProofDiagnostic(
        package_id=proof.package_id,
        code="unmapped-signal-pad",
        severity=FootprintProofSeverity.ERROR,
        message="signal pads are not referenced by pin_map",
        expected="all signal pads mapped",
        observed=", ".join(unmapped_signal_pads),
    )


def _pin_name_mismatch_diagnostic(
    proof: FootprintProof, expected_pins: set[str]
) -> FootprintProofDiagnostic | None:
    actual_pins = set(proof.pin_map)
    missing = sorted(expected_pins - actual_pins)
    unexpected = sorted(actual_pins - expected_pins)
    if not missing and not unexpected:
        return None
    return FootprintProofDiagnostic(
        package_id=proof.package_id,
        code="pin-name-mismatch",
        severity=FootprintProofSeverity.ERROR,
        message="pin_map names do not match the expected component pins",
        expected=", ".join(sorted(expected_pins)),
        observed=", ".join(sorted(actual_pins)),
    )


def _pin1_diagnostic(proof: FootprintProof) -> FootprintProofDiagnostic | None:
    if proof.pin1.present:
        return None
    return FootprintProofDiagnostic(
        package_id=proof.package_id,
        code="missing-pin1-evidence",
        severity=FootprintProofSeverity.ERROR,
        message="footprint has no explicit pin-1 evidence",
    )


def _courtyard_diagnostic(proof: FootprintProof) -> FootprintProofDiagnostic | None:
    if proof.courtyard_mm != (0.0, 0.0):
        return None
    return FootprintProofDiagnostic(
        package_id=proof.package_id,
        code="missing-courtyard",
        severity=FootprintProofSeverity.ERROR,
        message="footprint courtyard is missing or zero-sized",
    )


def validate_footprint_proof(
    proof: FootprintProof,
    *,
    expected_pins: set[str] | None = None,
    expected_physical_pins: set[str] | None = None,
    require_pin1: bool = True,
    require_courtyard: bool = True,
) -> FootprintProofValidationReport:
    """Validate pad/pin-count and pin-map consistency for one footprint proof."""
    pad_ids = {pad.pad_id for pad in proof.pads}
    thermal = set(proof.thermal_pads)
    signal_pad_ids = pad_ids - thermal
    mapped_pads = set(proof.pin_map.values())

    candidates = (
        _pad_count_diagnostic(proof),
        _pad_pin_count_diagnostic(proof, signal_pad_ids),
        _pin_map_count_diagnostic(proof),
        _pin_map_pad_missing_diagnostic(proof, pad_ids, mapped_pads),
        _unmapped_signal_pad_diagnostic(proof, signal_pad_ids, mapped_pads),
        _pin_name_mismatch_diagnostic(proof, expected_pins) if expected_pins is not None else None,
        _physical_pin_contract_diagnostic(proof, expected_physical_pins, thermal)
        if expected_physical_pins is not None
        else None,
        _pin1_diagnostic(proof) if require_pin1 else None,
        _courtyard_diagnostic(proof) if require_courtyard else None,
    )
    diagnostics = [item for item in candidates if item is not None]

    errors = sum(1 for item in diagnostics if item.severity == FootprintProofSeverity.ERROR)
    warnings = sum(1 for item in diagnostics if item.severity == FootprintProofSeverity.WARNING)
    return FootprintProofValidationReport(
        proof_count=1,
        blocked=errors > 0,
        error_count=errors,
        warning_count=warnings,
        diagnostics=diagnostics,
    )


def validate_footprint_proofs(proofs: list[FootprintProof]) -> FootprintProofValidationReport:
    """Validate multiple footprint proofs and aggregate diagnostics."""
    diagnostics: list[FootprintProofDiagnostic] = []
    for proof in proofs:
        diagnostics.extend(validate_footprint_proof(proof).diagnostics)
    errors = sum(1 for item in diagnostics if item.severity == FootprintProofSeverity.ERROR)
    warnings = sum(1 for item in diagnostics if item.severity == FootprintProofSeverity.WARNING)
    return FootprintProofValidationReport(
        proof_count=len(proofs),
        blocked=errors > 0,
        error_count=errors,
        warning_count=warnings,
        diagnostics=diagnostics,
    )


def write_footprint_proof(proof: FootprintProof, output_path: str | Path) -> Path:
    """Write a footprint proof JSON artifact."""
    out = Path(output_path)
    if out.suffix.lower() != ".json":
        raise ValueError(f"unexpected footprint proof suffix: {out.suffix}")
    resolved = out.resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    # nosemgrep: python.lang.security.audit.path-traversal.path-traversal-write
    resolved.write_text(proof.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return resolved
