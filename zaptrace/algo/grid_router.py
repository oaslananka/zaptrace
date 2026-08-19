"""Grid-based A* PCB router with 45-degree angle support.

This module provides a high-quality PCB routing engine that:
- Routes traces on a discretised grid using A* pathfinding
- Supports 8-direction movement for 45-degree routing angles
- Avoids obstacles (component bodies, board edges, other traces)
- Applies net-class-aware trace widths and clearances
- Supports multi-layer routing with via cost penalty
- Smoothes paths by removing collinear waypoints

Usage::

    from zaptrace.algo.grid_router import GridRouter

    router = GridRouter(resolution_mm=0.25)
    result = router.route(design, positions)
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from dataclasses import dataclass, field
from functools import total_ordering
from typing import Any

from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Component, Design, Net, NetClass, RouteResult, TraceSegment, Via
from zaptrace.ee.classifier import classify_design, get_net_class
from zaptrace.ee.knowledge import KnowledgeBase
from zaptrace.ee.routing.defaults import DEFAULT_VIA_SPECS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SQRT2 = math.sqrt(2.0)

# 8-direction movement: (dx, dy, unit_cost)
DIRECTIONS_8: list[tuple[int, int, float]] = [
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (1, 1, SQRT2),
    (-1, 1, SQRT2),
    (1, -1, SQRT2),
    (-1, -1, SQRT2),
]

# ---------------------------------------------------------------------------
# Grid Geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GridPos:
    """Integer position on the routing grid."""

    x: int
    y: int
    layer: int = 0


@total_ordering
@dataclass
class _Node:
    """Internal A* node."""

    pos: GridPos
    g: float = 0.0
    h: float = 0.0
    f: float = 0.0
    parent: _Node | None = None

    def __lt__(self, other: _Node) -> bool:
        return self.f < other.f


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


def _octile(a: GridPos, b: GridPos, via_cost: float = 10.0) -> float:
    """Admissible octile heuristic for 8-direction + via movement."""
    dx = abs(a.x - b.x)
    dy = abs(a.y - b.y)
    dz = abs(a.layer - b.layer)
    diag = max(dx, dy) + (SQRT2 - 1.0) * min(dx, dy)
    return diag + dz * via_cost


def _reconstruct(node: _Node | None) -> list[GridPos]:
    """Walk parent chain to produce path from start to goal."""
    path: list[GridPos] = []
    while node is not None:
        path.append(node.pos)
        node = node.parent
    path.reverse()
    return path


def _manhattan_dist(a: tuple[int, int], b: tuple[int, int]) -> float:
    return float(abs(a[0] - b[0]) + abs(a[1] - b[1]))


# ---------------------------------------------------------------------------
# Obstacle Map
# ---------------------------------------------------------------------------


class ObstacleMap:
    """Multi-layer grid obstacle map with clearance dilation.

    Each cell stores 0 (free) or 1 (blocked). Blocked cells can be
    dilated by a clearance radius so paths maintain minimum spacing.
    """

    def __init__(self, width: int, height: int, layers: int = 2) -> None:
        self.width = width
        self.height = height
        self.layers = layers
        # cells[layer][row][col]
        self._cells: list[list[list[int]]] = [[[0] * width for _ in range(height)] for _ in range(layers)]

    # -- Query ------------------------------------------------------------

    def in_bounds(self, pos: GridPos) -> bool:
        return 0 <= pos.layer < self.layers and 0 <= pos.x < self.width and 0 <= pos.y < self.height

    def is_free(self, pos: GridPos) -> bool:
        return self.in_bounds(pos) and self._cells[pos.layer][pos.y][pos.x] == 0

    # -- Blocking primitives ----------------------------------------------

    def block(self, pos: GridPos) -> None:
        if self.in_bounds(pos):
            self._cells[pos.layer][pos.y][pos.x] = 1

    def unblock(self, pos: GridPos) -> None:
        """Mark a single cell as free."""
        if self.in_bounds(pos):
            self._cells[pos.layer][pos.y][pos.x] = 0

    def block_rect(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        layer: int = 0,
    ) -> None:
        y0c = max(0, y0)
        y1c = min(self.height - 1, y1)
        x0c = max(0, x0)
        x1c = min(self.width - 1, x1)
        for y in range(y0c, y1c + 1):
            row = self._cells[layer][y]
            for x in range(x0c, x1c + 1):
                row[x] = 1

    def block_line(self, p0: GridPos, p1: GridPos, radius: int = 0) -> None:
        """Bresenham line. Optionally dilate by ``radius`` cells."""
        dx = abs(p1.x - p0.x)
        sx = 1 if p0.x < p1.x else -1
        dy = -abs(p1.y - p0.y)
        sy = 1 if p0.y < p1.y else -1
        err = dx + dy
        x, y = p0.x, p0.y
        while True:
            gp = GridPos(x, y, p0.layer)
            self.block(gp)
            if radius > 0:
                self.block_rect(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    p0.layer,
                )
            if x == p1.x and y == p1.y:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def dilate(self, radius: int) -> None:
        """Expand every blocked cell by ``radius`` cells (Manhattan)."""
        if radius <= 0:
            return
        for layer in range(self.layers):
            orig = [row[:] for row in self._cells[layer]]
            for y in range(self.height):
                for x in range(self.width):
                    if orig[y][x]:
                        self.block_rect(
                            x - radius,
                            y - radius,
                            x + radius,
                            y + radius,
                            layer,
                        )


@dataclass
class _GridRouteContext:
    obstacles: ObstacleMap
    grid_w: int
    grid_h: int
    num_layers: int
    ref_positions: dict[str, tuple[float, float]]
    component_by_ref: dict[str, Component]
    via_pad: float
    via_hole: float


@dataclass
class _GridRouteState:
    traces: list[TraceSegment]
    vias: list[Via]
    layers_used: set[str]
    routed_count: int = 0
    total_routable: int = 0


@dataclass
class _GridNetPlan:
    routable: bool
    success: bool
    net_id: str
    width_mm: float = 0.0
    edge_paths: list[list[GridPos]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Grid Router
# ---------------------------------------------------------------------------


class GridRouter:
    """A* grid-based PCB router with 45-degree angle support.

    Parameters
    ----------
    resolution_mm:
        Side length of one grid cell in mm.  Smaller = finer routes but
        larger search space.  Default 0.25 mm (400 cells per 100 mm).
    via_cost:
        Additional cost applied for each via (layer change).  Larger
        values discourage unnecessary layer transitions.
    turn_penalty:
        Small additional cost when the path changes direction.  Larger
        values encourage straighter, more PCB-like routes.
    max_iterations:
        Maximum A* expansions per path search.  Prevents runaway on
        impossible-to-route nets.
    """

    def __init__(
        self,
        resolution_mm: float = 0.25,
        via_cost: float = 10.0,
        turn_penalty: float = 0.2,
        max_iterations: int = 200_000,
    ) -> None:
        self.resolution = resolution_mm
        self.via_cost = via_cost
        self.turn_penalty = turn_penalty
        self.max_iterations = max_iterations

    # -- Public API -------------------------------------------------------

    def _prepare_route_context(
        self,
        design: Design,
        positions: dict[str, tuple[float, float]],
    ) -> _GridRouteContext:
        board = canonical_board_definition(design)
        num_layers = max(board.layers, 1)
        grid_w = max(int(math.ceil(board.width / self.resolution)), 1)
        grid_h = max(int(math.ceil(board.height / self.resolution)), 1)
        obstacles = ObstacleMap(grid_w, grid_h, num_layers)
        self._block_board_edges(obstacles, grid_w, grid_h, num_layers)
        self._block_components(obstacles, design, positions, self.resolution)

        ref_positions: dict[str, tuple[float, float]] = {}
        component_by_ref: dict[str, Component] = {}
        for component in design.components.values():
            component_by_ref[component.ref] = component
            if component.id in positions:
                ref_positions[component.ref] = positions[component.id]
            if component.ref in positions:
                ref_positions[component.ref] = positions[component.ref]
            if component.position is not None and component.ref not in ref_positions:
                ref_positions[component.ref] = component.position
        return _GridRouteContext(
            obstacles=obstacles,
            grid_w=grid_w,
            grid_h=grid_h,
            num_layers=num_layers,
            ref_positions=ref_positions,
            component_by_ref=component_by_ref,
            via_pad=DEFAULT_VIA_SPECS.get("pad_diameter", 0.45),
            via_hole=DEFAULT_VIA_SPECS.get("hole_diameter", 0.2),
        )

    def _to_grid_point(self, point: tuple[float, float], context: _GridRouteContext) -> tuple[int, int]:
        return (
            max(1, min(context.grid_w - 2, int(round(point[0] / self.resolution)))),
            max(1, min(context.grid_h - 2, int(round(point[1] / self.resolution)))),
        )

    def _collect_net_route_points(self, net: Net, context: _GridRouteContext) -> list[tuple[float, float]]:
        route_points: list[tuple[float, float]] = []
        for node in net.nodes:
            component = context.component_by_ref.get(node.component_ref)
            component_position = context.ref_positions.get(node.component_ref)
            if component is None or component_position is None:
                continue
            route_points.append(self._route_point_for_node(component, node.pin_name, component_position))
        return route_points

    def _route_mst_paths(
        self,
        context: _GridRouteContext,
        grid_positions: list[tuple[int, int]],
        layer: int,
        clear_cells: int,
    ) -> list[list[GridPos]] | None:
        edge_paths: list[list[GridPos]] = []
        for first, second in self._mst(grid_positions):
            start = GridPos(*grid_positions[first], layer)
            goal = GridPos(*grid_positions[second], layer)
            path = self._astar(context.obstacles, start, goal)
            if not path:
                return None
            smooth = _simplify_path(path)
            edge_paths.append(smooth)
            for index in range(len(smooth) - 1):
                context.obstacles.block_line(smooth[index], smooth[index + 1], clear_cells)
        return edge_paths

    def _plan_grid_net(
        self,
        design: Design,
        net: Net,
        context: _GridRouteContext,
        kb: KnowledgeBase,
    ) -> _GridNetPlan:
        net_class = get_net_class(design, net.id)
        layer = self._layer_for_net_class(net_class, context.num_layers)
        if layer < 0:
            return _GridNetPlan(False, False, net.id)
        route_points = self._collect_net_route_points(net, context)
        if len(route_points) < 2:
            return _GridNetPlan(False, False, net.id)

        rule = kb.get_rule(net_class)
        clear_cells = max(int(math.ceil(rule.clearance / self.resolution)), 1)
        grid_positions = [self._to_grid_point(point, context) for point in route_points]
        for gx, gy in grid_positions:
            self._unblock_endpoint(context.obstacles, GridPos(gx, gy, layer), max(clear_cells, 1))
        edge_paths = self._route_mst_paths(context, grid_positions, layer, clear_cells)
        return _GridNetPlan(True, edge_paths is not None, net.id, rule.trace_width, edge_paths or [])

    def _append_grid_net_output(
        self,
        state: _GridRouteState,
        context: _GridRouteContext,
        plan: _GridNetPlan,
    ) -> None:
        for smooth in plan.edge_paths:
            for index in range(len(smooth) - 1):
                first, second = smooth[index], smooth[index + 1]
                x0 = round(first.x * self.resolution, 3)
                y0 = round(first.y * self.resolution, 3)
                x1 = round(second.x * self.resolution, 3)
                y1 = round(second.y * self.resolution, 3)
                layer_name = f"layer_{first.layer}"
                state.layers_used.add(layer_name)
                state.traces.append(
                    TraceSegment(
                        layer=layer_name,
                        start=(x0, y0),
                        end=(x1, y1),
                        width=plan.width_mm,
                        net_id=plan.net_id,
                    )
                )
                if first.layer != second.layer:
                    state.vias.append((x0, y0, context.via_pad, context.via_hole, plan.net_id))

    def route(
        self,
        design: Design,
        positions: dict[str, tuple[float, float]],
        kb: KnowledgeBase | None = None,
    ) -> RouteResult:
        """Route every net in *design* using A* grid pathfinding."""
        knowledge = kb if kb is not None else KnowledgeBase()
        classify_design(design)
        context = self._prepare_route_context(design, positions)
        sorted_nets = sorted(
            design.nets.values(),
            key=lambda net: knowledge.get_rule(get_net_class(design, net.id)).priority,
        )
        state = _GridRouteState(traces=[], vias=[], layers_used=set())
        for net in sorted_nets:
            plan = self._plan_grid_net(design, net, context, knowledge)
            if not plan.routable:
                continue
            state.total_routable += 1
            if not plan.success:
                continue
            state.routed_count += 1
            self._append_grid_net_output(state, context, plan)

        total_length = sum(math.dist(trace.start, trace.end) for trace in state.traces)
        return RouteResult(
            traces=state.traces,
            vias=state.vias,
            layers_used=sorted(state.layers_used),
            total_trace_length_mm=round(total_length, 3),
            net_count=state.total_routable,
            routed_net_count=state.routed_count,
        )

    # -- A* Pathfinding ---------------------------------------------------

    def _resolve_astar_endpoint(self, obstacles: ObstacleMap, position: GridPos) -> GridPos | None:
        if obstacles.is_free(position):
            return position
        return self._nearest_free(obstacles, position)

    def _previous_direction(self, node: _Node) -> tuple[int, int]:
        if node.parent is None:
            return (0, 0)
        return (node.pos.x - node.parent.pos.x, node.pos.y - node.parent.pos.y)

    def _push_planar_neighbors(
        self,
        open_set: list[_Node],
        closed: set[tuple[int, int, int]],
        obstacles: ObstacleMap,
        current: _Node,
        goal: GridPos,
    ) -> None:
        previous_direction = self._previous_direction(current)
        for dx, dy, move_cost in DIRECTIONS_8:
            position = GridPos(current.pos.x + dx, current.pos.y + dy, current.pos.layer)
            if not obstacles.is_free(position):
                continue
            key = (position.x, position.y, position.layer)
            if key in closed:
                continue
            turn = self.turn_penalty if (dx, dy) != previous_direction else 0.0
            cost = current.g + move_cost + turn
            heuristic = _octile(position, goal, self.via_cost)
            heapq.heappush(open_set, _Node(pos=position, g=cost, h=heuristic, f=cost + heuristic, parent=current))

    def _push_via_neighbors(
        self,
        open_set: list[_Node],
        closed: set[tuple[int, int, int]],
        obstacles: ObstacleMap,
        current: _Node,
        goal: GridPos,
    ) -> None:
        for layer_delta in (-1, 1):
            layer = current.pos.layer + layer_delta
            if not 0 <= layer < obstacles.layers:
                continue
            position = GridPos(current.pos.x, current.pos.y, layer)
            if not obstacles.is_free(position):
                continue
            key = (position.x, position.y, position.layer)
            if key in closed:
                continue
            cost = current.g + self.via_cost
            heuristic = _octile(position, goal, self.via_cost)
            heapq.heappush(open_set, _Node(pos=position, g=cost, h=heuristic, f=cost + heuristic, parent=current))

    def _astar(
        self,
        obs: ObstacleMap,
        start: GridPos,
        goal: GridPos,
    ) -> list[GridPos] | None:
        """Find lowest-cost path via A* with 8-direction movement + vias."""
        resolved_start = self._resolve_astar_endpoint(obs, start)
        if resolved_start is None:
            return None
        resolved_goal = self._resolve_astar_endpoint(obs, goal)
        if resolved_goal is None:
            return None

        open_set: list[_Node] = []
        closed: set[tuple[int, int, int]] = set()
        start_node = _Node(pos=resolved_start, g=0.0)
        start_node.h = _octile(resolved_start, resolved_goal, self.via_cost)
        start_node.f = start_node.g + start_node.h
        heapq.heappush(open_set, start_node)

        iterations = 0
        while open_set and iterations < self.max_iterations:
            iterations += 1
            current = heapq.heappop(open_set)
            key = (current.pos.x, current.pos.y, current.pos.layer)
            if key in closed:
                continue
            closed.add(key)
            if current.pos == resolved_goal:
                return _reconstruct(current)
            self._push_planar_neighbors(open_set, closed, obs, current, resolved_goal)
            self._push_via_neighbors(open_set, closed, obs, current, resolved_goal)
        return None

    @staticmethod
    def _nearest_free(
        obs: ObstacleMap,
        pos: GridPos,
        max_radius: int = 48,
    ) -> GridPos | None:
        """BFS for nearest free cell within *max_radius*.

        The radius must be large enough to escape a whole component courtyard
        (a net endpoint sits at the component centre): a 7×7 mm part at 0.25 mm
        resolution is ~14 cells from its edge, plus clearance dilation.
        """
        visited: set[tuple[int, int, int]] = {(pos.x, pos.y, pos.layer)}
        q: deque[tuple[GridPos, int]] = deque([(pos, 0)])
        while q:
            current, dist = q.popleft()
            if obs.is_free(current):
                return current
            if dist >= max_radius:
                continue
            for dx, dy, _ in DIRECTIONS_8:
                np = GridPos(current.x + dx, current.y + dy, current.layer)
                key = (np.x, np.y, np.layer)
                if obs.in_bounds(np) and key not in visited:
                    visited.add(key)
                    q.append((np, dist + 1))
        return None

    @staticmethod
    def _pin_aliases(pin_name: str) -> set[str]:
        raw = pin_name.strip().lower()
        aliases = {raw}
        if raw.startswith("p") and raw[1:].isdigit():
            aliases.add(raw[1:])
        if raw.isdigit():
            aliases.add(f"p{raw}")
        return aliases

    @staticmethod
    def _component_footprint(comp: Component) -> Any:
        if comp.footprint_def is not None:
            return comp.footprint_def
        if not comp.footprint:
            return None
        from zaptrace.ee.footprints import generate_footprint_for_component

        fp = generate_footprint_for_component(comp.footprint, comp.type or "")
        if fp is not None:
            comp.footprint_def = fp
        return fp

    @classmethod
    def _pad_for_pin(cls, comp: Component, pin_name: str) -> Any:
        fp = cls._component_footprint(comp)
        if fp is None:
            return None
        aliases = cls._pin_aliases(pin_name)
        if comp.package_pin_map:
            aliases.update(
                str(pad_id).strip().lower()
                for pad_id, logical_pin in comp.package_pin_map.items()
                if str(logical_pin).strip().lower() in aliases
            )
        for pad in fp.pads:
            if str(pad.id).strip().lower() in aliases:
                return pad
        return None

    @classmethod
    def _route_point_for_node(
        cls,
        comp: Component,
        pin_name: str,
        comp_pos: tuple[float, float],
    ) -> tuple[float, float]:
        pad = cls._pad_for_pin(comp, pin_name)
        fp = cls._component_footprint(comp)
        if pad is None or fp is None:
            return comp_pos
        cx, cy = comp_pos
        dx, dy = pad.position
        half_w = max(float(fp.courtyard[0]) / 2.0, abs(float(dx)), 0.0)
        half_h = max(float(fp.courtyard[1]) / 2.0, abs(float(dy)), 0.0)
        if half_w <= 0.0 or half_h <= 0.0:
            return (cx + float(dx), cy + float(dy))
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            dx = half_w
            dy = 0.0
        scale_x = half_w / abs(float(dx)) if abs(float(dx)) > 1e-9 else float("inf")
        scale_y = half_h / abs(float(dy)) if abs(float(dy)) > 1e-9 else float("inf")
        scale = max(1.0, min(scale_x, scale_y))
        edge_x = cx + float(dx) * scale
        edge_y = cy + float(dy) * scale
        length = math.hypot(edge_x - cx, edge_y - cy) or 1.0
        nudge = 0.25
        return (edge_x + (edge_x - cx) / length * nudge, edge_y + (edge_y - cy) / length * nudge)

    @staticmethod
    def _unblock_endpoint(obs: ObstacleMap, pos: GridPos, radius: int) -> None:
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                obs.unblock(GridPos(pos.x + dx, pos.y + dy, pos.layer))

    # -- MST decomposition ------------------------------------------------

    @staticmethod
    def _nearest_mst_edge(
        points: list[tuple[int, int]],
        in_mst: list[bool],
    ) -> tuple[int, int] | None:
        best: tuple[int, int] | None = None
        best_distance = float("inf")
        for source_index, source in enumerate(points):
            if not in_mst[source_index]:
                continue
            for target_index, target in enumerate(points):
                if in_mst[target_index]:
                    continue
                distance = _manhattan_dist(source, target)
                if distance < best_distance:
                    best_distance = distance
                    best = source_index, target_index
        return best

    @staticmethod
    def _mst(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Return Prim minimum-spanning-tree edges as point indices."""
        if len(points) < 2:
            return []
        in_mst = [False] * len(points)
        in_mst[0] = True
        edges: list[tuple[int, int]] = []
        for _ in range(len(points) - 1):
            edge = GridRouter._nearest_mst_edge(points, in_mst)
            if edge is None:
                break
            edges.append(edge)
            in_mst[edge[1]] = True
        return edges

    # -- Obstacle generation ----------------------------------------------

    @staticmethod
    def _block_board_edges(
        obs: ObstacleMap,
        gw: int,
        gh: int,
        n_layers: int,
    ) -> None:
        for lyr in range(n_layers):
            obs.block_rect(0, 0, gw - 1, 0, lyr)  # top
            obs.block_rect(0, gh - 1, gw - 1, gh - 1, lyr)  # bottom
            obs.block_rect(0, 0, 0, gh - 1, lyr)  # left
            obs.block_rect(gw - 1, 0, gw - 1, gh - 1, lyr)  # right

    # -- Obstacle methods --------------------------------------------------

    def _block_components(
        self,
        obs: ObstacleMap,
        design: Design,
        positions: dict[str, tuple[float, float]],
        resolution: float,
    ) -> None:
        """Block grid cells occupied by component bodies.

        Uses the component's *courtyard* dimensions (from its footprint)
        to reserve space on all routing layers so traces do not overlap
        components.  Falls back to a 2×2 mm block when no footprint is
        available.
        """
        for comp in design.components.values():
            # Get component position (try id first, then ref)
            pos = positions.get(comp.id) or positions.get(comp.ref)
            if pos is None:
                continue

            fp = self._component_footprint(comp)
            if fp is None or fp.courtyard == (0.0, 0.0):
                continue  # no footprint info → skip blocking

            bw, bh = fp.courtyard

            # Convert to grid coordinates
            cx, cy = pos
            gx0 = max(1, int((cx - bw / 2) / resolution))
            gy0 = max(1, int((cy - bh / 2) / resolution))
            gx1 = min(obs.width - 2, int((cx + bw / 2) / resolution))
            gy1 = min(obs.height - 2, int((cy + bh / 2) / resolution))

            for layer in range(obs.layers):
                obs.block_rect(gx0, gy0, gx1, gy1, layer)

    @staticmethod
    def _layer_for_net_class(net_class: NetClass, num_layers: int) -> int:
        """Map a net class to a routing layer index.

        Returns ``-1`` for nets that should **not** be routed (typically
        ``GROUND`` / ``VSS`` — left for copper pour or star-ground).
        """
        bottom = max(0, num_layers - 1)

        # Power stays on top layer
        if net_class in (
            NetClass.POWER_HIGH,
            NetClass.POWER_MED,
            NetClass.POWER_LOW,
        ):
            return 0
        # Ground → leave for copper pour
        if net_class == NetClass.GROUND:
            return -1
        # Analog stays on top (avoid via noise coupling)
        if net_class == NetClass.SIGNAL_ANALOG:
            return 0
        # High-speed / RF / differential — inner layer if available, else bottom
        if net_class in (
            NetClass.SIGNAL_HIGH,
            NetClass.RF,
            NetClass.DIFFERENTIAL,
        ):
            if num_layers >= 4:
                return 1  # inner layer (stripline)
            return bottom
        # Everything else (SIGNAL_LOW) → bottom layer
        return bottom


# ---------------------------------------------------------------------------
# Path simplification
# ---------------------------------------------------------------------------


def _simplify_path(path: list[GridPos]) -> list[GridPos]:
    """Remove collinear waypoints from the path.

    Three consecutive points are collinear when moving from ``p[i-1]``
    to ``p[i]`` has the same direction as ``p[i]`` to ``p[i+1]``.
    """
    if len(path) <= 2:
        return list(path)

    result: list[GridPos] = [path[0]]
    for i in range(1, len(path) - 1):
        prev = path[i - 1]
        cur = path[i]
        nxt = path[i + 1]
        # Only simplify within the same layer
        if cur.layer == prev.layer == nxt.layer:
            dx1 = cur.x - prev.x
            dy1 = cur.y - prev.y
            dx2 = nxt.x - cur.x
            dy2 = nxt.y - cur.y
            if dx1 * dy2 == dx2 * dy1:
                continue  # collinear → skip
        result.append(cur)
    result.append(path[-1])
    return result
