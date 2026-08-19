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

_ESTORE_SHA256 = "a404632caffb132168cdd779cd9700a67c5fa6c43c665958305fb8353c598e30"
_FOOTPRINT_SHA256 = "ec36273cf5fa99acf022c2f5af17310d123fa4b5ccfe98a2f562fedabe7f3f46"
_FOOTPRINT_NAME = "STM32G0B1CET6-LQFP48"
_EXPECTED_PACKAGE_MAP = {
    "1": "PC13",
    "2": "PC14_OSC32_IN",
    "3": "PC15_OSC32_OUT",
    "4": "VBAT",
    "5": "VREF_PLUS",
    "6": "VDD",
    "7": "VSS",
    "8": "PF0_OSC_IN",
    "9": "PF1_OSC_OUT",
    "10": "NRST",
    "11": "PA0",
    "12": "PA1",
    "13": "PA2",
    "14": "PA3",
    "15": "PA4",
    "16": "PA5",
    "17": "PA6",
    "18": "PA7",
    "19": "PB0",
    "20": "PB1",
    "21": "PB2",
    "22": "PB10",
    "23": "PB11",
    "24": "PB12",
    "25": "PB13",
    "26": "PB14",
    "27": "PB15",
    "28": "PA8",
    "29": "PA9",
    "30": "PC6",
    "31": "PC7",
    "32": "PA10",
    "33": "PA11",
    "34": "PA12",
    "35": "PA13",
    "36": "PA14_BOOT0",
    "37": "PA15",
    "38": "PD0",
    "39": "PD1",
    "40": "PD2",
    "41": "PD3",
    "42": "PB3",
    "43": "PB4",
    "44": "PB5",
    "45": "PB6",
    "46": "PB7",
    "47": "PB8",
    "48": "PB9",
}


def test_stm32g0b1_candidate_matches_exact_lqfp48_package_and_remains_heuristic() -> None:
    spec = LibraryLoader().get("stm32g0b1cet6")

    assert spec.manufacturer == "STMicroelectronics"
    assert spec.mpn == "STM32G0B1CET6"
    assert spec.package == "LQFP-48"
    assert spec.footprint == _FOOTPRINT_NAME
    assert spec.package_pin_map == _EXPECTED_PACKAGE_MAP
    assert set(spec.pins) == set(_EXPECTED_PACKAGE_MAP.values())
    assert {"USB_DP", "USB_DM", "UCPD1_CC1", "UCPD1_CC2"}.isdisjoint(spec.pins)
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_stm32g0b1_alternate_functions_preserve_usb_ucpd_and_debug_semantics() -> None:
    spec = LibraryLoader().get("stm32g0b1cet6")
    alternate = spec.properties["alternate_functions"]

    assert "USB_DM" in alternate["PA11"]
    assert "USB_DP" in alternate["PA12"]
    assert "UCPD1_CC1" in alternate["PA8"]
    assert "UCPD1_CC2" in alternate["PB15"]
    assert "SWDIO" in alternate["PA13"]
    assert {"SWCLK", "BOOT0"}.issubset(alternate["PA14_BOOT0"])


def test_stm32g0b1_provenance_is_authoritative_but_still_unreviewed() -> None:
    spec = LibraryLoader().get("stm32g0b1cet6")

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
        assert evidence.source_identity == "DS13560"
        assert evidence.source_version == "Rev 6 (2026-02)"
        assert evidence.source_sha256 == ""
        assert evidence.extracted_at == date(2026, 8, 9)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    for field in (ComponentField.LIFECYCLE, ComponentField.SOURCING):
        evidence = spec.field_provenance[field]
        assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_WEB
        assert evidence.source_sha256 == _ESTORE_SHA256
        assert evidence.source_version == "captured-2026-08-09"
        assert evidence.extracted_at == date(2026, 8, 9)
        assert evidence.reviewed_by == ""
        assert evidence.confidence is ProvenanceConfidence.MEDIUM

    assert spec.sourcing["status"] == "manufacturer-catalog-active"
    assert "datasheet SHA-256" in spec.provenance["production_note"]


def test_stm32g0b1_vendored_footprint_is_pinned_and_covers_all_48_pads() -> None:
    spec = LibraryLoader().get("stm32g0b1cet6")
    source_path = vendored_footprint_path(_FOOTPRINT_NAME)

    assert VENDOR_FOOTPRINTS[_FOOTPRINT_NAME] == "LQFP-48_7x7mm_P0.5mm.kicad_mod"
    assert source_path == Path("data/footprints/vendor/LQFP-48_7x7mm_P0.5mm.kicad_mod").resolve()
    assert file_sha256(source_path) == _FOOTPRINT_SHA256

    footprint = resolve_vendored_footprint(_FOOTPRINT_NAME)
    assert footprint is not None
    assert {pad.id for pad in footprint.pads} == set(_EXPECTED_PACKAGE_MAP)

    source = FootprintSourceProvenance(
        source_type=FootprintSourceType.VENDORED,
        source_name="KiCad official LQFP-48 7x7 mm P0.5 mm",
        source_path="data/footprints/vendor/LQFP-48_7x7mm_P0.5mm.kicad_mod",
        source_sha256=_FOOTPRINT_SHA256,
        attribution="data/footprints/vendor/ATTRIBUTION.md",
    )
    proof = build_footprint_proof(
        spec.package,
        footprint,
        footprint_name=spec.footprint,
        source=source,
        expected_pin_count=48,
        pin_map={pin_id: pin_id for pin_id in _EXPECTED_PACKAGE_MAP},
    )
    validation = validate_footprint_proof(proof, expected_physical_pins=set(_EXPECTED_PACKAGE_MAP))

    assert validation.blocked is False
    assert proof.pin_count == 48
    assert proof.pad_count == 48
