"""Tests for design-for-test and bring-up analysis."""

from __future__ import annotations

from zaptrace.analysis.dft import analyze_testability, bringup_checklist, tp_insertion_plan
from zaptrace.core.models import Component, Design, DesignMeta, Net, NetConstraints, NetNode, NetType


def _testable_design() -> Design:
    d = Design(meta=DesignMeta(name="Testable"))
    d.components["u1"] = Component(id="u1", ref="U1", type="mcu")
    d.components["tp1"] = Component(id="tp1", ref="TP1", type="testpoint")
    d.components["j1"] = Component(id="j1", ref="J1", type="swd-header")
    d.nets["vcc"] = Net(
        id="vcc",
        name="VCC",
        type=NetType.POWER,
        nodes=[NetNode(component_ref="U1", pin_name="VCC"), NetNode(component_ref="TP1", pin_name="1")],
    )
    d.nets["swd"] = Net(id="swd", name="SWDIO", nodes=[NetNode(component_ref="U1", pin_name="SWDIO")])
    d.nets["rst"] = Net(id="rst", name="NRST", nodes=[NetNode(component_ref="U1", pin_name="NRST")])
    return d


def _bare_design() -> Design:
    d = Design(meta=DesignMeta(name="Bare"))
    d.components["u1"] = Component(id="u1", ref="U1", type="mcu")
    d.nets["vcc"] = Net(id="vcc", name="VCC", type=NetType.POWER, nodes=[NetNode(component_ref="U1", pin_name="VCC")])
    return d


def test_testable_design_is_well_covered() -> None:
    report = analyze_testability(_testable_design())
    assert report.testpoint_count == 1
    assert report.power_rails_covered == ["VCC"]
    assert report.power_rails_uncovered == []
    assert report.has_debug_access is True
    assert report.has_reset_access is True
    assert report.recommendations == []


def test_bare_design_gets_recommendations() -> None:
    report = analyze_testability(_bare_design())
    assert report.testpoint_count == 0
    assert report.power_rails_uncovered == ["VCC"]
    assert report.has_debug_access is False
    assert report.has_reset_access is False
    # one rec for the uncovered rail, one for debug, one for reset
    assert len(report.recommendations) == 3
    assert any("VCC" in r for r in report.recommendations)
    assert any("debug" in r.lower() for r in report.recommendations)


def test_bringup_checklist_is_tailored() -> None:
    steps = bringup_checklist(_testable_design())
    assert any("short" in s.lower() for s in steps)  # short check before power
    assert any("VCC" in s for s in steps)  # measure the rail
    assert any("debug" in s.lower() for s in steps)
    # the rail-measure step comes after the power-up step
    powerup_idx = next(i for i, s in enumerate(steps) if "power up" in s.lower())
    measure_idx = next(i for i, s in enumerate(steps) if "VCC" in s)
    assert measure_idx > powerup_idx


def test_bringup_checklist_flags_missing_debug() -> None:
    steps = bringup_checklist(_bare_design())
    assert any("no debug access" in s.lower() for s in steps)


def test_report_serializable() -> None:
    data = analyze_testability(_testable_design()).to_dict()
    assert set(data) == {
        "testpoint_count",
        "power_rails_covered",
        "power_rails_uncovered",
        "has_debug_access",
        "has_reset_access",
        "recommendations",
    }


class TestTestpointInsertionPlan:
    def test_bare_design_gets_power_rail_tp(self) -> None:
        plan = tp_insertion_plan(_bare_design())
        nets = [tp.net_name for tp in plan.testpoints]
        assert "VCC" in nets

    def test_testable_design_needs_no_insertions(self) -> None:
        plan = tp_insertion_plan(_testable_design())
        assert len(plan.testpoints) == 0
        assert any("no insertions" in n.lower() for n in plan.notes)

    def test_high_current_net_gets_tp(self) -> None:
        d = Design(meta=DesignMeta(name="HighCurrent"))
        d.components["u1"] = Component(id="u1", ref="U1", type="mcu")
        d.nets["pwr"] = Net(
            id="pwr",
            name="VBAT",
            type=NetType.POWER,
            nodes=[NetNode(component_ref="U1", pin_name="VIN")],
            constraints=NetConstraints(is_high_current=True),
        )
        plan = tp_insertion_plan(d)
        assert any("VBAT" in tp.net_name for tp in plan.testpoints)

    def test_ref_designators_start_at_specified_offset(self) -> None:
        plan = tp_insertion_plan(_bare_design(), tp_ref_start=5)
        assert plan.testpoints[0].tp_ref == "TP5"

    def test_plan_serializable(self) -> None:
        plan = tp_insertion_plan(_bare_design())
        d = plan.to_dict()
        assert "testpoints" in d
        assert "notes" in d
