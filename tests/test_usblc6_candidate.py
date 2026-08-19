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

_DATASHEET_SHA256 = "bc30154f310cd631043214ed52571daefe04270587ec55072d49a23bd18b9068"
_PRODUCT_SHA256 = "b2c3da9b168f22c48b41d6a4fa0831488264b69fda48325d015f42b29eba5894"
_FOOTPRINT_SHA256 = "ea569e67e65b5714bde1897eb2edf94b1bb9cb0f9fe4e4885323fa2e9c364ed5"
_FOOTPRINT_NAME = "USBLC6-2SC6-SOT23-6L"


def test_usblc6_candidate_matches_st_physical_pinout_and_remains_heuristic() -> None:
    spec = LibraryLoader().get("usblc6-2sc6")

    assert spec.manufacturer == "STMicroelectronics"
    assert spec.mpn == "USBLC6-2SC6"
    assert spec.package == "SOT-23-6"
    assert spec.footprint == _FOOTPRINT_NAME
    assert spec.package_pin_map == {
        "1": "IO1",
        "2": "GND",
        "3": "IO2",
        "4": "IO2",
        "5": "VBUS",
        "6": "IO1",
    }
    assert set(spec.pins) == {"IO1", "GND", "IO2", "VBUS"}
    assert "NC" not in spec.pins
    assert spec.pins["VBUS"]["type"] == "power"
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_usblc6_candidate_provenance_is_hashed_but_unreviewed() -> None:
    spec = LibraryLoader().get("usblc6-2sc6")

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
        assert evidence.source_sha256 == _DATASHEET_SHA256
        assert evidence.source_identity == "DS4260"
        assert evidence.source_version == "Rev 7 (2021-12)"
        assert evidence.extracted_at == date(2026, 8, 9)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    for field in (ComponentField.LIFECYCLE, ComponentField.SOURCING):
        evidence = spec.field_provenance[field]
        assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_WEB
        assert evidence.source_sha256 == _PRODUCT_SHA256
        assert evidence.source_version == "captured-2026-08-09"
        assert evidence.extracted_at == date(2026, 8, 9)
        assert evidence.reviewed_by == ""
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    assert spec.sourcing["status"] == "manufacturer-catalog-active"
    assert spec.properties["breakdown_voltage_min_v"] == 6.0
    assert spec.properties["leakage_test_voltage_v"] == 5.25
    assert spec.properties["iec_61000_4_2_level4"] == {"air_kv": 15, "contact_kv": 8}
    assert spec.properties["absolute_peak_pulse_contact_kv"] == 15


def test_usblc6_vendored_footprint_is_pinned_and_covers_physical_pads() -> None:
    spec = LibraryLoader().get("usblc6-2sc6")
    source_path = vendored_footprint_path(_FOOTPRINT_NAME)

    assert VENDOR_FOOTPRINTS[_FOOTPRINT_NAME] == "SOT-23-6.kicad_mod"
    assert source_path == Path("data/footprints/vendor/SOT-23-6.kicad_mod").resolve()
    assert file_sha256(source_path) == _FOOTPRINT_SHA256

    footprint = resolve_vendored_footprint(_FOOTPRINT_NAME)
    assert footprint is not None
    assert {pad.id for pad in footprint.pads} == set(spec.package_pin_map)

    source = FootprintSourceProvenance(
        source_type=FootprintSourceType.VENDORED,
        source_name="KiCad official SOT-23-6",
        source_path=str(Path("data/footprints/vendor/SOT-23-6.kicad_mod")),
        source_sha256=_FOOTPRINT_SHA256,
        attribution="data/footprints/vendor/ATTRIBUTION.md",
    )
    proof = build_footprint_proof(
        spec.package,
        footprint,
        footprint_name=spec.footprint,
        source=source,
        expected_pin_count=6,
        pin_map={pin_id: pin_id for pin_id in spec.package_pin_map},
    )
    validation = validate_footprint_proof(proof, expected_pins=set(spec.package_pin_map))

    assert validation.blocked is False
    assert proof.pin_count == 6
    assert proof.pad_count == 6
