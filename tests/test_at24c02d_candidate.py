from __future__ import annotations

from datetime import date

from tests.candidate_footprint_helpers import assert_vendored_candidate_footprint
from zaptrace.library.loader import LibraryLoader
from zaptrace.library.schema import ComponentField, ComponentTrustTier, ProvenanceConfidence, ProvenanceSourceType

_DATASHEET_SHA256 = "faa30c91617d26513cec34f5555a3512b4110383c11e90db91235e187938a167"
_FOOTPRINT_SHA256 = "074ecb2092b24fa4b4b9cdd7c926fc587b0d7d6d21e7341e57935fd42d36894f"
_FOOTPRINT_NAME = "AT24C02D-SSHM-T-SOIC8-SN"
_PACKAGE_MAP = {
    "1": "A0",
    "2": "A1",
    "3": "A2",
    "4": "GND",
    "5": "SDA",
    "6": "SCL",
    "7": "WP",
    "8": "VCC",
}


def test_at24c02d_candidate_matches_exact_soic_pinout_and_remains_heuristic() -> None:
    spec = LibraryLoader().get("at24c02d-sshm-t")

    assert spec.manufacturer == "Microchip Technology"
    assert spec.mpn == "AT24C02D-SSHM-T"
    assert spec.package == "SOIC-8"
    assert spec.properties["manufacturer_package_name"] == "8-Lead SOIC (SN), Narrow 3.90 mm"
    assert spec.footprint == _FOOTPRINT_NAME
    assert spec.package_pin_map == _PACKAGE_MAP
    assert set(spec.pins) == set(_PACKAGE_MAP.values())
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_at24c02d_candidate_records_datasheet_limits_and_orderable_identity() -> None:
    spec = LibraryLoader().get("at24c02d-sshm-t")

    assert spec.properties["memory_density_bits"] == 2048
    assert spec.properties["organization"] == "256 x 8"
    assert spec.properties["page_write_bytes"] == 8
    assert spec.properties["max_write_cycle_ms"] == 5
    assert spec.properties["endurance_write_cycles"] == 1_000_000
    assert spec.properties["data_retention_years"] == 100
    assert spec.properties["supply_range_v"] == [1.7, 3.6]
    assert spec.properties["fast_mode_max_khz"] == 400
    assert spec.properties["fast_mode_plus_max_mhz"] == 1.0
    assert spec.properties["temperature_range_c"] == [-40, 85]
    assert spec.properties["absolute_max_vcc_v"] == 4.1
    assert spec.properties["package_body_mm"] == [3.9, 4.9]
    assert spec.properties["package_pitch_mm"] == 1.27
    assert spec.properties["manufacturer_recommended_pad_mm"] == [1.55, 0.6]
    assert spec.sourcing["status"] == "manufacturer-in-production"
    assert "Tape and Reel" in spec.sourcing["production_note"]


def test_at24c02d_candidate_provenance_is_authoritative_but_unreviewed() -> None:
    spec = LibraryLoader().get("at24c02d-sshm-t")

    for field in ComponentField:
        evidence = spec.field_provenance[field]
        if field is ComponentField.LIFECYCLE:
            assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_WEB
            assert evidence.source_identity == "AT24C02D product page"
            assert evidence.source_sha256 == ""
            assert evidence.source_version == "accessed 2026-08-18"
        else:
            assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_DOCUMENT
            assert evidence.source_identity == "DS20006100A"
            assert evidence.source_sha256 == _DATASHEET_SHA256
            assert evidence.source_version == "Rev A (2018-11)"
        assert evidence.extracted_at == date(2026, 8, 18)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    assert spec.provenance["review_status"] == "candidate-evidence-unreviewed"


def test_at24c02d_vendored_soic8_footprint_is_pinned_and_mismatch_is_explicit() -> None:
    spec = LibraryLoader().get("at24c02d-sshm-t")
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


def test_library_expansion_no_longer_regenerates_at24c02d_starter_record() -> None:
    from scripts.generate_library_expansion import collect_all_parts

    generated_ids = {part_id for _category, part_id, _data in collect_all_parts()}
    assert "at24c02d-sshm-t" not in generated_ids
