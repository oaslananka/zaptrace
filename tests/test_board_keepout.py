"""Physical board profile / drill exclusions for opt-in pad-aware routing."""

from __future__ import annotations

import math

import pytest

from zaptrace.algo.board_keepout import blocked_profile_cells
from zaptrace.algo.grid_router import GridPos, GridRouter
from zaptrace.core.models import (
    BoardConfig,
    BoardDefinition,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    MountingHole,
    Net,
    NetNode,
    Pad,
)


def _profile(
    *,
    outline: list[tuple[float, float]] | None = None,
    cutouts: list[list[tuple[float, float]]] | None = None,
    mounting_holes: list[MountingHole] | None = None,
) -> BoardDefinition:
    return BoardDefinition(
        width=40,
        height=30,
        layers=4,
        outline=outline or [],
        cutouts=cutouts or [],
        mounting_holes=mounting_holes or [],
    )


def test_non_rectangular_outline_excludes_outside_and_board_edge() -> None:
    profile = _profile(outline=[(0, 0), (40, 0), (40, 14), (16, 14), (16, 30), (0, 30)])
    mask = blocked_profile_cells(profile, 0.5, 80, 60)
    assert (60, 48) in mask  # 30x24 is outside the L outline
    assert (32, 28) in mask  # touches the internal concave corner
    assert (1, 1) in mask  # board edge too close for copper
    assert (16, 48) not in mask  # 8x24 safely inside the L
    assert (60, 14) not in mask  # 30x7 safely inside


def test_internal_cutout_and_mounting_holes_exclude_every_layer() -> None:
    profile = _profile(
        cutouts=[[(14, 8), (22, 8), (22, 16), (14, 16)]],
        mounting_holes=[MountingHole(position=(28, 22), diameter=2.0)],
    )
    mask = blocked_profile_cells(profile, 0.5, 80, 60)
    assert (36, 24) in mask  # cutout
    assert (28, 24) in mask  # cutout edge, includes margin
    assert (56, 44) in mask  # drill centre
    assert (56, 47) in mask  # hole wall + copper clearance
    assert (20, 24) not in mask
    assert (68, 44) not in mask

    d = Design(meta=DesignMeta(name="board-drills"), board=BoardConfig(width_mm=40, height_mm=30, layers=4))
    d.board_def = profile
    d.components["p1"] = Component(
        id="p1",
        ref="P1",
        type="connector",
        footprint_def=FootprintDef(pads=[Pad(id="1")]),
    )
    obs = GridRouter(resolution_mm=0.5, pad_aware=True)._prepare_route_context(d, {"p1": (10.0, 10.0)}).obstacles
    for layer in range(4):
        assert not obs.is_free(GridPos(56, 44, layer), net_id="SIG")
        assert not obs.is_free(GridPos(36, 24, layer), net_id="SIG")
    assert not obs.can_place_through_via(GridPos(56, 44), "SIG", radius_cells=2)


def test_valid_pcb_cutout_forces_detour_without_inventing_vias() -> None:
    d = Design(meta=DesignMeta(name="board-cutout-route"), board=BoardConfig(width_mm=40, height_mm=30, layers=2))
    d.board_def = BoardDefinition(
        width=40,
        height=30,
        layers=2,
        cutouts=[[(18, 4), (23, 4), (23, 19), (18, 19)]],
    )
    pos = {"a": (7.0, 10.0), "b": (33.0, 10.0)}
    for key in pos:
        d.components[key] = Component(
            id=key,
            ref=key.upper(),
            type="connector",
            footprint_def=FootprintDef(pads=[Pad(id="1", size=(1.4, 1.2))]),
        )
    d.nets["SIG"] = Net(
        id="SIG",
        name="SIG",
        nodes=[NetNode(component_ref="A", pin_name="1"), NetNode(component_ref="B", pin_name="1")],
    )
    r = GridRouter(resolution_mm=0.5, pad_aware=True).route(d, pos)
    assert (r.routed_net_count, r.net_count) == (1, 1)
    assert not r.vias
    assert len(r.traces) > 1
    assert r.traces[0].start == (7.0, 10.0)
    assert r.traces[-1].end == (33.0, 10.0)
    # The entire chosen detour stays clear of the forbidden cutout.
    mask = blocked_profile_cells(d.board_def, 0.5, 80, 60)
    for segment in r.traces:
        for step in range(101):
            x = segment.start[0] + (segment.end[0] - segment.start[0]) * step / 100
            y = segment.start[1] + (segment.end[1] - segment.start[1]) * step / 100
            # Conservative check covers selected grid samples only.
            assert (round(x / 0.5), round(y / 0.5)) not in mask


@pytest.mark.parametrize(
    "outline",
    [
        [(0, 0), (10, 10), (0, 10), (10, 0)],  # bowtie
        [(0, 0), (10, 0)],  # too few vertices
        [(0, 0), (10, 0), (10, 0), (0, 10)],  # zero-length edge
        [(0, 0), (10, 0), (10, math.inf)],  # nonfinite
    ],
)
def test_invalid_outline_is_rejected(outline: list[tuple[float, float]]) -> None:
    with pytest.raises(ValueError, match="polygon"):
        blocked_profile_cells(_profile(outline=outline), 0.5, 80, 60)


@pytest.mark.parametrize(
    "hole",
    [
        MountingHole(position=(12, 12), diameter=0),
        MountingHole(position=(45, 12), diameter=2),
        MountingHole(position=(12, 12), diameter=math.nan),
    ],
)
def test_bad_mounting_hole_must_not_be_ignored(hole: MountingHole) -> None:
    with pytest.raises(ValueError, match="Mounting drill"):
        blocked_profile_cells(_profile(mounting_holes=[hole]), 0.5, 80, 60)


def test_plated_mounting_hole_without_a_named_net_stays_blocked() -> None:
    p = _profile(mounting_holes=[MountingHole(position=(20, 15), diameter=1.0, plated=True)])
    assert (40, 30) in blocked_profile_cells(p, 0.5, 80, 60)
