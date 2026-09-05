from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from zaptrace.ee.footprint_proof import FootprintProof
from zaptrace.library.evidence_manifest import (
    ComponentEvidenceManifest,
    load_component_evidence_manifest,
    validate_component_evidence_manifest,
)
from zaptrace.library.loader import ComponentSpec
from zaptrace.library.schema import (
    ComponentField,
    ComponentTrustTier,
    FieldProvenance,
    HumanReviewApproval,
)


def _artifact(artifact_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_id": artifact_id,
        "source_type": "manufacturer_document",
        "source_locator": "https://manufacturer.example/acme-rev4.pdf",
        "source_identity": "ACME-LDO-DS",
        "source_sha256": "a" * 64,
        "source_version": "Rev 4",
        "captured_at": "2026-08-01",
    }
    payload.update(overrides)
    return payload


def _write_proof(
    tmp_path: Path,
    *,
    package_id: str = "SOT-23-5",
    footprint_name: str = "SOT-23-5",
    pin_map: dict[str, str] | None = None,
    source_sha256: str | None = None,
    thermal_pad_id: str | None = None,
) -> Path:
    source_path = tmp_path / "data" / "footprints" / "vendor" / "acme.kicad_mod"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("(footprint acme)\n", encoding="utf-8")
    resolved_source_sha256 = source_sha256 or hashlib.sha256(source_path.read_bytes()).hexdigest()
    proof_path = tmp_path / "evidence" / "footprints" / "acme-ldo.json"
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_pin_map = pin_map or {"1": "1"}
    pads = [
        {
            "pad_id": "1",
            "layer": "top",
            "shape": "rect",
            "position_mm": [0.0, 0.0],
            "size_mm": [0.6, 0.6],
        }
    ]
    thermal_pads: list[str] = []
    if thermal_pad_id is not None:
        pads.append(
            {
                "pad_id": thermal_pad_id,
                "layer": "top",
                "shape": "rect",
                "position_mm": [0.0, 0.8],
                "size_mm": [1.2, 1.2],
            }
        )
        thermal_pads.append(thermal_pad_id)
    proof = FootprintProof.model_validate(
        {
            "schema_version": "1.0",
            "package_id": package_id,
            "footprint_name": footprint_name,
            "source": {
                "source_type": "vendored",
                "source_name": "manufacturer-footprint",
                "source_path": "data/footprints/vendor/acme.kicad_mod",
                "source_sha256": resolved_source_sha256,
                "attribution": "test fixture",
            },
            "pad_count": len(pads),
            "pin_count": len(resolved_pin_map),
            "pin_map": resolved_pin_map,
            "pads": pads,
            "courtyard_mm": [2.0, 2.0],
            "paste_enabled_pad_count": len(pads),
            "paste_disabled_pad_count": 0,
            "thermal_pads": thermal_pads,
            "pin1": {
                "present": True,
                "pad_id": "1",
                "method": "explicit-pad-id",
                "message": "fixture pin 1",
            },
        }
    )
    proof_path.write_text(proof.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return proof_path


def _entry(**overrides: Any) -> dict[str, Any]:
    field_artifacts = {field.value: "datasheet-rev4" for field in ComponentField}
    field_artifacts[ComponentField.LIFECYCLE.value] = "lifecycle-2026-08"
    field_artifacts[ComponentField.SOURCING.value] = "sourcing-2026-08"
    payload: dict[str, Any] = {
        "component_id": "acme-ldo",
        "manufacturer": "Acme",
        "mpn": "ACME-LDO-1",
        "trust_tier": "verified",
        "artifacts": {
            "datasheet-rev4": _artifact("datasheet-rev4"),
            "lifecycle-2026-08": _artifact(
                "lifecycle-2026-08",
                source_type="manufacturer_web",
                source_identity="ACME-LDO-1-LIFECYCLE",
                source_sha256="e" * 64,
                source_version="2026-08-01",
                captured_at="2026-08-01",
                valid_until="2026-09-01",
            ),
            "sourcing-2026-08": _artifact(
                "sourcing-2026-08",
                source_type="authorized_distributor",
                source_identity="ACME-LDO-1-DIST",
                source_sha256="b" * 64,
                source_version="2026-08-01",
                captured_at="2026-08-01",
                valid_until="2026-09-01",
            ),
        },
        "field_artifacts": field_artifacts,
        "footprint_proof": {
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": "c" * 64,
            "artifact_id": "datasheet-rev4",
        },
        "review": {
            "approval_id": "LIB-REVIEW-2026-001",
            "reviewed_by": "engineer@example.com",
            "reviewed_at": "2026-08-02",
            "scopes": ["release", "fabrication"],
            "policy": "component-trust-v1",
        },
    }
    payload.update(overrides)
    return payload


def test_empty_component_evidence_manifest_is_valid() -> None:
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {}})

    assert manifest.schema_version == "1.0"
    assert manifest.components == {}


def test_verified_evidence_entry_parses_complete_contract() -> None:
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": _entry()}})

    entry = manifest.components["acme-ldo"]
    assert entry.component_id == "acme-ldo"
    assert entry.trust_tier is ComponentTrustTier.VERIFIED
    assert set(entry.field_artifacts) == set(ComponentField)
    assert entry.artifacts["sourcing-2026-08"].captured_at == date(2026, 8, 1)
    assert entry.footprint_proof.artifact_id == "datasheet-rev4"
    assert entry.review.reviewed_by == "engineer@example.com"


def test_manifest_loader_reads_only_json_below_allowed_root(tmp_path: Path) -> None:
    manifest_path = tmp_path / "component-evidence.json"
    manifest_path.write_text(
        json.dumps({"schema_version": "1.0", "components": {}}),
        encoding="utf-8",
    )

    manifest = load_component_evidence_manifest(manifest_path, allowed_root=tmp_path)

    assert manifest.components == {}


def _verified_spec() -> ComponentSpec:
    review = HumanReviewApproval.model_validate(_entry()["review"])
    field_provenance: dict[ComponentField, FieldProvenance] = {}
    for field in ComponentField:
        artifact_id = _entry()["field_artifacts"][field.value]
        artifact = _entry()["artifacts"][artifact_id]
        field_provenance[field] = FieldProvenance.model_validate(
            {
                "source_type": artifact["source_type"],
                "source_locator": artifact["source_locator"],
                "source_identity": artifact["source_identity"],
                "source_sha256": artifact["source_sha256"],
                "source_version": artifact["source_version"],
                "extraction_method": "manual-datasheet-review",
                "extracted_at": "2026-08-02",
                "reviewed_by": "engineer@example.com",
                "reviewed_at": "2026-08-02",
                "confidence": "high",
            }
        )
    return ComponentSpec(
        id="acme-ldo",
        name="ACME LDO",
        category="power",
        manufacturer="Acme",
        mpn="ACME-LDO-1",
        datasheet="https://manufacturer.example/acme-rev4.pdf",
        package="SOT-23-5",
        footprint="SOT-23-5",
        pins={"1": {"type": "input"}},
        package_pin_map={"1": "1"},
        electrical_limits={"max_voltage_v": 6.0},
        sourcing={"mpn": "ACME-LDO-1", "manufacturer": "Acme"},
        trust_tier=ComponentTrustTier.VERIFIED,
        field_provenance=field_provenance,
        human_review=review,
    )


def test_manifest_binds_exact_verified_component_and_proof_digest(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path)
    proof_sha256 = hashlib.sha256(proof.read_bytes()).hexdigest()
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": proof_sha256,
            "artifact_id": "datasheet-rev4",
        }
    )
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is True
    assert report.manifest_component_count == 1
    assert report.verified_component_count == 1
    assert report.bound_verified_component_count == 1
    assert len(report.manifest_digest) == 64
    assert report.violations == []


def test_manifest_blocks_verified_component_without_physical_package_pin_map(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path)
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    spec = _verified_spec()
    spec.package_pin_map = {}
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": spec},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is False
    assert [(item.code, item.field) for item in report.violations] == [("package-pin-map-missing", "package_pin_map")]


def test_manifest_validates_footprint_against_physical_package_pin_ids(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path, pin_map={"2": "1"})
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    spec = _verified_spec()
    spec.pins = {"VIN": {"type": "input"}}
    spec.package_pin_map = {"2": "VIN"}
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": spec},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is True
    assert report.violations == []


def test_manifest_accepts_exposed_thermal_pad_in_physical_package_map(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path, thermal_pad_id="EP")
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    spec = _verified_spec()
    spec.pins = {"VIN": {"type": "input"}, "PGND": {"type": "power"}}
    spec.package_pin_map = {"1": "VIN", "EP": "PGND"}
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": spec}, manifest, repository_root=tmp_path, as_of=date(2026, 8, 9)
    )

    assert report.passed is True
    assert report.violations == []


def test_manifest_rejects_exposed_thermal_pad_missing_from_physical_map(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path, thermal_pad_id="EP")
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()}, manifest, repository_root=tmp_path, as_of=date(2026, 8, 9)
    )

    assert report.passed is False
    assert "footprint-proof-blocked" in {item.code for item in report.violations}


def test_manifest_rejects_component_identity_mismatch(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path)
    entry = _entry(
        mpn="WRONG-MPN",
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        },
    )
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is False
    assert [violation.code for violation in report.violations] == ["component-mpn-mismatch"]


def test_manifest_rejects_footprint_proof_hash_mismatch(tmp_path: Path) -> None:
    _write_proof(tmp_path)
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": "d" * 64,
            "artifact_id": "datasheet-rev4",
        }
    )
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is False
    assert [violation.code for violation in report.violations] == ["footprint-proof-hash-mismatch"]


def test_verified_component_without_manifest_entry_is_blocked(tmp_path: Path) -> None:
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is False
    assert report.bound_verified_component_count == 0
    assert [violation.code for violation in report.violations] == ["verified-component-evidence-missing"]


def test_manifest_rejects_field_source_hash_mismatch(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path)
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    spec = _verified_spec()
    pin_map = spec.field_provenance[ComponentField.PIN_MAP].model_copy(update={"source_sha256": "f" * 64})
    spec.field_provenance[ComponentField.PIN_MAP] = pin_map
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": spec},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is False
    assert [(violation.code, violation.field) for violation in report.violations] == [
        ("field-source-hash-mismatch", "pin_map")
    ]


@pytest.mark.parametrize(
    ("attribute", "replacement", "expected_code"),
    [
        ("source_type", "manufacturer_web", "field-source-type-mismatch"),
        ("source_locator", "https://manufacturer.example/other.pdf", "field-source-locator-mismatch"),
        ("source_identity", "OTHER-DOCUMENT", "field-source-identity-mismatch"),
        ("source_version", "Rev 5", "field-source-version-mismatch"),
    ],
)
def test_manifest_requires_exact_field_source_metadata(
    tmp_path: Path, attribute: str, replacement: str, expected_code: str
) -> None:
    proof = _write_proof(tmp_path)
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    spec = _verified_spec()
    evidence = spec.field_provenance[ComponentField.DATASHEET].model_copy(update={attribute: replacement})
    spec.field_provenance[ComponentField.DATASHEET] = evidence
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": spec},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is False
    assert [(violation.code, violation.field) for violation in report.violations] == [(expected_code, "datasheet")]


def test_manifest_rejects_non_verified_component_binding(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path)
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    spec = _verified_spec()
    spec.trust_tier = ComponentTrustTier.HEURISTIC
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": spec}, manifest, repository_root=tmp_path, as_of=date(2026, 8, 9)
    )

    assert [violation.code for violation in report.violations] == ["component-trust-tier-mismatch"]


def test_manifest_review_must_match_component_review(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path)
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    spec = _verified_spec()
    assert spec.human_review is not None
    spec.human_review = spec.human_review.model_copy(update={"reviewed_by": "other@example.com"})
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": spec}, manifest, repository_root=tmp_path, as_of=date(2026, 8, 9)
    )

    assert [violation.code for violation in report.violations] == ["review-metadata-mismatch"]


@pytest.mark.parametrize(
    ("field", "valid_until", "expected_code"),
    [
        (ComponentField.LIFECYCLE, None, "time-bound-evidence-missing-expiry"),
        (ComponentField.SOURCING, "2026-08-08", "time-bound-evidence-stale"),
    ],
)
def test_lifecycle_and_sourcing_evidence_must_be_time_bound_and_current(
    tmp_path: Path,
    field: ComponentField,
    valid_until: str | None,
    expected_code: str,
) -> None:
    proof = _write_proof(tmp_path)
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    artifact_id = entry["field_artifacts"][field.value]
    entry["artifacts"][artifact_id]["valid_until"] = valid_until
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is False
    assert [(violation.code, violation.field) for violation in report.violations] == [(expected_code, field.value)]


def test_footprint_proof_must_bind_the_footprint_field_artifact() -> None:
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": "c" * 64,
            "artifact_id": "sourcing-2026-08",
        }
    )

    with pytest.raises(ValidationError, match="footprint field binding"):
        ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})


def test_manifest_rejects_evidence_captured_after_as_of_date(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path)
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    entry["artifacts"]["datasheet-rev4"]["captured_at"] = "2026-08-10"
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is False
    assert [violation.code for violation in report.violations] == ["evidence-captured-in-future"]


def test_manifest_rejects_footprint_proof_for_different_package(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path, package_id="QFN-32", footprint_name="QFN-32")
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is False
    assert [violation.code for violation in report.violations] == ["footprint-proof-mismatch"]


def test_manifest_rejects_semantically_invalid_footprint_pin_map(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path, pin_map={"1": "99"})
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is False
    assert [violation.code for violation in report.violations] == ["footprint-proof-blocked"]


def test_manifest_rejects_unknown_artifact_fields() -> None:
    entry = _entry()
    entry["artifacts"]["datasheet-rev4"]["unexpected"] = True

    with pytest.raises(ValidationError, match="unexpected"):
        ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})


def test_manifest_rejects_missing_critical_field_binding() -> None:
    entry = _entry()
    del entry["field_artifacts"][ComponentField.PIN_MAP.value]

    with pytest.raises(ValidationError, match="every critical field"):
        ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})


def test_manifest_rejects_incomplete_review_metadata() -> None:
    entry = _entry()
    del entry["review"]["reviewed_by"]

    with pytest.raises(ValidationError, match="reviewed_by"):
        ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})


def test_manifest_rejects_footprint_proof_source_hash_mismatch(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path, source_sha256="f" * 64)
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is False
    assert [violation.code for violation in report.violations] == ["footprint-proof-source-hash-mismatch"]


def test_manifest_enforces_existing_risky_package_footprint_policy(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path, package_id="LGA-8", footprint_name="LGA-8")
    payload = json.loads(proof.read_text(encoding="utf-8"))
    payload["source"]["source_type"] = "generated"
    payload["source"]["generator"] = "tests"
    payload["source"]["generator_version"] = "1"
    proof.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    spec = _verified_spec()
    spec.package = "LGA-8"
    spec.footprint = "LGA-8"
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": spec},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is False
    assert [violation.code for violation in report.violations] == ["footprint-proof-risk-policy-blocked"]


def _mutable_lifecycle_capture_report(tmp_path: Path, *, claim_value: str):
    capture_relative_path = "evidence/web/acme-lifecycle.json"
    capture_path = tmp_path / capture_relative_path
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    capture_payload = {
        "schema_version": "1.0",
        "component_id": "acme-ldo",
        "source_type": "manufacturer_web",
        "source_locator": "https://manufacturer.example/acme-rev4.pdf",
        "source_identity": "ACME-LDO-1-LIFECYCLE",
        "source_version": "2026-08-01",
        "captured_at": "2026-08-01",
        "claims": {"lifecycle": {"claim": "catalog_status", "value": claim_value}},
        "non_claims": ["human review required"],
    }
    capture_path.write_text(json.dumps(capture_payload, sort_keys=True) + "\n", encoding="utf-8")
    capture_sha256 = hashlib.sha256(capture_path.read_bytes()).hexdigest()

    proof = _write_proof(tmp_path)
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    artifact_data = {
        "source_type": "manufacturer_web",
        "source_locator": "https://manufacturer.example/acme-rev4.pdf",
        "source_identity": "ACME-LDO-1-LIFECYCLE",
        "source_sha256": "",
        "source_capture_path": capture_relative_path,
        "source_capture_sha256": capture_sha256,
        "source_version": "2026-08-01",
    }
    entry["artifacts"]["lifecycle-2026-08"] = _artifact(
        "lifecycle-2026-08",
        **artifact_data,
        captured_at="2026-08-01",
        valid_until="2026-09-01",
    )

    spec = _verified_spec()
    spec.field_provenance[ComponentField.LIFECYCLE] = FieldProvenance(
        **artifact_data,
        extraction_method="bounded-web-claim-capture",
        extracted_at=date(2026, 8, 1),
        reviewed_by="engineer@example.com",
        reviewed_at=date(2026, 8, 2),
        confidence="high",
    )
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})
    return validate_component_evidence_manifest(
        {"acme-ldo": spec},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )


def test_manifest_accepts_and_verifies_mutable_web_capture_binding(tmp_path: Path) -> None:
    report = _mutable_lifecycle_capture_report(tmp_path, claim_value="active")

    assert report.passed is True
    assert report.violations == []


def test_manifest_rejects_mutable_web_capture_claim_that_disagrees_with_component(tmp_path: Path) -> None:
    report = _mutable_lifecycle_capture_report(tmp_path, claim_value="discontinued")

    assert report.passed is False
    assert [(violation.code, violation.field) for violation in report.violations] == [
        ("field-source-capture-claim-mismatch", "lifecycle")
    ]
