"""Tests for ERC auto-patch suggestions."""

from __future__ import annotations

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode, NetType, Pin
from zaptrace.erc.models import ERCResult, ERCSeverity, ERCViolation
from zaptrace.erc.patches import _infer_rail_voltage, _patch_for_violation, suggest_patches


def _result(violation: ERCViolation) -> ERCResult:
    return ERCResult(
        violations=[violation],
        design_name="test",
        total_errors=0,
        total_warnings=0,
        total_info=0,
    )


def _design() -> Design:
    return Design(
        meta=DesignMeta(name="test"),
        components={
            "c1": Component(id="c1", ref="R1", type="resistor"),
        },
    )


class TestSuggestPatches:
    def test_no_violations(self) -> None:
        result = ERCResult(violations=[], design_name="test", total_errors=0, total_warnings=0, total_info=0)
        patches = suggest_patches(_design(), result)
        assert patches == []

    def test_erc012_net_remove_patch(self) -> None:
        result = ERCResult(
            violations=[
                ERCViolation(
                    rule_id="ERC012",
                    severity=ERCSeverity.ERROR,
                    message="Duplicate net name",
                    net_refs=["n1"],
                ),
            ],
            design_name="test",
            total_errors=1,
            total_warnings=0,
            total_info=0,
        )
        patches = suggest_patches(_design(), result)
        assert len(patches) == 1
        assert patches[0]["op"] == "remove_net"

    def test_erc001_patch_with_suggestion(self) -> None:
        result = ERCResult(
            violations=[
                ERCViolation(
                    rule_id="ERC001",
                    severity=ERCSeverity.ERROR,
                    message="Unconnected power pin",
                    component_refs=["R1"],
                    patch_suggestion="Connect VCC to power net",
                ),
            ],
            design_name="test",
            total_errors=1,
            total_warnings=0,
            total_info=0,
        )
        patches = suggest_patches(_design(), result)
        assert len(patches) == 1
        assert patches[0]["op"] == "add_note"
        assert patches[0]["note"] == "Connect VCC to power net"


class TestComputedPatches:
    def test_erc008_led_resistor_is_computed(self) -> None:
        design = Design(
            meta=DesignMeta(name="led"),
            components={
                "d1": Component(
                    id="d1",
                    ref="D1",
                    type="LED",
                    pins={
                        "ANODE": Pin(name="ANODE", type="passive"),
                        "CATHODE": Pin(name="CATHODE", type="passive"),
                    },
                ),
            },
            nets={
                "n5v": Net(
                    id="n5v",
                    name="5V",
                    type=NetType.POWER,
                    nodes=[NetNode(component_ref="D1", pin_name="ANODE")],
                ),
            },
        )
        violation = ERCViolation(
            rule_id="ERC008",
            severity=ERCSeverity.ERROR,
            message="LED on power net without series resistor",
            component_refs=["D1"],
            patch_suggestion="Add a current-limiting resistor",
        )
        patches = suggest_patches(design, _result(violation))
        assert len(patches) == 1
        assert patches[0]["op"] == "add_series_resistor"
        assert patches[0]["ref"] == "D1"
        assert patches[0]["value"] == "300"  # (5 - 2.0) / 10mA = 300 ohm
        assert "Vsupply=5V" in patches[0]["assumptions"]

    def test_erc008_falls_back_to_note_when_voltage_unknown(self) -> None:
        design = Design(
            meta=DesignMeta(name="led"),
            components={
                "d1": Component(
                    id="d1",
                    ref="D1",
                    type="LED",
                    pins={"ANODE": Pin(name="ANODE", type="passive")},
                ),
            },
            nets={
                "vx": Net(
                    id="vx",
                    name="VLED",  # no inferable voltage
                    type=NetType.POWER,
                    nodes=[NetNode(component_ref="D1", pin_name="ANODE")],
                ),
            },
        )
        violation = ERCViolation(
            rule_id="ERC008",
            severity=ERCSeverity.ERROR,
            message="LED without series resistor",
            component_refs=["D1"],
            patch_suggestion="Add a current-limiting resistor",
        )
        patches = suggest_patches(design, _result(violation))
        assert len(patches) == 1
        assert patches[0]["op"] == "add_note"

    def test_erc005_i2c_pullup_is_computed(self) -> None:
        design = Design(
            meta=DesignMeta(name="i2c"),
            components={"u1": Component(id="u1", ref="U1", type="mcu", voltage_supply="3.3")},
            nets={
                "sda": Net(
                    id="sda",
                    name="I2C_SDA",
                    nodes=[NetNode(component_ref="U1", pin_name="SDA")],
                ),
            },
        )
        violation = ERCViolation(
            rule_id="ERC005",
            severity=ERCSeverity.WARNING,
            message="I2C net has no pull-up",
            net_refs=["sda"],
            patch_suggestion="Add pull-ups",
        )
        patches = suggest_patches(design, _result(violation))
        assert len(patches) == 1
        assert patches[0]["op"] == "add_pullup"
        assert patches[0]["value"] == "11k"  # 3.3V, 100pF, 100kHz -> 11k
        assert "Vdd=3.3V" in patches[0]["assumptions"]


def test_patch_dispatch_rejects_unsupported_and_incomplete_violations() -> None:
    design = _design()
    unsupported = ERCViolation(rule_id="ERC999", severity=ERCSeverity.INFO, message="unsupported")
    incomplete_remove = ERCViolation(rule_id="ERC012", severity=ERCSeverity.ERROR, message="missing net")
    incomplete_led = ERCViolation(rule_id="ERC008", severity=ERCSeverity.ERROR, message="missing ref")
    incomplete_i2c = ERCViolation(rule_id="ERC005", severity=ERCSeverity.WARNING, message="missing net")

    assert _patch_for_violation(design, unsupported) is None
    assert _patch_for_violation(design, incomplete_remove) is None
    assert _patch_for_violation(design, incomplete_led) is None
    assert _patch_for_violation(design, incomplete_i2c) is None


def test_patch_dispatch_returns_none_without_fallback_suggestions() -> None:
    design = _design()
    missing_power_note = ERCViolation(
        rule_id="ERC001",
        severity=ERCSeverity.ERROR,
        message="power pin",
        component_refs=["R1"],
    )
    missing_led_note = ERCViolation(
        rule_id="ERC008",
        severity=ERCSeverity.ERROR,
        message="LED resistor",
        component_refs=["D1"],
    )

    assert _patch_for_violation(design, missing_power_note) is None
    assert _patch_for_violation(design, missing_led_note) is None


def test_i2c_patch_value_error_uses_optional_fallback_note() -> None:
    design = Design(
        meta=DesignMeta(name="invalid-i2c-rail"),
        components={"u1": Component(id="u1", ref="U1", type="mcu", voltage_supply="-1")},
        nets={
            "sda": Net(
                id="sda",
                name="I2C_SDA",
                nodes=[NetNode(component_ref="U1", pin_name="SDA")],
            )
        },
    )
    with_note = ERCViolation(
        rule_id="ERC005",
        severity=ERCSeverity.WARNING,
        message="I2C net has no pull-up",
        net_refs=["sda"],
        patch_suggestion="Review the rail and add a pull-up",
    )
    without_note = ERCViolation(
        rule_id="ERC005",
        severity=ERCSeverity.WARNING,
        message="I2C net has no pull-up",
        net_refs=["sda"],
    )

    assert _patch_for_violation(design, with_note) == {
        "op": "add_note",
        "net_id": "sda",
        "note": "Review the rail and add a pull-up",
    }
    assert _patch_for_violation(design, without_note) is None


def test_patch_suggestions_preserve_violation_order() -> None:
    result = ERCResult.from_violations(
        [
            ERCViolation(
                rule_id="ERC001",
                severity=ERCSeverity.ERROR,
                message="first",
                component_refs=["R1"],
                patch_suggestion="first note",
            ),
            ERCViolation(
                rule_id="ERC012",
                severity=ERCSeverity.ERROR,
                message="second",
                net_refs=["n1"],
            ),
        ],
        design_name="test",
    )

    assert [patch["op"] for patch in suggest_patches(_design(), result)] == ["add_note", "remove_net"]


def test_patch_rail_voltage_patterns_are_bounded() -> None:
    for name, expected in (("VCC 3.3V", 3.3), ("3V3", 3.3), ("12V", 12.0)):
        design = Design(meta=DesignMeta(name="rail"), nets={"rail": Net(id="rail", name=name)})
        assert _infer_rail_voltage(design, "rail") == expected

    long_name = "9" * 100_000 + ".3V"
    design = Design(meta=DesignMeta(name="rail"), nets={"rail": Net(id="rail", name=long_name)})
    assert _infer_rail_voltage(design, "rail") is None
