from __future__ import annotations

from datetime import date
from pathlib import Path

from zaptrace.core.models import Design, DesignMeta, Net
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
from zaptrace.synthesis.peripherals import instantiate_sensor

_DATASHEET_SHA256 = "5fe00cf9509daba7ca311cd0a461debc563dd57598c5de3bf9c31903dc2238da"
_FOOTPRINT_SHA256 = "8d2841a74e13e6aa9ff353b36a4946df71e473655a2ec824de8486d5adb3b7b9"
_FOOTPRINT_NAME = "ADS1115IDGSR-DGS10"
_PACKAGE_MAP = {
    "1": "ADDR",
    "2": "ALERT",
    "3": "GND",
    "4": "AIN0",
    "5": "AIN1",
    "6": "AIN2",
    "7": "AIN3",
    "8": "VDD",
    "9": "SDA",
    "10": "SCL",
}


def test_ads1115_candidate_matches_exact_dgs_package_and_remains_heuristic() -> None:
    spec = LibraryLoader().get("ads1115")

    assert spec.manufacturer == "Texas Instruments"
    assert spec.mpn == "ADS1115IDGSR"
    assert spec.package == "MSOP-10"
    assert spec.properties["manufacturer_package_name"] == "VSSOP (DGS)"
    assert spec.footprint == _FOOTPRINT_NAME
    assert spec.package_pin_map == _PACKAGE_MAP
    assert set(spec.pins) == set(_PACKAGE_MAP.values())
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_ads1115_candidate_records_current_rev_e_electrical_and_land_pattern_evidence() -> None:
    spec = LibraryLoader().get("ads1115")

    assert spec.properties["resolution_bit"] == 16
    assert spec.properties["channels_single_ended"] == 4
    assert spec.properties["channels_differential"] == 2
    assert spec.properties["sample_rate_sps"] == 860
    assert spec.properties["supply_range_v"] == [2.0, 5.5]
    assert spec.properties["absolute_max_vdd_v"] == 7.0
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


def test_ads1115_candidate_provenance_is_authoritative_but_unreviewed() -> None:
    spec = LibraryLoader().get("ads1115")

    for field in ComponentField:
        evidence = spec.field_provenance[field]
        assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_DOCUMENT
        assert evidence.source_identity == "SBAS444E"
        assert evidence.source_sha256 == _DATASHEET_SHA256
        assert evidence.source_version == "Rev E (2024-12)"
        assert evidence.extracted_at == date(2026, 8, 10)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    assert spec.sourcing["status"] == "manufacturer-active-production"


def test_ads1115_vendored_dgs_footprint_is_pinned_and_covers_all_pads() -> None:
    spec = LibraryLoader().get("ads1115")
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


def test_ads1115_i2c_synthesis_preserves_physical_map_and_expected_wiring() -> None:
    design = Design(meta=DesignMeta(name="ads1115_candidate"))
    for net in ("VDD_3V3", "GND", "SDA", "SCL"):
        design.nets[net] = Net(id=net, name=net)

    ref = instantiate_sensor(design, "ads1115", rail_net="VDD_3V3")

    assert ref is not None
    component = design.components[ref]
    assert component.package_pin_map == _PACKAGE_MAP
    rail_pins = {n.pin_name for n in design.nets["VDD_3V3"].nodes if n.component_ref == ref}
    ground_pins = {n.pin_name for n in design.nets["GND"].nodes if n.component_ref == ref}
    sda_pins = {n.pin_name for n in design.nets["SDA"].nodes if n.component_ref == ref}
    scl_pins = {n.pin_name for n in design.nets["SCL"].nodes if n.component_ref == ref}
    assert "VDD" in rail_pins
    assert {"GND", "ADDR"} <= ground_pins
    assert sda_pins == {"SDA"}
    assert scl_pins == {"SCL"}


def test_ads1115_legacy_id_is_safe_canonical_compatibility_mirror() -> None:
    loader = LibraryLoader()
    canonical = loader.get("ads1115")
    legacy = loader.get("ads1115idgsr")

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


def test_ads1115_duplicate_group_resolves_without_conflict() -> None:
    report = run_library_integrity_gate()
    group = next(
        group
        for group in report.duplicate_groups
        if group.canonical_id == "ads1115" and "ads1115idgsr" in group.alternate_ids
    )
    assert group.conflict is False


def test_library_expansion_no_longer_regenerates_superseded_ads1115_legacy_record() -> None:
    from scripts.generate_library_expansion import collect_all_parts

    generated_ids = {part_id for _category, part_id, _data in collect_all_parts()}
    assert "ads1115idgsr" not in generated_ids
