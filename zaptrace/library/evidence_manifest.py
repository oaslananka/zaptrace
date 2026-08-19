"""Strict component evidence manifest contract.

The manifest binds independently reviewable source artifacts to governed
component records without changing component trust-tier semantics.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from zaptrace.ee.footprint_proof import (
    FootprintProof,
    FootprintSourceType,
    validate_footprint_proof,
    validate_risky_package_policy,
)
from zaptrace.library.schema import (
    ComponentField,
    ComponentTrustTier,
    HumanReviewApproval,
    ProvenanceSourceType,
    ReviewScope,
    StrictSchemaModel,
)

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class ComponentEvidenceArtifact(StrictSchemaModel):
    """Immutable identity and freshness metadata for one external source."""

    artifact_id: str = Field(min_length=1)
    source_type: ProvenanceSourceType
    source_locator: str = Field(min_length=1)
    source_identity: str = Field(min_length=1)
    source_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_version: str = Field(min_length=1)
    captured_at: date
    valid_until: date | None = None

    @model_validator(mode="after")
    def validate_validity_window(self) -> ComponentEvidenceArtifact:
        if self.valid_until is not None and self.valid_until < self.captured_at:
            raise ValueError("valid_until must not be earlier than captured_at")
        return self


class FootprintProofBinding(StrictSchemaModel):
    """Digest-bound path to independently reviewable footprint evidence."""

    proof_path: str = Field(min_length=1)
    proof_sha256: str = Field(pattern=_SHA256_PATTERN)
    artifact_id: str = Field(min_length=1)


class ComponentEvidenceEntry(StrictSchemaModel):
    """Part-specific evidence linkage for one verified component record."""

    component_id: str = Field(min_length=1)
    manufacturer: str = Field(min_length=1)
    mpn: str = Field(min_length=1)
    trust_tier: ComponentTrustTier
    artifacts: dict[str, ComponentEvidenceArtifact]
    field_artifacts: dict[ComponentField, str]
    footprint_proof: FootprintProofBinding
    review: HumanReviewApproval

    @model_validator(mode="after")
    def validate_verified_contract(self) -> ComponentEvidenceEntry:
        if self.trust_tier is not ComponentTrustTier.VERIFIED:
            raise ValueError("component evidence entries must declare verified trust tier")
        missing_fields = set(ComponentField) - set(self.field_artifacts)
        unexpected_fields = set(self.field_artifacts) - set(ComponentField)
        if missing_fields or unexpected_fields:
            raise ValueError("component evidence requires bindings for every critical field")
        for artifact_id, artifact in self.artifacts.items():
            if artifact.artifact_id != artifact_id:
                raise ValueError(f"artifact key {artifact_id!r} does not match artifact_id {artifact.artifact_id!r}")
        unknown_artifacts = set(self.field_artifacts.values()) - set(self.artifacts)
        if unknown_artifacts:
            raise ValueError("field_artifacts reference unknown artifacts: " + ", ".join(sorted(unknown_artifacts)))
        if self.footprint_proof.artifact_id not in self.artifacts:
            raise ValueError("footprint proof references unknown artifact")
        if self.footprint_proof.artifact_id != self.field_artifacts[ComponentField.FOOTPRINT]:
            raise ValueError("footprint proof artifact must match the footprint field binding")
        required_scopes = {ReviewScope.RELEASE, ReviewScope.FABRICATION}
        if not required_scopes.issubset(self.review.scopes):
            raise ValueError("verified evidence review requires release and fabrication scopes")
        return self


class ComponentEvidenceManifest(StrictSchemaModel):
    """Repository-level manifest of part-specific evidence entries."""

    schema_version: Literal["1.0"] = "1.0"
    components: dict[str, ComponentEvidenceEntry] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_component_keys(self) -> ComponentEvidenceManifest:
        for component_id, entry in self.components.items():
            if entry.component_id != component_id:
                raise ValueError(f"component key {component_id!r} does not match component_id {entry.component_id!r}")
        return self


def _validated_manifest_path(path: str | Path, *, allowed_root: str | Path) -> Path:
    """Resolve one regular JSON manifest below an explicit workspace boundary."""

    root = Path(allowed_root).resolve(strict=True)
    candidate = Path(path)
    if candidate.is_symlink():
        raise ValueError(f"component evidence manifest must not be a symbolic link: {candidate}")
    resolved = candidate.resolve(strict=True)
    if resolved.suffix.lower() != ".json":
        raise ValueError(f"component evidence manifest must be JSON: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"component evidence manifest is not a regular file: {resolved}")
    if not resolved.is_relative_to(root):
        raise ValueError(f"component evidence manifest is outside allowed root {root}: {resolved}")
    return resolved


def load_component_evidence_manifest(path: str | Path, *, allowed_root: str | Path) -> ComponentEvidenceManifest:
    """Load a component evidence manifest from an explicit workspace root."""

    resolved = _validated_manifest_path(path, allowed_root=allowed_root)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    return ComponentEvidenceManifest.model_validate(payload)


class ComponentEvidenceViolation(StrictSchemaModel):
    """One deterministic manifest-to-library binding failure."""

    code: str
    component_id: str
    field: str = ""
    message: str


class ComponentEvidenceReport(StrictSchemaModel):
    """Deterministic result of binding evidence to governed components."""

    schema_version: Literal["1.0"] = "1.0"
    passed: bool
    manifest_component_count: int = Field(ge=0)
    verified_component_count: int = Field(ge=0)
    bound_verified_component_count: int = Field(ge=0)
    manifest_digest: str = Field(pattern=_SHA256_PATTERN)
    violations: list[ComponentEvidenceViolation] = Field(default_factory=list)


def _manifest_digest(manifest: ComponentEvidenceManifest) -> str:
    payload = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _proof_path(proof_path: str, *, repository_root: Path) -> Path:
    root = repository_root.resolve(strict=True)
    candidate = repository_root / proof_path
    if candidate.is_symlink():
        raise ValueError(f"footprint proof must not be a symbolic link: {candidate}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError(f"footprint proof is outside repository root or not a regular file: {resolved}")
    return resolved


def _field_source_violations(
    component_id: str, spec: Any, entry: ComponentEvidenceEntry
) -> list[ComponentEvidenceViolation]:
    findings: list[ComponentEvidenceViolation] = []
    provenance = getattr(spec, "field_provenance", {})
    comparisons = (
        ("source_type", "field-source-type-mismatch"),
        ("source_locator", "field-source-locator-mismatch"),
        ("source_identity", "field-source-identity-mismatch"),
        ("source_sha256", "field-source-hash-mismatch"),
        ("source_version", "field-source-version-mismatch"),
    )
    for field_name in ComponentField:
        evidence = provenance.get(field_name)
        if evidence is None:
            findings.append(
                ComponentEvidenceViolation(
                    code="field-provenance-missing",
                    component_id=component_id,
                    field=field_name.value,
                    message="component field has no provenance to bind to evidence",
                )
            )
            continue
        artifact = entry.artifacts[entry.field_artifacts[field_name]]
        for attribute, code in comparisons:
            if getattr(evidence, attribute) != getattr(artifact, attribute):
                findings.append(
                    ComponentEvidenceViolation(
                        code=code,
                        component_id=component_id,
                        field=field_name.value,
                        message=f"component field {attribute} does not match evidence artifact",
                    )
                )
    return findings


def _time_bound_evidence_violations(
    component_id: str, entry: ComponentEvidenceEntry, *, as_of: date
) -> list[ComponentEvidenceViolation]:
    findings: list[ComponentEvidenceViolation] = []
    for artifact_id, artifact in entry.artifacts.items():
        if artifact.captured_at > as_of:
            findings.append(
                ComponentEvidenceViolation(
                    code="evidence-captured-in-future",
                    component_id=component_id,
                    field=f"artifacts.{artifact_id}.captured_at",
                    message="evidence capture date is later than the gate as-of date",
                )
            )
    for field_name in (ComponentField.LIFECYCLE, ComponentField.SOURCING):
        artifact = entry.artifacts[entry.field_artifacts[field_name]]
        if artifact.valid_until is None:
            findings.append(
                ComponentEvidenceViolation(
                    code="time-bound-evidence-missing-expiry",
                    component_id=component_id,
                    field=field_name.value,
                    message="lifecycle and sourcing evidence require a validity horizon",
                )
            )
        elif artifact.valid_until < as_of:
            findings.append(
                ComponentEvidenceViolation(
                    code="time-bound-evidence-stale",
                    component_id=component_id,
                    field=field_name.value,
                    message=f"evidence expired on {artifact.valid_until.isoformat()}",
                )
            )
    return findings


def _verified_component_ids(specs: dict[str, Any]) -> set[str]:
    return {
        component_id
        for component_id, spec in specs.items()
        if getattr(spec, "trust_tier", None) is ComponentTrustTier.VERIFIED
    }


def _identity_violation(
    component_id: str, spec: Any, entry: ComponentEvidenceEntry
) -> ComponentEvidenceViolation | None:
    comparisons = (
        ("mpn", "component-mpn-mismatch", "MPN"),
        ("manufacturer", "component-manufacturer-mismatch", "manufacturer"),
    )
    for field, code, label in comparisons:
        if getattr(spec, field, "") != getattr(entry, field):
            return ComponentEvidenceViolation(
                code=code,
                component_id=component_id,
                field=field,
                message=f"evidence {label} does not match the component record",
            )
    return None


def _record_binding_violation(
    component_id: str, spec: Any, entry: ComponentEvidenceEntry
) -> ComponentEvidenceViolation | None:
    if getattr(spec, "trust_tier", None) is not ComponentTrustTier.VERIFIED:
        return ComponentEvidenceViolation(
            code="component-trust-tier-mismatch",
            component_id=component_id,
            field="trust_tier",
            message="evidence manifest entry requires a verified component record",
        )
    review = getattr(spec, "human_review", None)
    if review is None or review.model_dump(mode="json") != entry.review.model_dump(mode="json"):
        return ComponentEvidenceViolation(
            code="review-metadata-mismatch",
            component_id=component_id,
            field="human_review",
            message="manifest review metadata does not match the component record",
        )
    return None


def _proof_file_violation(
    component_id: str, entry: ComponentEvidenceEntry, *, repository_root: Path
) -> tuple[Path | None, ComponentEvidenceViolation | None]:
    try:
        proof = _proof_path(entry.footprint_proof.proof_path, repository_root=repository_root)
    except (OSError, ValueError) as exc:
        return None, ComponentEvidenceViolation(
            code="footprint-proof-unavailable",
            component_id=component_id,
            field="footprint_proof",
            message=str(exc),
        )
    observed_digest = hashlib.sha256(proof.read_bytes()).hexdigest()
    if observed_digest != entry.footprint_proof.proof_sha256:
        return None, ComponentEvidenceViolation(
            code="footprint-proof-hash-mismatch",
            component_id=component_id,
            field="footprint_proof.proof_sha256",
            message="footprint proof digest does not match committed evidence",
        )
    return proof, None


def _proof_source_violation(
    component_id: str, proof: FootprintProof, *, repository_root: Path
) -> ComponentEvidenceViolation | None:
    if proof.source.source_type not in {FootprintSourceType.VENDORED, FootprintSourceType.IMPORTED}:
        return None
    if not proof.source.source_path:
        return ComponentEvidenceViolation(
            code="footprint-proof-source-unavailable",
            component_id=component_id,
            field="footprint_proof.source.source_path",
            message="vendored/imported footprint proof requires a repository source path",
        )
    try:
        source = _proof_path(proof.source.source_path, repository_root=repository_root)
    except (OSError, ValueError) as exc:
        return ComponentEvidenceViolation(
            code="footprint-proof-source-unavailable",
            component_id=component_id,
            field="footprint_proof.source.source_path",
            message=str(exc),
        )
    if hashlib.sha256(source.read_bytes()).hexdigest() == proof.source.source_sha256:
        return None
    return ComponentEvidenceViolation(
        code="footprint-proof-source-hash-mismatch",
        component_id=component_id,
        field="footprint_proof.source.source_sha256",
        message="footprint proof source digest does not match the repository source file",
    )


def _risky_proof_violation(
    component_id: str, entry: ComponentEvidenceEntry, proof: FootprintProof
) -> ComponentEvidenceViolation | None:
    policy = validate_risky_package_policy(proof, reviewed=True, approval_id=entry.review.approval_id)
    if not policy.blocked:
        return None
    codes = sorted({item.code for item in policy.diagnostics if item.severity.value == "error"})
    return ComponentEvidenceViolation(
        code="footprint-proof-risk-policy-blocked",
        component_id=component_id,
        field="footprint_proof",
        message="risky package footprint policy failed: " + ", ".join(codes),
    )


def _proof_identity_violation(component_id: str, spec: Any, proof: FootprintProof) -> ComponentEvidenceViolation | None:
    if proof.package_id == getattr(spec, "package", "") and proof.footprint_name == getattr(spec, "footprint", ""):
        return None
    return ComponentEvidenceViolation(
        code="footprint-proof-mismatch",
        component_id=component_id,
        field="footprint_proof",
        message="footprint proof belongs to a different package or footprint",
    )


def _physical_package_pin_ids(
    component_id: str, spec: Any
) -> tuple[set[str] | None, ComponentEvidenceViolation | None]:
    package_pin_map = getattr(spec, "package_pin_map", {})
    if package_pin_map:
        return set(package_pin_map), None
    return None, ComponentEvidenceViolation(
        code="package-pin-map-missing",
        component_id=component_id,
        field="package_pin_map",
        message="verified component requires an exact physical package pin map",
    )


def _proof_semantic_violations(
    component_id: str, spec: Any, entry: ComponentEvidenceEntry, proof_path: Path, *, repository_root: Path
) -> list[ComponentEvidenceViolation]:
    try:
        proof = FootprintProof.model_validate_json(proof_path.read_bytes())
    except (OSError, ValueError) as exc:
        return [
            ComponentEvidenceViolation(
                code="footprint-proof-invalid",
                component_id=component_id,
                field="footprint_proof",
                message=f"footprint proof does not satisfy schema: {exc}",
            )
        ]
    source_violation = _proof_source_violation(component_id, proof, repository_root=repository_root)
    if source_violation is not None:
        return [source_violation]
    physical_pin_ids, pin_map_violation = _physical_package_pin_ids(component_id, spec)
    if pin_map_violation is not None:
        return [pin_map_violation]
    assert physical_pin_ids is not None
    validation = validate_footprint_proof(proof, expected_physical_pins=physical_pin_ids)
    findings: list[ComponentEvidenceViolation] = []
    if validation.blocked:
        codes = sorted({item.code for item in validation.diagnostics if item.severity.value == "error"})
        findings.append(
            ComponentEvidenceViolation(
                code="footprint-proof-blocked",
                component_id=component_id,
                field="footprint_proof",
                message="footprint proof validation failed: " + ", ".join(codes),
            )
        )
    risk_violation = _risky_proof_violation(component_id, entry, proof)
    if risk_violation is not None:
        findings.append(risk_violation)
    identity_violation = _proof_identity_violation(component_id, spec, proof)
    if identity_violation is not None:
        findings.append(identity_violation)
    return findings


def _entry_violations(
    component_id: str, spec: Any, entry: ComponentEvidenceEntry, *, repository_root: Path, as_of: date
) -> list[ComponentEvidenceViolation]:
    violation = _identity_violation(component_id, spec, entry)
    if violation is not None:
        return [violation]
    violation = _record_binding_violation(component_id, spec, entry)
    if violation is not None:
        return [violation]
    findings = _field_source_violations(component_id, spec, entry)
    findings.extend(_time_bound_evidence_violations(component_id, entry, as_of=as_of))
    if findings:
        return findings
    proof, violation = _proof_file_violation(component_id, entry, repository_root=repository_root)
    if violation is not None:
        return [violation]
    assert proof is not None
    return _proof_semantic_violations(component_id, spec, entry, proof, repository_root=repository_root)


def _missing_verified_violations(
    verified_ids: set[str], manifest: ComponentEvidenceManifest
) -> list[ComponentEvidenceViolation]:
    return [
        ComponentEvidenceViolation(
            code="verified-component-evidence-missing",
            component_id=component_id,
            message="verified component has no part-level evidence manifest entry",
        )
        for component_id in sorted(verified_ids - set(manifest.components))
    ]


def validate_component_evidence_manifest(
    specs: dict[str, Any],
    manifest: ComponentEvidenceManifest,
    *,
    repository_root: str | Path,
    as_of: date,
) -> ComponentEvidenceReport:
    """Bind manifest entries to exact verified components and proof files."""

    verified_ids = _verified_component_ids(specs)
    violations = _missing_verified_violations(verified_ids, manifest)
    bound_ids: set[str] = set()
    for component_id, entry in manifest.components.items():
        spec = specs.get(component_id)
        if spec is None:
            violations.append(
                ComponentEvidenceViolation(
                    code="component-not-found",
                    component_id=component_id,
                    message="evidence entry does not match a committed component",
                )
            )
            continue
        findings = _entry_violations(component_id, spec, entry, repository_root=Path(repository_root), as_of=as_of)
        violations.extend(findings)
        if not findings:
            bound_ids.add(component_id)
    return ComponentEvidenceReport(
        passed=not violations,
        manifest_component_count=len(manifest.components),
        verified_component_count=len(verified_ids),
        bound_verified_component_count=len(bound_ids & verified_ids),
        manifest_digest=_manifest_digest(manifest),
        violations=violations,
    )
