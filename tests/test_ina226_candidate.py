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
from zaptrace.library.integrity import run_library_integrity_gate
from zaptrace.library.loader import LibraryLoader
from zaptrace.library.schema import ComponentField, ComponentTrustTier, ProvenanceConfidence, ProvenanceSourceType

_DATASHEET_SHA256 = "99885a0f3a52c837376c6e86411b9ea623dea9f0cf278c06cddb68d5b31b3137"
_FOOTPRINT_SHA256 = "8d2841a74e13e6aa9ff353b36a4946df71e473655a2ec824de8486d5adb3b7b9"
_FOOTPRINT_NAME = "INA226-MSOP10"
_PACKAGE_MAP = {
    "1": "A1",
    "2": "A0",
    "3": "ALERT",
    "4": "SDA",
    "5": "SCL",
    "6": "VS",
    "7": "GND",
    "8": "VBUS",
    "9": "IN-",
    "10": "IN+",
}


def test_ina226_candidate_matches_exact_dgs_package_and_remains_heuristic() -> None:
    spec = LibraryLoader().get("ina226")

    assert spec.manufacturer == "Texas Instruments"
    assert spec.mpn == "INA226AIDGSR"
    assert spec.package == "MSOP-10"
    assert spec.properties["manufacturer_package_name"] == "VSSOP (DGS)"
    assert spec.footprint == _FOOTPRINT_NAME
    assert spec.package_pin_map == _PACKAGE_MAP
    assert set(spec.pins) == set(_PACKAGE_MAP.values())
    assert "VBP" not in spec.pins
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_ina226_candidate_records_rev_b_electrical_and_package_evidence() -> None:
    spec = LibraryLoader().get("ina226")

    assert spec.properties["resolution_bit"] == 16
    assert spec.properties["supply_range_v"] == [2.7, 5.5]
    assert spec.properties["bus_voltage_range_v"] == [0.0, 36.0]
    assert spec.properties["absolute_max_supply_v"] == 6.0
    assert spec.properties["absolute_max_input_common_mode_v"] == [-0.3, 40.0]
    assert spec.properties["gain_error_max_percent"] == 0.1
    assert spec.properties["input_offset_max_uv"] == 10
    assert spec.properties["temperature_range_c"] == [-40, 125]
    assert spec.properties["manufacturer_land_pattern_mm"] == {
        "pad_length": 1.45,
        "pad_width": 0.30,
        "pin_pitch": 0.50,
    }
    repo = spec.properties["repository_land_pattern"]
    assert repo["pad_size_mm"] == [1.50, 0.35]
    assert repo["pin_pitch"] == 0.50
    assert "not dimension-identical" in repo["review_note"]


def test_ina226_candidate_provenance_is_authoritative_but_unreviewed() -> None:
    spec = LibraryLoader().get("ina226")

    for field in ComponentField:
        evidence = spec.field_provenance[field]
        assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_DOCUMENT
        assert evidence.source_identity == "SBOS547B"
        assert evidence.source_sha256 == _DATASHEET_SHA256
        assert evidence.source_version == "Rev B (2024-09)"
        assert evidence.extracted_at == date(2026, 8, 10)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    assert spec.sourcing["status"] == "manufacturer-active-production"


def test_ina226_vendored_dgs_footprint_is_pinned_and_covers_all_pads() -> None:
    spec = LibraryLoader().get("ina226")
    source_path = vendored_footprint_path(_FOOTPRINT_NAME)

    assert VENDOR_FOOTPRINTS[_FOOTPRINT_NAME] == "MSOP-10_3x3mm_P0.5mm.kicad_mod"
    assert source_path == Path("data/footprints/vendor/MSOP-10_3x3mm_P0.5mm.kicad_mod").resolve()
    assert file_sha256(source_path) == _FOOTPRINT_SHA256

    footprint = resolve_vendored_footprint(_FOOTPRINT_NAME)
    assert footprint is not None
    assert {pad.id for pad in footprint.pads} == set(_PACKAGE_MAP)

    source = FootprintSourceProvenance(
        source_type=FootprintSourceType.VENDORED,
        source_name="KiCad official MSOP-10 3x3 mm P0.5",
        source_path="data/footprints/vendor/MSOP-10_3x3mm_P0.5mm.kicad_mod",
        source_sha256=_FOOTPRINT_SHA256,
        attribution="data/footprints/vendor/ATTRIBUTION.md",
    )
    proof = build_footprint_proof(
        spec.package,
        footprint,
        footprint_name=spec.footprint,
        source=source,
        expected_pin_count=10,
        pin_map={pin_id: pin_id for pin_id in _PACKAGE_MAP},
    )
    validation = validate_footprint_proof(proof, expected_physical_pins=set(_PACKAGE_MAP))

    assert validation.blocked is False
    assert proof.pin_count == 10
    assert proof.pad_count == 10


def test_ina226_legacy_id_is_safe_canonical_compatibility_mirror() -> None:
    loader = LibraryLoader()
    canonical = loader.get("ina226")
    legacy = loader.get("ina226aidgsr")

    assert legacy.properties["canonical_component_id"] == canonical.id
    assert legacy.manufacturer == canonical.manufacturer
    assert legacy.mpn == canonical.mpn
    assert legacy.datasheet == canonical.datasheet
    assert legacy.package == canonical.package
    assert legacy.footprint == canonical.footprint
    assert legacy.pins == canonical.pins
    assert legacy.package_pin_map == canonical.package_pin_map
    assert legacy.electrical_limits == canonical.electrical_limits
    assert "CS" not in legacy.pins
    assert "INT" not in legacy.pins


def test_ina226_duplicate_group_resolves_without_conflict() -> None:
    report = run_library_integrity_gate()
    group = next(
        group
        for group in report.duplicate_groups
        if group.canonical_id == "ina226" and "ina226aidgsr" in group.alternate_ids
    )
    assert group.conflict is False


def test_library_expansion_no_longer_regenerates_superseded_ina226_legacy_record() -> None:
    from scripts.generate_library_expansion import collect_all_parts

    generated_ids = {part_id for _category, part_id, _data in collect_all_parts()}
    assert "ina226aidgsr" not in generated_ids
