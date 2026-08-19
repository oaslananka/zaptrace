"""Tests for net routing algorithms."""

from __future__ import annotations

import logging
import math

import pytest

import zaptrace.algo.router as router_mod
from zaptrace.algo.router import _route_net_mst, route_design_smart, route_nets
from zaptrace.core.models import (
    Component,
    Design,
    DesignMeta,
    Net,
    NetNode,
    RouteResult,
    TraceSegment,
)
from zaptrace.ee.constraints.net_classes import NetClass
from zaptrace.ee.knowledge import KnowledgeBase


class TestRouteNetMst:
    def test_less_than_two_points(self) -> None:
        segments = _route_net_mst([(10.0, 10.0)], "test")
        assert segments == []

    def test_two_points(self) -> None:
        segments = _route_net_mst([(10.0, 10.0), (50.0, 30.0)], "test")
        assert len(segments) == 3  # chamfered L-shape: leg + 45-degree chamfer + leg

    def test_three_points(self) -> None:
        segments = _route_net_mst(
            [(10.0, 10.0), (50.0, 30.0), (80.0, 60.0)],
            "test",
        )
        assert len(segments) >= 2

    def test_segments_have_net_name(self) -> None:
        segments = _route_net_mst([(10.0, 10.0), (50.0, 30.0)], "VCC")
        assert all(s.net_name == "VCC" for s in segments)

    def test_power_net_routes_vertical_first(self) -> None:
        segments = _route_net_mst([(10.0, 10.0), (50.0, 30.0)], "VCC_3V3")
        assert (segments[0].x1, segments[0].y1, segments[0].x2, segments[0].y2) == (10.0, 10.0, 10.0, 29.8)

    def test_clock_net_routes_horizontal_first(self) -> None:
        segments = _route_net_mst([(10.0, 10.0), (50.0, 30.0)], "I2C_SCL")
        assert (segments[0].x1, segments[0].y1, segments[0].x2, segments[0].y2) == (10.0, 10.0, 49.8, 10.0)


class TestRouteNets:
    def test_costed_routing_avoids_existing_trace(self) -> None:
        existing = [TraceSegment(layer="F.Cu", start=(1.0, 0.0), end=(9.0, 0.0), width=0.2, net_id="vcc")]
        segments = _route_net_mst(
            [(0.0, 0.0), (10.0, 10.0)],
            "I2C_SCL",
            existing_traces=existing,
            width_mm=0.2,
            net_id="scl",
            layer="F.Cu",
            clearance_mm=0.2,
        )
        assert segments[0].x1 == segments[0].x2

    def _make_design(self) -> Design:
        d = Design(meta=DesignMeta(name="test"))
        d.components["c1"] = Component(id="c1", ref="U1", type="mcu")
        d.components["c2"] = Component(id="c2", ref="U2", type="mcu")
        d.nets["n1"] = Net(
            id="n1",
            name="BUS",
            nodes=[
                NetNode(component_ref="U1", pin_name="pin1"),
                NetNode(component_ref="U2", pin_name="pin1"),
            ],
        )
        return d

    def test_empty_design(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        result = route_nets(d, {})
        assert result.routed_nets == 0
        assert result.coverage_pct == 100.0

    def test_simple_routing(self) -> None:
        d = self._make_design()
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        result = route_nets(d, positions)
        assert result.routed_nets >= 1
        assert result.coverage_pct > 0

    def test_component_reference_positions_override_id_positions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        design = self._make_design()
        positions = {
            "c1": (1.0, 1.0),
            "c2": (2.0, 2.0),
            "U1": (10.0, 10.0),
            "U2": (50.0, 30.0),
        }

        from types import SimpleNamespace

        monkeypatch.setattr(
            router_mod,
            "compute_escape_point",
            lambda _component, _pin_name, position: SimpleNamespace(escape_point=position),
        )
        result = route_nets(design, positions)

        assert result.routed_nets == 1
        assert result.segments[0].x1 == 10.0
        assert result.segments[0].y1 == 10.0

    def test_routing_unrouted_nets(self) -> None:
        d = self._make_design()
        d.nets["n2"] = Net(
            id="n2",
            name="NO_POS",
            nodes=[
                NetNode(component_ref="U1", pin_name="pin1"),
                NetNode(component_ref="MISSING", pin_name="pin1"),
            ],
        )
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        result = route_nets(d, positions)
        # n2 should be unrouted because MISSING has no position
        assert result.total_nets >= 1

    def test_zero_nets_returns_100_pct(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        result = route_nets(d, {})
        assert result.coverage_pct == 100.0


class TestRouteDesignSmart:
    def _design_with_nets(self) -> Design:
        d = Design(meta=DesignMeta(name="test"))
        d.components["c1"] = Component(id="c1", ref="U1", type="mcu")
        d.components["c2"] = Component(id="c2", ref="R1", type="resistor")
        d.nets["n1"] = Net(
            id="n1",
            name="VCC",
            nodes=[
                NetNode(component_ref="U1", pin_name="vcc"),
                NetNode(component_ref="R1", pin_name="p1"),
            ],
        )
        return d

    def test_returns_route_result(self) -> None:
        d = self._design_with_nets()
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        routing, route, _ = route_design_smart(d, positions)
        assert isinstance(route, RouteResult)
        assert route.routed_net_count >= 1

    def test_net_class_aware_trace_width(self) -> None:
        d = self._design_with_nets()
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        _, route, _sc = route_design_smart(d, positions)
        # VCC classified as POWER_MED → trace_width = 0.5
        assert len(route.traces) > 0
        expected = KnowledgeBase().get_rule(NetClass.POWER_MED).trace_width
        assert all(t.width == expected for t in route.traces)

    def test_empty_design(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        routing, route, _ = route_design_smart(d, {})
        assert route.net_count == 0
        assert route.routed_net_count == 0
        assert route.total_trace_length_mm == 0.0
        assert routing.coverage_pct == 100.0

    def test_custom_kb(self) -> None:
        d = self._design_with_nets()
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        kb = KnowledgeBase()
        # Override POWER_MED width to a non-standard value
        from zaptrace.ee.constraints.net_classes import NetClassRule

        kb.set_rule(
            NetClass.POWER_MED,
            NetClassRule(trace_width=0.35, clearance=0.2, max_vias=4, priority=2, description="custom"),
        )
        _, route, _sc = route_design_smart(d, positions, kb=kb)
        assert all(t.width == 0.35 for t in route.traces)

    def test_custom_layer(self) -> None:
        d = self._design_with_nets()
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        _, route, _sc = route_design_smart(d, positions, layer="B.Cu")
        assert route.layers_used == ["B.Cu"]
        assert all(t.layer == "B.Cu" for t in route.traces)

    def test_total_length(self) -> None:
        d = self._design_with_nets()
        positions = {"c1": (0.0, 0.0), "c2": (10.0, 20.0)}
        _, route, _sc = route_design_smart(d, positions)
        expected = round(sum(math.dist(t.start, t.end) for t in route.traces), 3)
        assert route.total_trace_length_mm == expected
        assert expected > 0.0

    def test_no_routable_nets(self) -> None:
        d = self._design_with_nets()
        # Only 1 component has position — no net can route
        positions = {"c1": (10.0, 10.0)}
        routing, route, _ = route_design_smart(d, positions)
        assert route.routed_net_count == 0
        assert route.net_count == 0


class TestRoutingFailureSurfaces:
    """A net that raises during routing must be logged (not swallowed) and marked unrouted."""

    def _design(self) -> Design:
        d = Design(meta=DesignMeta(name="boom"))
        d.components["c1"] = Component(id="c1", ref="U1", type="mcu")
        d.components["c2"] = Component(id="c2", ref="U2", type="mcu")
        d.nets["n1"] = Net(
            id="n1",
            name="BUS",
            nodes=[
                NetNode(component_ref="U1", pin_name="pin1"),
                NetNode(component_ref="U2", pin_name="pin1"),
            ],
        )
        return d

    def test_route_nets_logs_and_marks_unrouted(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def boom(*_a: object, **_k: object) -> list:
            raise RuntimeError("synthetic routing failure")

        monkeypatch.setattr(router_mod, "_route_net_mst", boom)
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        with caplog.at_level(logging.WARNING, logger="zaptrace.algo.router"):
            result = route_nets(self._design(), positions)
        assert "BUS" in result.unrouted_nets
        assert any("Failed to route net" in r.message for r in caplog.records)

    def test_route_design_smart_logs_and_marks_unrouted(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def boom(*_a: object, **_k: object) -> list:
            raise RuntimeError("synthetic routing failure")

        monkeypatch.setattr(router_mod, "_route_net_mst", boom)
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        with caplog.at_level(logging.WARNING, logger="zaptrace.algo.router"):
            _, route, _sc = route_design_smart(self._design(), positions)
        assert route.routed_net_count == 0
        assert any("Failed to route net" in r.message for r in caplog.records)


class TestRoutingRefactorCharacterization:
    def test_equal_candidate_scores_preserve_first_candidate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(router_mod, "_score_route_candidate", lambda *_args, **_kwargs: 1.0)
        candidates = router_mod._route_edge_candidates(0.0, 0.0, 10.0, 10.0, "SIG")

        selected = router_mod._route_edge_costed(
            0.0,
            0.0,
            10.0,
            10.0,
            "SIG",
            existing_traces=[],
            width_mm=0.2,
            net_id="sig",
            layer="F.Cu",
            clearance_mm=0.2,
        )

        assert selected == candidates[0]

    def test_equal_distance_mst_preserves_prim_tie_order(self) -> None:
        segments = _route_net_mst([(0.0, 0.0), (10.0, 0.0), (0.0, 10.0), (10.0, 10.0)], "SIG")

        assert [(segment.x1, segment.y1, segment.x2, segment.y2) for segment in segments] == [
            (0.0, 0.0, 10.0, 0.0),
            (0.0, 0.0, 0.0, 10.0),
            (10.0, 0.0, 10.0, 10.0),
        ]

    def test_right_angle_scoring_preserves_junction_and_internal_filters(self) -> None:
        candidate = [
            router_mod.RouteSegment(0.0, 0.0, 1.0, 0.0, "N"),
            router_mod.RouteSegment(1.0, 0.0, 1.0, 1.0, "N"),
        ]
        existing = [TraceSegment(layer="F.Cu", start=(1.0, 0.0), end=(1.0, 1.0), width=0.2, net_id="n")]

        assert router_mod._candidate_internal_right_angles(candidate) == 1
        assert router_mod._candidate_junction_right_angles(candidate[:1], existing, "n") == 1

        short_candidate = [
            router_mod.RouteSegment(0.0, 0.0, 0.2, 0.0, "N"),
            router_mod.RouteSegment(0.2, 0.0, 0.2, 1.0, "N"),
        ]
        assert router_mod._candidate_internal_right_angles(short_candidate) == 0

    def test_route_design_smart_is_deterministic_for_same_fixture(self) -> None:
        def design() -> Design:
            item = Design(meta=DesignMeta(name="routing-refactor-snapshot"))
            item.components["c1"] = Component(id="c1", ref="U1", type="mcu")
            item.components["c2"] = Component(id="c2", ref="R1", type="resistor")
            item.nets["n1"] = Net(
                id="n1",
                name="VCC",
                nodes=[
                    NetNode(component_ref="U1", pin_name="vcc"),
                    NetNode(component_ref="R1", pin_name="p1"),
                ],
            )
            return item

        first_routing, first_route, first_scorecard = route_design_smart(
            design(), {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        )
        second_routing, second_route, second_scorecard = route_design_smart(
            design(), {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        )

        assert first_routing == second_routing
        assert first_route.model_dump(mode="json") == second_route.model_dump(mode="json")
        assert first_scorecard.to_dict() == second_scorecard.to_dict()
        assert first_route.total_trace_length_mm == 56.03
        assert first_scorecard.to_dict()["pad_type_counts"] == {"unknown": 2}
