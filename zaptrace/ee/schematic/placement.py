"""Auto-placement algorithm for schematic symbols.

Uses a simple force-directed approach with net connectivity guiding
the attraction between related components.  The goal is to minimise
wire crossings and keep connected symbols close together.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict

from zaptrace.core.models import Component, Design

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CANVAS_W = 1200.0
CANVAS_H = 900.0
MARGIN = 60.0
MIN_GAP = 80.0  # minimum gap between component centers
REPULSION = 8000.0  # inter-component repulsion strength
ATTRACTION = 0.01  # net-connectivity attraction strength
CENTER_FORCE = 0.001  # gentle pull towards canvas center
DAMPING = 0.85
MIN_VELOCITY = 0.5
MAX_ITERATIONS = 150
COOL_DOWN = 0.97


# ---------------------------------------------------------------------------
# Force-directed placement
# ---------------------------------------------------------------------------


def _net_connections(design: Design) -> dict[str, set[str]]:
    connections: dict[str, set[str]] = defaultdict(set)
    for net in design.nets.values():
        refs = [node.component_ref for node in net.nodes]
        for ref in refs:
            connections[ref].update(refs)
    return connections


def _initial_force_state(
    comps: list[Component], width: float, height: float
) -> tuple[dict[str, tuple[float, float]], dict[str, tuple[float, float]]]:
    positions: dict[str, tuple[float, float]] = {}
    velocities: dict[str, tuple[float, float]] = {}
    count = len(comps)
    cols = max(1, int(math.ceil(math.sqrt(count * width / height))))
    cell_w = (width - 2 * MARGIN) / cols
    cell_h = max(MIN_GAP, (height - 2 * MARGIN) / max(1, int(math.ceil(count / cols))))
    for index, comp in enumerate(comps):
        col, row = index % cols, index // cols
        positions[comp.id] = (
            MARGIN + col * cell_w + cell_w / 2 + random.uniform(-5, 5),
            MARGIN + row * cell_h + cell_h / 2 + random.uniform(-5, 5),
        )
        velocities[comp.id] = (0.0, 0.0)
    return positions, velocities


def _repulsion_force(
    comp: Component, comps: list[Component], positions: dict[str, tuple[float, float]]
) -> tuple[float, float]:
    cx, cy = positions[comp.id]
    force_x = force_y = 0.0
    for other in comps:
        if other.id == comp.id:
            continue
        ox, oy = positions[other.id]
        dx, dy = cx - ox, cy - oy
        distance = math.hypot(dx, dy) + 1.0
        force_x += (dx / distance) * REPULSION / (distance * distance)
        force_y += (dy / distance) * REPULSION / (distance * distance)
    return force_x, force_y


def _attraction_force(
    comp: Component,
    positions: dict[str, tuple[float, float]],
    connections: dict[str, set[str]],
    ref_to_id: dict[str, str],
) -> tuple[float, float]:
    cx, cy = positions[comp.id]
    force_x = force_y = 0.0
    for ref in connections.get(comp.ref, set()):
        other_id = ref_to_id.get(ref)
        if other_id is None or other_id == comp.id or other_id not in positions:
            continue
        ox, oy = positions[other_id]
        force_x += (ox - cx) * ATTRACTION
        force_y += (oy - cy) * ATTRACTION
    return force_x, force_y


def _boundary_force(x: float, y: float, width: float, height: float) -> tuple[float, float]:
    center_x, center_y = width / 2.0, height / 2.0
    force_x = (center_x - x) * CENTER_FORCE
    force_y = (center_y - y) * CENTER_FORCE
    inner_margin = MARGIN + 20.0
    wall = 3.0
    if x < inner_margin:
        force_x += wall * (inner_margin - x)
    if x > width - inner_margin:
        force_x -= wall * (x - (width - inner_margin))
    if y < inner_margin:
        force_y += wall * (inner_margin - y)
    if y > height - inner_margin:
        force_y -= wall * (y - (height - inner_margin))
    return force_x, force_y


def _step_component(
    comp: Component,
    comps: list[Component],
    positions: dict[str, tuple[float, float]],
    velocities: dict[str, tuple[float, float]],
    connections: dict[str, set[str]],
    ref_to_id: dict[str, str],
    width: float,
    height: float,
    temperature: float,
) -> float:
    cx, cy = positions[comp.id]
    rep_x, rep_y = _repulsion_force(comp, comps, positions)
    att_x, att_y = _attraction_force(comp, positions, connections, ref_to_id)
    bound_x, bound_y = _boundary_force(cx, cy, width, height)
    vx, vy = velocities[comp.id]
    vx = (vx + rep_x + att_x + bound_x) * DAMPING
    vy = (vy + rep_y + att_y + bound_y) * DAMPING
    velocity = math.hypot(vx, vy)
    if velocity > temperature:
        vx, vy = vx / velocity * temperature, vy / velocity * temperature
    velocities[comp.id] = (vx, vy)
    positions[comp.id] = (
        max(MARGIN, min(width - MARGIN, cx + vx)),
        max(MARGIN, min(height - MARGIN, cy + vy)),
    )
    return abs(vx) + abs(vy)


def _run_force_iterations(
    comps: list[Component],
    positions: dict[str, tuple[float, float]],
    velocities: dict[str, tuple[float, float]],
    connections: dict[str, set[str]],
    width: float,
    height: float,
) -> None:
    ref_to_id = {comp.ref: comp.id for comp in comps}
    temperature = max(width, height) / 3.0
    for _ in range(MAX_ITERATIONS):
        movement = sum(
            _step_component(comp, comps, positions, velocities, connections, ref_to_id, width, height, temperature)
            for comp in comps
        )
        temperature *= COOL_DOWN
        if movement < MIN_VELOCITY * len(comps):
            break


def place_schematic(
    design: Design,
    block_list: list[list[str]] | None = None,
    width: float = CANVAS_W,
    height: float = CANVAS_H,
) -> dict[str, tuple[float, float]]:
    """Place all components on a schematic canvas."""
    comps = list(design.components.values())
    if not comps:
        return {}
    if block_list:
        return _block_placement(comps, block_list, width)
    positions, velocities = _initial_force_state(comps, width, height)
    _run_force_iterations(comps, positions, velocities, _net_connections(design), width, height)
    _enforce_min_gap(positions, MIN_GAP)
    return positions


def _enforce_min_gap(
    positions: dict[str, tuple[float, float]],
    min_gap: float,
) -> None:
    """Push apart any components that are too close together."""
    keys = list(positions.keys())
    for _ in range(5):  # multiple passes
        moved = False
        for i, k1 in enumerate(keys):
            x1, y1 = positions[k1]
            for k2 in keys[i + 1 :]:
                x2, y2 = positions[k2]
                dx = x2 - x1
                dy = y2 - y1
                dist = math.hypot(dx, dy)
                if dist < min_gap and dist > 0.01:
                    push = (min_gap - dist) / 2.0
                    nx = dx / dist * push
                    ny = dy / dist * push
                    positions[k1] = (x1 - nx, y1 - ny)
                    positions[k2] = (x2 + nx, y2 + ny)
                    moved = True
        if not moved:
            break


def _block_placement(
    comps: list,
    block_list: list[list[str]],
    width: float,
) -> dict[str, tuple[float, float]]:
    """Place component blocks on a grid, then place components within blocks."""
    comp_map = {c.id: c for c in comps}
    all_ids = {c.id for c in comps}
    placed_ids: set[str] = set()

    result: dict[str, tuple[float, float]] = {}
    block_w = 200.0
    block_h = 150.0
    cols = max(1, int(width / (block_w + MARGIN)))

    for bi, block in enumerate(block_list):
        col = bi % cols
        row = bi // cols
        bx = MARGIN + col * (block_w + MARGIN)
        by = MARGIN + row * (block_h + MARGIN)

        members = [cid for cid in block if cid in comp_map]
        if not members:
            continue
        placed_ids.update(members)

        # Simple grid within block
        per_row = max(1, int(math.sqrt(len(members))))
        for i, cid in enumerate(members):
            px = bx + (i % per_row) * (block_w / per_row) + 20
            py = by + (i // per_row) * 50 + 20
            result[cid] = (px, py)

    # Place remaining ungrouped components
    remaining = [cid for cid in all_ids if cid not in placed_ids]
    for i, cid in enumerate(remaining):
        bi = (i // cols) + len(block_list)
        col = i % cols
        bx = MARGIN + col * (block_w + MARGIN)
        by = MARGIN + bi * (block_h + MARGIN)
        result[cid] = (bx + 20, by + 20)

    return result
