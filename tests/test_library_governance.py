from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import yaml

from zaptrace.library.governance import (
    ComponentGovernanceSeverity,
    governed_component_from_spec,
    validate_component_library,
    validate_governed_component,
    write_component_governance_report,
)
from zaptrace.library.loader import ComponentSpec, LibraryLoader
from zaptrace.library.schema import (
    ComponentField,
    ComponentTrustTier,
    FieldProvenance,
    HumanReviewApproval,
    ProvenanceConfidence,
    ProvenanceSourceType,
    ReviewScope,
)


def _verified_field() -> FieldProvenance:
    return FieldProvenance(
        source_type=ProvenanceSourceType.MANUFACTURER_DOCUMENT,
        source_locator="https://example.com/acme-ldo-1.pdf",
        source_identity="ACME-LDO-DS",
        source_sha256="a" * 64,
        source_version="Rev 1",
        extraction_method="manual-review",
        extracted_at=date(2026, 7, 27),
        reviewed_by="engineer@example.com",
        reviewed_at=date(2026, 7, 27),
        confidence=ProvenanceConfidence.HIGH,
    )


def _heuristic_field() -> FieldProvenance:
    return FieldProvenance(
        source_type=ProvenanceSourceType.INTERNAL_MANIFEST,
        source_locator="offline-manifest",
        source_identity="legacy-library-v1",
        source_version="1",
        extraction_method="legacy-migration",
        confidence=ProvenanceConfidence.LOW,
    )


def _approval() -> HumanReviewApproval:
    return HumanReviewApproval(
        approval_id="LIB-REVIEW-1",
        reviewed_by="engineer@example.com",
        reviewed_at=date(2026, 7, 27),
        scopes={ReviewScope.RELEASE, ReviewScope.FABRICATION},
    )


def _strict_record(spec: ComponentSpec) -> dict[str, object]:
    return {
        "schema_version": spec.schema_version,
        "id": spec.id,
        "name": spec.name,
        "category": spec.category,
        "manufacturer": spec.manufacturer,
        "mpn": spec.mpn,
        "description": spec.description,
        "datasheet": spec.datasheet,
        "package": spec.package,
        "footprint": spec.footprint,
        "lifecycle": spec.lifecycle,
        "voltage_supply": spec.voltage_supply,
        "pins": spec.pins,
        "package_pin_map": spec.package_pin_map,
        "electrical_limits": spec.electrical_limits,
        "sourcing": spec.sourcing,
        "compliance": spec.compliance,
        "provenance": spec.provenance,
        "properties": spec.properties,
        "trust_tier": spec.trust_tier.value,
        "field_provenance": {
            field.value: evidence.model_dump(mode="json", exclude_none=True)
            for field, evidence in spec.field_provenance.items()
        },
        "human_review": (spec.human_review.model_dump(mode="json") if spec.human_review is not None else None),
    }


def _reviewed_spec(**overrides: object) -> ComponentSpec:
    data: dict[str, object] = {
        "id": "ldo-1",
        "name": "LDO 1",
        "category": "power",
        "manufacturer": "Acme Analog",
        "mpn": "ACME-LDO-1",
        "description": "reviewed regulator",
        "datasheet": "https://example.com/acme-ldo-1.pdf",
        "package": "SOT-23-5",
        "footprint": "Package_TO_SOT_SMD:SOT-23-5",
        "lifecycle": "active",
        "voltage_supply": "3.3",
        "pins": {
            "1": {"type": "input", "description": "VIN"},
            "2": {"type": "power", "description": "GND"},
            "5": {"type": "output", "description": "VOUT"},
        },
        "package_pin_map": {"1": "1", "2": "2", "5": "5"},
        "electrical_limits": {"max_voltage_v": 6.0, "current_rating_a": 0.3},
        "sourcing": {"authorized_distributors": ["Digi-Key"], "mpn": "ACME-LDO-1"},
        "compliance": {"rohs": True, "reach": True},
        "provenance": {"reviewed_by": "library-ci", "datasheet_sha256": "a" * 64},
        "schema_version": "2.0",
        "trust_tier": ComponentTrustTier.VERIFIED,
        "field_provenance": {field: _verified_field() for field in ComponentField},
        "human_review": _approval(),
    }
    data.update(overrides)
    return ComponentSpec(**data)  # type: ignore[arg-type]


def test_governed_component_schema_v1_contains_required_contract_fields() -> None:
    governed = governed_component_from_spec(_reviewed_spec())
    dumped = governed.model_dump(mode="json")

    for field in (
        "mpn",
        "manufacturer",
        "datasheet",
        "lifecycle",
        "package",
        "footprint",
        "pins",
        "package_pin_map",
        "electrical_limits",
        "sourcing",
        "compliance",
        "provenance",
    ):
        assert field in dumped
    assert dumped["schema_version"] == "2.0"
    assert dumped["pins"]["1"]["type"] == "input"
    assert dumped["package_pin_map"] == {"1": "1", "2": "2", "5": "5"}


def test_reviewed_component_validates_ready() -> None:
    validation = validate_governed_component(_reviewed_spec())

    assert validation.valid is True
    assert validation.reviewed_ready is True
    assert validation.release_eligible is True
    assert validation.human_review_required is False
    assert validation.trust_tier is ComponentTrustTier.VERIFIED
    assert validation.findings == []
    assert validation.coverage_score == 1.0


def test_verified_governance_requires_physical_package_pin_map() -> None:
    validation = validate_governed_component(_reviewed_spec(package_pin_map={}))

    assert validation.valid is False
    assert validation.release_eligible is False
    assert [(finding.field, finding.severity) for finding in validation.findings] == [
        ("package_pin_map", ComponentGovernanceSeverity.ERROR)
    ]


def test_missing_identity_or_traceability_is_error() -> None:
    validation = validate_governed_component(_reviewed_spec(datasheet="", footprint=""))

    assert validation.valid is False
    assert validation.reviewed_ready is False
    fields = {finding.field: finding.severity for finding in validation.findings}
    assert fields["datasheet"] == ComponentGovernanceSeverity.ERROR
    assert fields["footprint"] == ComponentGovernanceSeverity.ERROR


def test_missing_governance_sections_are_warnings_not_schema_errors() -> None:
    validation = validate_governed_component(
        _reviewed_spec(electrical_limits={}, sourcing={}, compliance={}, provenance={}, voltage_supply="")
    )

    assert validation.valid is True
    assert validation.reviewed_ready is False
    fields = {finding.field: finding.severity for finding in validation.findings}
    assert fields["electrical_limits"] == ComponentGovernanceSeverity.WARNING
    assert fields["compliance"] == ComponentGovernanceSeverity.WARNING
    assert "sourcing" not in fields  # derived from MPN/manufacturer
    assert "provenance" not in fields  # derived from datasheet URL


def test_validate_component_library_report_is_deterministic() -> None:
    specs = {"b": _reviewed_spec(id="b", mpn="B"), "a": _reviewed_spec(id="a", mpn="A", datasheet="")}

    report = validate_component_library(specs)

    assert report.component_count == 2
    assert report.valid_count == 1
    assert report.error_count == 1
    assert [row.component_id for row in report.validations] == ["a", "b"]


def test_loader_writes_machine_readable_governance_report(tmp_path: Path) -> None:
    spec = _reviewed_spec(id="part-1")
    report_path = write_component_governance_report({"part-1": spec}, tmp_path / "component-governance.json")

    data = json.loads(report_path.read_text(encoding="utf-8"))

    assert data["schema_version"] == "2.0"
    assert data["historical_snapshot"] is True
    assert data["evidence_status"] == "historical-governance-snapshot"
    assert data["component_count"] == 1
    assert data["reviewed_ready_count"] == 1


def test_library_loader_exposes_governance_report(tmp_path: Path) -> None:
    root = tmp_path / "library"
    path = root / "power" / "ldo.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(_strict_record(_reviewed_spec(id="ldo")), sort_keys=False),
        encoding="utf-8",
    )
    loader = LibraryLoader(root)

    report = loader.governance_report()
    out = loader.write_governance_report(tmp_path / "report.json")

    assert report.component_count == 1
    assert report.reviewed_ready_count == 1
    assert json.loads(out.read_text(encoding="utf-8"))["valid_count"] == 1


def test_heuristic_component_is_schema_valid_but_release_blocked() -> None:
    validation = validate_governed_component(
        _reviewed_spec(
            trust_tier=ComponentTrustTier.HEURISTIC,
            field_provenance={field: _heuristic_field() for field in ComponentField},
            human_review=None,
        )
    )

    assert validation.valid is True
    assert validation.release_eligible is False
    assert validation.human_review_required is True
    assert validation.trust_tier is ComponentTrustTier.HEURISTIC


def test_policy_approved_heuristic_component_can_be_release_eligible() -> None:
    validation = validate_governed_component(
        _reviewed_spec(
            trust_tier=ComponentTrustTier.HEURISTIC,
            field_provenance={field: _heuristic_field() for field in ComponentField},
            human_review=_approval(),
        )
    )

    assert validation.valid is True
    assert validation.release_eligible is True
    assert validation.human_review_required is False


def test_placeholder_component_cannot_be_unblocked_by_review() -> None:
    validation = validate_governed_component(
        _reviewed_spec(
            trust_tier=ComponentTrustTier.PLACEHOLDER,
            field_provenance={field: _heuristic_field() for field in ComponentField},
            human_review=_approval(),
        )
    )

    assert validation.valid is True
    assert validation.release_eligible is False
    assert validation.human_review_required is True


def test_library_report_includes_trust_and_repeated_pin_signature_evidence() -> None:
    specs = {
        f"sensor-{index}": _reviewed_spec(
            id=f"sensor-{index}",
            category="sensor",
            mpn=f"SENSOR-{index}",
            trust_tier=ComponentTrustTier.HEURISTIC,
            field_provenance={field: _heuristic_field() for field in ComponentField},
            human_review=None,
        )
        for index in range(3)
    }

    report = validate_component_library(specs)

    assert report.trust_tier_counts == {"heuristic": 3}
    assert report.release_eligible_count == 0
    assert report.blocked_component_count == 3
    assert report.human_review_required_count == 3
    assert len(report.repeated_pin_signatures) == 1
    assert report.repeated_pin_signatures[0].component_ids == [
        "sensor-0",
        "sensor-1",
        "sensor-2",
    ]


def test_real_shipped_library_can_be_validated_against_schema_v1() -> None:
    loader = LibraryLoader()
    report = loader.governance_report()

    assert report.component_count >= 80
    assert report.error_count >= 0
    assert 0.0 <= report.mean_coverage_score <= 1.0
    assert len(report.validations) == report.component_count
