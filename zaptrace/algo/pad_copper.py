"""Conservative grid rasterization of physical footprint-pad copper.

Coordinates use the same mm axes and positive-degree convention as the
design placement model. This module does not inspect KiCad or grant DRC
approval: it builds conservative forbidden corridors for a reference router.
"""

from __future__ import annotations

import math

from zaptrace.core.models import LayerSet, Pad, PadShape


def rotated_offset(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    """KiCad screen-space rotation: positive 90 moves a right-side pad up."""
    theta = math.radians(-angle_deg)
    return (x * math.cos(theta) - y * math.sin(theta), x * math.sin(theta) + y * math.cos(theta))


def copper_layers(pad: Pad, layer_count: int) -> tuple[int, ...]:
    """Return actual copper layers; a plated PTH is present on all layers."""
    if pad.drill and pad.plated:
        return tuple(range(layer_count))
    if pad.layer == LayerSet.ALL:
        return tuple(range(layer_count))
    if pad.layer == LayerSet.TOP:
        return (0,)
    if pad.layer == LayerSet.BOTTOM:
        return (layer_count - 1,)
    if pad.layer == LayerSet.INNER:
        return tuple(range(1, layer_count - 1))
    raise ValueError("Unknown copper pad layer")


def _distance_in_local_shape(dx: float, dy: float, pad: Pad) -> float:
    """Distance to copper shape: signed inside values are clamped to zero."""
    w, h = pad.size
    if min(w, h) <= 0 or not all(map(math.isfinite, (w, h))):
        raise ValueError("Pad copper dimensions must be finite and positive")
    if pad.shape == PadShape.CIRCLE:
        return max(0.0, math.hypot(dx, dy) - max(w, h) / 2)
    if pad.shape == PadShape.RECT:
        return math.hypot(max(abs(dx) - w / 2, 0), max(abs(dy) - h / 2, 0))
    if pad.shape == PadShape.OVAL:
        if w >= h:
            return max(0.0, math.hypot(max(abs(dx) - (w - h) / 2, 0), dy) - h / 2)
        return max(0.0, math.hypot(dx, max(abs(dy) - (h - w) / 2, 0)) - w / 2)
    # Without a custom copper polygon, its bounding rectangle is NOT a
    # trustworthy bound. Require a distinct native-geometry implementation.
    raise ValueError("Custom pad copper geometry cannot be projected safely")


def pad_cells(
    pad: Pad,
    position_mm: tuple[float, float],
    footprint_rotation_deg: float,
    resolution_mm: float,
    width_cells: int,
    height_cells: int,
    clearance_mm: float,
) -> set[tuple[int, int]]:
    """Conservative rotated RECT/CIRCLE/OVAL mask, including grid uncertainty."""
    if not (resolution_mm > 0 and math.isfinite(resolution_mm)):
        raise ValueError("Grid resolution must be finite and positive")
    if not (clearance_mm >= 0 and math.isfinite(clearance_mm)):
        raise ValueError("Copper clearance must be non-negative")
    if not math.isfinite(footprint_rotation_deg):
        raise ValueError("Footprint rotation must be finite")

    if pad.shape == PadShape.CUSTOM:
        raise ValueError("Custom pad copper geometry cannot be projected safely")
    if not all(math.isfinite(float(n)) for n in (*pad.position, *pad.size, pad.rotation, *position_mm)):
        raise ValueError("Pad position, size and rotation must be finite")
    if min(pad.size) <= 0:
        raise ValueError("Pad copper dimensions must be finite and positive")
    px, py = rotated_offset(*pad.position, footprint_rotation_deg)
    cx, cy = position_mm[0] + px, position_mm[1] + py
    if not (0 <= cx < width_cells * resolution_mm and 0 <= cy < height_cells * resolution_mm):
        raise ValueError("Pad centre lies outside the routing grid")
    theta = math.radians(-(float(pad.rotation) + footprint_rotation_deg))
    co, si = math.cos(theta), math.sin(theta)
    # Every grid cell represents an AREA, not just a point. Expand by its
    # half-diagonal so sub-cell pad copper cannot slip between sample points.
    margin = clearance_mm + resolution_mm / math.sqrt(2)
    extent = math.hypot(*pad.size) / 2 + margin
    x0 = max(0, math.floor((cx - extent) / resolution_mm))
    x1 = min(width_cells - 1, math.ceil((cx + extent) / resolution_mm))
    y0 = max(0, math.floor((cy - extent) / resolution_mm))
    y1 = min(height_cells - 1, math.ceil((cy + extent) / resolution_mm))
    points: set[tuple[int, int]] = set()
    for gy in range(y0, y1 + 1):
        for gx in range(x0, x1 + 1):
            dx, dy = gx * resolution_mm - cx, gy * resolution_mm - cy
            local_x, local_y = co * dx + si * dy, -si * dx + co * dy
            if _distance_in_local_shape(local_x, local_y, pad) <= margin:
                points.add((gx, gy))
    return points


def finished_hole_cells(
    pad: Pad,
    position_mm: tuple[float, float],
    footprint_rotation_deg: float,
    resolution_mm: float,
    width_cells: int,
    height_cells: int,
    margin_mm: float,
) -> set[tuple[int, int]]:
    """NPTH drill keepout; all layers are obstructed by the physical hole."""
    if not pad.drill:
        return set()
    if pad.shape != PadShape.CIRCLE:
        # Scalar hole diameter cannot encode an NPTH oval/milled slot.
        raise ValueError("Non-circular NPTH hole geometry needs a verified slot definition")
    hole = pad.model_copy(update={"shape": PadShape.CIRCLE, "size": (pad.drill, pad.drill), "position": pad.position})
    return pad_cells(hole, position_mm, footprint_rotation_deg, resolution_mm, width_cells, height_cells, margin_mm)
