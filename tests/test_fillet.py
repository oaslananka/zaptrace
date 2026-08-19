"""Tests for arc fillet post-processor."""

from __future__ import annotations

import math

from zaptrace.algo.fillet import (
    _approx_arc,
    _fillet_chain,
    _order_chain,
    apply_fillets,
)
from zaptrace.core.models import TraceSegment


def _seg(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    width: float = 0.2,
    net_id: str = "N1",
    layer: str = "F.Cu",
) -> TraceSegment:
    return TraceSegment(layer=layer, start=(x1, y1), end=(x2, y2), width=width, net_id=net_id)


# ---------------------------------------------------------------------------
# Chain ordering
# ---------------------------------------------------------------------------


class TestOrderChain:
    def test_single_segment(self) -> None:
        c = [_seg(0, 0, 10, 0)]
        assert _order_chain(c) == c

    def test_two_segments_ordered(self) -> None:
        c = [_seg(0, 0, 10, 0), _seg(10, 0, 20, 5)]
        o = _order_chain(c)
        assert o == c

    def test_two_segments_reversed(self) -> None:
        c = [_seg(10, 0, 20, 5), _seg(0, 0, 10, 0)]
        o = _order_chain(c)
        assert len(o) == 2
        # They should connect at (10, 0)
        assert (
            o[0].end == (10.0, 0.0) or o[1].start == (10.0, 0.0) or o[1].end == (10.0, 0.0) or o[0].start == (10.0, 0.0)
        )  # noqa: E501

    def test_three_in_chain(self) -> None:
        c = [
            _seg(10, 0, 20, 0),
            _seg(0, 0, 10, 0),
            _seg(20, 0, 30, 0),
        ]
        o = _order_chain(c)
        assert len(o) == 3
        assert o[0].start == (0, 0)
        assert o[-1].end == (30, 0)

    def test_closed_loop_uses_first_segment_as_start(self) -> None:
        chain = [
            _seg(0, 0, 10, 0),
            _seg(10, 0, 10, 10),
            _seg(10, 10, 0, 0),
        ]

        ordered = _order_chain(chain)

        assert ordered == chain

    def test_reverses_segment_that_meets_current_end(self) -> None:
        c = [
            _seg(10, 0, 20, 0),
            _seg(30, 0, 20, 0),
            _seg(0, 0, 10, 0),
        ]

        ordered = _order_chain(c)

        assert [segment.start for segment in ordered] == [(30, 0), (20, 0), (10, 0)]
        assert [segment.end for segment in ordered] == [(20, 0), (10, 0), (0, 0)]

    def test_different_net_ids_ignored_in_chain(self) -> None:
        c = [
            _seg(0, 0, 10, 0, net_id="A"),
            _seg(10, 0, 20, 0, net_id="B"),
        ]
        # Chains are built by net, so different net_ids means different groups
        o = _order_chain(c)
        assert len(o) == 2  # no reordering needed


# ---------------------------------------------------------------------------
# Arc approximation
# ---------------------------------------------------------------------------


class TestApproxArc:
    def test_returns_segments(self) -> None:
        segs = _approx_arc(
            center=(5.0, 5.0),
            t1=(5.0, 0.0),
            t2=(10.0, 5.0),
            r=5.0,
            n_segments=4,
            width=0.2,
            net_id="N1",
            layer="F.Cu",
        )
        assert len(segs) >= 2
        for s in segs:
            assert s.net_id == "N1"

    def test_arc_smoothes_90_deg_corner(self) -> None:
        """A 90-degree corner should produce curved segments."""
        # Corner at (10, 10): horizontal incoming, vertical outgoing.
        # Tangent points at 1mm from corner along each segment.
        segs = _approx_arc(
            center=(9.0, 11.0),  # 45° bisector from corner, r*sqrt(2) away
            t1=(9.0, 10.0),  # 1mm back along horizontal (from corner at 10,10)
            t2=(10.0, 11.0),  # 1mm along vertical from corner
            r=1.0,
            n_segments=8,
            width=0.2,
            net_id="N1",
            layer="F.Cu",
        )
        assert len(segs) == 8  # exactly n_segments

    def test_zero_radius_no_segments(self) -> None:
        segs = _approx_arc(
            center=(0, 0),
            t1=(1, 0),
            t2=(0, 1),
            r=0,  # noqa: E741
            n_segments=4,
            width=0.2,
            net_id="N1",
            layer="F.Cu",
        )
        assert len(segs) == 0


# ---------------------------------------------------------------------------
# Fillet chain
# ---------------------------------------------------------------------------


class TestFilletChain:
    def test_empty_chain(self) -> None:
        assert _fillet_chain([]) == []

    def test_single_segment_no_change(self) -> None:
        c = [_seg(0, 0, 10, 0)]
        r = _fillet_chain(c)
        assert len(r) == 1
        assert r[0] == c[0]

    def test_two_segments_no_corner(self) -> None:
        """Disconnected segments should remain unchanged."""
        c = [_seg(0, 0, 10, 0), _seg(20, 0, 30, 0)]
        r = _fillet_chain(c)
        assert len(r) == 2

    def test_90_degree_corner_filleted(self) -> None:
        """Horizontal then vertical at (10, 0)."""
        c = [
            _seg(0, 0, 10, 0, width=0.2),
            _seg(10, 0, 10, 10, width=0.2),
        ]
        r = _fillet_chain(c, default_radius=0.5, segments_per_arc=6)
        # Should produce: shortened horizontal + arc segments + shortened vertical
        assert len(r) >= 3
        # First segment should be shortened (not reaching corner)
        assert r[0].end != (10, 0)
        # Last segment should be shortened (not starting at corner)
        assert r[-1].start != (10, 0)
        # Arc segments in the middle
        arc_segs = r[1:-1]
        assert len(arc_segs) > 1
        # All segments should share the same net_id
        for seg in r:
            assert seg.net_id == "N1"

    def test_45_degree_corner(self) -> None:
        """Horizontal to 45° diagonal corner."""
        c = [
            _seg(0, 0, 10, 0, width=0.2),
            _seg(10, 0, 15, 5, width=0.2),
        ]
        r = _fillet_chain(c, default_radius=0.3, segments_per_arc=4)
        assert len(r) >= 3

    def test_different_layers_ignored(self) -> None:
        """Corner between different layers should not be filleted."""
        c = [
            _seg(0, 0, 10, 0, layer="F.Cu"),
            _seg(10, 0, 10, 10, layer="B.Cu"),
        ]
        r = _fillet_chain(c)
        assert len(r) == 2
        assert r[0].end == (10, 0)
        assert r[1].start == (10, 0)

    def test_near_straight_angle_skipped(self) -> None:
        """Nearly straight corner (170°) should not be filleted."""
        c = [
            _seg(0, 0, 10, 0),
            _seg(10, 0, 20, 0.5),  # very slight bend
        ]
        r = _fillet_chain(c, min_angle_deg=10.0)
        # Should remain unchanged for very shallow angles
        assert len(r) == 2

    def test_very_short_segments_skip_fillet(self) -> None:
        """Tiny segments should not cause errors."""
        c = [
            _seg(0, 0, 0.01, 0, width=0.2),
            _seg(0.01, 0, 0.01, 0.01, width=0.2),
        ]
        r = _fillet_chain(c, default_radius=0.5)
        assert len(r) >= 2  # no crash


# ---------------------------------------------------------------------------
# apply_fillets — integration
# ---------------------------------------------------------------------------


class TestApplyFillets:
    def test_empty_list(self) -> None:
        assert apply_fillets([]) == []

    def test_single_net_no_corners(self) -> None:
        traces = [_seg(0, 0, 10, 0)]
        r = apply_fillets(traces)
        assert r == traces

    def test_single_net_with_corner(self) -> None:
        traces = [
            _seg(0, 0, 10, 0),
            _seg(10, 0, 10, 10),
        ]
        r = apply_fillets(traces, default_radius=0.5)
        assert len(r) >= 3

    def test_multiple_nets_independent(self) -> None:
        traces = [
            _seg(0, 0, 10, 0, net_id="A"),
            _seg(10, 0, 10, 10, net_id="A"),
            _seg(0, 10, 10, 10, net_id="B"),
            _seg(10, 10, 10, 20, net_id="B"),
        ]
        r = apply_fillets(traces, default_radius=0.5)
        # Both nets should be filleted independently
        assert len(r) >= 6

    def test_three_segment_chain(self) -> None:
        """Chain: horizontal → vertical → horizontal (Z-shape)."""
        traces = [
            _seg(0, 0, 10, 0),
            _seg(10, 0, 10, 10),
            _seg(10, 10, 20, 10),
        ]
        r = apply_fillets(traces, default_radius=0.5)
        # Two corners → both should be filleted
        assert len(r) >= 5

    def test_trace_width_scales_radius(self) -> None:
        """Wider traces should get larger fillet radii."""
        traces = [
            _seg(0, 0, 10, 0, width=1.0),
            _seg(10, 0, 10, 10, width=1.0),
        ]
        r = apply_fillets(traces, default_radius=5.0, radius_scale=2.0)
        # Arc should have reasonable number of segments
        assert len(r) >= 3

    def test_radius_scale_clamps_to_default(self) -> None:
        """radius_scale=1.0 with width=0.2 → r=0.2"""
        traces = [
            _seg(0, 0, 10, 0, width=0.2),
            _seg(10, 0, 10, 10, width=0.2),
        ]
        r = apply_fillets(traces, default_radius=1.0, radius_scale=1.0)
        assert len(r) >= 3

    def test_no_fillet_below_min_radius(self) -> None:
        """Very small default_radius should skip fillets."""
        traces = [
            _seg(0, 0, 10, 0),
            _seg(10, 0, 10, 10),
        ]
        r = apply_fillets(traces, default_radius=0.01, min_radius=0.05)
        assert len(r) == 2  # unchanged (both segments kept as-is)

    def test_layer_is_preserved(self) -> None:
        traces = [
            _seg(0, 0, 10, 0, layer="B.Cu"),
            _seg(10, 0, 10, 10, layer="B.Cu"),
        ]
        r = apply_fillets(traces, default_radius=0.5)
        for seg in r:
            assert seg.layer == "B.Cu"

    def test_trace_length_after_fillet(self) -> None:
        """Fillet should reduce overall trace length slightly (chord is shorter)."""
        traces = [
            _seg(0, 0, 10, 0),
            _seg(10, 0, 10, 5),
        ]
        orig_len = sum(math.dist(t.start, t.end) for t in traces)
        r = apply_fillets(traces, default_radius=2.0)
        new_len = sum(math.dist(t.start, t.end) for t in r)
        assert new_len < orig_len


class TestFilletRefactorCharacterization:
    def test_right_angle_fillet_preserves_exact_segment_geometry(self) -> None:
        chain = [
            _seg(0, 0, 10, 0, width=0.2),
            _seg(10, 0, 10, 10, width=0.2),
        ]

        result = _fillet_chain(chain, default_radius=0.5, segments_per_arc=4)

        assert [(segment.start, segment.end) for segment in result] == [
            ((0.0, 0.0), (9.5, 0.0)),
            ((9.5, 0.0), (9.691, 0.038)),
            ((9.691, 0.038), (9.854, 0.146)),
            ((9.854, 0.146), (9.962, 0.309)),
            ((9.962, 0.309), (10.0, 0.5)),
            ((10.0, 0.5000000000000001), (10.0, 10.0)),
        ]

    def test_layer_discontinuity_preserves_original_segments(self) -> None:
        chain = [
            _seg(0, 0, 10, 0, layer="F.Cu"),
            _seg(10, 0, 10, 10, layer="B.Cu"),
        ]

        assert _fillet_chain(chain) == chain
