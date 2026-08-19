from __future__ import annotations

from zaptrace.analysis.rail_current import RailBudgetStatus, build_rail_current_budget_report
from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode, NetType, Pin, PinType


def _rail_design(*, load_a: float | None = 0.15, source_a: float = 0.5) -> Design:
    regulator = Component(
        id="reg",
        ref="U1",
        type="buck regulator",
        value="TLV62569",
        current_rating=source_a,
        pins={
            "VIN": Pin(name="VIN", type=PinType.POWER, net="vin"),
            "VOUT": Pin(name="VOUT", type=PinType.OUTPUT, net="vdd"),
        },
    )
    mcu_props = {} if load_a is None else {"current_a": load_a}
    mcu = Component(id="mcu", ref="U2", type="mcu", value="STM32", properties=mcu_props)
    sensor = Component(id="sensor", ref="U3", type="sensor", value="50mA")
    return Design(
        meta=DesignMeta(name="rail-budget"),
        components={"reg": regulator, "mcu": mcu, "sensor": sensor},
        nets={
            "vdd": Net(
                id="vdd",
                name="VDD_3V3",
                type=NetType.POWER,
                nodes=[
                    NetNode(component_ref="U1", pin_name="VOUT"),
                    NetNode(component_ref="U2", pin_name="VDD"),
                    NetNode(component_ref="U3", pin_name="VDD"),
                ],
            )
        },
    )


def test_rail_current_budget_passes_with_margin() -> None:
    report = build_rail_current_budget_report(_rail_design(load_a=0.15, source_a=0.5))
    rail = report.rails[0]

    assert report.blocked is False
    assert report.human_review_required is False
    assert rail.status == RailBudgetStatus.PASS
    assert rail.source_refs == ["U1"]
    assert rail.source_current_a == 0.5
    assert rail.total_load_current_a == 0.2
    assert rail.margin_a == 0.3
    assert rail.margin_pct == 60.0


def test_rail_current_budget_failure_blocks() -> None:
    report = build_rail_current_budget_report(_rail_design(load_a=0.7, source_a=0.5))
    rail = report.rails[0]

    assert report.blocked is True
    assert report.failure_count == 1
    assert rail.status == RailBudgetStatus.FAIL
    assert rail.total_load_current_a == 0.75
    assert rail.margin_a == -0.25


def test_missing_load_current_metadata_requires_human_review() -> None:
    report = build_rail_current_budget_report(_rail_design(load_a=None, source_a=0.5))
    rail = report.rails[0]

    assert report.blocked is False
    assert report.human_review_required is True
    assert report.missing_metadata_count == 1
    assert rail.status == RailBudgetStatus.HUMAN_REVIEW_REQUIRED
    assert rail.missing_current_refs == ["U2"]


def test_current_parser_accepts_ma_case_variants() -> None:
    from zaptrace.analysis.rail_current import _parse_current

    assert _parse_current("250mA") == 0.25
    assert _parse_current("250ma") == 0.25


def test_duplicate_component_nodes_are_counted_once() -> None:
    design = _rail_design(load_a=0.15, source_a=0.5)
    design.nets["vdd"].nodes.append(NetNode(component_ref="U2", pin_name="VDDA"))

    rail = build_rail_current_budget_report(design).rails[0]

    assert [load.component_ref for load in rail.loads] == ["U2", "U3"]
    assert rail.total_load_current_a == 0.2


def test_overcurrent_failure_takes_precedence_over_missing_metadata() -> None:
    design = _rail_design(load_a=None, source_a=0.01)

    rail = build_rail_current_budget_report(design).rails[0]

    assert rail.status == RailBudgetStatus.FAIL
    assert rail.missing_current_refs == ["U2"]
