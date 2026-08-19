from __future__ import annotations

from zaptrace.analysis.regulator_margin import RegulatorMarginStatus, build_regulator_margin_report
from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode, NetType, Pin, PinType


def _ldo_design(*, vin: float = 5.0, load_a: float = 0.1, theta: float = 50.0, missing: bool = False) -> Design:
    props = (
        {}
        if missing
        else {
            "input_voltage_v": vin,
            "output_voltage_v": 3.3,
            "dropout_voltage_v": 0.3,
            "theta_ja_c_per_w": theta,
            "ambient_c": 50.0,
            "junction_max_c": 125.0,
        }
    )
    reg = Component(
        id="reg",
        ref="U1",
        type="ldo regulator",
        value="LDO_3V3",
        current_rating=0.5,
        properties=props,
        pins={
            "IN": Pin(name="IN", type=PinType.POWER, net="vin"),
            "OUT": Pin(name="OUT", type=PinType.OUTPUT, net="vdd"),
        },
    )
    load = Component(id="load", ref="U2", type="mcu", value="MCU", properties={"current_a": load_a})
    return Design(
        meta=DesignMeta(name="reg-margin"),
        components={"reg": reg, "load": load},
        nets={
            "vin": Net(id="vin", name="VBUS", type=NetType.POWER, nodes=[NetNode(component_ref="U1", pin_name="IN")]),
            "vdd": Net(
                id="vdd",
                name="VDD_3V3",
                type=NetType.POWER,
                nodes=[NetNode(component_ref="U1", pin_name="OUT"), NetNode(component_ref="U2", pin_name="VDD")],
            ),
        },
    )


def test_regulator_margin_passes_supported_ldo_profile() -> None:
    report = build_regulator_margin_report(_ldo_design())
    entry = report.regulators[0]

    assert report.blocked is False
    assert report.human_review_required is False
    assert entry.status == RegulatorMarginStatus.PASS
    assert entry.vin_v == 5.0
    assert entry.vout_v == 3.3
    assert entry.iout_a == 0.1
    assert entry.dropout_margin_v == 1.4
    assert entry.power_dissipation_w == 0.17
    assert entry.junction_c == 58.5
    assert entry.thermal_margin_c == 66.5


def test_regulator_margin_blocks_dropout_failure() -> None:
    report = build_regulator_margin_report(_ldo_design(vin=3.4))
    entry = report.regulators[0]

    assert report.blocked is True
    assert report.failure_count == 1
    assert entry.status == RegulatorMarginStatus.FAIL
    assert entry.dropout_margin_v == -0.2


def test_regulator_margin_blocks_thermal_failure() -> None:
    report = build_regulator_margin_report(_ldo_design(vin=12.0, load_a=1.0, theta=80.0))
    entry = report.regulators[0]

    assert report.blocked is True
    assert entry.status == RegulatorMarginStatus.FAIL
    assert entry.thermal_margin_c is not None
    assert entry.thermal_margin_c < 0


def test_regulator_margin_missing_metadata_requires_human_review() -> None:
    report = build_regulator_margin_report(_ldo_design(missing=True))
    entry = report.regulators[0]

    assert report.blocked is False
    assert report.human_review_required is True
    assert entry.status == RegulatorMarginStatus.HUMAN_REVIEW_REQUIRED
    assert "dropout_v" in entry.missing_fields
    assert "theta_ja_c_per_w" in entry.missing_fields
