from __future__ import annotations

from datetime import date
from pathlib import Path

from zaptrace.ee.footprint_proof import (
    FootprintSourceProvenance,
    FootprintSourceType,
    build_footprint_proof,
    file_sha256,
    validate_footprint_proof,
)
from zaptrace.ee.footprint_vendor import VENDOR_FOOTPRINTS, resolve_vendored_footprint, vendored_footprint_path
from zaptrace.library.loader import LibraryLoader
from zaptrace.library.schema import (
    ComponentField,
    ComponentTrustTier,
    ProvenanceConfidence,
    ProvenanceSourceType,
)

_DATASHEET_SHA256 = "ef8d376f2ec356e29172eb9e053819a0ebdcc576dba7fc9ab0505c568427920f"
_PACKAGE_DOC_SHA256 = "acb75d3d3d00fd80c33ab471832cc90a26746de7867aa98f9abb165676f9c66c"
_FOOTPRINT_SHA256 = "2a5c9e030fb192cd2393b5f95872fe796deb29ae7570c83050e19f7b78ceea71"
_FOOTPRINT_NAME = "AP2112K-3.3TRG1-SOT25"
_PACKAGE_MAP = {"1": "VIN", "2": "GND", "3": "EN", "4": "NC", "5": "VOUT"}


def test_ap2112_candidate_matches_exact_sot25_orderable_part_and_remains_heuristic() -> None:
    spec = LibraryLoader().get("ap2112k-3.3")

    assert spec.manufacturer == "Diodes Incorporated"
    assert spec.mpn == "AP2112K-3.3TRG1"
    assert spec.package == "SOT-23-5"
    assert spec.properties["manufacturer_package_name"] == "SOT25"
    assert spec.footprint == _FOOTPRINT_NAME
    assert spec.package_pin_map == _PACKAGE_MAP
    assert set(spec.pins) == set(_PACKAGE_MAP.values())
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_ap2112_candidate_corrects_3v3_electrical_and_package_evidence() -> None:
    spec = LibraryLoader().get("ap2112k-3.3")

    assert spec.properties["output_voltage_v"] == 3.3
    assert spec.properties["output_current_ma"] == 600
    assert spec.properties["input_voltage_range_v"] == [2.5, 6.0]
    assert spec.properties["absolute_max_input_voltage_v"] == 6.5
    assert spec.properties["dropout_voltage_mv_at_600ma"] == {"typical": 250, "maximum": 400}
    assert spec.properties["manufacturer_footprint_recommendation_mm"] == {
        "pad_width": 0.55,
        "pad_length": 0.80,
        "pin_pitch": 0.95,
        "row_center_spacing": 2.40,
        "overall_pad_span": 3.20,
        "inner_row_gap": 1.60,
    }
    repository = spec.properties["repository_land_pattern"]
    assert repository["pad_size_mm"] == [1.325, 0.60]
    assert repository["pin_pitch"] == 0.95
    assert "not dimension-identical" in repository["review_note"]


def test_ap2112_candidate_provenance_is_authoritative_but_unreviewed() -> None:
    spec = LibraryLoader().get("ap2112k-3.3")

    for field in (
        ComponentField.MPN,
        ComponentField.DATASHEET,
        ComponentField.PIN_MAP,
        ComponentField.PACKAGE,
        ComponentField.ELECTRICAL_LIMITS,
    ):
        evidence = spec.field_provenance[field]
        assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_DOCUMENT
        assert evidence.source_identity == "DS39724"
        assert evidence.source_sha256 == _DATASHEET_SHA256
        assert evidence.source_version == "Rev 2-2 (2017-06)"
        assert evidence.extracted_at == date(2026, 8, 10)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    footprint_evidence = spec.field_provenance[ComponentField.FOOTPRINT]
    assert footprint_evidence.source_type is ProvenanceSourceType.MANUFACTURER_DOCUMENT
    assert footprint_evidence.source_identity == "Diodes SOT25 Package Information"
    assert footprint_evidence.source_sha256 == _PACKAGE_DOC_SHA256
    assert footprint_evidence.source_version == "Rev 2017-04-11"
    assert footprint_evidence.extracted_at == date(2026, 8, 10)
    assert footprint_evidence.reviewed_by == ""
    assert footprint_evidence.confidence is ProvenanceConfidence.MEDIUM

    for field in (ComponentField.LIFECYCLE, ComponentField.SOURCING):
        evidence = spec.field_provenance[field]
        assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_WEB
        assert evidence.source_identity == "diodes:ap2112-product-page"
        assert evidence.source_sha256 == ""
        assert evidence.source_version == "accessed-2026-08-10"
        assert evidence.extracted_at == date(2026, 8, 10)
        assert evidence.reviewed_by == ""
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    assert spec.sourcing["status"] == "manufacturer-catalog-active"


def test_ap2112_candidate_vendored_sot25_footprint_is_pinned_and_covers_all_pads() -> None:
    spec = LibraryLoader().get("ap2112k-3.3")
    source_path = vendored_footprint_path(_FOOTPRINT_NAME)

    assert VENDOR_FOOTPRINTS[_FOOTPRINT_NAME] == "SOT-23-5.kicad_mod"
    assert source_path == Path("data/footprints/vendor/SOT-23-5.kicad_mod").resolve()
    assert file_sha256(source_path) == _FOOTPRINT_SHA256

    footprint = resolve_vendored_footprint(_FOOTPRINT_NAME)
    assert footprint is not None
    assert {pad.id for pad in footprint.pads} == set(_PACKAGE_MAP)

    source = FootprintSourceProvenance(
        source_type=FootprintSourceType.VENDORED,
        source_name="KiCad official SOT-23-5",
        source_path="data/footprints/vendor/SOT-23-5.kicad_mod",
        source_sha256=_FOOTPRINT_SHA256,
        attribution="data/footprints/vendor/ATTRIBUTION.md",
    )
    proof = build_footprint_proof(
        spec.package,
        footprint,
        footprint_name=spec.footprint,
        source=source,
        expected_pin_count=5,
        pin_map={pin_id: pin_id for pin_id in _PACKAGE_MAP},
    )
    validation = validate_footprint_proof(proof, expected_physical_pins=set(_PACKAGE_MAP))

    assert validation.blocked is False
    assert proof.pin_count == 5
    assert proof.pad_count == 5


def test_ap2112_legacy_id_is_a_safe_canonical_compatibility_mirror() -> None:
    loader = LibraryLoader()
    canonical = loader.get("ap2112k-3.3")
    legacy = loader.get("ap2112k-3.3trg1")

    assert legacy.properties["canonical_component_id"] == canonical.id
    assert legacy.manufacturer == canonical.manufacturer
    assert legacy.mpn == canonical.mpn
    assert legacy.datasheet == canonical.datasheet
    assert legacy.package == canonical.package
    assert legacy.footprint == canonical.footprint
    assert legacy.pins == canonical.pins
    assert legacy.package_pin_map == canonical.package_pin_map
    assert legacy.electrical_limits == canonical.electrical_limits
    assert "BYP" not in legacy.pins


def test_ap2112_duplicate_group_resolves_to_canonical_id_without_conflict() -> None:
    from zaptrace.library.integrity import run_library_integrity_gate

    report = run_library_integrity_gate()
    group = next(
        group
        for group in report.duplicate_groups
        if group.canonical_id == "ap2112k-3.3" and "ap2112k-3.3trg1" in group.alternate_ids
    )

    assert group.conflict is False


def test_library_expansion_no_longer_regenerates_the_superseded_ap2112_legacy_record() -> None:
    from scripts.generate_library_expansion import collect_all_parts

    generated_ids = {part_id for _category, part_id, _data in collect_all_parts()}

    assert "ap2112k-3.3trg1" not in generated_ids
