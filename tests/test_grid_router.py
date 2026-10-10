"""Tests for the A* grid router (45-degree, obstacle-aware, multi-layer)."""

from __future__ import annotations

import math

import pytest

from zaptrace.algo.grid_router import (
    GridPos,
    GridRouter,
    ObstacleMap,
    _octile,
    _simplify_path,
)
from zaptrace.core.models import (
    BoardConfig,
    BoardDefinition,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    Net,
    NetClass,
    NetNode,
    Pad,
    Pin,
    PinType,
    RouteResult,
)
from zaptrace.ee.knowledge import KnowledgeBase

# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def simple_design() -> Design:
    """2 resistors, 1 net (VCC)."""
    d = Design(meta=DesignMeta(name="simple", author="test"))
    d.components["c1"] = Component(id="c1", ref="R1", type="resistor", value="10k")
    d.components["c2"] = Component(id="c2", ref="R2", type="resistor", value="10k")
    d.nets["n1"] = Net(
        id="n1",
        name="VCC",
        nodes=[
            NetNode(component_ref="R1", pin_name="p1"),
            NetNode(component_ref="R2", pin_name="p1"),
        ],
    )
    return d


@pytest.fixture
def three_comp_design() -> Design:
    """3 components, 2 nets."""
    d = Design(meta=DesignMeta(name="three_comp"))
    d.components["c1"] = Component(id="c1", ref="U1", type="mcu")
    d.components["c2"] = Component(id="c2", ref="R1", type="resistor")
    d.components["c3"] = Component(id="c3", ref="C1", type="capacitor")
    d.nets["n1"] = Net(
        id="n1",
        name="VCC",
        nodes=[NetNode(component_ref="U1", pin_name="vcc"), NetNode(component_ref="R1", pin_name="p1")],
    )
    d.nets["n2"] = Net(
        id="n2",
        name="GND",
        nodes=[NetNode(component_ref="U1", pin_name="gnd"), NetNode(component_ref="C1", pin_name="p1")],
    )
    return d


@pytest.fixture
def router() -> GridRouter:
    return GridRouter(resolution_mm=0.5)


# ======================================================================
# MST decomposition tests
# ======================================================================


def test_mst_empty_and_single_point() -> None:
    assert GridRouter._mst([]) == []
    assert GridRouter._mst([(0, 0)]) == []


def test_mst_connects_each_point_once() -> None:
    points = [(0, 0), (2, 0), (10, 0), (10, 1)]
    edges = GridRouter._mst(points)
    assert len(edges) == len(points) - 1
    assert edges[0] == (0, 1)
    assert {target for _, target in edges} == {1, 2, 3}


def test_nearest_mst_edge_uses_manhattan_distance() -> None:
    points = [(0, 0), (8, 0), (1, 2)]
    assert GridRouter._nearest_mst_edge(points, [True, False, False]) == (0, 2)


# ======================================================================
# ObstacleMap tests
# ======================================================================


class TestObstacleMap:
    def test_in_bounds(self) -> None:
        obs = ObstacleMap(100, 80, 2)
        assert obs.in_bounds(GridPos(50, 40, 0))
        assert obs.in_bounds(GridPos(0, 0, 1))
        assert obs.in_bounds(GridPos(99, 79, 1))
        assert not obs.in_bounds(GridPos(100, 40, 0))
        assert not obs.in_bounds(GridPos(50, 80, 0))
        assert not obs.in_bounds(GridPos(0, 0, 2))  # out of layer range

    def test_block_and_free(self) -> None:
        obs = ObstacleMap(10, 10, 1)
        assert obs.is_free(GridPos(5, 5, 0))
        obs.block(GridPos(5, 5, 0))
        assert not obs.is_free(GridPos(5, 5, 0))

    def test_block_rect(self) -> None:
        obs = ObstacleMap(10, 10, 1)
        obs.block_rect(2, 2, 4, 4, 0)
        assert not obs.is_free(GridPos(2, 2, 0))
        assert not obs.is_free(GridPos(4, 4, 0))
        assert obs.is_free(GridPos(1, 1, 0))
        assert obs.is_free(GridPos(5, 5, 0))

    def test_block_rect_clips_boundary(self) -> None:
        obs = ObstacleMap(10, 10, 1)
        # No crash for out-of-bounds
        obs.block_rect(-2, -2, 15, 15, 0)

    def test_dilate(self) -> None:
        obs = ObstacleMap(10, 10, 1)
        obs.block(GridPos(5, 5, 0))
        obs.dilate(1)
        # Center should still be blocked
        assert not obs.is_free(GridPos(5, 5, 0))
        # Adjacent should be blocked
        assert not obs.is_free(GridPos(4, 5, 0))
        assert not obs.is_free(GridPos(5, 4, 0))
        assert not obs.is_free(GridPos(6, 5, 0))
        assert not obs.is_free(GridPos(5, 6, 0))
        # Far should be free
        assert obs.is_free(GridPos(3, 5, 0))

    def test_dilate_zero_does_nothing(self) -> None:
        obs = ObstacleMap(10, 10, 1)
        obs.block(GridPos(5, 5, 0))
        obs.dilate(0)
        assert not obs.is_free(GridPos(5, 5, 0))
        assert obs.is_free(GridPos(4, 5, 0))

    def test_line_blocking(self) -> None:
        obs = ObstacleMap(10, 10, 1)
        obs.block_line(GridPos(1, 1, 0), GridPos(4, 4, 0))
        for d in range(4):  # (1,1) through (4,4) inclusive
            assert not obs.is_free(GridPos(1 + d, 1 + d, 0))
        # (5,5) is past the end — should be free
        assert obs.is_free(GridPos(5, 5, 0))

    def test_line_blocking_with_radius(self) -> None:
        obs = ObstacleMap(10, 10, 1)
        obs.block_line(GridPos(1, 1, 0), GridPos(1, 4, 0), radius=1)
        # The line cells and their radius-1 neighbors should be blocked
        assert not obs.is_free(GridPos(1, 2, 0))
        assert not obs.is_free(GridPos(0, 2, 0))  # radius neighbor
        assert not obs.is_free(GridPos(2, 2, 0))  # radius neighbor

    def test_multi_layer(self) -> None:
        obs = ObstacleMap(10, 10, 3)
        obs.block(GridPos(5, 5, 1))
        assert obs.is_free(GridPos(5, 5, 0))
        assert not obs.is_free(GridPos(5, 5, 1))
        assert obs.is_free(GridPos(5, 5, 2))


# ======================================================================
# Octile heuristic
# ======================================================================


class TestOctile:
    def test_zero_distance(self) -> None:
        assert _octile(GridPos(5, 5, 0), GridPos(5, 5, 0)) == 0.0

    def test_cardinal_distance(self) -> None:
        d = _octile(GridPos(0, 0, 0), GridPos(10, 0, 0))
        assert d == 10.0

    def test_diagonal_distance(self) -> None:
        d = _octile(GridPos(0, 0, 0), GridPos(5, 5, 0))
        # diag = max(5,5) + (sqrt2-1) * min(5,5) = 5 + 0.414*5 = 7.07
        expected = max(5, 5) + (math.sqrt(2) - 1) * min(5, 5)
        assert d == pytest.approx(expected, rel=1e-6)

    def test_layer_distance(self) -> None:
        d = _octile(GridPos(0, 0, 0), GridPos(0, 0, 2), via_cost=10.0)
        assert d == 20.0  # 2 * 10 = 20


# ======================================================================
# Path simplification
# ======================================================================


class TestSimplifyPath:
    def test_short_path_unchanged(self) -> None:
        p = [GridPos(0, 0), GridPos(10, 10)]
        assert _simplify_path(p) == p

    def test_removes_collinear_horizontal(self) -> None:
        p = [GridPos(0, 0), GridPos(5, 0), GridPos(10, 0)]
        r = _simplify_path(p)
        assert r == [GridPos(0, 0), GridPos(10, 0)]

    def test_removes_collinear_vertical(self) -> None:
        p = [GridPos(5, 0), GridPos(5, 5), GridPos(5, 10)]
        r = _simplify_path(p)
        assert r == [GridPos(5, 0), GridPos(5, 10)]

    def test_removes_collinear_diagonal(self) -> None:
        p = [GridPos(0, 0), GridPos(2, 2), GridPos(4, 4)]
        r = _simplify_path(p)
        assert r == [GridPos(0, 0), GridPos(4, 4)]

    def test_preserves_turns(self) -> None:
        p = [GridPos(0, 0), GridPos(5, 0), GridPos(5, 5)]
        r = _simplify_path(p)
        assert len(r) == 3

    def test_multi_layer_preserved(self) -> None:
        p = [GridPos(0, 0, 0), GridPos(5, 0, 0), GridPos(5, 0, 1)]
        r = _simplify_path(p)
        assert len(r) == 3  # layer change should not be collapsed


# ======================================================================
# GridRouter integration tests
# ======================================================================


class TestGridRouterBasic:
    def test_empty_design(self, router: GridRouter) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        result = router.route(d, {})
        assert isinstance(result, RouteResult)
        assert result.net_count == 0
        assert result.routed_net_count == 0
        assert result.total_trace_length_mm == 0.0

    def test_single_net_routed(self, router: GridRouter, simple_design: Design) -> None:
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        result = router.route(simple_design, positions)
        assert result.routed_net_count >= 1
        assert result.traces is not None
        assert len(result.traces) > 0

    def test_returns_route_result(self, router: GridRouter, simple_design: Design) -> None:
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        result = router.route(simple_design, positions)
        assert isinstance(result, RouteResult)
        assert result.net_count >= 1

    def test_trace_net_ids(self, router: GridRouter, simple_design: Design) -> None:
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        result = router.route(simple_design, positions)
        for t in result.traces:
            assert t.net_id == "n1"

    def test_trace_width_from_net_class(
        self,
        router: GridRouter,
        simple_design: Design,
    ) -> None:
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        result = router.route(simple_design, positions)
        # VCC should be POWER_MED → 0.5 mm
        assert all(t.width == 0.5 for t in result.traces)

    def test_total_length_positive(
        self,
        router: GridRouter,
        simple_design: Design,
    ) -> None:
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        result = router.route(simple_design, positions)
        assert result.total_trace_length_mm > 0

    def test_pad_aware_routing_uses_escape_points_not_component_centres(self) -> None:
        """Matched pads should move route endpoints to footprint escape points."""
        d = Design(meta=DesignMeta(name="pad_escape"), board=BoardConfig(width_mm=60, height_mm=30))
        fp = FootprintDef(
            courtyard=(4.0, 2.0),
            pads=[
                Pad(id="p1", position=(-1.5, 0.0), size=(1.0, 1.0)),
                Pad(id="p2", position=(1.5, 0.0), size=(1.0, 1.0)),
            ],
        )
        d.components["r1"] = Component(id="r1", ref="R1", type="resistor", footprint_def=fp)
        d.components["r2"] = Component(id="r2", ref="R2", type="resistor", footprint_def=fp)
        d.nets["n1"] = Net(
            id="n1",
            name="SIG",
            nodes=[
                NetNode(component_ref="R1", pin_name="p2"),
                NetNode(component_ref="R2", pin_name="p1"),
            ],
        )
        result = GridRouter(resolution_mm=0.25).route(d, {"r1": (10.0, 15.0), "r2": (40.0, 15.0)})
        assert result.routed_net_count == 1
        endpoints = {point for trace in result.traces for point in (trace.start, trace.end)}
        assert (10.0, 15.0) not in endpoints
        assert (40.0, 15.0) not in endpoints
        assert any(x > 11.5 and y == 15.0 for x, y in endpoints)
        assert any(x < 38.5 and y == 15.0 for x, y in endpoints)

    def test_multi_net_routing(
        self,
        router: GridRouter,
        three_comp_design: Design,
    ) -> None:
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0), "c3": (20.0, 60.0)}
        result = router.route(three_comp_design, positions)
        assert result.routed_net_count == 1  # VCC only; GND is left for copper pour
        assert len(result.traces) > 0


class TestGridRouterObstacles:
    def test_avoids_components(self) -> None:
        """Two nets on opposite sides of a component should route around it."""
        d = Design(meta=DesignMeta(name="obstacle"))
        d.components["big"] = Component(id="big", ref="BIG", type="mcu")
        d.components["left"] = Component(id="left", ref="L", type="resistor")
        d.components["right"] = Component(id="right", ref="R", type="resistor")
        d.nets["n1"] = Net(
            id="n1",
            name="NET1",
            nodes=[NetNode(component_ref="L", pin_name="p1"), NetNode(component_ref="R", pin_name="p1")],
        )
        router = GridRouter(resolution_mm=0.5)
        positions = {"big": (50.0, 50.0), "left": (10.0, 50.0), "right": (90.0, 50.0)}
        result = router.route(d, positions)
        # Should route around the big component at (50, 50)
        assert result.routed_net_count == 1
        assert len(result.traces) > 0

    def test_within_board_bounds(self, router: GridRouter, simple_design: Design) -> None:
        """Traces should stay within board boundaries."""
        d = Design(meta=DesignMeta(name="bounded"))
        d.components["c1"] = Component(id="c1", ref="R1", type="resistor")
        d.components["c2"] = Component(id="c2", ref="R2", type="resistor")
        d.nets["n1"] = Net(
            id="n1",
            name="SIG",
            nodes=[NetNode(component_ref="R1", pin_name="p1"), NetNode(component_ref="R2", pin_name="p1")],
        )
        positions = {"c1": (15.0, 15.0), "c2": (85.0, 65.0)}
        result = router.route(d, positions)
        assert result.routed_net_count >= 1
        for t in result.traces:
            x0, y0 = t.start
            x1, y1 = t.end
            assert 0 <= x0 <= 100.0
            assert 0 <= y0 <= 80.0
            assert 0 <= x1 <= 100.0
            assert 0 <= y1 <= 80.0


class TestGridRouterCustomKB:
    def test_custom_trace_width(self, router: GridRouter, simple_design: Design) -> None:
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}
        kb = KnowledgeBase()
        from zaptrace.ee.constraints.net_classes import NetClass, NetClassRule

        kb.set_rule(
            NetClass.POWER_MED,
            NetClassRule(trace_width=0.35, clearance=0.2, max_vias=4, priority=2, description="custom"),
        )
        result = router.route(simple_design, positions, kb=kb)
        assert all(t.width == 0.35 for t in result.traces)

    def test_custom_board_size(self) -> None:
        """Custom board_def size should be respected."""
        d = Design(meta=DesignMeta(name="custom_board"))
        d.components["c1"] = Component(id="c1", ref="R1", type="resistor")
        d.components["c2"] = Component(id="c2", ref="R2", type="resistor")
        d.nets["n1"] = Net(
            id="n1",
            name="NET",
            nodes=[NetNode(component_ref="R1", pin_name="p1"), NetNode(component_ref="R2", pin_name="p1")],
        )
        d.board_def = BoardDefinition(width=50.0, height=40.0, layers=2)

        router = GridRouter(resolution_mm=0.5)
        positions = {"c1": (10.0, 10.0), "c2": (40.0, 30.0)}
        result = router.route(d, positions)
        assert result.routed_net_count == 1


class TestGridRouterResolution:
    def test_finer_resolution_more_detailed(self) -> None:
        d = Design(meta=DesignMeta(name="test"))
        d.components["c1"] = Component(id="c1", ref="R1", type="resistor")
        d.components["c2"] = Component(id="c2", ref="R2", type="resistor")
        d.nets["n1"] = Net(
            id="n1",
            name="NET",
            nodes=[NetNode(component_ref="R1", pin_name="p1"), NetNode(component_ref="R2", pin_name="p1")],
        )
        positions = {"c1": (10.0, 10.0), "c2": (50.0, 30.0)}

        coarse = GridRouter(resolution_mm=1.0).route(d, positions)
        fine = GridRouter(resolution_mm=0.25).route(d, positions)
        assert coarse.routed_net_count == 1
        assert fine.routed_net_count == 1
        # Finer resolution should have more trace segments
        assert len(fine.traces) >= len(coarse.traces)


# ======================================================================
# Path direction / angle validation
# ======================================================================


class TestGridRouterAngles:
    def test_no_strict_90_only(self, router: GridRouter, simple_design: Design) -> None:
        """Grid router should produce 45-degree traces, not just 90-degree."""
        # Place components so a direct diagonal would be shortest
        d = Design(meta=DesignMeta(name="diag"))
        d.components["c1"] = Component(id="c1", ref="R1", type="resistor")
        d.components["c2"] = Component(id="c2", ref="R2", type="resistor")
        d.nets["n1"] = Net(
            id="n1",
            name="SIG",
            nodes=[NetNode(component_ref="R1", pin_name="p1"), NetNode(component_ref="R2", pin_name="p1")],
        )
        positions = {"c1": (5.0, 5.0), "c2": (45.0, 45.0)}
        result = router.route(d, positions)
        assert result.routed_net_count == 1

        # Check that at least some segments are diagonal (dx ≈ dy)
        has_diagonal = False
        for t in result.traces:
            dx = abs(t.end[0] - t.start[0])
            dy = abs(t.end[1] - t.start[1])
            if dx > 0.5 and dy > 0.5 and abs(dx - dy) < max(dx, dy) * 0.3:
                has_diagonal = True
                break
        assert has_diagonal, "Expected at least one 45-degree (diagonal) segment"


# ======================================================================
# Phase 3.4: Component body blocking + layer-aware routing
# ======================================================================


class TestComponentBlocking:
    """GridRouter._block_components prevents traces through component bodies."""

    def _make_router(self) -> GridRouter:
        return GridRouter(resolution_mm=0.5)  # simplified grid for deterministic blocking

    def test_blocks_with_footprint_def(self) -> None:
        """Components with footprint_def have their bodies blocked."""
        from zaptrace.core.models import FootprintDef

        d = Design(meta=DesignMeta(name="block_test"))
        d.components["c1"] = Component(
            id="c1",
            ref="Q1",
            type="mcu",
            footprint_def=FootprintDef(courtyard=(6.0, 6.0)),
        )
        obs = ObstacleMap(200, 200, 2)
        positions = {"c1": (50.0, 50.0)}
        router = self._make_router()
        router._block_components(obs, d, positions, resolution=0.5)
        # Grid position (100, 100) = 50mm / 0.5mm — centre of component, should be blocked
        assert not obs.is_free(GridPos(100, 100, 0))
        assert not obs.is_free(GridPos(100, 100, 1))

    def test_blocks_with_generated_footprint(self) -> None:
        design = Design(meta=DesignMeta(name="generated_fp"))
        design.components["r1"] = Component(id="r1", ref="R1", type="resistor", footprint="0402")
        obstacles = ObstacleMap(40, 40, 2)

        self._make_router()._block_components(obstacles, design, {"R1": (5.0, 5.0)}, resolution=0.5)

        assert design.components["r1"].footprint_def is not None
        assert not obstacles.is_free(GridPos(10, 10, 0))
        assert not obstacles.is_free(GridPos(10, 10, 1))

    def test_skips_components_without_footprint(self) -> None:
        """Components without footprint_def are not blocked."""
        d = Design(meta=DesignMeta(name="nofp"))
        d.components["c1"] = Component(id="c1", ref="R1", type="resistor")
        obs = ObstacleMap(200, 200, 2)
        positions = {"c1": (50.0, 50.0)}
        router = self._make_router()
        router._block_components(obs, d, positions, resolution=0.5)
        assert obs.is_free(GridPos(100, 100, 0))

    def test_integration_avoids_blocked_ic(self) -> None:
        """Traces route around a component with a real footprint."""
        from zaptrace.algo.grid_router import GridRouter
        from zaptrace.ee.footprints import footprint_qfn

        fp = footprint_qfn("QFN-32")
        assert fp is not None

        d = Design(meta=DesignMeta(name="blocked"), board=BoardConfig(width_mm=100, height_mm=100))
        d.components["ic"] = Component(
            id="ic",
            ref="U1",
            type="mcu",
            footprint_def=fp,
            pins={"p1": Pin(name="IO1", type=PinType.BIDIRECTIONAL), "p2": Pin(name="IO2", type=PinType.BIDIRECTIONAL)},
        )
        d.components["l"] = Component(id="l", ref="R1", type="resistor")
        d.components["r"] = Component(id="r", ref="R2", type="resistor")
        d.nets["n1"] = Net(
            id="n1",
            name="SIG",
            nodes=[NetNode(component_ref="R1", pin_name="p1"), NetNode(component_ref="R2", pin_name="p1")],
        )
        router = GridRouter(resolution_mm=0.5)
        # Place components: IC in centre, resistors on left and right
        positions = {"ic": (50.0, 50.0), "l": (10.0, 50.0), "r": (90.0, 50.0)}
        result = router.route(d, positions)
        assert result.routed_net_count == 1
        # The trace should NOT pass through the IC's centre (47.5–52.5 mm)
        for t in result.traces:
            mid_x = (t.start[0] + t.end[0]) / 2
            mid_y = (t.start[1] + t.end[1]) / 2
            assert not (47.5 <= mid_x <= 52.5 and 47.5 <= mid_y <= 52.5), f"Trace segment passes through IC body: {t}"


class TestLayerAwareRouting:
    """GridRouter._layer_for_net_class assigns layers by net class."""

    def test_power_on_top_layer(self) -> None:
        assert GridRouter._layer_for_net_class(NetClass.POWER_HIGH, 2) == 0
        assert GridRouter._layer_for_net_class(NetClass.POWER_MED, 2) == 0
        assert GridRouter._layer_for_net_class(NetClass.POWER_LOW, 4) == 0

    def test_ground_skipped(self) -> None:
        assert GridRouter._layer_for_net_class(NetClass.GROUND, 2) == -1
        assert GridRouter._layer_for_net_class(NetClass.GROUND, 4) == -1

    def test_analog_on_top(self) -> None:
        assert GridRouter._layer_for_net_class(NetClass.SIGNAL_ANALOG, 2) == 0
        assert GridRouter._layer_for_net_class(NetClass.SIGNAL_ANALOG, 4) == 0

    def test_high_speed_on_inner_for_4layer(self) -> None:
        assert GridRouter._layer_for_net_class(NetClass.SIGNAL_HIGH, 4) == 1
        assert GridRouter._layer_for_net_class(NetClass.RF, 4) == 1

    def test_high_speed_on_bottom_for_2layer(self) -> None:
        assert GridRouter._layer_for_net_class(NetClass.SIGNAL_HIGH, 2) == 1
        assert GridRouter._layer_for_net_class(NetClass.DIFFERENTIAL, 2) == 1

    def test_low_signal_on_bottom(self) -> None:
        assert GridRouter._layer_for_net_class(NetClass.SIGNAL_LOW, 2) == 1
        assert GridRouter._layer_for_net_class(NetClass.SIGNAL_LOW, 4) == 3

    def test_power_net_routed_on_layer0(self) -> None:
        """POWER net should end up on layer_0 after full routing."""
        d = Design(meta=DesignMeta(name="power_layer"), board=BoardConfig(width_mm=50, height_mm=40))
        d.components["c1"] = Component(id="c1", ref="R1", type="resistor")
        d.components["c2"] = Component(id="c2", ref="R2", type="resistor")
        d.nets["n1"] = Net(
            id="n1",
            name="3V3",
            nodes=[NetNode(component_ref="R1", pin_name="p1"), NetNode(component_ref="R2", pin_name="p1")],
        )
        router = GridRouter(resolution_mm=0.25)
        positions = {"c1": (5.0, 20.0), "c2": (45.0, 20.0)}
        result = router.route(d, positions)
        assert result.routed_net_count == 1
        for t in result.traces:
            assert t.layer == "layer_0", f"POWER trace on {t.layer} not layer_0"

    def test_signal_net_routed_on_bottom_layer(self) -> None:
        """SIGNAL_LOW net should end up on bottom layer."""
        d = Design(meta=DesignMeta(name="sig_layer"), board=BoardConfig(width_mm=50, height_mm=40))
        d.components["c1"] = Component(id="c1", ref="R1", type="resistor")
        d.components["c2"] = Component(id="c2", ref="R2", type="resistor")
        d.nets["n1"] = Net(
            id="n1",
            name="I2C_SCL",
            nodes=[NetNode(component_ref="R1", pin_name="p1"), NetNode(component_ref="R2", pin_name="p1")],
        )
        router = GridRouter(resolution_mm=0.25)
        positions = {"c1": (5.0, 20.0), "c2": (45.0, 20.0)}
        result = router.route(d, positions)
        assert result.routed_net_count == 1
        for t in result.traces:
            assert t.layer == "layer_1", f"SIGNAL trace on {t.layer} not layer_1"


class TestEndpointsInCourtyards:
    def test_routes_when_endpoints_sit_inside_component_courtyards(self) -> None:
        """A net endpoint is the component centre, inside its blocked courtyard;
        the router must escape the courtyard (nearest-free) and still route.

        Regression: with a too-small nearest-free radius the A* router returned
        no path for any net whose parts carried a real (large) footprint.
        """
        from zaptrace.core.models import BoardConfig, Component, Design, DesignMeta, Net, NetNode
        from zaptrace.ee.footprints import generate_footprint_for_component

        d = Design(meta=DesignMeta(name="courtyard"), board=BoardConfig(width_mm=60, height_mm=40))
        for cid, ref in (("c1", "U1"), ("c2", "U2")):
            comp = Component(id=cid, ref=ref, type="ic", footprint="LQFP-48")
            comp.footprint_def = generate_footprint_for_component("LQFP-48", "ic")
            d.components[cid] = comp
        d.nets["n1"] = Net(
            id="n1",
            name="SIG",
            nodes=[NetNode(component_ref="U1", pin_name="1"), NetNode(component_ref="U2", pin_name="1")],
        )
        result = GridRouter(resolution_mm=0.25).route(d, {"c1": (15, 20), "c2": (45, 20)})
        assert result.routed_net_count == 1
        assert result.traces


class TestGridRouterRefactorCharacterization:
    def test_astar_preserves_equal_cost_path_order(self) -> None:
        router = GridRouter(resolution_mm=1.0, max_iterations=100)
        obstacles = ObstacleMap(8, 8, 1)

        path = router._astar(obstacles, GridPos(1, 1, 0), GridPos(4, 3, 0))

        assert path == [
            GridPos(1, 1, 0),
            GridPos(2, 2, 0),
            GridPos(3, 3, 0),
            GridPos(4, 3, 0),
        ]

    def test_astar_returns_none_when_no_free_endpoint_exists(self) -> None:
        router = GridRouter(resolution_mm=1.0, max_iterations=100)
        obstacles = ObstacleMap(5, 5, 1)
        obstacles.block_rect(0, 0, 4, 4, 0)

        assert router._astar(obstacles, GridPos(2, 2, 0), GridPos(3, 3, 0)) is None


def test_package_pin_map_resolves_logical_pin_to_physical_pad() -> None:
    component = Component(
        id="u1",
        ref="U1",
        type="mcu",
        pins={},
        package_pin_map={"12": "GPIO0"},
        footprint_def=FootprintDef(
            description="mapped",
            pads=[Pad(id="12", position=(2.0, 3.0), size=(0.5, 0.5))],
            courtyard=(5.0, 5.0),
        ),
    )

    pad = GridRouter._pad_for_pin(component, "GPIO0")

    assert pad is not None
    assert pad.id == "12"
