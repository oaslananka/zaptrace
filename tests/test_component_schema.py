from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from zaptrace.library.schema import (
    ComponentField,
    ComponentRecordV2,
    ComponentTrustTier,
    FieldProvenance,
    HumanReviewApproval,
    ProvenanceConfidence,
    ProvenanceSourceType,
    ReviewScope,
    validate_component_record,
)


def _field_provenance(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source_type": "internal_manifest",
        "source_locator": "offline-manifest",
        "source_identity": "legacy-library-v1",
        "source_version": "1",
        "extraction_method": "legacy-migration",
        "confidence": "low",
    }
    data.update(overrides)
    return data


def heuristic_record(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": "2.0",
        "id": "acme-ldo",
        "name": "ACME LDO",
        "category": "power",
        "manufacturer": "Acme",
        "mpn": "ACME-LDO-1",
        "description": "test regulator",
        "datasheet": "https://example.com/acme-ldo.pdf",
        "package": "SOT-23-5",
        "footprint": "Package_TO_SOT_SMD:SOT-23-5",
        "lifecycle": "active",
        "voltage_supply": "3.3",
        "pins": {
            "1": {"type": "input", "description": "VIN"},
            "2": {"type": "power", "description": "GND"},
            "5": {"type": "output", "description": "VOUT"},
        },
        "electrical_limits": {"max_voltage_v": 6.0},
        "sourcing": {
            "mpn": "ACME-LDO-1",
            "manufacturer": "Acme",
            "status": "starter-library-entry",
            "production_note": "confirm before production",
        },
        "compliance": {
            "rohs": "supplier-confirmation-required",
            "reach": "supplier-confirmation-required",
            "production_note": "not certification",
        },
        "provenance": {
            "source": "offline-manifest",
            "reviewed_by": "unreviewed",
            "generation": "tests",
        },
        "properties": {"custom_domain_value": 42},
        "trust_tier": "heuristic",
        "field_provenance": {field.value: _field_provenance() for field in ComponentField},
    }
    data.update(overrides)
    return data


def verified_field(source_type: str = "manufacturer_document") -> dict[str, Any]:
    return _field_provenance(
        source_type=source_type,
        source_locator="https://manufacturer.example/datasheet.pdf",
        source_identity="ACME-LDO-DS",
        source_sha256="a" * 64,
        source_version="Rev 4",
        extraction_method="manual-datasheet-review",
        extracted_at="2026-07-27",
        reviewed_by="engineer@example.com",
        reviewed_at="2026-07-27",
        confidence="high",
    )


def verified_record(**overrides: Any) -> dict[str, Any]:
    data = heuristic_record(
        trust_tier="verified",
        package_pin_map={"1": "1", "2": "2", "5": "5"},
        field_provenance={
            field.value: verified_field(
                "authorized_distributor" if field is ComponentField.SOURCING else "manufacturer_document"
            )
            for field in ComponentField
        },
        human_review={
            "approval_id": "LIB-REVIEW-2026-001",
            "reviewed_by": "engineer@example.com",
            "reviewed_at": "2026-07-27",
            "scopes": ["release", "fabrication"],
            "policy": "component-trust-v1",
        },
    )
    data.update(overrides)
    return data


def test_heuristic_component_record_validates_with_explicit_provenance() -> None:
    record = validate_component_record(heuristic_record())

    assert isinstance(record, ComponentRecordV2)
    assert record.schema_version == "2.0"
    assert record.trust_tier is ComponentTrustTier.HEURISTIC
    assert set(record.field_provenance) == set(ComponentField)
    assert record.properties["custom_domain_value"] == 42


def test_unknown_top_level_key_is_rejected() -> None:
    raw = heuristic_record(**{'description"': "typo"})

    with pytest.raises(ValidationError, match='description"'):
        validate_component_record(raw)


def test_unknown_pin_key_is_rejected() -> None:
    raw = heuristic_record(pins={"1": {"type": "power", 'description"': "typo"}})

    with pytest.raises(ValidationError, match='description"'):
        validate_component_record(raw)


def test_all_critical_fields_require_provenance() -> None:
    raw = heuristic_record()
    del raw["field_provenance"][ComponentField.PIN_MAP.value]

    with pytest.raises(ValidationError, match="pin_map"):
        validate_component_record(raw)


def test_verified_claim_rejects_missing_source_hash_and_review_metadata() -> None:
    fields = {field.value: verified_field() for field in ComponentField}
    fields[ComponentField.PIN_MAP.value] = _field_provenance(
        source_type="manufacturer_document",
        confidence="high",
    )

    raw = heuristic_record(trust_tier="verified", field_provenance=fields)

    with pytest.raises(ValidationError, match="verified"):
        validate_component_record(raw)


def test_verified_record_requires_physical_package_pin_map() -> None:
    raw = verified_record()
    raw.pop("package_pin_map", None)

    with pytest.raises(ValidationError, match="package pin map"):
        validate_component_record(raw)


def test_heuristic_record_accepts_physical_package_pin_map() -> None:
    record = validate_component_record(heuristic_record(package_pin_map={"1": "1", "2": "2", "5": "5"}))

    assert record.package_pin_map == {"1": "1", "2": "2", "5": "5"}


def test_package_pin_map_rejects_empty_physical_or_logical_pin() -> None:
    raw = heuristic_record(package_pin_map={"": "1"})

    with pytest.raises(ValidationError, match="cannot contain empty"):
        validate_component_record(raw)


def test_package_pin_map_rejects_unknown_logical_pin() -> None:
    raw = heuristic_record(
        pins={"VIN": {"type": "input"}, "GND": {"type": "power"}},
        package_pin_map={"1": "VIN", "2": "MISSING"},
    )

    with pytest.raises(ValidationError, match="unknown logical pin"):
        validate_component_record(raw)


def test_verified_package_pin_map_covers_all_declared_logical_pins() -> None:
    raw = verified_record(
        pins={"VIN": {"type": "input"}, "GND": {"type": "power"}, "VOUT": {"type": "output"}},
        package_pin_map={"1": "VIN", "2": "GND"},
    )

    with pytest.raises(ValidationError, match="does not cover declared logical pins"):
        validate_component_record(raw)


def test_verified_record_requires_complete_manufacturer_evidence() -> None:
    record = validate_component_record(verified_record())

    assert record.trust_tier is ComponentTrustTier.VERIFIED
    assert record.human_review is not None
    assert record.human_review.scopes == {
        ReviewScope.RELEASE,
        ReviewScope.FABRICATION,
    }
    assert all(evidence.confidence is ProvenanceConfidence.HIGH for evidence in record.field_provenance.values())


def test_strict_models_export_stable_enum_values() -> None:
    evidence = FieldProvenance.model_validate(verified_field())
    approval = HumanReviewApproval.model_validate(verified_record()["human_review"])

    assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_DOCUMENT
    assert evidence.extracted_at == date(2026, 7, 27)
    assert approval.policy == "component-trust-v1"


def test_curated_claim_requires_reviewed_part_specific_provenance() -> None:
    fields = {
        field.value: _field_provenance(
            source_type="internal_manifest",
            confidence="low",
        )
        for field in ComponentField
    }

    raw = heuristic_record(
        trust_tier="curated",
        field_provenance=fields,
        human_review=None,
    )

    with pytest.raises(ValidationError, match="curated"):
        validate_component_record(raw)


def test_curated_record_accepts_medium_confidence_reviewed_sources() -> None:
    fields = {
        field.value: _field_provenance(
            source_type=("authorized_distributor" if field is ComponentField.SOURCING else "manufacturer_web"),
            source_locator="https://manufacturer.example/part",
            source_identity="ACME-PART-REV-A",
            source_version="Rev A",
            extraction_method="manual-curation",
            extracted_at="2026-07-27",
            reviewed_by="engineer@example.com",
            reviewed_at="2026-07-27",
            confidence="medium",
        )
        for field in ComponentField
    }

    record = validate_component_record(
        heuristic_record(
            trust_tier="curated",
            field_provenance=fields,
            human_review={
                "approval_id": "CURATION-1",
                "reviewed_by": "engineer@example.com",
                "reviewed_at": "2026-07-27",
                "scopes": ["release"],
                "policy": "component-trust-v1",
            },
        )
    )

    assert record.trust_tier is ComponentTrustTier.CURATED


def test_verified_mutable_web_evidence_accepts_separate_capture_identity() -> None:
    fields = {field.value: verified_field() for field in ComponentField}
    fields[ComponentField.LIFECYCLE.value] = verified_field("manufacturer_web") | {
        "source_locator": "https://manufacturer.example/part",
        "source_identity": "ACME part page",
        "source_sha256": "",
        "source_version": "captured-2026-09-05",
        "source_capture_path": "data/library/evidence/web/acme-lifecycle.json",
        "source_capture_sha256": "b" * 64,
    }

    record = validate_component_record(verified_record(field_provenance=fields))

    lifecycle = record.field_provenance[ComponentField.LIFECYCLE]
    assert lifecycle.source_sha256 == ""
    assert lifecycle.source_capture_path == "data/library/evidence/web/acme-lifecycle.json"
    assert lifecycle.source_capture_sha256 == "b" * 64


def test_verified_document_evidence_cannot_replace_source_hash_with_web_capture() -> None:
    fields = {field.value: verified_field() for field in ComponentField}
    fields[ComponentField.DATASHEET.value] = verified_field() | {
        "source_sha256": "",
        "source_capture_path": "data/library/evidence/web/not-a-document.json",
        "source_capture_sha256": "c" * 64,
    }

    raw = verified_record(field_provenance=fields)

    with pytest.raises(ValidationError, match="mutable authoritative web"):
        validate_component_record(raw)


def test_field_provenance_rejects_partial_mutable_web_capture_identity() -> None:
    raw = verified_field("manufacturer_web")
    raw.update(
        source_sha256="",
        source_capture_path="data/library/evidence/web/part.json",
    )

    with pytest.raises(ValidationError, match="source capture path and SHA-256"):
        FieldProvenance.model_validate(raw)


def test_field_provenance_rejects_capture_identity_for_immutable_document() -> None:
    raw = verified_field("manufacturer_document")
    raw.update(
        source_sha256="",
        source_capture_path="data/library/evidence/web/part.json",
        source_capture_sha256="d" * 64,
    )

    with pytest.raises(ValidationError, match="mutable authoritative web"):
        FieldProvenance.model_validate(raw)
