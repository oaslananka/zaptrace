from __future__ import annotations

from collections import Counter
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
from zaptrace.ee.footprint_vendor import resolve_vendored_footprint, vendored_footprint_path
from zaptrace.library.loader import LibraryLoader
from zaptrace.library.schema import ComponentField, ComponentTrustTier, ProvenanceConfidence, ProvenanceSourceType
from zaptrace.synthesis.mcu import instantiate_mcu

_DATASHEET_URL = "https://documentation.espressif.com/esp32-c3-mini-1_datasheet_en.pdf"
_DATASHEET_SHA256 = "de7361381348d82a1abd337f10170be7a420675987568f71fe3c5b100deed270"
_DATASHEET_VERSION = "v2.2 (2026-05-06)"
_FOOTPRINT = "ESP32-C3-MINI-1"
_FOOTPRINT_SHA256 = "f1899b54ab6c007d50e76334f3fb8f340a827bc1d26f1ba24003333c214a7626"
_KICAD_RELEASE = "3.2.1"
_KICAD_COMMIT = "1dfc3110895c9cd62daf332f49c49ee0ee200831"

_EXPOSED_GPIOS = {
    "GPIO0",
    "GPIO1",
    "GPIO2",
    "GPIO3",
    "GPIO4",
    "GPIO5",
    "GPIO6",
    "GPIO7",
    "GPIO8",
    "GPIO9",
    "GPIO10",
    "GPIO18",
    "GPIO19",
    "GPIO20",
    "GPIO21",
}
_NON_EXPOSED_GPIOS = {f"GPIO{pin}" for pin in range(11, 18)}
_NC_PHYSICAL = {"4", "7", "9", "10", "15", "17", "24", "25", "28", "29", "32", "33", "34", "35"}
_GND_PHYSICAL = {"1", "2", "11", "14", *{str(pin) for pin in range(36, 54)}}
_EXPECTED_PACKAGE_PIN_MAP = {
    **{pin: "GND" for pin in _GND_PHYSICAL},
    "3": "VCC",
    **{pin: "NC" for pin in _NC_PHYSICAL},
    "5": "GPIO2",
    "6": "GPIO3",
    "8": "EN",
    "12": "GPIO0",
    "13": "GPIO1",
    "16": "GPIO10",
    "18": "GPIO4",
    "19": "GPIO5",
    "20": "GPIO6",
    "21": "GPIO7",
    "22": "GPIO8",
    "23": "GPIO9",
    "26": "GPIO18",
    "27": "GPIO19",
    "30": "GPIO20",
    "31": "GPIO21",
}


def _assert_authoritative_unreviewed_provenance(component_id: str) -> None:
    spec = LibraryLoader().get(component_id)
    for field in ComponentField:
        evidence = spec.field_provenance[field]
        assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_DOCUMENT
        assert evidence.source_locator == _DATASHEET_URL
        assert evidence.source_identity == "ESP32-C3-MINI-1 & MINI-1U Datasheet"
        assert evidence.source_sha256 == _DATASHEET_SHA256
        assert evidence.source_version == _DATASHEET_VERSION
        assert evidence.extraction_method == "structured-manufacturer-source-capture"
        assert evidence.extracted_at == date(2026, 8, 11)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM


def _assert_physical_module_contract(component_id: str) -> None:
    spec = LibraryLoader().get(component_id)
    assert spec.package == "SMD-module-53pin"
    assert spec.footprint == _FOOTPRINT
    assert spec.package_pin_map == _EXPECTED_PACKAGE_PIN_MAP
    assert set(spec.package_pin_map) == {str(pin) for pin in range(1, 54)}
    assert set(spec.pins) >= _EXPOSED_GPIOS
    assert _NON_EXPOSED_GPIOS.isdisjoint(spec.pins)
    assert "USB_DP" not in spec.pins
    assert "USB_DM" not in spec.pins
    assert spec.pins["GPIO18"]["description"] == "GPIO18 / USB D-"
    assert spec.pins["GPIO19"]["description"] == "GPIO19 / USB D+"
    assert spec.pins["GPIO20"]["description"] == "GPIO20 / UART0 RXD"
    assert spec.pins["GPIO21"]["description"] == "GPIO21 / UART0 TXD"
    assert spec.pins["NC"]["type"] == "passive"


def test_esp32_c3_stable_candidate_is_exact_recommended_n4x() -> None:
    spec = LibraryLoader().get("esp32-c3-mini-1")

    _assert_authoritative_unreviewed_provenance(spec.id)
    _assert_physical_module_contract(spec.id)
    assert spec.manufacturer == "Espressif Systems"
    assert spec.mpn == "ESP32-C3-MINI-1-N4X"
    assert spec.name == "ESP32-C3-MINI-1-N4X"
    assert spec.datasheet == _DATASHEET_URL
    assert spec.lifecycle == "active"
    assert spec.properties["manufacturer_lifecycle"] == "recommended"
    assert spec.properties["embedded_chip"] == "ESP32-C3FH4X"
    assert spec.properties["chip_revision"] == "v1.1"
    assert spec.properties["flash_mb"] == 4
    assert spec.properties["gpio_count"] == 15
    assert spec.properties["module_dimensions_mm"] == [13.2, 16.6, 2.4]
    assert spec.properties["supply_range_v"] == [3.0, 3.6]
    assert spec.properties["external_supply_min_a"] == 0.5
    assert spec.properties["operating_ambient_c"] == [-40, 85]
    assert spec.properties["strapping_pins"] == ["GPIO2", "GPIO8", "GPIO9"]
    assert spec.properties["antenna"] == "on-board PCB antenna"
    assert spec.electrical_limits["voltage_supply"] == "3.0-3.6 V"
    assert spec.electrical_limits["frequency_mhz"] == 160
    assert spec.electrical_limits["temperature_range"] == [-40, 85]
    assert spec.sourcing["status"] == "manufacturer-recommended"
    assert spec.compliance["rohs"] == "manufacturer-datasheet-declared"
    assert spec.compliance["reach"] == "manufacturer-datasheet-declared"
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_esp32_c3_legacy_n4_record_is_exact_nrnd_variant_not_fake_family_template() -> None:
    spec = LibraryLoader().get("esp32-c3-mini-1-n4")

    _assert_authoritative_unreviewed_provenance(spec.id)
    _assert_physical_module_contract(spec.id)
    assert spec.manufacturer == "Espressif Systems"
    assert spec.mpn == "ESP32-C3-MINI-1-N4"
    assert spec.name == "ESP32-C3-MINI-1-N4"
    assert spec.lifecycle == "nrnd"
    assert spec.properties["manufacturer_lifecycle"] == "nrnd"
    assert spec.properties["replacement_component_id"] == "esp32-c3-mini-1"
    assert spec.properties["embedded_chip"] == "ESP32-C3FH4"
    assert spec.properties["chip_revision"] == "v0.4"
    assert {"RESET", "XTAL1", "XTAL2", "GPIO", "SWDIO", "SWCLK"}.isdisjoint(spec.pins)
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None


def test_esp32_c3_official_vendored_footprint_matches_53_pin_module_contract() -> None:
    source_path = vendored_footprint_path(_FOOTPRINT)
    assert source_path == Path("data/footprints/vendor/ESP32-C3-MINI-1.kicad_mod").resolve()
    assert file_sha256(source_path) == _FOOTPRINT_SHA256

    footprint = resolve_vendored_footprint(_FOOTPRINT)
    assert footprint is not None
    pad_ids = [pad.id for pad in footprint.pads]
    counts = Counter(pad_ids)
    assert len(footprint.pads) == 61
    assert set(pad_ids) == {str(pin) for pin in range(1, 54)}
    assert counts["49"] == 9
    assert all(counts[str(pin)] == 1 for pin in range(1, 54) if pin != 49)

    source = FootprintSourceProvenance(
        source_type=FootprintSourceType.VENDORED,
        source_name="Espressif official ESP32-C3-MINI-1 footprint",
        source_path="data/footprints/vendor/ESP32-C3-MINI-1.kicad_mod",
        source_sha256=_FOOTPRINT_SHA256,
        attribution="data/footprints/vendor/ATTRIBUTION.md",
    )
    proof = build_footprint_proof(
        "SMD-module-53pin",
        footprint,
        footprint_name=_FOOTPRINT,
        source=source,
        expected_pin_count=53,
        pin_map={str(pin): str(pin) for pin in range(1, 54)},
    )
    validation = validate_footprint_proof(proof, expected_physical_pins={str(pin) for pin in range(1, 54)})
    policy = validate_risky_package_policy(proof)

    assert validation.blocked is False
    assert validation.error_count == 0
    assert proof.pin_count == 53
    assert proof.pad_count == 61
    assert policy.risky is True
    assert policy.family == "ESP32-C3-MINI"
    assert policy.blocked is True
    assert {item.code for item in policy.diagnostics} == {"unreviewed-risky-package"}


def test_esp32_c3_footprint_attribution_pins_current_espressif_release() -> None:
    text = Path("data/footprints/vendor/ATTRIBUTION.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if "`ESP32-C3-MINI-1.kicad_mod`" in line)
    assert _KICAD_RELEASE in row
    assert _KICAD_COMMIT in row


def test_esp32_c3_runtime_uses_only_physically_exposed_gpio_and_preserves_pin_map() -> None:
    design = Design(meta=DesignMeta(name="esp32-c3-candidate-runtime"))
    for net in ("VDD_3V3", "GND", "SDA", "SCL"):
        design.nets[net] = Net(id=net, name=net)

    result = instantiate_mcu(design, "esp32", ["i2c", "spi", "ethernet"], rail_net="VDD_3V3")
    assert result.realized is True
    assert result.part_id == "esp32-c3-mini-1"
    component = design.components[result.ref]
    assert component.mpn == "ESP32-C3-MINI-1-N4X"
    assert component.package_pin_map == _EXPECTED_PACKAGE_PIN_MAP
    assert len(component.package_pin_map) == 53
    assigned_interface_pins = {item.pin for item in result.assignments if ":" in item.function}
    assert assigned_interface_pins <= _EXPOSED_GPIOS
    assert _NON_EXPOSED_GPIOS.isdisjoint(assigned_interface_pins)


def test_library_expansion_no_longer_regenerates_fake_esp32_c3_n4_record() -> None:
    from scripts.generate_library_expansion import collect_all_parts

    generated_ids = {part_id for _category, part_id, _data in collect_all_parts()}
    assert "esp32-c3-mini-1-n4" not in generated_ids
