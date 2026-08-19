"""Auto-placement algorithm for schematic symbols.

Uses a simple force-directed approach with net connectivity guiding
the attraction between related components.  The goal is to minimise
wire crossings and keep connected symbols close together.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict

from zaptrace.core.models import Design

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


def place_schematic(
    design: Design,
    block_list: list[list[str]] | None = None,
    width: float = CANVAS_W,
    height: float = CANVAS_H,
) -> dict[str, tuple[float, float]]:
    """Place all components on a schematic canvas.

    Returns a dict ``component_id -> (x, y)`` with positions in
    schematic-coordinate space (pixels / arbitrary units).

    Parameters
    ----------
    design:
        The design whose components are to be placed.
    block_list:
        Optional grouping: each inner list holds component IDs that
        should stay close together (sub-circuit grouping).
    width, height:
        Canvas dimensions.
    """
    comps = list(design.components.values())
    if not comps:
        return {}

    if block_list:
        return _block_placement(comps, block_list, width)

    # Build connectivity graph
    net_connections: dict[str, set[str]] = defaultdict(set)
    for net in design.nets.values():
        refs = [n.component_ref for n in net.nodes]
        for r in refs:
            net_connections[r].update(refs)

    # Grid-based initial positions with small jitter
    positions: dict[str, tuple[float, float]] = {}
    velocities: dict[str, tuple[float, float]] = {}
    n = len(comps)
    cols = max(1, int(math.ceil(math.sqrt(n * width / height))))
    cell_w = (width - 2 * MARGIN) / cols
    cell_h = max(MIN_GAP, (height - 2 * MARGIN) / max(1, int(math.ceil(n / cols))))

    for i, comp in enumerate(comps):
        col = i % cols
        row = i // cols
        px = MARGIN + col * cell_w + cell_w / 2 + random.uniform(-5, 5)
        py = MARGIN + row * cell_h + cell_h / 2 + random.uniform(-5, 5)
        positions[comp.id] = (px, py)
        velocities[comp.id] = (0.0, 0.0)

    ref_to_id = {c.ref: c.id for c in comps}
    center_x = width / 2.0
    center_y = height / 2.0
    inner_margin = MARGIN + 20.0

    # Force-directed iteration
    temp = max(width, height) / 3.0

    for _iteration in range(MAX_ITERATIONS):
        total_movement = 0.0

        for comp in comps:
            cid = comp.id
            fx, fy = 0.0, 0.0
            cx, cy = positions[cid]

            # Repulsion from all other components (inverse-square)
            for other in comps:
                if other.id == cid:
                    continue
                ox, oy = positions[other.id]
                dx = cx - ox
                dy = cy - oy
                dist = math.hypot(dx, dy) + 1.0
                fx += (dx / dist) * REPULSION / (dist * dist)
                fy += (dy / dist) * REPULSION / (dist * dist)

            # Attraction along nets (spring force proportional to distance)
            connected_refs = net_connections.get(comp.ref, set())
            for ref in connected_refs:
                oid = ref_to_id.get(ref)
                if oid is None or oid == cid or oid not in positions:
                    continue
                ox, oy = positions[oid]
                dx = ox - cx
                dy = oy - cy
                fx += dx * ATTRACTION
                fy += dy * ATTRACTION

            # Gentle pull towards canvas center (prevents edge clustering)
            fx += (center_x - cx) * CENTER_FORCE
            fy += (center_y - cy) * CENTER_FORCE

            # Bounding box push-back (soft wall)
            wall = 3.0
            if cx < inner_margin:
                fx += wall * (inner_margin - cx)
            if cx > width - inner_margin:
                fx -= wall * (cx - (width - inner_margin))
            if cy < inner_margin:
                fy += wall * (inner_margin - cy)
            if cy > height - inner_margin:
                fy -= wall * (cy - (height - inner_margin))

            # Update velocity with damping
            vx, vy = velocities[cid]
            vx = (vx + fx) * DAMPING
            vy = (vy + fy) * DAMPING

            # Temperature-based velocity clamping
            v_len = math.hypot(vx, vy)
            if v_len > temp:
                vx = vx / v_len * temp
                vy = vy / v_len * temp

            velocities[cid] = (vx, vy)

            # Apply movement
            nx = cx + vx
            ny = cy + vy
            nx = max(MARGIN, min(width - MARGIN, nx))
            ny = max(MARGIN, min(height - MARGIN, ny))
            positions[cid] = (nx, ny)
            total_movement += abs(vx) + abs(vy)

        # Cool down
        temp *= COOL_DOWN
        if total_movement < MIN_VELOCITY * n:
            break

    # Ensure minimum gap between nearby components
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
