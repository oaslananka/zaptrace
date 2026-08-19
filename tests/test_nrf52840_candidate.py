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
from zaptrace.ee.footprint_vendor import resolve_vendored_footprint, vendored_footprint_path
from zaptrace.library.loader import LibraryLoader
from zaptrace.library.schema import ComponentField, ComponentTrustTier, ProvenanceConfidence, ProvenanceSourceType
from zaptrace.synthesis.mcu import instantiate_mcu

_PS_ROOT = "https://docs.nordicsemi.com/r/bundle/ps_nrf52840"
_PIN_URL = f"{_PS_ROOT}/page/pin.html"
_ORDERING_URL = f"{_PS_ROOT}/page/ordering_info.html"
_OPERATING_URL = f"{_PS_ROOT}/page/recommended_op_conditions.html"
_PS_VERSION = "1.11 (2024-10)"
_FOOTPRINT = "nRF52840-QIAA"
_FOOTPRINT_FILE = "Nordic_AQFN-73-1EP_7x7mm_P0.5mm.kicad_mod"
_FOOTPRINT_SHA256 = "b1d3fb2b429e53beda8001f4604c456f4561cffd88c65af1f795f147828c0105"
_KICAD_REVISION = "a2cd6bea801640f3b5c0067744ac7f84dc324f1e"

_QIAA_PACKAGE_PIN_MAP = {
    "A8": "P0_31",
    "A10": "P0_29",
    "A12": "P0_02",
    "A14": "P1_15",
    "A16": "P1_13",
    "A18": "DEC2",
    "A20": "P1_10",
    "A22": "VDD",
    "A23": "XC2",
    "B1": "VDD",
    "B3": "DCC",
    "B5": "DEC4",
    "B7": "VSS",
    "B9": "P0_30",
    "B11": "P0_28",
    "B13": "P0_03",
    "B15": "P1_14",
    "B17": "P1_12",
    "B19": "P1_11",
    "B24": "XC1",
    "C1": "DEC1",
    "D2": "P0_00",
    "D23": "DEC3",
    "E24": "DEC6",
    "F2": "P0_01",
    "F23": "VSS",
    "G1": "P0_26",
    "H2": "P0_27",
    "H23": "ANT",
    "J1": "P0_04",
    "J24": "P0_10",
    "K2": "P0_05",
    "L1": "P0_06",
    "L24": "P0_09",
    "M2": "P0_07",
    "N1": "P0_08",
    "N24": "NC",
    "P2": "P1_08",
    "P23": "P1_07",
    "R1": "P1_09",
    "R24": "P1_06",
    "T2": "P0_11",
    "T23": "P1_05",
    "U1": "P0_12",
    "U24": "P1_04",
    "V23": "P1_03",
    "W1": "VDD",
    "W24": "P1_02",
    "Y2": "VDDH",
    "Y23": "P1_01",
    "AA24": "SWDCLK",
    "AB2": "DCCH",
    "AC5": "DECUSB",
    "AC9": "P0_14",
    "AC11": "P0_16",
    "AC13": "P0_18",
    "AC15": "P0_19",
    "AC17": "P0_21",
    "AC19": "P0_23",
    "AC21": "P0_25",
    "AC24": "SWDIO",
    "AD2": "VBUS",
    "AD4": "USB_DM",
    "AD6": "USB_DP",
    "AD8": "P0_13",
    "AD10": "P0_15",
    "AD12": "P0_17",
    "AD14": "VDD",
    "AD16": "P0_20",
    "AD18": "P0_22",
    "AD20": "P0_24",
    "AD22": "P1_00",
    "AD23": "VDD",
    "EP": "VSS",
}
_LEGACY_QIAA_PACKAGE_PIN_MAP = {**_QIAA_PACKAGE_PIN_MAP, "N24": "DEC5"}
_GPIO_NAMES = {f"P0_{pin:02d}" for pin in range(32)} | {f"P1_{pin:02d}" for pin in range(16)}


def _assert_field_provenance(component_id: str) -> None:
    spec = LibraryLoader().get(component_id)
    for field in ComponentField:
        evidence = spec.field_provenance[field]
        assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_WEB
        assert evidence.source_version == _PS_VERSION
        assert evidence.extraction_method == "structured-manufacturer-source-capture"
        assert evidence.extracted_at == date(2026, 8, 11)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM
        if field in {ComponentField.MPN, ComponentField.LIFECYCLE, ComponentField.SOURCING}:
            assert evidence.source_locator == _ORDERING_URL
            assert evidence.source_identity == "Nordic nRF52840 ordering information"
        elif field is ComponentField.ELECTRICAL_LIMITS:
            assert evidence.source_locator == _OPERATING_URL
            assert evidence.source_identity == "Nordic nRF52840 recommended operating conditions"
        elif field is ComponentField.DATASHEET:
            assert evidence.source_locator == _PS_ROOT
            assert evidence.source_identity == "Nordic nRF52840 Product Specification"
        else:
            assert evidence.source_locator == _PIN_URL
            assert evidence.source_identity == "Nordic nRF52840 aQFN73 pin assignments"


def _assert_common_qiaa_contract(component_id: str, expected_map: dict[str, str]) -> None:
    spec = LibraryLoader().get(component_id)

    assert spec.manufacturer == "Nordic Semiconductor"
    assert spec.package == "aQFN-73-1EP"
    assert spec.footprint == _FOOTPRINT
    assert spec.package_pin_map == expected_map
    assert len(spec.package_pin_map) == 74
    assert set(spec.pins) >= _GPIO_NAMES
    assert len(_GPIO_NAMES) == 48
    assert spec.pins["VDD"]["type"] == "power"
    assert spec.pins["VSS"]["type"] == "power"
    for nonautomatic in ("VDDH", "VBUS", "DEC1", "DEC2", "DEC3", "DEC4", "DEC6", "DCC", "DCCH", "ANT"):
        assert spec.pins[nonautomatic]["type"] == "passive"
    assert spec.pins["USB_DM"]["type"] == "bidirectional"
    assert spec.pins["USB_DP"]["type"] == "bidirectional"
    assert spec.pins["SWDIO"]["type"] == "bidirectional"
    assert spec.pins["SWDCLK"]["type"] == "input"
    assert spec.properties["core"] == "Arm Cortex-M4F"
    assert spec.properties["frequency_mhz"] == 64
    assert spec.properties["flash_kb"] == 1024
    assert spec.properties["sram_kb"] == 256
    assert spec.properties["gpio_count"] == 48
    assert spec.properties["package_dimensions_mm"] == [7.0, 7.0]
    assert spec.properties["manufacturer_ball_count"] == 73
    assert spec.properties["exposed_die_pad_count"] == 1
    assert spec.properties["ball_pitch_mm"] == 0.5
    assert spec.properties["soc_revision"] == 3
    assert spec.electrical_limits["voltage_supply"] == "1.7-3.6 V"
    assert spec.electrical_limits["temperature_range"] == [-40, 85]
    assert spec.electrical_limits["frequency_mhz"] == 64
    assert spec.properties["vddh_range_v"] == [2.5, 5.5]
    assert spec.properties["vbus_range_v"] == [4.35, 5.5]
    assert spec.properties["junction_temperature_max_c"] == 90
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None
    _assert_field_provenance(component_id)


def test_nrf52840_stable_candidate_uses_current_f_r7_orderable_variant() -> None:
    spec = LibraryLoader().get("nrf52840-qiaa")

    _assert_common_qiaa_contract(spec.id, _QIAA_PACKAGE_PIN_MAP)
    assert spec.name == "nRF52840-QIAA-F-R7"
    assert spec.mpn == "nRF52840-QIAA-F-R7"
    assert spec.lifecycle == "active"
    assert spec.properties["function_variant"] == "AA-F"
    assert spec.properties["access_port_protection"] == "hardware-and-software"
    assert spec.properties["container"] == '7" reel'
    assert spec.properties["minimum_order_quantity"] == 800
    assert spec.properties["dec5_status"] == "not-connected-for-Fxx-and-later"
    assert spec.sourcing["status"] == "manufacturer-current-option"


def test_nrf52840_legacy_r7_record_is_nrnd_and_keeps_build_sensitive_dec5() -> None:
    spec = LibraryLoader().get("nrf52840-qiaa-r7")

    _assert_common_qiaa_contract(spec.id, _LEGACY_QIAA_PACKAGE_PIN_MAP)
    assert spec.name == "nRF52840-QIAA-R7"
    assert spec.mpn == "nRF52840-QIAA-R7"
    assert spec.lifecycle == "nrnd"
    assert spec.properties["function_variant"] == "AA"
    assert spec.properties["access_port_protection"] == "hardware"
    assert spec.properties["replacement_component_id"] == "nrf52840-qiaa"
    assert spec.properties["dec5_status"] == "build-code-dependent"
    assert spec.pins["DEC5"]["type"] == "passive"
    assert spec.sourcing["status"] == "manufacturer-nrnd"


def test_nrf52840_current_kicad_footprint_matches_nordic_ball_identity_set() -> None:
    source_path = vendored_footprint_path(_FOOTPRINT)
    assert source_path == Path(f"data/footprints/vendor/{_FOOTPRINT_FILE}").resolve()
    assert file_sha256(source_path) == _FOOTPRINT_SHA256

    footprint = resolve_vendored_footprint(_FOOTPRINT)
    assert footprint is not None
    assert len(footprint.pads) == 74
    assert {pad.id for pad in footprint.pads} == set(_QIAA_PACKAGE_PIN_MAP)
    assert next(pad for pad in footprint.pads if pad.id == "EP").size == (4.85, 4.85)
    assert all(pad.size == (0.25, 0.25) for pad in footprint.pads if pad.id != "EP")

    source = FootprintSourceProvenance(
        source_type=FootprintSourceType.VENDORED,
        source_name="KiCad official Nordic aQFN73 footprint",
        source_path=f"data/footprints/vendor/{_FOOTPRINT_FILE}",
        source_sha256=_FOOTPRINT_SHA256,
        attribution="data/footprints/vendor/ATTRIBUTION.md",
    )
    proof = build_footprint_proof(
        "aQFN-73-1EP",
        footprint,
        footprint_name=_FOOTPRINT,
        source=source,
        expected_pin_count=74,
        pin_map={pin_id: pin_id for pin_id in _QIAA_PACKAGE_PIN_MAP},
    )
    validation = validate_footprint_proof(proof, expected_physical_pins=set(_QIAA_PACKAGE_PIN_MAP))
    policy = validate_risky_package_policy(proof)

    assert validation.blocked is True
    assert {item.code for item in validation.diagnostics} == {"missing-pin1-evidence"}
    assert proof.pin_count == 74
    assert proof.pad_count == 74
    assert policy.risky is True
    assert policy.family == "AQFN"
    assert policy.blocked is True
    assert {item.code for item in policy.diagnostics} == {"unreviewed-risky-package", "risky-package-missing-pin1"}


def test_nrf52840_footprint_attribution_pins_current_kicad_revision() -> None:
    text = Path("data/footprints/vendor/ATTRIBUTION.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if f"`{_FOOTPRINT_FILE}`" in line)
    assert _KICAD_REVISION in row
    assert _FOOTPRINT_SHA256 in row


def test_nrf52_runtime_wires_only_normal_supply_and_assignable_gpio() -> None:
    design = Design(meta=DesignMeta(name="nrf52840-candidate-runtime"))
    for net in ("VDD_3V3", "GND", "SDA", "SCL"):
        design.nets[net] = Net(id=net, name=net)

    result = instantiate_mcu(design, "nrf52", ["i2c", "spi"], rail_net="VDD_3V3")
    assert result.realized is True
    assert result.part_id == "nrf52840-qiaa"
    component = design.components[result.ref]
    assert component.mpn == "nRF52840-QIAA-F-R7"
    assert component.package_pin_map == _QIAA_PACKAGE_PIN_MAP

    assigned_interface_pins = {item.pin for item in result.assignments if ":" in item.function}
    assert assigned_interface_pins <= _GPIO_NAMES
    rail_pins = {node.pin_name for node in design.nets["VDD_3V3"].nodes if node.component_ref == result.ref}
    ground_pins = {node.pin_name for node in design.nets["GND"].nodes if node.component_ref == result.ref}
    assert rail_pins == {"VDD"}
    assert ground_pins == {"VSS"}
    for forbidden in ("VDDH", "VBUS", "DEC1", "DEC2", "DEC3", "DEC4", "DEC6", "DCC", "DCCH"):
        assert forbidden not in rail_pins
        assert forbidden not in ground_pins


def test_library_expansion_no_longer_regenerates_nrnd_nrf52840_r7_record() -> None:
    from scripts.generate_library_expansion import collect_all_parts

    generated_ids = {part_id for _category, part_id, _data in collect_all_parts()}
    assert "nrf52840-qiaa-r7" not in generated_ids
