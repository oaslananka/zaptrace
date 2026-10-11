"""Fail-closed pad-owned layer and via-clearance projection, Issue #35."""

from __future__ import annotations

import math

import pytest

from zaptrace.algo.grid_router import GridPos, GridRouter, ObstacleMap
from zaptrace.algo.pad_copper import copper_layers, pad_cells, rotated_offset
from zaptrace.core.models import (
    BoardConfig,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    LayerSet,
    Net,
    NetNode,
    Pad,
    PadShape,
)


def _board(
    *pads: tuple[str, tuple[float, float], Pad],
    layers: int = 2,
) -> tuple[Design, dict[str, tuple[float, float]]]:
    design = Design(
        meta=DesignMeta(name="pad-masks"),
        board=BoardConfig(
            width_mm=40,
            height_mm=30,
            layers=layers,
        ),
    )
    locations = {}
    for ref, xy, pad in pads:
        design.components[ref] = Component(
            id=ref,
            ref=ref.upper(),
            type="connector",
            footprint_def=FootprintDef(pads=[pad], courtyard=(1.8, 1.8)),
        )
        locations[ref] = xy
    return design, locations


def _net(design: Design, name: str, *refs: str) -> None:
    design.nets[name] = Net(
        id=name,
        name=name,
        nodes=[NetNode(component_ref=ref.upper(), pin_name="1") for ref in refs],
    )


def test_smd_top_only_does_not_reserve_bottom_layer() -> None:
    design, positions = _board(
        (
            "x",
            (12, 12),
            Pad(
                id="1",
                layer=LayerSet.TOP,
                shape=PadShape.RECT,
                size=(2, 1),
            ),
        )
    )
    ctx = GridRouter(resolution_mm=0.5, pad_aware=True)._prepare_route_context(design, positions)
    top, bottom = GridPos(24, 24, 0), GridPos(24, 24, 1)
    assert not ctx.obstacles.is_free(top, net_id="foreign")
    assert ctx.obstacles.is_free(bottom, net_id="foreign")
    assert ctx.obstacles.owner(top) is None
    assert not ctx.obstacles.can_place_through_via(bottom, "foreign", 1)


def test_plated_holes_and_npht_keepouts_span_all_copper_layers() -> None:
    pth = Pad(id="1", drill=0.8, layer=LayerSet.TOP, shape=PadShape.CIRCLE, size=(1.8, 1.8))
    npth = Pad(id="", drill=1.2, plated=False, layer=LayerSet.TOP, shape=PadShape.CIRCLE, size=(1.2, 1.2))
    d, pos = _board(("pth", (12, 12), pth), ("npth", (26, 12), npth), layers=4)
    _net(d, "SIG", "pth")
    router = GridRouter(pad_aware=True, resolution_mm=0.5)
    obs = router._prepare_route_context(d, pos).obstacles
    for layer in range(4):
        assert obs.is_free(GridPos(24, 24, layer), net_id="SIG")
        assert not obs.is_free(GridPos(24, 24, layer), net_id="OTHER")
        assert not obs.is_free(GridPos(52, 24, layer), net_id="SIG")
    assert copper_layers(pth, 4) == (0, 1, 2, 3)
    assert copper_layers(Pad(id="a", layer=LayerSet.INNER), 4) == (1, 2)
    assert not obs.can_place_through_via(GridPos(52, 24), "SIG", 1)


def test_component_rotation_and_local_pad_rotation_both_apply() -> None:
    pad = Pad(id="1", position=(2, 0), rotation=90, shape=PadShape.RECT, size=(3, 1))
    d, pos = _board(("a", (10, 10), pad))
    d.components["a"].properties["rotation"] = 90.0
    ctx = GridRouter(resolution_mm=0.5, pad_aware=True)._prepare_route_context(d, pos)
    assert ctx.rotation_by_ref["A"] == 90.0
    assert ctx.obstacles.is_free(GridPos(20, 16), net_id="foreign") is False
    assert ctx.obstacles.is_free(GridPos(24, 20), net_id="foreign")
    assert rotated_offset(2, 0, 90) == pytest.approx((0, -2))
    # Pad local rotation and footprint rotation follow the native KiCad convention.
    assert (23, 16) in pad_cells(pad, (10, 10), 90, 0.5, 80, 60, 0)
    assert (20, 19) not in pad_cells(pad, (10, 10), 90, 0.5, 80, 60, 0)


def test_top_only_pad_pair_routes_on_top_and_detours_around_foreign_pad() -> None:
    d, pos = _board(
        ("start", (6, 10), Pad(id="1", shape=PadShape.RECT, size=(1.5, 1))),
        ("finish", (30, 10), Pad(id="1", shape=PadShape.RECT, size=(1.5, 1))),
        ("barrier", (18, 10), Pad(id="1", shape=PadShape.RECT, size=(5, 2), rotation=90)),
    )
    _net(d, "SIGNAL_A", "start", "finish")
    _net(d, "SIGNAL_B", "barrier")
    router = GridRouter(pad_aware=True, resolution_mm=0.5)
    result = router.route(d, pos)
    assert result.net_count == 1
    assert result.routed_net_count == 1
    assert result.vias == []
    assert all(t.layer == "layer_0" for t in result.traces)
    assert result.traces[0].start == (6, 10)
    assert result.traces[-1].end == (30, 10)
    assert len(result.traces) > 1
    ctx = router._prepare_route_context(d, pos)
    for seg in result.traces:
        for x, y in [(seg.start[0], seg.start[1]), (seg.end[0], seg.end[1])]:
            p = GridPos(int(round(x * 2)), int(round(y * 2)), 0)
            assert ctx.obstacles.is_free(p, net_id="SIGNAL_A")


def test_pad_mode_fails_closed_when_pad_center_off_grid() -> None:
    d, pos = _board(("a", (10.1, 10), Pad(id="1")), ("b", (20, 10), Pad(id="1")))
    _net(d, "SIG", "a", "b")
    result = GridRouter(pad_aware=True, resolution_mm=0.5).route(d, pos)
    assert result.net_count == 1
    assert result.routed_net_count == 0
    assert result.traces == []


def test_top_bottom_smd_pair_requires_unimplemented_via_and_is_not_counted() -> None:
    d, pos = _board(
        ("top", (8, 10), Pad(id="1", layer=LayerSet.TOP)),
        ("bottom", (26, 10), Pad(id="1", layer=LayerSet.BOTTOM)),
    )
    _net(d, "SIG", "top", "bottom")
    result = GridRouter(pad_aware=True, resolution_mm=0.5).route(d, pos)
    assert result.net_count == 1
    assert result.routed_net_count == 0


def test_overlapping_foreign_pads_fail_closed_and_cannot_be_carved() -> None:
    d, pos = _board(
        ("a", (12, 12), Pad(id="1", size=(2, 2))),
        ("b", (12, 12), Pad(id="1", size=(2, 2))),
    )
    _net(d, "A", "a")
    _net(d, "B", "b")
    obs = GridRouter(pad_aware=True, resolution_mm=0.5)._prepare_route_context(d, pos).obstacles
    center = GridPos(24, 24, 0)
    assert center in obs._pad_conflicts
    for net in ("A", "B"):
        obs.open_for_net(center, net)
        assert not obs.is_free(center, net)
    assert not obs.can_place_through_via(center, "A", 0)


def test_custom_pad_and_unknown_footprint_rejected_not_treated_as_void() -> None:
    d, pos = _board(("a", (12, 12), Pad(id="1", shape=PadShape.CUSTOM)))
    with pytest.raises(ValueError, match="Custom pad"):
        GridRouter(pad_aware=True)._prepare_route_context(d, pos)
    d.components["a"].footprint_def = None
    with pytest.raises(ValueError, match="explicit footprint"):
        GridRouter(pad_aware=True)._prepare_route_context(d, pos)


def test_via_clearance_requires_all_layers_even_if_one_face_open() -> None:
    obs = ObstacleMap(20, 20, 4)
    obs.mark_pad(GridPos(10, 10, 1), "B")
    obs.enforce_static_clearance = True
    assert not obs.can_place_through_via(GridPos(10, 10), "A", 0)
    assert obs.can_place_through_via(GridPos(7, 7), "A", 1)
    obs.block(GridPos(7, 7, 3))
    assert not obs.can_place_through_via(GridPos(7, 7), "A", 1)
    assert not obs.can_place_through_via(GridPos(7, 7), "A", -1)


def test_invalid_pad_geometry_and_rotation_are_fail_closed() -> None:
    bad = Pad(id="1", size=(0, 1))
    with pytest.raises(ValueError, match="positive"):
        pad_cells(bad, (10, 10), 0, 0.25, 100, 100, 0.2)
    with pytest.raises(ValueError, match="finite"):
        pad_cells(Pad(id="1"), (10, 10), math.inf, 0.25, 100, 100, 0.2)
    with pytest.raises(ValueError, match="non-negative"):
        pad_cells(Pad(id="1"), (10, 10), 0, 0.25, 100, 100, -0.2)


def test_missing_logical_pin_pad_is_routable_debt_not_silently_ignored() -> None:
    d, pos = _board(
        ("x", (10, 10), Pad(id="1")),
        ("y", (20, 10), Pad(id="2")),
    )
    _net(d, "SIG", "x", "y")
    assert GridRouter(pad_aware=True, resolution_mm=0.5).route(d, pos).net_count == 1
    result = GridRouter(pad_aware=True, resolution_mm=0.5).route(d, pos)
    assert result.routed_net_count == 0
    assert result.traces == []


def test_foreign_pad_endpoint_is_never_displaced_to_nearest_free_grid_cell() -> None:
    d, pos = _board(
        ("x", (10, 10), Pad(id="1", size=(1.8, 1.8))),
        ("y", (25, 10), Pad(id="1", size=(1.8, 1.8))),
        ("foreign", (10, 10), Pad(id="1", size=(1.8, 1.8))),
    )
    _net(d, "SIG", "x", "y")
    _net(d, "OTHER", "foreign")
    router = GridRouter(pad_aware=True, resolution_mm=0.5)
    result = router.route(d, pos)
    assert result.net_count == 1
    assert result.routed_net_count == 0
    assert result.traces == []


def test_oval_mask_conservatively_reserves_actual_capsule_corners() -> None:
    oval = Pad(id="1", shape=PadShape.OVAL, size=(4.0, 1.0))
    shape = pad_cells(oval, (12, 12), 0, 0.5, 80, 80, 0.1)
    assert (24, 24) in shape
    assert (28, 24) in shape
    assert (24, 28) not in shape
    upright = pad_cells(oval, (12, 12), 90, 0.5, 80, 80, 0.1)
    assert (24, 28) in upright
    assert (28, 24) not in upright


def test_dnp_footprint_remains_a_real_pad_obstacle() -> None:
    d, pos = _board(("x", (10, 10), Pad(id="1", size=(2.0, 2.0))))
    d.components["x"].dnp = True
    obs = GridRouter(pad_aware=True, resolution_mm=0.5)._prepare_route_context(d, pos).obstacles
    assert not obs.is_free(GridPos(20, 20, 0), net_id="OTHER")


def test_bottom_pad_only_blocks_bottom_but_via_is_not_clear() -> None:
    d, pos = _board(("x", (10, 10), Pad(id="1", layer=LayerSet.BOTTOM)))
    _net(d, "BOTTOM_NET", "x")
    obs = GridRouter(pad_aware=True, resolution_mm=0.5)._prepare_route_context(d, pos).obstacles
    at_top = GridPos(20, 20, 0)
    assert obs.is_free(at_top, net_id="OTHER")
    assert not obs.is_free(GridPos(20, 20, 1), net_id="OTHER")
    assert not obs.can_place_through_via(at_top, "OTHER", 1)


def test_non_circular_npth_slot_and_nonfinite_pad_geometry_fail_closed() -> None:
    from zaptrace.algo.pad_copper import finished_hole_cells

    npth_slot = Pad(id="", drill=0.8, plated=False, shape=PadShape.OVAL, size=(1.8, 0.8))
    with pytest.raises(ValueError, match="Non-circular NPTH"):
        finished_hole_cells(npth_slot, (10, 10), 0, 0.5, 80, 80, 0.3)
    with pytest.raises(ValueError, match="finite"):
        pad_cells(Pad(id="1", rotation=float("nan")), (10, 10), 0, 0.5, 80, 80, 0)
    with pytest.raises(ValueError, match="outside"):
        pad_cells(Pad(id="1"), (-3, 10), 0, 0.5, 80, 80, 0)
