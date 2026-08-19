"""Differential pair routing engine.

Routes coupled, length-matched traces for differential signals
(USB, HDMI, Ethernet, DDR, etc.).  Built on top of the A* grid
router for obstacle-aware pathfinding.

Usage::

    from zaptrace.algo.diff_pair import DiffPairRouter

    router = DiffPairRouter(gap=0.25, width=0.2)
    result = router.route_diff_pairs(design, positions, kb)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from zaptrace.algo.grid_router import GridRouter
from zaptrace.core.models import Design, NetClass, RouteResult, TraceSegment, Via
from zaptrace.ee.classifier import classify_design, get_net_class
from zaptrace.ee.knowledge import KnowledgeBase

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_GAP_MM = 0.2  # default edge-to-edge gap
_DEFAULT_WIDTH_MM = 0.2  # default trace width
_MAX_LENGTH_MISMATCH_MM = 0.5  # max allowed skew before meandering
_MEANDER_AMPLITUDE_MM = 1.0  # meander tooth height
_MEANDER_MIN_SEGMENT_MM = 3.0  # minimum straight segment to insert meanders


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class DiffPairConfig:
    """Configuration for a differential pair."""

    gap: float = _DEFAULT_GAP_MM
    width: float = _DEFAULT_WIDTH_MM
    target_impedance: float = 90.0  # ohms
    max_length_mismatch: float = _MAX_LENGTH_MISMATCH_MM
    meander_amplitude: float = _MEANDER_AMPLITUDE_MM


# Default configs for common standards
STD_CONFIGS: dict[str, DiffPairConfig] = {
    "usb": DiffPairConfig(gap=0.25, width=0.2, target_impedance=90.0),
    "usb_c": DiffPairConfig(gap=0.2, width=0.18, target_impedance=90.0),
    "ethernet": DiffPairConfig(gap=0.3, width=0.25, target_impedance=100.0),
    "hdmi": DiffPairConfig(gap=0.15, width=0.15, target_impedance=100.0),
    "ddr": DiffPairConfig(gap=0.2, width=0.15, target_impedance=100.0),
    "pcie": DiffPairConfig(gap=0.2, width=0.2, target_impedance=85.0),
    "mipi": DiffPairConfig(gap=0.1, width=0.12, target_impedance=100.0),
}


# ---------------------------------------------------------------------------
# Pair identification
# ---------------------------------------------------------------------------

_PAIR_PATTERNS: list[tuple[str, str, str]] = [
    # (pattern name, positive suffix, negative suffix)
    ("_DP/_DM", "_DP", "_DM"),
    ("_DP/_DN", "_DP", "_DN"),
    ("_P/_N", "_P", "_N"),
    ("+/−", "+", "-"),
    ("_P/_N mid", "/_P", "/_N"),
]


def _pair_candidate_for_pattern(
    design: Design,
    net_id: str,
    name: str,
    used: set[str],
    positive_suffix: str,
    negative_suffix: str,
) -> tuple[str, str] | None:
    if name.endswith(positive_suffix):
        partner_name = name[: -len(positive_suffix)] + negative_suffix
        partner = _net_by_name(design, partner_name)
        if partner and partner not in used:
            return net_id, partner
    if name.endswith(negative_suffix):
        partner_name = name[: -len(negative_suffix)] + positive_suffix
        partner = _net_by_name(design, partner_name)
        if partner and partner not in used:
            return partner, net_id
    return None


def _find_pair_candidate(
    design: Design,
    net_id: str,
    used: set[str],
) -> tuple[str, str] | None:
    name = design.nets[net_id].name
    for _, positive_suffix, negative_suffix in _PAIR_PATTERNS:
        candidate = _pair_candidate_for_pattern(
            design,
            net_id,
            name,
            used,
            positive_suffix,
            negative_suffix,
        )
        if candidate is not None:
            return candidate
    return None


def _find_diff_pairs(
    design: Design,
) -> list[tuple[str, str]]:
    """Identify differential pair net-IDs from the design's netlist."""
    classify_design(design)
    differential_net_ids = [net_id for net_id in design.nets if get_net_class(design, net_id) == NetClass.DIFFERENTIAL]
    pairs: list[tuple[str, str]] = []
    used: set[str] = set()
    for net_id in differential_net_ids:
        if net_id in used:
            continue
        candidate = _find_pair_candidate(design, net_id, used)
        if candidate is None:
            continue
        pairs.append(candidate)
        used.update(candidate)
    return pairs


def _net_by_name(design: Design, name: str) -> str | None:
    """Find net ID by net name."""
    for nid, net in design.nets.items():
        if net.name == name:
            return nid
    return None


# ---------------------------------------------------------------------------
# Differential Pair Router
# ---------------------------------------------------------------------------


class DiffPairRouter:
    """Router for differential signal pairs.

    Routes the positive trace via the A* grid router, then generates
    the negative trace as a parallel offset.  Applies length matching
    (meanders) when the skew exceeds the configurable threshold.

    Parameters
    ----------
    gap:
        Edge-to-edge spacing between the two traces (mm).
    width:
        Trace width for both traces (mm).
    max_length_mismatch:
        Maximum allowed length difference before meandering (mm).
    meander_amplitude:
        Height of meander teeth (mm).
    meander_spacing:
        Spacing between meander teeth (mm).
    """

    def __init__(
        self,
        gap: float = _DEFAULT_GAP_MM,
        width: float = _DEFAULT_WIDTH_MM,
        max_length_mismatch: float = _MAX_LENGTH_MISMATCH_MM,
        meander_amplitude: float = _MEANDER_AMPLITUDE_MM,
        meander_spacing: float = 2.0,
    ) -> None:
        self.gap = gap
        self.width = width
        self.max_length_mismatch = max_length_mismatch
        self.meander_amplitude = meander_amplitude
        self.meander_spacing = meander_spacing

    # -- Public API -------------------------------------------------------

    def route_diff_pairs(
        self,
        design: Design,
        positions: dict[str, tuple[float, float]],
        kb: KnowledgeBase | None = None,
        grid_router: GridRouter | None = None,
    ) -> RouteResult:
        """Route all differential pairs in *design*.

        Args:
            design:
                Design containing differential nets to route.
            positions:
                Mapping ``component_id -> (x, y)`` in mm.
            kb:
                Optional knowledge base for net-class rules.
            grid_router:
                Optional pre-configured grid router.  A default is
                created when ``None``.

        Returns:
            :class:`RouteResult` with both single-ended and differential
            traces merged.
        """
        if kb is None:
            kb = KnowledgeBase()
        if grid_router is None:
            grid_router = GridRouter()

        pairs = _find_diff_pairs(design)
        if not pairs:
            return RouteResult()

        all_traces: list[TraceSegment] = []
        all_vias: list[Via] = []
        layers_used: set[str] = set()

        for pos_id, neg_id in pairs:
            result = self._route_single_pair(
                design,
                positions,
                kb,
                grid_router,
                pos_id,
                neg_id,
            )
            all_traces.extend(result.traces)
            all_vias.extend(result.vias)
            layers_used.update(result.layers_used)

        total_length = sum(math.dist(t.start, t.end) for t in all_traces)

        return RouteResult(
            traces=all_traces,
            vias=all_vias,
            layers_used=sorted(layers_used),
            total_trace_length_mm=round(total_length, 3),
            net_count=len(pairs) * 2,
            routed_net_count=len(pairs) * 2,
        )

    # -- Internal pair routing --------------------------------------------

    def _route_single_pair(
        self,
        design: Design,
        positions: dict[str, tuple[float, float]],
        kb: KnowledgeBase,
        grid_router: GridRouter,
        pos_net_id: str,
        neg_net_id: str,
    ) -> RouteResult:
        """Route one differential pair (positive + negative)."""
        # Create a temporary design with just the positive net
        pos_design = _design_for_net(design, pos_net_id)

        # Route positive trace
        pos_result = grid_router.route(pos_design, positions, kb)

        if not pos_result.traces:
            return RouteResult()

        # Build the positive trace as a continuous path (extract vertices)
        pos_vertices = _traces_to_vertices(pos_result.traces)

        # Generate negative trace as parallel offset
        total_gap = self.gap + self.width  # centre-to-centre spacing
        neg_vertices = _parallel_offset(pos_vertices, -total_gap)

        # Create TraceSegments for the negative trace
        w = self.width
        neg_traces: list[TraceSegment] = []
        for i in range(len(neg_vertices) - 1):
            neg_traces.append(
                TraceSegment(
                    layer="F.Cu",
                    start=neg_vertices[i],
                    end=neg_vertices[i + 1],
                    width=w,
                    net_id=neg_net_id,
                )
            )

        # Length matching
        pos_len = _path_length(pos_vertices)
        neg_len = _path_length(neg_vertices)

        if abs(pos_len - neg_len) > self.max_length_mismatch:
            if pos_len < neg_len:
                pos_vertices = _add_meanders(
                    pos_vertices,
                    target_length=neg_len,
                    amplitude=self.meander_amplitude,
                    min_segment_len=self.meander_amplitude * 3,
                )
                # Rebuild positive traces
                pos_traces_new: list[TraceSegment] = []
                for i in range(len(pos_vertices) - 1):
                    pos_traces_new.append(
                        TraceSegment(
                            layer="F.Cu",
                            start=pos_vertices[i],
                            end=pos_vertices[i + 1],
                            width=w,
                            net_id=pos_net_id,
                        )
                    )
                pos_result = RouteResult(traces=pos_traces_new)
            else:
                neg_vertices = _add_meanders(
                    neg_vertices,
                    target_length=pos_len,
                    amplitude=self.meander_amplitude,
                    min_segment_len=self.meander_amplitude * 3,
                )
                neg_traces = []
                for i in range(len(neg_vertices) - 1):
                    neg_traces.append(
                        TraceSegment(
                            layer="F.Cu",
                            start=neg_vertices[i],
                            end=neg_vertices[i + 1],
                            width=w,
                            net_id=neg_net_id,
                        )
                    )

        # Merge results
        merged_traces = pos_result.traces + neg_traces
        merged_vias = list(pos_result.vias)
        merged_layers = set(pos_result.layers_used)
        merged_len = sum(math.dist(t.start, t.end) for t in merged_traces)

        return RouteResult(
            traces=merged_traces,
            vias=merged_vias,
            layers_used=sorted(merged_layers),
            total_trace_length_mm=round(merged_len, 3),
            net_count=2,
            routed_net_count=2,
        )


# ---------------------------------------------------------------------------
# Parallel offset
# ---------------------------------------------------------------------------


def _unit_vector(dx: float, dy: float) -> tuple[float, float]:
    length = math.sqrt(dx * dx + dy * dy)
    if length <= 1e-9:
        return 0.0, 0.0
    return dx / length, dy / length


def _vertex_direction(
    vertices: list[tuple[float, float]],
    index: int,
) -> tuple[float, float]:
    if index == 0:
        return vertices[1][0] - vertices[0][0], vertices[1][1] - vertices[0][1]
    if index == len(vertices) - 1:
        return vertices[index][0] - vertices[index - 1][0], vertices[index][1] - vertices[index - 1][1]
    incoming = _unit_vector(
        vertices[index][0] - vertices[index - 1][0],
        vertices[index][1] - vertices[index - 1][1],
    )
    outgoing = _unit_vector(
        vertices[index + 1][0] - vertices[index][0],
        vertices[index + 1][1] - vertices[index][1],
    )
    return incoming[0] + outgoing[0], incoming[1] + outgoing[1]


def _offset_vertex(
    vertex: tuple[float, float],
    direction: tuple[float, float],
    offset: float,
) -> tuple[float, float] | None:
    dx, dy = direction
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-9:
        return None
    return vertex[0] - (dy / length) * offset, vertex[1] + (dx / length) * offset


def _parallel_offset(
    vertices: list[tuple[float, float]],
    offset: float,
) -> list[tuple[float, float]]:
    """Create a parallel trace offset by *offset* mm."""
    if len(vertices) <= 1:
        return vertices[:]
    result: list[tuple[float, float]] = []
    for index, vertex in enumerate(vertices):
        offset_vertex = _offset_vertex(vertex, _vertex_direction(vertices, index), offset)
        if offset_vertex is not None:
            result.append(offset_vertex)
        elif result:
            result.append(result[-1])
        else:
            result.append(vertex)
    return result


# ---------------------------------------------------------------------------
# Length matching / meanders
# ---------------------------------------------------------------------------


def _path_length(vertices: list[tuple[float, float]]) -> float:
    """Compute total path length in mm."""
    return sum(math.dist(vertices[i], vertices[i + 1]) for i in range(len(vertices) - 1))


def _traces_to_vertices(traces: list[TraceSegment]) -> list[tuple[float, float]]:
    """Extract ordered vertices from a list of trace segments.

    Assumes the segments form a continuous chain (result of _order_chain).
    """
    if not traces:
        return []
    vertices: list[tuple[float, float]] = [traces[0].start]
    for t in traces:
        # Avoid duplicate vertices
        last = vertices[-1]
        d1 = math.dist(last, t.start)
        math.dist(last, t.end)
        if d1 > 0.0001:
            vertices.append(t.start)
        vertices.append(t.end)
    return _dedupe_vertices(vertices)


def _dedupe_vertices(
    vertices: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Remove consecutive duplicate vertices."""
    if not vertices:
        return []
    result: list[tuple[float, float]] = [vertices[0]]
    for v in vertices[1:]:
        if math.dist(result[-1], v) > 0.0001:
            result.append(v)
    return result


def _add_meanders(
    vertices: list[tuple[float, float]],
    target_length: float,
    amplitude: float,
    min_segment_len: float = 3.0,
) -> list[tuple[float, float]]:
    """Insert meander patterns to increase path length to *target_length*.

    Meanders are added to the longest straight segment in the path.
    Each meander adds ``4 * amplitude`` of extra length per tooth.
    """
    current_len = _path_length(vertices)
    needed = target_length - current_len
    if needed <= 0:
        return vertices

    # Find the longest straight segment
    best_idx = -1
    best_len = 0.0
    for i in range(len(vertices) - 1):
        seg_len = math.dist(vertices[i], vertices[i + 1])
        if seg_len >= min_segment_len and seg_len > best_len:
            best_len = seg_len
            best_idx = i

    if best_idx < 0:
        return vertices  # no suitable segment

    # Compute tooth count
    tooth_extra = 4.0 * amplitude  # extra length per full meander tooth
    num_teeth = max(1, int(math.ceil(needed / tooth_extra)))

    # Clamp total meander length to not exceed the segment
    meander_len = min(best_len * 0.8, num_teeth * (amplitude * 2))
    num_teeth = max(1, int(meander_len / (amplitude * 2)))

    # Direction of the segment
    p0 = vertices[best_idx]
    p1 = vertices[best_idx + 1]
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    seg_len = math.sqrt(dx * dx + dy * dy)
    if seg_len < 1e-9:
        return vertices

    ux = dx / seg_len
    uy = dy / seg_len

    # Perpendicular direction
    nx = -uy
    ny = ux

    # Build meandered segment
    tooth_spacing = meander_len / num_teeth
    meandered: list[tuple[float, float]] = [p0]

    for tooth in range(num_teeth):
        t_start = tooth * tooth_spacing
        t_mid = t_start + tooth_spacing * 0.5
        t_end = (tooth + 1) * tooth_spacing

        # Go forward
        mid_fwd = (
            p0[0] + ux * t_mid + nx * amplitude,
            p0[1] + uy * t_mid + ny * amplitude,
        )
        mid_back = (
            p0[0] + ux * t_mid - nx * amplitude,
            p0[1] + uy * t_mid - ny * amplitude,
        )

        meandered.append((p0[0] + ux * (t_start + tooth_spacing * 0.25), p0[1] + uy * (t_start + tooth_spacing * 0.25)))
        meandered.append(mid_fwd)
        meandered.append(mid_back)
        meandered.append((p0[0] + ux * (t_end - tooth_spacing * 0.25), p0[1] + uy * (t_end - tooth_spacing * 0.25)))

    meandered.append(p1)

    # Rebuild full vertex list
    result = vertices[:best_idx] + meandered + vertices[best_idx + 1 :]
    return _dedupe_vertices(result)


# ---------------------------------------------------------------------------
# Helper: single-net design
# ---------------------------------------------------------------------------


def _design_for_net(
    design: Design,
    net_id: str,
) -> Design:
    """Create a minimal design containing only *net_id* for routing.

    Includes only the components referenced by the net nodes so the
    grid router can resolve node positions.
    """
    net = design.nets.get(net_id)
    if net is None:
        return Design(meta=design.meta.model_copy())

    # Collect components referenced by this net
    referenced_refs = {node.component_ref for node in net.nodes}
    comps = {cid: c for cid, c in design.components.items() if c.ref in referenced_refs}

    return Design(
        meta=design.meta.model_copy(),
        nets={net_id: net},
        components=comps,
        board=design.board,
        board_def=design.board_def,
    )
