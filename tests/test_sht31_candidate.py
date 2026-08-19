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
    validate_risky_package_policy,
)
from zaptrace.ee.footprint_vendor import VENDOR_FOOTPRINTS, resolve_vendored_footprint, vendored_footprint_path
from zaptrace.library.integrity import run_library_integrity_gate
from zaptrace.library.loader import LibraryLoader
from zaptrace.library.schema import ComponentField, ComponentTrustTier, ProvenanceConfidence, ProvenanceSourceType
from zaptrace.synthesis.peripherals import instantiate_sensor

_DATASHEET_SHA256 = "095b1853e7f4328f5897c9ca6c392a7dd8b0202eda66b0a2629f9cb840dd496d"
_PRODUCT_PAGE_SHA256 = "019a96b3dfec974c8b78e8601fa2bd7ada383c62b3e9a1e17158a5bd3d7b6c02"
_FOOTPRINT_SHA256 = "2380f3b4d6982902f05e8940603f19f7cfbc1bdfd6ae0f78ebd281c1a3f30a8f"
_FOOTPRINT_NAME = "SHT31-DIS-DFN8"
_PACKAGE_MAP = {
    "1": "SDA",
    "2": "ADDR",
    "3": "ALERT",
    "4": "SCL",
    "5": "VDD",
    "6": "nRESET",
    "7": "R",
    "8": "VSS",
    "9": "VSS",
}


def test_sht31_candidate_matches_exact_orderable_dfn_variant_and_remains_heuristic() -> None:
    spec = LibraryLoader().get("sht31-dis")

    assert spec.manufacturer == "Sensirion"
    assert spec.mpn == "SHT31-DIS-B2.5kS"
    assert spec.package == "DFN-8-1EP"
    assert spec.footprint == _FOOTPRINT_NAME
    assert spec.package_pin_map == _PACKAGE_MAP
    assert set(spec.pins) == set(_PACKAGE_MAP.values())
    assert spec.pins["R"]["description"].startswith("Reserved")
    assert spec.properties["manufacturer_order_number"] == "1-101386-01"
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_sht31_candidate_records_datasheet_electrical_and_land_pattern_evidence() -> None:
    spec = LibraryLoader().get("sht31-dis")

    assert spec.properties["series"] == "SHT3x-DIS"
    assert spec.properties["supply_range_v"] == [2.15, 5.5]
    assert spec.properties["humidity_range_percent_rh"] == [0, 100]
    assert spec.properties["humidity_accuracy_typical_percent_rh"] == 2.0
    assert spec.properties["temperature_range_c"] == [-40, 125]
    assert spec.properties["temperature_accuracy_typical_c_0_to_90"] == 0.2
    assert spec.properties["i2c_max_frequency_khz"] == 1000
    assert spec.properties["package_size_mm"] == [2.5, 2.5, 0.9]
    assert spec.properties["ground_strap_pins"] == ["R"]
    assert spec.properties["manufacturer_land_pattern_mm"] == {
        "io_pad_length": 0.55,
        "io_pad_width": 0.25,
        "pin_pitch": 0.5,
        "exposed_pad_width": 1.0,
        "exposed_pad_length": 1.7,
    }
    repository = spec.properties["repository_land_pattern"]
    assert repository["source_sha256"] == _FOOTPRINT_SHA256
    assert repository["io_pad_size_mm"] == [0.55, 0.25]
    assert repository["pin_pitch"] == 0.5
    assert repository["exposed_pad_bbox_mm"] == [1.0, 1.7]
    assert "human review" in repository["review_note"]
    assert spec.electrical_limits["voltage_supply"] == "2.15-5.5 V"
    assert spec.electrical_limits["temperature_range"] == [-40, 125]


def test_sht31_candidate_provenance_is_authoritative_but_unreviewed() -> None:
    spec = LibraryLoader().get("sht31-dis")

    for field in (
        ComponentField.MPN,
        ComponentField.DATASHEET,
        ComponentField.PIN_MAP,
        ComponentField.PACKAGE,
        ComponentField.FOOTPRINT,
        ComponentField.ELECTRICAL_LIMITS,
    ):
        evidence = spec.field_provenance[field]
        assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_DOCUMENT
        assert evidence.source_identity == "Sensirion SHT3x-DIS datasheet"
        assert evidence.source_sha256 == _DATASHEET_SHA256
        assert evidence.source_version == "Version 7 (2022-12)"
        assert evidence.extracted_at == date(2026, 8, 11)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    for field in (ComponentField.LIFECYCLE, ComponentField.SOURCING):
        evidence = spec.field_provenance[field]
        assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_WEB
        assert evidence.source_identity == "sensirion:sht31-dis-b-product-page"
        assert evidence.source_sha256 == _PRODUCT_PAGE_SHA256
        assert evidence.source_version == "captured-2026-08-11"
        assert evidence.extracted_at == date(2026, 8, 11)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    assert spec.sourcing["status"] == "manufacturer-current-catalog"


def test_sht31_vendored_footprint_covers_eight_pins_and_exposed_vss_pad() -> None:
    spec = LibraryLoader().get("sht31-dis")
    source_path = vendored_footprint_path(_FOOTPRINT_NAME)

    assert VENDOR_FOOTPRINTS[_FOOTPRINT_NAME] == "Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm.kicad_mod"
    assert (
        source_path
        == Path("data/footprints/vendor/Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm.kicad_mod").resolve()
    )
    assert file_sha256(source_path) == _FOOTPRINT_SHA256

    footprint = resolve_vendored_footprint(_FOOTPRINT_NAME)
    assert footprint is not None
    assert {pad.id for pad in footprint.pads} == set(_PACKAGE_MAP)

    source = FootprintSourceProvenance(
        source_type=FootprintSourceType.VENDORED,
        source_name="KiCad official Sensirion SHT3x DFN-8-1EP footprint",
        source_path="data/footprints/vendor/Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm.kicad_mod",
        source_sha256=_FOOTPRINT_SHA256,
        attribution="data/footprints/vendor/ATTRIBUTION.md",
    )
    proof = build_footprint_proof(
        spec.package,
        footprint,
        footprint_name=spec.footprint,
        source=source,
        expected_pin_count=len(_PACKAGE_MAP),
        pin_map={pin_id: pin_id for pin_id in _PACKAGE_MAP},
    )
    validation = validate_footprint_proof(proof, expected_physical_pins=set(_PACKAGE_MAP))

    assert validation.blocked is False
    assert proof.pin_count == 9
    assert proof.pad_count == 9

    risky = validate_risky_package_policy(proof)
    assert risky.family == "DFN"
    assert risky.blocked is True
    assert any(item.code == "unreviewed-risky-package" for item in risky.diagnostics)


def test_sht31_runtime_ties_reserved_r_pin_to_ground() -> None:
    design = Design(meta=DesignMeta(name="sht31_candidate"))
    for net in ("VDD_3V3", "GND", "SDA", "SCL"):
        design.nets[net] = Net(id=net, name=net)

    ref = instantiate_sensor(design, "sht31-dis", rail_net="VDD_3V3")

    assert ref is not None
    ground_pins = {node.pin_name for node in design.nets["GND"].nodes if node.component_ref == ref}
    assert {"VSS", "R", "ADDR"} <= ground_pins
    assert design.components[ref].package_pin_map == _PACKAGE_MAP


def test_sht31_legacy_id_is_safe_canonical_compatibility_mirror() -> None:
    loader = LibraryLoader()
    canonical = loader.get("sht31-dis")
    legacy = loader.get("sht31-dis-b2.5ksdaa")

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


def test_sht31_duplicate_group_resolves_without_conflict() -> None:
    report = run_library_integrity_gate()
    group = next(
        group
        for group in report.duplicate_groups
        if group.canonical_id == "sht31-dis" and "sht31-dis-b2.5ksdaa" in group.alternate_ids
    )
    assert group.conflict is False


def test_library_expansion_no_longer_regenerates_superseded_sht31_legacy_record() -> None:
    from scripts.generate_library_expansion import collect_all_parts

    generated_ids = {part_id for _category, part_id, _data in collect_all_parts()}
    assert "sht31-dis-b2.5ksdaa" not in generated_ids
