"""Conservative board-edge, cutout and mounting-hole copper keepouts.

Only used by the opt-in pad-aware reference GridRouter. Copper is not
allowed at an outline, through a cutout or around a board mounting drill.
No inference about manufacturer drill capabilities is made.
"""

from __future__ import annotations

import math

from zaptrace.core.models import BoardDefinition

_Point = tuple[float, float]
_Polygon = tuple[_Point, ...]


def _distance_to_segment(point: _Point, a: _Point, b: _Point) -> float:
    vx, vy = b[0] - a[0], b[1] - a[1]
    denominator = vx * vx + vy * vy
    if denominator <= 0:
        raise ValueError("Board polygon includes a zero-length edge")
    t = max(0.0, min(1.0, ((point[0] - a[0]) * vx + (point[1] - a[1]) * vy) / denominator))
    return math.hypot(point[0] - (a[0] + t * vx), point[1] - (a[1] + t * vy))


def _segments_intersect(a: _Point, b: _Point, c: _Point, d: _Point) -> bool:
    def orientation(p: _Point, q: _Point, r: _Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_segment(p: _Point, q: _Point, r: _Point) -> bool:
        return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])

    o1, o2 = orientation(a, b, c), orientation(a, b, d)
    o3, o4 = orientation(c, d, a), orientation(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    return (
        (o1 == 0 and on_segment(a, c, b))
        or (o2 == 0 and on_segment(a, d, b))
        or (o3 == 0 and on_segment(c, a, d))
        or (o4 == 0 and on_segment(c, b, d))
    )


def _check_polygon(vertices: list[_Point] | tuple[_Point, ...]) -> _Polygon:
    poly = tuple((float(x), float(y)) for x, y in vertices)
    if len(poly) < 3 or not all(math.isfinite(v) for xy in poly for v in xy):
        raise ValueError("Board polygon must have at least three finite vertices")
    if poly[0] == poly[-1]:
        poly = poly[:-1]
    if len(poly) < 3:
        raise ValueError("Board polygon has fewer than three unique vertices")
    area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1], strict=True))
    if abs(area2) <= 1e-9:
        raise ValueError("Board polygon has zero enclosed area")
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        if a == b:
            raise ValueError("Board polygon has repeated adjacent vertices")
        for j in range(i + 1, len(poly)):
            if j == i + 1 or (i == 0 and j == len(poly) - 1):
                continue  # Adjacent segments intentionally share vertices
            c, d = poly[j], poly[(j + 1) % len(poly)]
            if _segments_intersect(a, b, c, d):
                raise ValueError("Board polygon is self-intersecting")
    return poly


def _in_polygon(point: _Point, vertices: _Polygon) -> bool:
    x, y = point
    inside = False
    for a, b in zip(vertices, vertices[1:] + vertices[:1], strict=True):
        if (a[1] > y) != (b[1] > y) and x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
            inside = not inside
    return inside


def _near_edge(point: _Point, poly: _Polygon, margin: float) -> bool:
    return any(_distance_to_segment(point, a, b) <= margin for a, b in zip(poly, poly[1:] + poly[:1], strict=True))


def blocked_profile_cells(
    board: BoardDefinition, resolution_mm: float, width_cells: int, height_cells: int
) -> set[tuple[int, int]]:
    """Cells unavailable to physical copper; expand for grid and clearance.

    Rejects self-intersecting/degenerate profiles instead of treating them as
    an ambiguous valid board. A plated mounting hole without an electrical
    net is conservatively excluded on every layer as well.
    """
    if not (math.isfinite(resolution_mm) and resolution_mm > 0):
        raise ValueError("Board raster resolution must be finite and positive")
    c = board.constraints
    half_trace = max(c.default_trace_signal, c.default_trace_power, c.min_trace_power) / 2
    margin = max(c.min_clearance, c.min_clearance_high_voltage) + half_trace + resolution_mm / math.sqrt(2)
    if not math.isfinite(margin) or margin <= 0:
        raise ValueError("Board edge clearance rules must be finite and positive")

    outline = _check_polygon(
        board.outline or [(0.0, 0.0), (board.width, 0.0), (board.width, board.height), (0.0, board.height)]
    )
    cutouts = [_check_polygon(vertices) for vertices in board.cutouts]
    holes = []
    for hole in board.mounting_holes:
        if not (
            math.isfinite(hole.diameter)
            and hole.diameter > 0
            and all(math.isfinite(v) for v in hole.position)
            and _in_polygon(hole.position, outline)
        ):
            raise ValueError("Mounting drill must have finite positive size inside the board outline")
        holes.append((hole.position, hole.diameter / 2 + margin))

    excluded: set[tuple[int, int]] = set()
    for gy in range(height_cells):
        for gx in range(width_cells):
            point = (gx * resolution_mm, gy * resolution_mm)
            if (
                not _in_polygon(point, outline)
                or _near_edge(point, outline, margin)
                or any(_in_polygon(point, cutout) or _near_edge(point, cutout, margin) for cutout in cutouts)
                or any(math.dist(point, center) <= radius for center, radius in holes)
            ):
                excluded.add((gx, gy))
    return excluded
