"""Tests for the regulatory compliance pre-check."""

from __future__ import annotations

import pytest

from zaptrace.analysis.compliance import compliance_checklist, product_class_profile
from zaptrace.synthesis.requirements import parse_requirements


def _standards(req_text: str) -> set[str]:
    items = compliance_checklist(parse_requirements(req_text))
    return {item.standard for item in items}


def test_baseline_always_includes_rohs_reach_emc() -> None:
    standards = _standards("a simple LED blinker, 5V")
    assert "EU RoHS 2011/65/EU" in standards
    assert "EU REACH (SVHC)" in standards
    assert "EU EMC Directive 2014/30/EU" in standards
    # nothing wireless / battery / high-voltage
    assert "EU RED 2014/53/EU" not in standards
    assert "EU Battery Regulation 2023/1542" not in standards


def test_wireless_triggers_red_and_fcc() -> None:
    standards = _standards("ESP32 BLE sensor, 3.3V")
    assert "EU RED 2014/53/EU" in standards
    assert "FCC Part 15" in standards


def test_battery_triggers_battery_regulation() -> None:
    standards = _standards("Li-ion powered logger, 3.3V")
    assert "EU Battery Regulation 2023/1542" in standards


def test_low_voltage_rail_does_not_trigger_lvd() -> None:
    standards = _standards("3.3V and 5V board")
    assert "EU Low Voltage Directive 2014/35/EU" not in standards


def test_high_voltage_rail_triggers_lvd() -> None:
    standards = _standards("48V PoE powered device with 5V rail")
    assert "EU Low Voltage Directive 2014/35/EU" not in standards  # 48V < 50V
    standards_high = _standards("60V industrial supply")
    assert "EU Low Voltage Directive 2014/35/EU" in standards_high


def test_items_are_ordered_and_serializable() -> None:
    items = compliance_checklist(parse_requirements("ESP32 WiFi node, Li-ion, 3.3V"))
    # baseline three come first, deterministic order
    assert items[0].standard == "EU RoHS 2011/65/EU"
    data = items[0].to_dict()
    assert set(data) == {"standard", "category", "applies_because", "action"}
    assert all(item.action for item in items)


def test_ukca_always_present() -> None:
    standards = _standards("5V LED controller")
    assert "UKCA 2023 (UK market)" in standards


def test_weee_always_present() -> None:
    standards = _standards("5V LED controller")
    assert "EU WEEE Directive 2012/19/EU" in standards


def test_iec62368_always_present() -> None:
    standards = _standards("microcontroller board 3.3V")
    assert "IEC 62368-1 (safety for AV/IT equipment)" in standards


def test_industrial_env_triggers_iec61000_4() -> None:
    standards = _standards("industrial automation controller 24V")
    assert "IEC 61000-4-x (EMC immunity)" in standards


def test_non_industrial_does_not_trigger_iec61000_4() -> None:
    standards = _standards("consumer BLE device 3.3V")
    assert "IEC 61000-4-x (EMC immunity)" not in standards


class TestProductClassProfile:
    def test_consumer_profile(self) -> None:
        profile = product_class_profile("consumer")
        assert profile.product_class == "consumer"
        assert "EU RoHS 2011/65/EU" in profile.required_standards
        assert "FCC Part 15 (US)" in profile.required_standards
        assert "EU" in profile.primary_markets

    def test_industrial_profile(self) -> None:
        profile = product_class_profile("industrial")
        assert profile.product_class == "industrial"
        assert any("61000" in s for s in profile.required_standards)

    def test_wireless_profile(self) -> None:
        profile = product_class_profile("wireless")
        assert any("RED" in s for s in profile.required_standards)
        assert any("FCC" in s for s in profile.required_standards)

    def test_battery_profile(self) -> None:
        profile = product_class_profile("battery")
        assert any("UN 38.3" in s for s in profile.required_standards)
        assert any("IEC 62133" in s for s in profile.required_standards)

    def test_case_insensitive(self) -> None:
        assert product_class_profile("CONSUMER").product_class == "consumer"
        assert product_class_profile("Wireless").product_class == "wireless"

    def test_unknown_class_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown product class"):
            product_class_profile("underwater")

    def test_to_dict(self) -> None:
        d = product_class_profile("consumer").to_dict()
        assert set(d) == {"product_class", "primary_markets", "required_standards", "notes"}
