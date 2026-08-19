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
from zaptrace.library.schema import ComponentField, ComponentTrustTier, ProvenanceConfidence, ProvenanceSourceType

_DATASHEET_SHA256 = "58004eda854d07478e6fc6f4398c114f60a3bcf18d4877471c7c1a306d1fa1cb"
_FOOTPRINT_SHA256 = "f4891c800213c5b817c42db6fd6dcd3f7e1614ae8460cec9e00c03859ad4004d"
_FOOTPRINT_NAME = "INA219AIDCNR-SOT23-8"
_PACKAGE_MAP = {
    "1": "IN+",
    "2": "IN-",
    "3": "GND",
    "4": "VS",
    "5": "SCL",
    "6": "SDA",
    "7": "A0",
    "8": "A1",
}


def test_ina219_candidate_matches_exact_dcn_package_and_remains_heuristic() -> None:
    spec = LibraryLoader().get("ina219aidcnr")

    assert spec.manufacturer == "Texas Instruments"
    assert spec.mpn == "INA219AIDCNR"
    assert spec.package == "SOT-23-8"
    assert spec.properties["manufacturer_package_name"] == "SOT-23 (DCN)"
    assert spec.footprint == _FOOTPRINT_NAME
    assert spec.package_pin_map == _PACKAGE_MAP
    assert set(spec.pins) == set(_PACKAGE_MAP.values())
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_ina219_candidate_records_rev_g_limits_and_current_orderable_status() -> None:
    spec = LibraryLoader().get("ina219aidcnr")

    assert spec.properties["resolution_bit"] == 12
    assert spec.properties["supply_range_v"] == [3.0, 5.5]
    assert spec.properties["bus_voltage_operating_max_v"] == 26.0
    assert spec.properties["shunt_full_scale_max_mv"] == 320
    assert spec.properties["absolute_max_supply_v"] == 6.0
    assert spec.properties["temperature_range_c"] == [-40, 125]
    assert spec.properties["package_body_nominal_mm"] == [2.9, 1.63]
    assert spec.properties["thermal_rtheta_ja_c_per_w"] == 135.4
    assert spec.sourcing["status"] == "manufacturer-active-production"
    assert spec.properties["package_qty"] == 3000
    assert spec.properties["carrier"] == "large-tape-and-reel"
    assert spec.properties["part_marking"] == "A219"


def test_ina219_candidate_provenance_is_authoritative_but_unreviewed() -> None:
    spec = LibraryLoader().get("ina219aidcnr")

    for field in ComponentField:
        evidence = spec.field_provenance[field]
        assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_DOCUMENT
        assert evidence.source_identity == "SBOS448G"
        assert evidence.source_sha256 == _DATASHEET_SHA256
        assert evidence.source_version == "Rev G (2015-12; package addendum 2026-03-05)"
        assert evidence.extracted_at == date(2026, 8, 18)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    assert spec.provenance["review_status"] == "candidate-evidence-unreviewed"


def test_ina219_vendored_sot23_8_footprint_is_pinned_and_covers_all_pads() -> None:
    spec = LibraryLoader().get("ina219aidcnr")
    source_path = vendored_footprint_path(_FOOTPRINT_NAME)

    assert VENDOR_FOOTPRINTS[_FOOTPRINT_NAME] == "SOT-23-8.kicad_mod"
    assert source_path == Path("data/footprints/vendor/SOT-23-8.kicad_mod").resolve()
    assert file_sha256(source_path) == _FOOTPRINT_SHA256

    footprint = resolve_vendored_footprint(_FOOTPRINT_NAME)
    assert footprint is not None
    assert {pad.id for pad in footprint.pads} == set(_PACKAGE_MAP)

    source = FootprintSourceProvenance(
        source_type=FootprintSourceType.VENDORED,
        source_name="KiCad official SOT-23-8",
        source_path="data/footprints/vendor/SOT-23-8.kicad_mod",
        source_sha256=_FOOTPRINT_SHA256,
        attribution="data/footprints/vendor/ATTRIBUTION.md",
    )
    proof = build_footprint_proof(
        spec.package,
        footprint,
        footprint_name=spec.footprint,
        source=source,
        expected_pin_count=8,
        pin_map={pin_id: pin_id for pin_id in _PACKAGE_MAP},
    )
    validation = validate_footprint_proof(proof, expected_physical_pins=set(_PACKAGE_MAP))

    assert validation.blocked is False
    assert proof.pin_count == 8
    assert proof.pad_count == 8


def test_library_expansion_no_longer_regenerates_ina219_starter_record() -> None:
    from scripts.generate_library_expansion import collect_all_parts

    generated_ids = {part_id for _category, part_id, _data in collect_all_parts()}
    assert "ina219aidcnr" not in generated_ids
