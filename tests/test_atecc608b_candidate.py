from __future__ import annotations

from datetime import date

from tests.candidate_footprint_helpers import assert_vendored_candidate_footprint
from zaptrace.library.loader import LibraryLoader
from zaptrace.library.schema import ComponentField, ComponentTrustTier, ProvenanceConfidence, ProvenanceSourceType

_DATASHEET_SHA256 = "1b21d7b0d5c6265fcca2bbd28e88174e9d3a3d05c57be30712e8951c75503acc"
_ORDERING_SHA256 = "9d790a0fe64acaf312070243862e22d027d0a82148c2f9a03fa73187a7b82f5a"
_LIFECYCLE_CAPTURE_SHA256 = "122550c3ac40b5135dfa5019c753edab8d1ee7b39b8af555ec6a7c151b03b6ae"
_FOOTPRINT_SHA256 = "074ecb2092b24fa4b4b9cdd7c926fc587b0d7d6d21e7341e57935fd42d36894f"
_FOOTPRINT_NAME = "ATECC608B-SSHDA-T-SOIC8"
_PACKAGE_MAP = {
    "1": "NC",
    "2": "NC",
    "3": "NC",
    "4": "GND",
    "5": "SDA",
    "6": "SCL",
    "7": "NC",
    "8": "VCC",
}


def test_atecc608b_candidate_matches_exact_soic_i2c_pinout_and_remains_heuristic() -> None:
    spec = LibraryLoader().get("atecc608b")

    assert spec.manufacturer == "Microchip Technology"
    assert spec.mpn == "ATECC608B-SSHDA-T"
    assert spec.package == "SOIC-8"
    assert spec.properties["manufacturer_package_name"] == '8-Lead 0.150" SOIC (SSH)'
    assert spec.footprint == _FOOTPRINT_NAME
    assert spec.package_pin_map == _PACKAGE_MAP
    assert set(spec.pins) == set(_PACKAGE_MAP.values())
    assert {"SDA2", "SCL2", "RST"}.isdisjoint(spec.pins)
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_atecc608b_candidate_records_bounded_limits_orderable_identity_and_nondesign_status() -> None:
    spec = LibraryLoader().get("atecc608b")

    assert spec.lifecycle == "not-recommended-for-new-designs"
    assert spec.properties["supply_range_v"] == [2.0, 5.5]
    assert spec.properties["io_voltage_range_v"] == [1.8, 5.5]
    assert spec.properties["i2c_max_mhz"] == 1.0
    assert spec.properties["sleep_current_max_na"] == 150
    assert spec.properties["temperature_range_c"] == [-40, 85]
    assert spec.properties["absolute_max_supply_v"] == 6.0
    assert spec.properties["key_slots"] == 16
    assert spec.properties["package_body_mm"] == [3.9, 4.9]
    assert spec.properties["package_pitch_mm"] == 1.27
    assert spec.properties["manufacturer_recommended_pad_mm"] == [1.55, 0.6]
    assert spec.sourcing["mpn"] == "ATECC608B-SSHDA-T"
    assert spec.sourcing["status"] == "manufacturer-nrnd"
    assert "Tape and Reel" in spec.sourcing["production_note"]
    assert "4,000" in spec.sourcing["production_note"]


def test_atecc608b_candidate_provenance_is_part_specific_but_unreviewed() -> None:
    spec = LibraryLoader().get("atecc608b")

    for field in ComponentField:
        evidence = spec.field_provenance[field]
        if field in {ComponentField.MPN, ComponentField.SOURCING}:
            assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_WEB
            assert evidence.source_identity == "ATECC608B product identification system"
            assert evidence.source_sha256 == _ORDERING_SHA256
            assert evidence.source_version == "accessed 2026-08-18"
        elif field is ComponentField.LIFECYCLE:
            assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_WEB
            assert evidence.source_identity == "ATECC608B product page"
            assert evidence.source_sha256 == ""
            assert evidence.source_capture_path == "data/library/evidence/web/atecc608b-2026-09-05.json"
            assert evidence.source_capture_sha256 == _LIFECYCLE_CAPTURE_SHA256
            assert evidence.source_version == "captured-2026-09-05"
            assert evidence.extraction_method == "bounded-web-claim-capture"
        else:
            assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_DOCUMENT
            assert evidence.source_identity == "DS40002239B"
            assert evidence.source_sha256 == _DATASHEET_SHA256
            assert evidence.source_version == "DS40002239B"
        expected_extracted_at = date(2026, 9, 5) if field is ComponentField.LIFECYCLE else date(2026, 8, 18)
        assert evidence.extracted_at == expected_extracted_at
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    assert spec.provenance["review_status"] == "candidate-evidence-unreviewed"


def test_atecc608b_vendored_soic8_footprint_is_pinned_and_mismatch_is_explicit() -> None:
    spec = LibraryLoader().get("atecc608b")
    assert_vendored_candidate_footprint(
        spec,
        footprint_name=_FOOTPRINT_NAME,
        filename="SOIC-8_3.9x4.9mm_P1.27mm.kicad_mod",
        source_sha256=_FOOTPRINT_SHA256,
        physical_pin_ids=set(_PACKAGE_MAP),
        repository_pad_size_mm=[1.95, 0.6],
        manufacturer_pad_size_mm=[1.55, 0.6],
        source_name="KiCad official narrow SOIC-8",
    )
