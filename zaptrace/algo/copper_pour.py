"""Copper pour (flood fill) engine.

Generates copper pour areas — typically ground planes — on PCB layers
with thermal relief spokes and stitching vias.

Algorithm
---------
1.  Create a high-resolution grid over the board area.
2.  Mark obstacles: board outline (reverse), component bodies, pads,
    mounting holes, board cutouts.
3.  Flood fill from a seed point inside the board boundary to find
    all reachable free cells.
4.  Trace the outline of the filled region to produce the pour polygon.
5.  (Optional)  Add thermal-relief spokes for specified pads/vias.
6.  (Optional)  Generate stitching-via positions along the pour.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from zaptrace.core.models import (
    BoardConfig,
    BoardDefinition,
    Component,
    CopperPourArea,
    Design,
    Net,
    Pad,
    ThermalRelief,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_RESOLUTION = 0.25  # mm per grid cell
_THERMAL_DEFAULT_SPOKES = 4
_THERMAL_DEFAULT_WIDTH = 0.3  # mm
_THERMAL_DEFAULT_GAP = 0.2  # mm
_STITCH_SPACING = 5.0  # mm between stitching vias


# ---------------------------------------------------------------------------
# Grid helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GridPt:
    x: int
    y: int


def _mm_to_grid(pos: tuple[float, float], res: float) -> _GridPt:
    return _GridPt(
        int(round(pos[0] / res)),
        int(round(pos[1] / res)),
    )


def _grid_to_mm(pt: _GridPt, res: float) -> tuple[float, float]:
    return (round(pt.x * res, 3), round(pt.y * res, 3))


def _in_polygon(
    pt: _GridPt,
    poly: list[tuple[float, float]],
    res: float,
) -> bool:
    """Ray-casting point-in-polygon test."""
    x, y = pt.x * res, pt.y * res
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


# ---------------------------------------------------------------------------
# Obstacle helpers
# ---------------------------------------------------------------------------


def _component_keepout(
    comp: Component,
    position: tuple[float, float] | None,
    clearance: float = 0.3,
) -> list[tuple[float, float]]:
    """Conservative rectangular keepout polygon for a component.

    Uses the footprint courtyard if available, otherwise falls back
    to a default 10×10 mm bounding box centred on the placement
    position.
    """
    pos = position or (0.0, 0.0)
    if comp.footprint_def is not None:
        cw, ch = comp.footprint_def.courtyard
        ox, oy = pos
        return [
            (ox - cw / 2 - clearance, oy - ch / 2 - clearance),
            (ox + cw / 2 + clearance, oy - ch / 2 - clearance),
            (ox + cw / 2 + clearance, oy + ch / 2 + clearance),
            (ox - cw / 2 - clearance, oy + ch / 2 + clearance),
        ]
    # Fallback: 10×10 mm box
    hw = 5.0 + clearance
    hh = 5.0 + clearance
    return [
        (pos[0] - hw, pos[1] - hh),
        (pos[0] + hw, pos[1] - hh),
        (pos[0] + hw, pos[1] + hh),
        (pos[0] - hw, pos[1] + hh),
    ]


def _board_outline_points(board: BoardDefinition | BoardConfig) -> list[tuple[float, float]]:
    """Board outline as a closed polygon.

    Returns the explicit outline if present, otherwise a simple
    rectangle from width/height.
    """
    if isinstance(board, BoardDefinition) and board.outline:
        return list(board.outline)
    w = board.width if isinstance(board, BoardDefinition) else board.width_mm
    h = board.height if isinstance(board, BoardDefinition) else board.height_mm
    return [(0, 0), (w, 0), (w, h), (0, h)]


# ---------------------------------------------------------------------------
# Flood fill
# ---------------------------------------------------------------------------


def _grid_size(
    board: BoardDefinition | BoardConfig,
    res: float,
) -> tuple[int, int]:
    w = board.width if isinstance(board, BoardDefinition) else board.width_mm
    h = board.height if isinstance(board, BoardDefinition) else board.height_mm
    return max(int(math.ceil(w / res)), 1), max(int(math.ceil(h / res)), 1)


# ---------------------------------------------------------------------------
# Copper pour generator
# ---------------------------------------------------------------------------


class CopperPourGenerator:
    """Generates copper pour/flood-fill areas for a PCB design layer.

    Typical usage::

        gen = CopperPourGenerator(resolution_mm=0.25)
        pour = gen.generate_ground_pour(
            design=design,
            positions=design.placement or {},
            layer="F.Cu",
            net_id="GND",
            add_stitching_vias=True,
        )
        design.copper_pours["F.Cu_GND"] = pour
    """

    def __init__(self, resolution_mm: float = _DEFAULT_RESOLUTION) -> None:
        self.res = resolution_mm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _block_board_features(
        self,
        grid: list[list[int]],
        board: BoardDefinition | BoardConfig,
    ) -> None:
        self._block_outside_board(grid, _board_outline_points(board))
        if not isinstance(board, BoardDefinition):
            return
        for cutout in board.cutouts:
            self._block_polygon(grid, cutout)
        for mounting_hole in board.mounting_holes:
            radius = int(math.ceil((mounting_hole.diameter / 2 + 0.2) / self.res))
            cx = int(round(mounting_hole.position[0] / self.res))
            cy = int(round(mounting_hole.position[1] / self.res))
            self._block_circle(grid, cx, cy, radius)

    def _block_component_keepouts(
        self,
        grid: list[list[int]],
        design: Design,
        positions: dict[str, tuple[float, float]],
        component_clearance: float,
        keepout_fn: Callable | None,
    ) -> None:
        for component in design.components.values():
            position = positions.get(component.id) or positions.get(component.ref)
            keepout = (
                keepout_fn(component, position)
                if keepout_fn is not None
                else _component_keepout(component, position, component_clearance)
            )
            self._block_polygon(grid, keepout)

    def _prepare_pour_grid(
        self,
        design: Design,
        positions: dict[str, tuple[float, float]],
        layer: str,
        component_clearance: float,
        keepout_fn: Callable | None,
    ) -> tuple[list[list[int]], int, int]:
        board = design.board_def if design.board_def is not None else design.board
        grid_width, grid_height = _grid_size(board, self.res)
        grid = [[0] * grid_width for _ in range(grid_height)]
        self._block_board_features(grid, board)
        self._block_component_keepouts(grid, design, positions, component_clearance, keepout_fn)
        self._block_traces(grid, design, layer)
        return grid, grid_width, grid_height

    @staticmethod
    def _fill_all_free_cells(grid: list[list[int]]) -> set[_GridPt]:
        filled: set[_GridPt] = set()
        for y, row in enumerate(grid):
            for x, cell in enumerate(row):
                if cell == 0:
                    filled.add(_GridPt(x, y))
        return filled

    def _filled_pour_cells(
        self,
        grid: list[list[int]],
        grid_width: int,
        grid_height: int,
    ) -> set[_GridPt]:
        filled = self._flood_fill(grid, _GridPt(grid_width // 2, grid_height // 2))
        return filled if filled else self._fill_all_free_cells(grid)

    def generate_ground_pour(
        self,
        design: Design,
        positions: dict[str, tuple[float, float]],
        layer: str = "F.Cu",
        net_id: str = "GND",
        add_thermal_reliefs: bool = True,
        add_stitching_vias: bool = True,
        stitch_spacing: float = _STITCH_SPACING,
        component_clearance: float = 0.3,
        keepout_fn: Callable | None = None,
    ) -> CopperPourArea:
        """Generate a ground copper pour on *layer*."""
        grid, grid_width, grid_height = self._prepare_pour_grid(
            design, positions, layer, component_clearance, keepout_fn
        )
        filled = self._filled_pour_cells(grid, grid_width, grid_height)
        polygon = self._trace_outline(filled, grid_width, grid_height)
        thermal_reliefs = (
            self._generate_thermal_reliefs(design, positions, filled, net_id=net_id) if add_thermal_reliefs else []
        )
        stitching_vias = (
            self._generate_stitching_vias(design, positions, filled, stitch_spacing) if add_stitching_vias else []
        )
        return CopperPourArea(
            layer=layer,
            net_id=net_id,
            polygon=polygon,
            thermal_reliefs=thermal_reliefs,
            stitching_vias=stitching_vias,
        )

    # ------------------------------------------------------------------
    # Grid blocking
    # ------------------------------------------------------------------

    def _block_outside_board(
        self,
        grid: list[list[int]],
        outline: list[tuple[float, float]],
    ) -> None:
        """Block all cells outside the board outline polygon."""
        gh = len(grid)
        gw = len(grid[0]) if gh > 0 else 0
        if not outline:
            return
        for y in range(gh):
            for x in range(gw):
                if not _in_polygon(_GridPt(x, y), outline, self.res):
                    grid[y][x] = 1

    def _block_polygon(
        self,
        grid: list[list[int]],
        polygon: list[tuple[float, float]],
    ) -> None:
        """Block all cells inside the given polygon."""
        gh = len(grid)
        gw = len(grid[0]) if gh > 0 else 0
        if not polygon:
            return
        # Bounding box
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        min_x = max(0, int(math.floor(min(xs) / self.res)))
        max_x = min(gw - 1, int(math.ceil(max(xs) / self.res)))
        min_y = max(0, int(math.floor(min(ys) / self.res)))
        max_y = min(gh - 1, int(math.ceil(max(ys) / self.res)))
        for y in range(min_y, max_y + 1):
            row = grid[y]
            for x in range(min_x, max_x + 1):
                if row[x] == 0 and _in_polygon(_GridPt(x, y), polygon, self.res):
                    row[x] = 1

    def _block_circle(
        self,
        grid: list[list[int]],
        cx: int,
        cy: int,
        radius: int,
    ) -> None:
        """Block cells within a circle."""
        gh = len(grid)
        gw = len(grid[0]) if gh > 0 else 0
        r2 = radius * radius
        for dy in range(-radius, radius + 1):
            y = cy + dy
            if y < 0 or y >= gh:
                continue
            row = grid[y]
            for dx in range(-radius, radius + 1):
                x = cx + dx
                if x < 0 or x >= gw:
                    continue
                if dx * dx + dy * dy <= r2:
                    row[x] = 1

    def _block_traces(
        self,
        grid: list[list[int]],
        design: Design,
        layer: str,
    ) -> None:
        """Block grid cells occupied by existing traces on *layer*."""
        if design.routing is None:
            return
        half_cells = max(int(math.ceil(0.15 / self.res)), 1)
        for seg in design.routing.traces:
            if seg.layer != layer:
                continue
            w2 = int(math.ceil(seg.width / self.res / 2))
            b = max(w2, half_cells)
            x0 = int(round(seg.start[0] / self.res))
            y0 = int(round(seg.start[1] / self.res))
            x1 = int(round(seg.end[0] / self.res))
            y1 = int(round(seg.end[1] / self.res))
            self._block_line(grid, x0, y0, x1, y1, b)

    @staticmethod
    def _block_radius_at(
        grid: list[list[int]],
        x: int,
        y: int,
        radius: int,
    ) -> None:
        grid_height = len(grid)
        grid_width = len(grid[0]) if grid_height > 0 else 0
        for radius_y in range(-radius, radius + 1):
            target_y = y + radius_y
            if target_y < 0 or target_y >= grid_height:
                continue
            row = grid[target_y]
            for radius_x in range(-radius, radius + 1):
                target_x = x + radius_x
                if 0 <= target_x < grid_width:
                    row[target_x] = 1

    @staticmethod
    def _next_bresenham_point(
        x: int,
        y: int,
        error: int,
        dx: int,
        dy: int,
        step_x: int,
        step_y: int,
    ) -> tuple[int, int, int]:
        doubled_error = 2 * error
        if doubled_error >= dy:
            error += dy
            x += step_x
        if doubled_error <= dx:
            error += dx
            y += step_y
        return x, y, error

    def _block_line(
        self,
        grid: list[list[int]],
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        radius: int = 1,
    ) -> None:
        """Bresenham line with optional radius."""
        dx = abs(x1 - x0)
        step_x = 1 if x0 < x1 else -1
        dy = -abs(y1 - y0)
        step_y = 1 if y0 < y1 else -1
        error = dx + dy
        x, y = x0, y0
        while True:
            self._block_radius_at(grid, x, y, radius)
            if x == x1 and y == y1:
                break
            x, y, error = self._next_bresenham_point(x, y, error, dx, dy, step_x, step_y)

    # ------------------------------------------------------------------
    # Flood fill
    # ------------------------------------------------------------------

    @staticmethod
    def _reachable_neighbors(
        grid: list[list[int]], point: _GridPt, filled: set[_GridPt], gw: int, gh: int
    ) -> list[_GridPt]:
        neighbors: list[_GridPt] = []
        for dx, dy in (
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
            (-1, -1),
            (-1, 1),
            (1, -1),
            (1, 1),
        ):
            nx, ny = point.x + dx, point.y + dy
            candidate = _GridPt(nx, ny)
            if 0 <= nx < gw and 0 <= ny < gh and candidate not in filled and grid[ny][nx] == 0:
                neighbors.append(candidate)
        return neighbors

    @staticmethod
    def _flood_fill(
        grid: list[list[int]],
        seed: _GridPt,
    ) -> set[_GridPt]:
        """BFS flood fill from *seed*, returning all reachable free cells."""
        gh = len(grid)
        gw = len(grid[0]) if gh > 0 else 0
        if not (0 <= seed.x < gw and 0 <= seed.y < gh):
            return set()
        if grid[seed.y][seed.x] != 0:
            return set()

        filled = {seed}
        queue = deque([seed])
        while queue:
            point = queue.popleft()
            for neighbor in CopperPourGenerator._reachable_neighbors(grid, point, filled, gw, gh):
                filled.add(neighbor)
                queue.append(neighbor)
        return filled

    # ------------------------------------------------------------------
    # Outline tracing
    # ------------------------------------------------------------------

    def _trace_outline(
        self,
        filled: set[_GridPt],
        gw: int,
        gh: int,
    ) -> list[tuple[float, float]]:
        """Extract the outer boundary of the filled region.

        Uses a simple Moore-neighbour boundary walk.  Returns the
        outline as a list of ``(x_mm, y_mm)`` points (clockwise).
        """
        if not filled:
            return []

        # Find top-leftmost filled cell
        start = min(filled, key=lambda p: (p.y, p.x))

        # Moore neighbour ordering: starts at (1,0) and goes clockwise
        moore = [
            (1, 0),
            (1, 1),
            (0, 1),
            (-1, 1),
            (-1, 0),
            (-1, -1),
            (0, -1),
            (1, -1),
        ]

        boundary: list[_GridPt] = [start]
        current = start
        prev_dir = 7  # Start pointing to the previous search direction

        for _ in range(gw * gh):  # Upper bound
            found = False
            for offset in range(8):
                idx = (prev_dir + 1 + offset) % 8
                dx, dy = moore[idx]
                nb = _GridPt(current.x + dx, current.y + dy)
                if nb in filled:
                    boundary.append(nb)
                    current = nb
                    prev_dir = (idx + 4) % 8  # opposite of entry direction
                    found = True
                    break
            if not found or current == start:
                break

        # Remove trailing duplicates of start
        while len(boundary) > 1 and boundary[-1] == start:
            boundary.pop()

        return [_grid_to_mm(p, self.res) for p in boundary]

    # ------------------------------------------------------------------
    # Thermal reliefs
    # ------------------------------------------------------------------

    def _routing_via_reliefs(
        self,
        design: Design,
        filled: set[_GridPt],
        seen: set[tuple[float, float]],
        *,
        net_id: str,
    ) -> list[ThermalRelief]:
        """Return pour reliefs only for routing vias with explicit matching net identity."""
        reliefs: list[ThermalRelief] = []
        if design.routing is None:
            return reliefs
        for via in design.routing.vias:
            if len(via) < 5 or str(via[4]) != net_id:
                continue
            x, y, pad_diameter, _hole = via[:4]
            key = (round(x, 2), round(y, 2))
            if key in seen:
                continue
            seen.add(key)
            grid_point = _GridPt(int(round(x / self.res)), int(round(y / self.res)))
            if grid_point in filled:
                reliefs.append(ThermalRelief(pad_position=(x, y), pad_diameter=pad_diameter))
        return reliefs

    def _thermal_relief_for_pad(
        self,
        position: tuple[float, float],
        pad: Pad,
        filled: set[_GridPt],
        seen: set[tuple[float, float]],
    ) -> ThermalRelief | None:
        pad_x = round(position[0] + pad.position[0], 3)
        pad_y = round(position[1] + pad.position[1], 3)
        key = (pad_x, pad_y)
        if key in seen:
            return None
        seen.add(key)
        grid_point = _GridPt(int(round(pad_x / self.res)), int(round(pad_y / self.res)))
        if grid_point not in filled:
            return None
        pad_diameter = max(pad.size) if pad.size else 0.45
        return ThermalRelief(pad_position=(pad_x, pad_y), pad_diameter=pad_diameter)

    @staticmethod
    def _logical_pin_aliases(pin_name: str) -> set[str]:
        raw = pin_name.strip().lower()
        aliases = {raw}
        if raw.startswith("p") and raw[1:].isdigit():
            aliases.add(raw[1:])
        if raw.isdigit():
            aliases.add(f"p{raw}")
        return aliases

    @staticmethod
    def _net_by_id(design: Design, net_id: str) -> Net | None:
        direct = design.nets.get(net_id)
        if direct is not None and direct.id == net_id:
            return direct
        return next((net for net in design.nets.values() if net.id == net_id), None)

    @classmethod
    def _physical_pad_ids_for_net(cls, design: Design, component: Component, net_id: str) -> set[str]:
        """Resolve physical pad IDs for one component's nodes on *net_id*."""
        net = cls._net_by_id(design, net_id)
        if net is None or component.footprint_def is None:
            return set()
        logical_aliases: set[str] = set()
        for node in net.nodes:
            if node.component_ref in (component.id, component.ref):
                logical_aliases.update(cls._logical_pin_aliases(node.pin_name))
        if not logical_aliases:
            return set()

        if component.package_pin_map:
            return {
                str(pad_id)
                for pad_id, logical_pin in component.package_pin_map.items()
                if cls._logical_pin_aliases(str(logical_pin)) & logical_aliases
            }

        return {
            str(pad.id)
            for pad in component.footprint_def.pads
            if cls._logical_pin_aliases(str(pad.id)) & logical_aliases
        }

    def _component_pad_reliefs(
        self,
        design: Design,
        positions: dict[str, tuple[float, float]],
        filled: set[_GridPt],
        seen: set[tuple[float, float]],
        *,
        net_id: str,
    ) -> list[ThermalRelief]:
        reliefs: list[ThermalRelief] = []
        for component in design.components.values():
            position = positions.get(component.id) or positions.get(component.ref)
            if position is None or component.footprint_def is None:
                continue
            allowed_pad_ids = {pad_id.lower() for pad_id in self._physical_pad_ids_for_net(design, component, net_id)}
            if not allowed_pad_ids:
                continue
            for pad in component.footprint_def.pads:
                if str(pad.id).strip().lower() not in allowed_pad_ids:
                    continue
                relief = self._thermal_relief_for_pad(position, pad, filled, seen)
                if relief is not None:
                    reliefs.append(relief)
        return reliefs

    def _generate_thermal_reliefs(
        self,
        design: Design,
        positions: dict[str, tuple[float, float]],
        filled: set[_GridPt],
        *,
        net_id: str,
    ) -> list[ThermalRelief]:
        """Generate thermal reliefs only for pads/vias proven to belong to the pour net."""
        seen: set[tuple[float, float]] = set()
        reliefs = self._routing_via_reliefs(design, filled, seen, net_id=net_id)
        reliefs.extend(self._component_pad_reliefs(design, positions, filled, seen, net_id=net_id))
        return reliefs

    # ------------------------------------------------------------------
    # Stitching vias
    # ------------------------------------------------------------------

    @staticmethod
    def _occupied_stitching_positions(
        design: Design,
        positions: dict[str, tuple[float, float]],
    ) -> set[tuple[float, float]]:
        occupied: set[tuple[float, float]] = set()
        for comp in design.components.values():
            position = positions.get(comp.id) or positions.get(comp.ref)
            if position is not None:
                occupied.add((round(position[0], 1), round(position[1], 1)))
        return occupied

    @staticmethod
    def _is_fill_edge(point: _GridPt, filled: set[_GridPt]) -> bool:
        return any(_GridPt(point.x + dx, point.y + dy) not in filled for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)))

    @staticmethod
    def _is_clear_of_components(
        position: tuple[float, float],
        occupied: set[tuple[float, float]],
    ) -> bool:
        return all(math.dist(position, component_position) >= 3.0 for component_position in occupied)

    def _generate_stitching_vias(
        self,
        design: Design,
        positions: dict[str, tuple[float, float]],
        filled: set[_GridPt],
        spacing: float,
    ) -> list[tuple[float, float]]:
        """Generate stitching via positions along the pour area.

        Vias are placed near the pour boundary at regular intervals,
        avoiding component positions.
        """
        vias: list[tuple[float, float]] = []
        occupied = self._occupied_stitching_positions(design, positions)
        step = max(int(round(spacing / self.res)), 5)
        last_placed = -step  # grid cells
        count = 0

        for point in sorted(filled, key=lambda item: (item.y, item.x)):
            if not self._is_fill_edge(point, filled):
                continue

            count += 1
            if count - last_placed < step:
                continue

            position = _grid_to_mm(point, self.res)
            if not self._is_clear_of_components(position, occupied):
                continue

            vias.append(position)
            last_placed = count

        return vias
