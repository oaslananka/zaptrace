"""Tests for component placement algorithms."""

from __future__ import annotations

from zaptrace.algo.placer import (
    _apply_repulsion_forces,
    _apply_spring_forces,
    _build_connections,
    _grid_positions,
    _prefer_less_overlapping_grid,
    _update_positions,
    place_components,
)
from zaptrace.core.models import BoardConfig, Component, Design, DesignMeta, FootprintDef, Net, NetNode


def _design_with_components(n: int) -> Design:
    d = Design(meta=DesignMeta(name="test"))
    for i in range(n):
        d.components[f"c{i}"] = Component(id=f"c{i}", ref=f"R{i}", type="resistor")
    return d


class TestPlaceComponents:
    def test_empty_design(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        positions = place_components(d)
        assert positions == {}

    def test_single_component(self) -> None:
        d = _design_with_components(1)
        positions = place_components(d)
        assert len(positions) == 1
        x, y = positions["c0"]
        assert x > 0
        assert y > 0

    def test_multiple_components(self) -> None:
        d = _design_with_components(5)
        positions = place_components(d)
        assert len(positions) == 5
        # All positions should be within board bounds
        for x, y in positions.values():
            assert 5.0 <= x <= 95.0
            assert 5.0 <= y <= 75.0

    def test_positions_within_board(self) -> None:
        d = _design_with_components(3)
        positions = place_components(d)
        for cid, (x, y) in positions.items():
            assert x >= 5.0, f"{cid} x={x} out of bounds"
            assert y >= 5.0, f"{cid} y={y} out of bounds"
            assert x <= 95.0, f"{cid} x={x} out of bounds"
            assert y <= 75.0, f"{cid} y={y} out of bounds"

    def test_connections_built(self) -> None:
        d = _design_with_components(3)
        d.nets["n1"] = Net(
            id="n1",
            name="NET1",
            nodes=[
                NetNode(component_ref="R0", pin_name="p1"),
                NetNode(component_ref="R1", pin_name="p1"),
            ],
        )
        conns = _build_connections(d)
        assert len(conns) >= 1

    def test_force_directed_refines(self) -> None:
        """Force-directed should move components toward connected ones."""
        d = _design_with_components(4)
        d.nets["n1"] = Net(
            id="n1",
            name="BUS",
            nodes=[
                NetNode(component_ref="R0", pin_name="p1"),
                NetNode(component_ref="R1", pin_name="p1"),
                NetNode(component_ref="R2", pin_name="p1"),
                NetNode(component_ref="R3", pin_name="p1"),
            ],
        )
        positions = place_components(d)
        # All positions should be populated
        assert all(cid in positions for cid in d.components)


def test_high_fanout_connections_use_first_node_as_star_root() -> None:
    design = _design_with_components(6)
    design.nets["bus"] = Net(
        id="bus",
        name="DATA_BUS",
        nodes=[NetNode(component_ref=f"R{i}", pin_name="p1") for i in range(6)],
    )

    assert _build_connections(design) == [(0, 1), (0, 2), (0, 3), (0, 4), (0, 5)]


def test_power_net_connections_are_excluded() -> None:
    design = _design_with_components(2)
    design.nets["vcc"] = Net(
        id="vcc",
        name="VCC_3V3",
        nodes=[
            NetNode(component_ref="R0", pin_name="p1"),
            NetNode(component_ref="R1", pin_name="p1"),
        ],
    )

    assert _build_connections(design) == []


def test_overlap_fallback_rejects_grid_that_places_courtyard_outside_board() -> None:
    design = Design(meta=DesignMeta(name="bounded"), board=BoardConfig(width_mm=40.0, height_mm=40.0))
    for index in range(3):
        design.components[f"c{index}"] = Component(
            id=f"c{index}",
            ref=f"U{index + 1}",
            type="ic",
            footprint_def=FootprintDef(courtyard=(30.0, 10.0)),
        )
    original = {component_id: (20.0, 20.0) for component_id in design.components}

    chosen = _prefer_less_overlapping_grid(design, original)

    assert chosen == original


def test_grid_positions_are_bounded_and_complete() -> None:
    positions = _grid_positions(["a", "b", "c"], 100.0, 80.0, 5.0)
    assert set(positions) == {"a", "b", "c"}
    assert all(5.0 <= x <= 95.0 and 5.0 <= y <= 75.0 for x, y in positions.values())


def test_force_helpers_preserve_equal_and_opposite_forces() -> None:
    component_ids = ["a", "b"]
    positions = {"a": (10.0, 10.0), "b": (15.0, 10.0)}
    spring_forces = {component_id: [0.0, 0.0] for component_id in component_ids}
    _apply_spring_forces(component_ids, [(0, 1)], positions, spring_forces)
    assert spring_forces["a"][0] == -spring_forces["b"][0]
    assert spring_forces["a"][1] == -spring_forces["b"][1]

    repulsion_forces = {component_id: [0.0, 0.0] for component_id in component_ids}
    _apply_repulsion_forces(component_ids, positions, repulsion_forces)
    assert repulsion_forces["a"][0] == -repulsion_forces["b"][0]


def test_spring_force_preserves_legacy_float_operation_order() -> None:
    component_ids = ["a", "b"]
    positions = {
        "a": (-62.19734726462236, -92.49191078830022),
        "b": (-20.456914308845754, 0.7393389740832532),
    }
    forces = {component_id: [0.0, 0.0] for component_id in component_ids}

    _apply_spring_forces(component_ids, [(0, 1)], positions, forces)

    dx = positions["b"][0] - positions["a"][0]
    dy = positions["b"][1] - positions["a"][1]
    distance = max((dx**2 + dy**2) ** 0.5, 0.1)
    expected_x = 0.05 * (distance - 8.0) * (dx / distance)
    expected_y = 0.05 * (distance - 8.0) * (dy / distance)
    assert forces["a"] == [expected_x, expected_y]
    assert forces["b"] == [-expected_x, -expected_y]


def test_position_update_clamps_to_board_margin() -> None:
    positions = {"a": (5.0, 5.0)}
    forces = {"a": [-100.0, 100.0]}
    _update_positions(["a"], positions, forces, width=100.0, height=80.0, margin=5.0)
    assert positions["a"] == (5.0, 75.0)
