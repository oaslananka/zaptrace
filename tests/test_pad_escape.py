"""Tests for zaptrace.algo.pad_escape — pad classification, escape-point
computation, and DRC evidence scorecard."""

from __future__ import annotations

import math

import pytest

import zaptrace.algo.pad_escape as pad_escape_mod
from zaptrace.algo.pad_escape import (
    RouteEvidenceScorecard,
    classify_pad,
    compute_escape_point,
)
from zaptrace.core.models import Component, FootprintDef, Pad

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_comp(
    ref: str = "U1",
    pads: list[Pad] | None = None,
    courtyard: tuple[float, float] = (4.0, 4.0),
    footprint_def: FootprintDef | None = None,
) -> Component:
    if footprint_def is None and pads is not None:
        footprint_def = FootprintDef(pads=pads, courtyard=courtyard)
    return Component(id=ref.lower(), ref=ref, type="ic", footprint_def=footprint_def)


def _smd_pad(pid: str, x: float = 0.0, y: float = 0.0) -> Pad:
    return Pad(id=pid, position=(x, y), drill=None)


def _tht_pad(pid: str, x: float = 0.0, y: float = 0.0, drill: float = 0.8) -> Pad:
    return Pad(id=pid, position=(x, y), drill=drill)


# ---------------------------------------------------------------------------
# classify_pad
# ---------------------------------------------------------------------------


class TestClassifyPad:
    def test_tht_pad_with_drill(self) -> None:
        assert classify_pad(_tht_pad("1")) == "tht"

    def test_smd_pad_no_drill(self) -> None:
        assert classify_pad(_smd_pad("1")) == "smd"

    def test_thermal_pad_by_id(self) -> None:
        pad = _smd_pad("ep")
        assert classify_pad(pad) == "thermal"

    def test_thermal_pad_thermal_id(self) -> None:
        pad = _smd_pad("thermal")
        assert classify_pad(pad) == "thermal"

    def test_gnd_pad_classified_thermal(self) -> None:
        pad = _smd_pad("gnd")
        assert classify_pad(pad) == "thermal"

    def test_connector_pad_j_prefix(self) -> None:
        pad = _smd_pad("J1")
        assert classify_pad(pad) == "connector"

    def test_regular_smd_id_stays_smd(self) -> None:
        pad = _smd_pad("2")
        assert classify_pad(pad) == "smd"


# ---------------------------------------------------------------------------
# compute_escape_point — fallback cases
# ---------------------------------------------------------------------------


class TestComputeEscapePointFallback:
    def test_no_footprint_def_returns_fallback(self) -> None:
        comp = _make_comp(ref="R1", footprint_def=None)
        ep = compute_escape_point(comp, "1", (10.0, 20.0))
        assert ep.is_fallback is True
        assert ep.escape_point != (10.0, 20.0)
        assert ep.pad_center == ep.escape_point
        assert "no footprint_def" in ep.fallback_reason
        assert "synthetic pin escape" in ep.fallback_reason

    def test_pin_not_in_footprint_returns_fallback(self) -> None:
        comp = _make_comp(ref="R1", pads=[_smd_pad("1"), _smd_pad("2")])
        ep = compute_escape_point(comp, "99", (5.0, 5.0))
        assert ep.is_fallback is True
        assert "99" in ep.fallback_reason

    def test_empty_pads_returns_fallback(self) -> None:
        comp = _make_comp(ref="R1", pads=[])
        ep = compute_escape_point(comp, "1", (3.0, 3.0))
        assert ep.is_fallback is True

    def test_no_footprint_def_uses_pin_specific_synthetic_escape(self) -> None:
        comp = _make_comp(ref="J1", footprint_def=None)
        vbus = compute_escape_point(comp, "VBUS", (10.0, 20.0))
        gnd = compute_escape_point(comp, "GND", (10.0, 20.0))

        assert vbus.is_fallback is True
        assert gnd.is_fallback is True
        assert vbus.escape_point != gnd.escape_point
        assert vbus.escape_point != (10.0, 20.0)
        assert gnd.escape_point != (10.0, 20.0)


# ---------------------------------------------------------------------------
# compute_escape_point — happy paths
# ---------------------------------------------------------------------------


class TestComputeEscapePointHappy:
    def test_smd_pad_escape_outside_courtyard(self) -> None:
        # Component centre at (0,0); pad at (1.0, 0.0) inside courtyard (4x4).
        comp = _make_comp(ref="U1", pads=[_smd_pad("1", x=1.0, y=0.0)], courtyard=(4.0, 4.0))
        ep = compute_escape_point(comp, "1", (0.0, 0.0))
        assert ep.is_fallback is False
        assert ep.pad_type == "smd"
        # escape_point should be to the right of comp centre, outside courtyard
        assert ep.escape_point[0] > 2.0  # beyond half-courtyard width 2.0

    def test_tht_pad_escape_type(self) -> None:
        comp = _make_comp(ref="Q1", pads=[_tht_pad("B", x=0.0, y=1.5)], courtyard=(3.0, 3.0))
        ep = compute_escape_point(comp, "B", (10.0, 10.0))
        assert ep.is_fallback is False
        assert ep.pad_type == "tht"

    def test_escape_point_outside_courtyard(self) -> None:
        # Pad is at (0, 0.5) inside a 2x2 courtyard.  Escape must exit courtyard.
        comp = _make_comp(ref="C1", pads=[_smd_pad("1", x=0.0, y=0.5)], courtyard=(2.0, 2.0))
        ep = compute_escape_point(comp, "1", (5.0, 5.0), escape_margin_mm=0.1)
        _cy = 5.0
        half_h = 1.0
        # escape_point must be outside or at edge of courtyard
        ex, ey = ep.escape_point
        # y component of escape should be > cy + half_h (1 mm + some margin)
        cy = 5.0
        assert ey >= cy + half_h

    def test_escape_uses_margin(self) -> None:
        # Larger margin → escape point is farther out.
        comp = _make_comp(ref="R1", pads=[_smd_pad("1", x=1.5, y=0.0)], courtyard=(4.0, 4.0))
        ep_small = compute_escape_point(comp, "1", (0.0, 0.0), escape_margin_mm=0.1)
        ep_large = compute_escape_point(comp, "1", (0.0, 0.0), escape_margin_mm=1.0)
        assert ep_large.escape_point[0] > ep_small.escape_point[0]

    def test_zero_courtyard_returns_pad_center(self) -> None:
        # When courtyard is (0, 0), we just use pad position without projection.
        comp = _make_comp(ref="R1", pads=[_smd_pad("1", x=0.5, y=0.0)], courtyard=(0.0, 0.0))
        ep = compute_escape_point(comp, "1", (10.0, 10.0))
        assert ep.escape_point == pytest.approx((10.5, 10.0))

    def test_numeric_pin_name_matched(self) -> None:
        # Pin name "1" should match pad id "1"
        comp = _make_comp(ref="R1", pads=[_smd_pad("1", x=0.5, y=0.0)])
        ep = compute_escape_point(comp, "1", (0.0, 0.0))
        assert ep.is_fallback is False
        assert ep.pad_id == "1"

    def test_centered_pad_escapes_in_x_direction(self) -> None:
        # Pad at (0, 0) inside a 4x4 courtyard should fall back gracefully.
        comp = _make_comp(ref="U1", pads=[_smd_pad("EP", x=0.0, y=0.0)], courtyard=(4.0, 4.0))
        ep = compute_escape_point(comp, "EP", (0.0, 0.0))
        # EP is a thermal pad, but escape logic should still produce a valid point.
        ex, ey = ep.escape_point
        assert math.isfinite(ex)
        assert math.isfinite(ey)


# ---------------------------------------------------------------------------
# RouteEvidenceScorecard
# ---------------------------------------------------------------------------


class TestRouteEvidenceScorecard:
    def test_initial_state(self) -> None:
        sc = RouteEvidenceScorecard()
        assert sc.total_nets == 0
        assert sc.routed_nets == 0
        assert sc.unrouted_nets == 0
        assert sc.escape_fallback_nets == 0
        assert sc.clearance_debt_nets == 0
        assert sc.failures == []

    def test_record_route_failure(self) -> None:
        sc = RouteEvidenceScorecard()
        sc.record_route_failure("n1", "GND", "MST exception")
        assert sc.unrouted_nets == 1
        assert len(sc.failures) == 1
        f = sc.failures[0]
        assert f.kind == "route_failure"
        assert f.net_id == "n1"
        assert f.detail == "MST exception"

    def test_record_escape_fallback(self) -> None:
        sc = RouteEvidenceScorecard()
        sc.record_escape_fallback("n2", "VCC", ["U1"], ["no footprint_def"])
        assert sc.escape_fallback_nets == 1
        f = sc.failures[0]
        assert f.kind == "escape_failure"
        assert "U1" in f.component_refs

    def test_record_clearance_debt(self) -> None:
        sc = RouteEvidenceScorecard()
        sc.record_clearance_debt("n3", "DIFF_P", "< 0.1 mm")
        assert sc.clearance_debt_nets == 1
        f = sc.failures[0]
        assert f.kind == "clearance_debt"

    def test_increment_pad_type(self) -> None:
        sc = RouteEvidenceScorecard()
        sc.increment_pad_type("smd")
        sc.increment_pad_type("smd")
        sc.increment_pad_type("tht")
        assert sc.pad_type_counts["smd"] == 2
        assert sc.pad_type_counts["tht"] == 1

    def test_to_dict_structure(self) -> None:
        sc = RouteEvidenceScorecard(
            total_nets=5,
            routed_nets=4,
            non_claims=["not fabrication-ready"],
        )
        sc.record_route_failure("n1", "GND")
        d = sc.to_dict()
        assert d["schema_version"] == "1.0"
        assert d["total_nets"] == 5
        assert d["routed_nets"] == 4
        assert len(d["failures"]) == 1
        assert d["non_claims"] == ["not fabrication-ready"]

    def test_multiple_failures_accumulated(self) -> None:
        sc = RouteEvidenceScorecard()
        sc.record_route_failure("n1", "GND")
        sc.record_escape_fallback("n2", "VCC", ["R1"], ["no fp"])
        sc.record_clearance_debt("n3", "CLK")
        assert len(sc.failures) == 3
        assert sc.unrouted_nets == 1
        assert sc.escape_fallback_nets == 1
        assert sc.clearance_debt_nets == 1


# ---------------------------------------------------------------------------
# Integration: route_design_smart returns scorecard
# ---------------------------------------------------------------------------


def _make_simple_design() -> object:
    """Minimal two-component, one-net design for integration tests."""
    from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode

    r1 = Component(id="r1", ref="R1", type="resistor")
    r2 = Component(id="r2", ref="R2", type="resistor")
    net = Net(
        id="net_signal",
        name="SIGNAL",
        nodes=[
            NetNode(component_ref="R1", pin_name="1"),
            NetNode(component_ref="R2", pin_name="1"),
        ],
    )
    return Design(
        meta=DesignMeta(name="test"),
        components={"r1": r1, "r2": r2},
        nets={"net_signal": net},
    )


class TestRouteDesignSmartScorecard:
    """Verify that route_design_smart produces a populated RouteEvidenceScorecard."""

    def test_scorecard_returned(self) -> None:
        from zaptrace.algo.router import route_design_smart

        d = _make_simple_design()
        positions = {"r1": (0.0, 0.0), "r2": (10.0, 0.0)}
        _, _, sc = route_design_smart(d, positions)  # type: ignore[arg-type]
        assert isinstance(sc, RouteEvidenceScorecard)
        assert sc.total_nets >= 0

    def test_scorecard_non_claims_present(self) -> None:
        from zaptrace.algo.router import route_design_smart

        d = _make_simple_design()
        positions = {"r1": (0.0, 0.0), "r2": (10.0, 0.0)}
        _, _, sc = route_design_smart(d, positions)  # type: ignore[arg-type]
        assert len(sc.non_claims) > 0

    def test_scorecard_escape_fallback_recorded_without_footprint(self) -> None:
        """Components without footprint_def should trigger escape_fallback in scorecard."""
        from zaptrace.algo.router import route_design_smart

        d = _make_simple_design()
        positions = {"r1": (0.0, 0.0), "r2": (10.0, 0.0)}
        _, _, sc = route_design_smart(d, positions)  # type: ignore[arg-type]
        # Both components have no footprint_def, so both pads fall back to component centre.
        assert sc.escape_fallback_nets > 0


class TestEscapeOutsideCourtyardCharacterization:
    @pytest.mark.parametrize(
        ("comp_center", "pad_offset", "courtyard_half", "margin", "expected"),
        [
            ((10.0, 10.0), (0.0, 0.0), (2.0, 2.0), 0.25, (12.25, 10.0)),
            ((10.0, 10.0), (3.0, 0.0), (2.0, 2.0), 0.25, (13.25, 10.0)),
            ((10.0, 10.0), (0.0, 0.0), (0.0, 0.0), 0.25, (10.0, 10.0)),
            ((10.0, 10.0), (1.0, 0.0), (2.0, 2.0), 0.25, (12.25, 10.0)),
            ((10.0, 10.0), (0.0, 1.0), (0.0, 2.0), 0.25, (10.0, 11.25)),
        ],
    )
    def test_escape_projection_preserves_branch_outputs(
        self,
        comp_center: tuple[float, float],
        pad_offset: tuple[float, float],
        courtyard_half: tuple[float, float],
        margin: float,
        expected: tuple[float, float],
    ) -> None:
        assert pad_escape_mod._escape_outside_courtyard(
            comp_center, pad_offset, courtyard_half, margin
        ) == pytest.approx(expected)
