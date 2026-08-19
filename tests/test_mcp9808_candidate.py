from __future__ import annotations

from datetime import date

from zaptrace.ee.footprint_proof import file_sha256
from zaptrace.ee.footprint_vendor import VENDOR_FOOTPRINTS, resolve_vendored_footprint, vendored_footprint_path
from zaptrace.library.loader import LibraryLoader
from zaptrace.library.schema import ComponentField, ComponentTrustTier, ProvenanceConfidence, ProvenanceSourceType

_DATASHEET_SHA256 = "e7b6502f744c3e605a424d7b784a23baa471a41f8bc6d51f6321027b0c43972f"
_FOOTPRINT_SHA256 = "c85207be7edf4b5e1a128249fb05f91b67d622f536fc832d7a9f2a7f1e9a1223"
_FOOTPRINT_NAME = "MCP9808-E-MS-MSOP8"
_PACKAGE_MAP = {
    "1": "SDA",
    "2": "SCL",
    "3": "ALERT",
    "4": "GND",
    "5": "A2",
    "6": "A1",
    "7": "A0",
    "8": "VDD",
}


def test_mcp9808_candidate_matches_exact_msop_i2c_pinout_and_remains_heuristic() -> None:
    spec = LibraryLoader().get("mcp9808-e-ms")

    assert spec.manufacturer == "Microchip Technology"
    assert spec.mpn == "MCP9808-E/MS"
    assert spec.package == "MSOP-8"
    assert spec.footprint == _FOOTPRINT_NAME
    assert spec.package_pin_map == _PACKAGE_MAP
    assert set(spec.pins) == set(_PACKAGE_MAP.values())
    assert "INT" not in spec.pins
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_mcp9808_candidate_records_datasheet_limits_and_current_product_status() -> None:
    spec = LibraryLoader().get("mcp9808-e-ms")

    assert spec.lifecycle == "active"
    assert spec.properties["supply_range_v"] == [2.7, 5.5]
    assert spec.properties["i2c_max_khz"] == 400
    assert spec.properties["temperature_range_c"] == [-40, 125]
    assert spec.properties["accuracy_max_c"] == {
        "-20_to_100": 0.5,
        "-40_to_125": 1.0,
    }
    assert spec.properties["resolution_c"] == 0.0625
    assert spec.properties["absolute_max_supply_v"] == 6.0
    assert spec.properties["package_body_mm"] == [3.0, 3.0]
    assert spec.properties["package_pitch_mm"] == 0.65
    assert spec.sourcing["status"] == "manufacturer-in-production"


def test_mcp9808_candidate_provenance_is_authoritative_but_unreviewed() -> None:
    spec = LibraryLoader().get("mcp9808-e-ms")

    for field in ComponentField:
        evidence = spec.field_provenance[field]
        if field is ComponentField.LIFECYCLE:
            assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_WEB
            assert evidence.source_identity == "MCP9808 product page"
            assert evidence.source_sha256 == ""
            assert evidence.source_version == "accessed 2026-08-18"
        else:
            assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_DOCUMENT
            assert evidence.source_identity == "DS20005095B"
            assert evidence.source_sha256 == _DATASHEET_SHA256
            assert evidence.source_version == "DS20005095B"
        assert evidence.extracted_at == date(2026, 8, 18)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    assert spec.provenance["review_status"] == "candidate-evidence-unreviewed"


def test_mcp9808_vendored_msop8_footprint_is_pinned_and_requires_human_equivalence_review() -> None:
    spec = LibraryLoader().get("mcp9808-e-ms")

    assert VENDOR_FOOTPRINTS[_FOOTPRINT_NAME] == "MSOP-8_3x3mm_P0.65mm.kicad_mod"
    source_path = vendored_footprint_path(_FOOTPRINT_NAME)
    assert source_path is not None
    assert file_sha256(source_path) == _FOOTPRINT_SHA256
    footprint = resolve_vendored_footprint(_FOOTPRINT_NAME)
    assert footprint is not None
    assert {pad.id for pad in footprint.pads} == set(_PACKAGE_MAP)
    assert spec.properties["repository_land_pattern"]["pad_size_mm"] == [1.625, 0.4]
    assert "human" in spec.properties["repository_land_pattern"]["review_note"].lower()


def test_library_expansion_no_longer_regenerates_mcp9808_starter_record() -> None:
    from scripts.generate_library_expansion import collect_all_parts

    generated_ids = {part_id for _category, part_id, _data in collect_all_parts()}
    assert "mcp9808-e-ms" not in generated_ids
