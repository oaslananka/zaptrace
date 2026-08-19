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
from zaptrace.library.loader import LibraryLoader
from zaptrace.library.schema import (
    ComponentField,
    ComponentTrustTier,
    ProvenanceConfidence,
    ProvenanceSourceType,
)
from zaptrace.synthesis.peripherals import instantiate_spi_flash

_DATASHEET_SHA256 = "b51bb4303e17a17750c9cbcafc9a776dea842a8971d7cdd5edc70ff738efb1fe"
_PRODUCT_SHA256 = "48e4ccec42a3a9cb056900e00e97e5d1656a4f3f6d329a986ef2d14a0a05f7e0"
_FOOTPRINT_SHA256 = "f1e0c38853533124658835d81f20f634b4a9f2b660b6d11fe2d14fdac7545356"
_FOOTPRINT_NAME = "W25Q128JVSIQ-SOIC8-208MIL"
_PACKAGE = "SOIC-8-208MIL"
_PACKAGE_MAP = {
    "1": "CS",
    "2": "DO",
    "3": "WP",
    "4": "GND",
    "5": "DI",
    "6": "CLK",
    "7": "HOLD",
    "8": "VCC",
}


def test_w25q128jv_candidate_matches_current_winbond_sop8_package_and_remains_heuristic() -> None:
    spec = LibraryLoader().get("w25q128jv")

    assert spec.manufacturer == "Winbond"
    assert spec.mpn == "W25Q128JVSIQ"
    assert spec.datasheet.endswith("W25Q128JV%20RevM%2012242024%20Plus.pdf")
    assert spec.package == _PACKAGE
    assert spec.footprint == _FOOTPRINT_NAME
    assert spec.package_pin_map == _PACKAGE_MAP
    assert set(spec.pins) == set(_PACKAGE_MAP.values())
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_w25q128jv_quad_spi_aliases_preserve_synthesis_facing_pin_names() -> None:
    spec = LibraryLoader().get("w25q128jv")
    alternate = spec.properties["alternate_functions"]

    assert alternate["DO"] == ["IO1"]
    assert alternate["WP"] == ["IO2"]
    assert alternate["DI"] == ["IO0"]
    assert set(alternate["HOLD"]) == {"RESET", "IO3"}

    design = Design(meta=DesignMeta(name="w25q-candidate"))
    for net in ("VDD_3V3", "GND", "SPI_SCK", "SPI_MOSI", "SPI_MISO", "SPI_CS"):
        design.nets[net] = Net(id=net, name=net)
    ref = instantiate_spi_flash(design, "w25q128jv", rail_net="VDD_3V3")

    assert ref is not None
    assert design.components[ref].package_pin_map == _PACKAGE_MAP
    assert any(node.component_ref == ref and node.pin_name == "DI" for node in design.nets["SPI_MOSI"].nodes)
    assert any(node.component_ref == ref and node.pin_name == "DO" for node in design.nets["SPI_MISO"].nodes)
    rail_pins = {node.pin_name for node in design.nets["VDD_3V3"].nodes if node.component_ref == ref}
    assert {"VCC", "WP", "HOLD"} <= rail_pins


def test_w25q128jv_provenance_uses_current_rev_m_and_mass_production_snapshot() -> None:
    spec = LibraryLoader().get("w25q128jv")

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
        assert evidence.source_identity == "W25Q128JV"
        assert evidence.source_version == "Rev M (2024-12-24)"
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

    assert spec.sourcing["status"] == "manufacturer-mass-production"
    assert spec.properties["package_nominal_mm"] == {"body_length": 5.28, "body_width": 5.23, "pin_pitch": 1.27}
    assert spec.properties["supply_range_v"] == [2.7, 3.6]
    assert spec.properties["temperature_range_c"] == [-40, 85]


def test_w25q128jv_vendored_208mil_footprint_is_pinned_and_covers_all_pads() -> None:
    spec = LibraryLoader().get("w25q128jv")
    source_path = vendored_footprint_path(_FOOTPRINT_NAME)

    assert VENDOR_FOOTPRINTS[_FOOTPRINT_NAME] == "SOIC-8_5.3x5.3mm_P1.27mm.kicad_mod"
    assert source_path == Path("data/footprints/vendor/SOIC-8_5.3x5.3mm_P1.27mm.kicad_mod").resolve()
    assert file_sha256(source_path) == _FOOTPRINT_SHA256

    footprint = resolve_vendored_footprint(_FOOTPRINT_NAME)
    assert footprint is not None
    assert {pad.id for pad in footprint.pads} == set(_PACKAGE_MAP)

    source = FootprintSourceProvenance(
        source_type=FootprintSourceType.VENDORED,
        source_name="KiCad official SOIC-8 5.3x5.3 mm P1.27 mm",
        source_path="data/footprints/vendor/SOIC-8_5.3x5.3mm_P1.27mm.kicad_mod",
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
