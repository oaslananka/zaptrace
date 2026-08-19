"""Tests for differential pair routing."""

from __future__ import annotations

import math

from zaptrace.algo.diff_pair import (
    DiffPairRouter,
    _add_meanders,
    _dedupe_vertices,
    _design_for_net,
    _find_diff_pairs,
    _pair_candidate_for_pattern,
    _parallel_offset,
    _path_length,
    _traces_to_vertices,
    _vertex_direction,
)
from zaptrace.core.models import (
    BoardConfig,
    Component,
    Design,
    DesignMeta,
    Net,
    NetNode,
    TraceSegment,
)


def _design_with_diff_pair() -> Design:
    """Create a design with a USB differential pair."""
    return Design(
        meta=DesignMeta(name="test_diff"),
        board=BoardConfig(width_mm=50, height_mm=40),
        components={
            "u1": Component(
                id="u1",
                ref="U1",
                type="mcu",
                pins={"dp": {"name": "DP", "type": "bidirectional"}, "dn": {"name": "DN", "type": "bidirectional"}},
            ),
            "j1": Component(
                id="j1",
                ref="J1",
                type="usb-c",
                pins={"d+": {"name": "D+", "type": "bidirectional"}, "d-": {"name": "D-", "type": "bidirectional"}},
            ),
        },
        nets={
            "n1": Net(
                id="n1",
                name="USB_DP",
                nodes=[
                    NetNode(component_ref="U1", pin_name="dp"),
                    NetNode(component_ref="J1", pin_name="d+"),
                ],
            ),
            "n2": Net(
                id="n2",
                name="USB_DN",
                nodes=[
                    NetNode(component_ref="U1", pin_name="dn"),
                    NetNode(component_ref="J1", pin_name="d-"),
                ],
            ),
        },
    )


def _design_no_diff() -> Design:
    """Design with no differential pairs."""
    return Design(
        meta=DesignMeta(name="no_diff"),
        components={
            "r1": Component(id="r1", ref="R1", type="resistor", pins={"p1": {"name": "1", "type": "passive"}}),
        },
        nets={
            "n1": Net(
                id="n1",
                name="NET1",
                nodes=[
                    NetNode(component_ref="R1", pin_name="p1"),
                ],
            ),
        },
    )


def _design_single_ended() -> Design:
    """Design with nets that look differential but aren't paired."""
    return Design(
        meta=DesignMeta(name="single"),
        board=BoardConfig(width_mm=20, height_mm=20),
        components={
            "r1": Component(id="r1", ref="R1", type="resistor", pins={"p1": {"name": "1", "type": "passive"}}),
        },
        nets={
            "n1": Net(
                id="n1",
                name="VCC",
                nodes=[
                    NetNode(component_ref="R1", pin_name="p1"),
                ],
            ),
        },
    )


# ---------------------------------------------------------------------------
# Pair identification
# ---------------------------------------------------------------------------


class TestFindDiffPairs:
    def test_finds_usb_pair(self) -> None:
        pairs = _find_diff_pairs(_design_with_diff_pair())
        assert len(pairs) == 1
        pos, neg = pairs[0]
        assert {pos, neg} == {"n1", "n2"}

    def test_no_diff_pairs(self) -> None:
        assert _find_diff_pairs(_design_no_diff()) == []

    def test_no_pairs_single(self) -> None:
        assert _find_diff_pairs(_design_single_ended()) == []

    def test_negative_suffix_candidate_is_ordered_positive_first(self) -> None:
        design = _design_with_diff_pair()
        assert _pair_candidate_for_pattern(design, "n2", "USB_DN", set(), "_DP", "_DN") == ("n1", "n2")

    def test_used_partner_is_not_reused(self) -> None:
        design = _design_with_diff_pair()
        assert _pair_candidate_for_pattern(design, "n1", "USB_DP", {"n2"}, "_DP", "_DN") is None


# ---------------------------------------------------------------------------
# Parallel offset
# ---------------------------------------------------------------------------


class TestParallelOffset:
    def test_horizontal_line_offset_up(self) -> None:
        verts = [(0.0, 0.0), (10.0, 0.0)]
        off = _parallel_offset(verts, 1.0)
        assert len(off) == 2
        # direction (10,0), CCW perp = (-0, 1) = (0,1)
        # offset = (0 + 0*1, 0 + 1*1) = (0, 1)
        assert abs(off[0][1] - 1.0) < 0.01

    def test_horizontal_offset(self) -> None:
        verts = [(0.0, 0.0), (10.0, 0.0)]
        off = _parallel_offset(verts, -1.0)
        # Negative offset = right side of forward direction
        # nx = 0, ny = 1, offset -1: (0 + 0*(-1), 0 + 1*(-1)) = (0, -1)
        assert abs(off[0][1] - (-1.0)) < 0.01

    def test_vertical_line(self) -> None:
        verts = [(0.0, 0.0), (0.0, 10.0)]
        off = _parallel_offset(verts, 1.0)
        assert len(off) == 2
        # direction = (0, 10), CCW perp = (-10, 0), normalized = (-1, 0)
        # offset = verts[i] + (-1, 0)*1 = (verts[i][0]-1, verts[i][1])
        assert abs(off[0][0] - (-1.0)) < 0.01

    def test_45_degree(self) -> None:
        verts = [(0.0, 0.0), (10.0, 10.0)]
        off = _parallel_offset(verts, 1.0)
        assert len(off) == 2
        # Perpendicular to (1,1): (-1, 1) normalized = (-0.707, 0.707)
        assert abs(abs(off[0][0]) - 0.707) < 0.01

    def test_single_vertex(self) -> None:
        assert _parallel_offset([(0.0, 0.0)], 1.0) == [(0.0, 0.0)]

    def test_duplicate_corner_direction_collapses(self) -> None:
        verts = [(0.0, 0.0), (0.0, 0.0), (10.0, 0.0)]
        assert _vertex_direction(verts, 1) == (1.0, 0.0)
        offset = _parallel_offset(verts, 1.0)
        assert len(offset) == len(verts)

    def test_reversing_corner_uses_previous_offset(self) -> None:
        verts = [(0.0, 0.0), (10.0, 0.0), (0.0, 0.0)]
        offset = _parallel_offset(verts, 1.0)
        assert offset[1] == offset[0]

    def test_three_vertices_corner(self) -> None:
        """L-shaped path."""
        verts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
        off = _parallel_offset(verts, 1.0)
        assert len(off) == 3
        # First vertex: direction (10,0), perp (0,1), offset (0,1)*1.0 = (0,1)
        assert abs(off[0][1] - 1.0) < 0.01
        # Last vertex: direction (0,10), perp (-1,0), offset (-1,0)*1.0 = (-1,0)
        assert abs(off[-1][0] - 9.0) < 0.01


# ---------------------------------------------------------------------------
# Length matching
# ---------------------------------------------------------------------------


class TestPathLength:
    def test_single_segment(self) -> None:
        assert abs(_path_length([(0, 0), (10, 0)]) - 10.0) < 0.001

    def test_two_segments(self) -> None:
        assert abs(_path_length([(0, 0), (10, 0), (10, 10)]) - 20.0) < 0.001

    def test_empty(self) -> None:
        assert _path_length([]) == 0.0

    def test_single_point(self) -> None:
        assert _path_length([(0, 0)]) == 0.0


class TestDedupeVertices:
    def test_no_dupes(self) -> None:
        v = [(0, 0), (10, 0), (10, 10)]
        assert _dedupe_vertices(v) == v

    def test_consecutive_dupes(self) -> None:
        v = [(0, 0), (5, 0), (5, 0), (10, 0)]
        d = _dedupe_vertices(v)
        assert len(d) == 3

    def test_empty(self) -> None:
        assert _dedupe_vertices([]) == []


class TestTracesToVertices:
    def test_single_trace(self) -> None:
        t = [TraceSegment(layer="F.Cu", start=(0, 0), end=(10, 0), width=0.2, net_id="N1")]
        v = _traces_to_vertices(t)
        assert v == [(0, 0), (10, 0)]

    def test_chain(self) -> None:
        t = [
            TraceSegment(layer="F.Cu", start=(0, 0), end=(10, 0), width=0.2, net_id="N1"),
            TraceSegment(layer="F.Cu", start=(10, 0), end=(10, 10), width=0.2, net_id="N1"),
        ]
        v = _traces_to_vertices(t)
        assert v == [(0, 0), (10, 0), (10, 10)]

    def test_empty(self) -> None:
        assert _traces_to_vertices([]) == []


class TestAddMeanders:
    def test_adds_length(self) -> None:
        verts = [(0, 0), (10, 0)]
        orig_len = _path_length(verts)
        result = _add_meanders(verts, target_length=15.0, amplitude=0.5)
        new_len = _path_length(result)
        assert new_len > orig_len
        assert abs(new_len - 15.0) < 2.0  # approximate

    def test_no_meander_if_already_long_enough(self) -> None:
        verts = [(0, 0), (10, 0)]
        result = _add_meanders(verts, target_length=5.0, amplitude=0.5)
        assert result == verts

    def test_short_segment_no_meander(self) -> None:
        """Very short segments should not be meandered."""
        verts = [(0, 0), (1, 0)]
        result = _add_meanders(verts, target_length=10.0, amplitude=0.5, min_segment_len=3.0)
        assert result == verts

    def test_meander_keeps_endpoints(self) -> None:
        verts = [(0, 0), (10, 0)]
        result = _add_meanders(verts, target_length=15.0, amplitude=0.5)
        assert result[0] == (0, 0)
        assert result[-1] == (10, 0)


# ---------------------------------------------------------------------------
# Design helper
# ---------------------------------------------------------------------------


class TestDesignForNet:
    def test_returns_design_with_one_net(self) -> None:
        d = _design_with_diff_pair()
        sub = _design_for_net(d, "n1")
        assert "n1" in sub.nets
        assert "n2" not in sub.nets

    def test_missing_net(self) -> None:
        d = _design_with_diff_pair()
        sub = _design_for_net(d, "nonexistent")
        assert len(sub.nets) == 0

    def test_meta_preserved(self) -> None:
        d = _design_with_diff_pair()
        sub = _design_for_net(d, "n1")
        assert sub.meta.name == "test_diff"


# ---------------------------------------------------------------------------
# Integration: DiffPairRouter
# ---------------------------------------------------------------------------


class TestDiffPairRouter:
    def test_no_pairs_returns_empty(self) -> None:
        router = DiffPairRouter()
        d = _design_no_diff()
        positions = {}
        result = router.route_diff_pairs(d, positions)
        assert result.net_count == 0

    def test_routes_diff_pair(self) -> None:
        router = DiffPairRouter(gap=0.2, width=0.2)
        d = _design_with_diff_pair()
        positions = {"u1": (5, 20), "j1": (45, 20)}
        result = router.route_diff_pairs(d, positions)
        assert result.net_count == 2
        assert len(result.traces) >= 2  # at least one trace per net

    def test_traces_have_correct_net_ids(self) -> None:
        router = DiffPairRouter(gap=0.2, width=0.2)
        d = _design_with_diff_pair()
        net_ids = set(d.nets)
        result = router.route_diff_pairs(d, positions={"u1": (5, 20), "j1": (45, 20)})
        result_nets = {t.net_id for t in result.traces}
        assert result_nets.issubset(net_ids)

    def test_negative_trace_parallel_to_positive(self) -> None:
        router = DiffPairRouter(gap=0.2, width=0.2)
        d = _design_with_diff_pair()
        positions = {"u1": (5, 20), "j1": (45, 20)}
        result = router.route_diff_pairs(d, positions)
        # Both traces should run roughly parallel
        pos_traces = [t for t in result.traces if t.net_id == "n1"]
        neg_traces = [t for t in result.traces if t.net_id == "n2"]
        assert len(pos_traces) > 0
        assert len(neg_traces) > 0

    def test_meandering_adds_length(self) -> None:
        router = DiffPairRouter(
            gap=0.2,
            width=0.2,
            max_length_mismatch=0.1,  # trigger meandering easily
            meander_amplitude=0.5,
        )
        d = _design_with_diff_pair()
        positions = {"u1": (5, 20), "j1": (45, 20)}
        result = router.route_diff_pairs(d, positions)
        # Both nets should have similar lengths
        pos_len = sum(math.dist(t.start, t.end) for t in result.traces if t.net_id == "n1")
        neg_len = sum(math.dist(t.start, t.end) for t in result.traces if t.net_id == "n2")
        assert abs(pos_len - neg_len) < 5.0  # approximately matched

    def test_standard_configs(self) -> None:
        router = DiffPairRouter(
            **{
                "gap": 0.25,
                "width": 0.2,
                "max_length_mismatch": 0.5,
                "meander_amplitude": 1.0,
            }
        )
        assert router.gap == 0.25
        assert router.width == 0.2
