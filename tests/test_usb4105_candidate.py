from __future__ import annotations

from datetime import date
from pathlib import Path

from zaptrace.ee.footprint_proof import (
    FootprintSourceProvenance,
    FootprintSourceType,
    build_footprint_proof,
    file_sha256,
    validate_footprint_proof,
    validate_risky_package_policy,
)
from zaptrace.ee.footprint_vendor import VENDOR_FOOTPRINTS, resolve_vendored_footprint, vendored_footprint_path
from zaptrace.library.loader import LibraryLoader
from zaptrace.library.schema import (
    ComponentField,
    ComponentTrustTier,
    ProvenanceConfidence,
    ProvenanceSourceType,
)

_DRAWING_SHA256 = "fb331fbabee8392ed2937ed757c1610cb0f174b84625147c0b580a18eea8c0e5"
_FOOTPRINT_SHA256 = "db924af7ac6b9ed7b16df1f598a56268c6a32ec33583557b6e5d8aa5056e3b2c"
_FOOTPRINT_NAME = "USB-C-16P-SMD"
_EXPECTED_PACKAGE_MAP = {
    "A1": "GND",
    "A4": "VBUS",
    "A5": "CC1",
    "A6": "D+",
    "A7": "D-",
    "A8": "SBU1",
    "A9": "VBUS",
    "A12": "GND",
    "B1": "GND",
    "B4": "VBUS",
    "B5": "CC2",
    "B6": "D+",
    "B7": "D-",
    "B8": "SBU2",
    "B9": "VBUS",
    "B12": "GND",
    "S1": "SHIELD",
}


def test_usb4105_candidate_matches_exact_gct_orderable_variant_and_remains_heuristic() -> None:
    spec = LibraryLoader().get("usb-c-16p")

    assert spec.manufacturer == "GCT"
    assert spec.mpn == "USB4105-15-A-120"
    assert spec.package == "SMD-16P"
    assert spec.properties["manufacturer_package_name"] == "GCT USB4105-15-A-120"
    assert spec.footprint == _FOOTPRINT_NAME
    assert spec.package_pin_map == _EXPECTED_PACKAGE_MAP
    assert set(spec.pins) == set(_EXPECTED_PACKAGE_MAP.values())
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_usb4105_candidate_records_exact_connector_and_electrical_evidence() -> None:
    spec = LibraryLoader().get("usb-c-16p")

    assert spec.properties["series"] == "USB4105"
    assert spec.properties["usb_version"] == "2.0"
    assert spec.properties["contact_count"] == 16
    assert spec.properties["pcb_mount_type"] == "surface-mount"
    assert spec.properties["orientation"] == "horizontal"
    assert spec.properties["mount_position"] == "top-mount"
    assert spec.properties["shell_stake_length_mm"] == 1.20
    assert spec.properties["contact_plating"] == "15 microinch gold"
    assert spec.properties["mating_cycles"] == 20_000
    assert spec.properties["operating_temperature_c"] == [-40, 85]
    assert spec.properties["vbus_collective_current_a"] == 5.0
    assert spec.properties["gnd_collective_current_a"] == 6.25
    assert spec.properties["cc_pin_current_a"] == 1.25
    assert spec.properties["other_pin_current_a"] == 0.25
    assert spec.electrical_limits["rated_voltage_v"] == 48
    assert spec.electrical_limits["current_rating_a"] == 5.0
    assert spec.electrical_limits["temperature_range"] == [-40, 85]


def test_usb4105_candidate_provenance_is_authoritative_but_unreviewed() -> None:
    spec = LibraryLoader().get("usb-c-16p")

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
        assert evidence.source_identity == "GCT USB4105 product drawing"
        assert evidence.source_sha256 == _DRAWING_SHA256
        assert evidence.source_version == "Revision B / PCN B4 (2023-12-18)"
        assert evidence.extracted_at == date(2026, 8, 10)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    for field in (ComponentField.LIFECYCLE, ComponentField.SOURCING):
        evidence = spec.field_provenance[field]
        assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_WEB
        assert evidence.source_identity == "gct:usb4105-product-page"
        assert evidence.source_version == "accessed-2026-08-10"
        assert evidence.extracted_at == date(2026, 8, 10)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    assert spec.sourcing["status"] == "manufacturer-catalog-active"


def test_usb4105_vendored_footprint_is_pinned_and_covers_all_unique_physical_pads() -> None:
    spec = LibraryLoader().get("usb-c-16p")
    source_path = vendored_footprint_path(_FOOTPRINT_NAME)

    assert VENDOR_FOOTPRINTS[_FOOTPRINT_NAME] == ("USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.kicad_mod")
    assert (
        source_path
        == Path("data/footprints/vendor/USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.kicad_mod").resolve()
    )
    assert file_sha256(source_path) == _FOOTPRINT_SHA256

    footprint = resolve_vendored_footprint(_FOOTPRINT_NAME)
    assert footprint is not None
    assert {pad.id for pad in footprint.pads} == set(_EXPECTED_PACKAGE_MAP)

    source = FootprintSourceProvenance(
        source_type=FootprintSourceType.VENDORED,
        source_name="KiCad official GCT USB4105 series footprint",
        source_path=("data/footprints/vendor/USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.kicad_mod"),
        source_sha256=_FOOTPRINT_SHA256,
        attribution="data/footprints/vendor/ATTRIBUTION.md",
    )
    proof = build_footprint_proof(
        spec.package,
        footprint,
        footprint_name=spec.footprint,
        source=source,
        expected_pin_count=len(_EXPECTED_PACKAGE_MAP),
        pin_map={pin_id: pin_id for pin_id in _EXPECTED_PACKAGE_MAP},
    )
    validation = validate_footprint_proof(proof, expected_physical_pins=set(_EXPECTED_PACKAGE_MAP))

    assert validation.blocked is False
    assert proof.pin_count == 17
    assert proof.pad_count == 20

    risky = validate_risky_package_policy(proof)
    assert risky.family == "USB-C"
    assert risky.blocked is True
    assert any(item.code == "unreviewed-risky-package" for item in risky.diagnostics)
