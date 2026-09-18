from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from zaptrace.algo.pad_escape import RouteEvidenceScorecard, compute_escape_point
from zaptrace.core.models import Component, Design, Net, RouteResult, TraceSegment
from zaptrace.ee.classifier import classify_design, get_net_class
from zaptrace.ee.knowledge import KnowledgeBase

logger = logging.getLogger(__name__)

_ZERO_LENGTH_TOLERANCE_MM = 1e-9
_CORNER_CHAMFER_MM = 0.2


@dataclass
class RouteSegment:
    x1: float
    y1: float
    x2: float
    y2: float
    net_name: str
    layer: int = 0
    width_mm: float = 0.2


@dataclass
class RoutingResult:
    segments: list[RouteSegment]
    routed_nets: int
    total_nets: int
    unrouted_nets: list[str]

    @property
    def coverage_pct(self) -> float:
        if self.total_nets == 0:
            return 100.0
        return round(self.routed_nets / self.total_nets * 100, 1)


def _route_component_lookups(
    design: Design,
    positions: dict[str, tuple[float, float]],
) -> tuple[dict[str, Component], dict[str, tuple[float, float]]]:
    component_by_ref: dict[str, Component] = {}
    ref_positions: dict[str, tuple[float, float]] = {}
    for component in design.components.values():
        component_by_ref[component.ref] = component
        if component.id in positions:
            ref_positions[component.ref] = positions[component.id]
        if component.ref in positions:
            ref_positions[component.ref] = positions[component.ref]
    return component_by_ref, ref_positions


def _net_escape_positions(
    net: Net,
    component_by_ref: dict[str, Component],
    ref_positions: dict[str, tuple[float, float]],
) -> list[tuple[float, float]]:
    node_positions: list[tuple[float, float]] = []
    for node in net.nodes:
        component_position = ref_positions.get(node.component_ref)
        if component_position is None:
            continue
        component = component_by_ref.get(node.component_ref)
        if component is None:
            node_positions.append(component_position)
            continue
        evidence = compute_escape_point(component, node.pin_name, component_position)
        node_positions.append(evidence.escape_point)
    return node_positions


def route_nets(design: Design, positions: dict[str, tuple[float, float]]) -> RoutingResult:
    """Route all nets using pad-aware Manhattan L-shaped routing."""
    segments: list[RouteSegment] = []
    routed = 0
    unrouted: list[str] = []
    total = 0
    component_by_ref, ref_positions = _route_component_lookups(design, positions)

    for net in design.nets.values():
        node_positions = _net_escape_positions(net, component_by_ref, ref_positions)
        if len(node_positions) < 2:
            continue
        total += 1
        try:
            segments.extend(_route_net_mst(node_positions, net.name))
            routed += 1
        except Exception:
            logger.warning("Failed to route net %s; marking unrouted", net.name, exc_info=True)
            unrouted.append(net.name)

    return RoutingResult(
        segments=segments,
        routed_nets=routed,
        total_nets=total,
        unrouted_nets=unrouted,
    )


def _is_zero_length(x1: float, y1: float, x2: float, y2: float) -> bool:
    return math.hypot(x2 - x1, y2 - y1) <= _ZERO_LENGTH_TOLERANCE_MM


def _append_segment_if_nonzero(
    segments: list[RouteSegment],
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    net_name: str,
) -> None:
    """Append a segment unless it has zero physical length.

    The Manhattan router may encounter aligned endpoints or duplicate synthetic
    escape points. Emitting zero-length copper creates artificial DRC/clearance
    hits downstream without representing real routed copper.
    """
    if _is_zero_length(x1, y1, x2, y2):
        return
    segments.append(RouteSegment(x1, y1, x2, y2, net_name))


def _prefer_vertical_first(net_name: str) -> bool:
    """Return a stable Manhattan corner orientation for a net.

    Power rails, ground, and SDA-style data nets often benefit from vertical
    escapes in compact sensor-node layouts, while SCL/SCK-style clock nets keep
    the legacy horizontal-first path.  Unknown nets use a deterministic fallback
    so output is stable without hard-coding a board-specific lookup table.
    """
    normalized = net_name.casefold()
    tokens = normalized.replace("-", "_").split("_")
    if any(token in {"gnd", "ground", "vss"} for token in tokens):
        return True
    if normalized.startswith(("vcc", "vdd", "vbus", "vin")) or normalized.endswith(("_vcc", "_vdd")):
        return True
    if any(token in {"sda", "mosi", "data"} for token in tokens):
        return True
    if any(token in {"scl", "sck", "clk", "clock"} for token in tokens):
        return False
    seed = sum((idx + 1) * ord(ch) for idx, ch in enumerate(net_name))
    return seed % 2 == 1


def _route_manhattan_edge(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    net_name: str,
    *,
    vertical_first: bool | None = None,
) -> list[RouteSegment]:
    """Route one MST edge as non-zero chamfered Manhattan segments."""
    segments: list[RouteSegment] = []
    if _is_zero_length(x1, y1, x2, y2):
        return segments
    if math.isclose(x1, x2, abs_tol=_ZERO_LENGTH_TOLERANCE_MM) or math.isclose(
        y1, y2, abs_tol=_ZERO_LENGTH_TOLERANCE_MM
    ):
        _append_segment_if_nonzero(segments, x1, y1, x2, y2, net_name)
        return segments

    use_vertical_first = _prefer_vertical_first(net_name) if vertical_first is None else vertical_first
    dx = x2 - x1
    dy = y2 - y1
    sx = 1.0 if dx > 0 else -1.0
    sy = 1.0 if dy > 0 else -1.0
    chamfer = min(_CORNER_CHAMFER_MM, abs(dx) / 2.0, abs(dy) / 2.0)

    if use_vertical_first:
        corner_entry = (x1, y2 - sy * chamfer)
        corner_exit = (x1 + sx * chamfer, y2)
        points = [(x1, y1), corner_entry, corner_exit, (x2, y2)]
    else:
        corner_entry = (x2 - sx * chamfer, y1)
        corner_exit = (x2, y1 + sy * chamfer)
        points = [(x1, y1), corner_entry, corner_exit, (x2, y2)]

    for start, end in zip(points, points[1:], strict=False):
        _append_segment_if_nonzero(segments, start[0], start[1], end[0], end[1], net_name)
    return segments


def _route_segment_length(seg: RouteSegment) -> float:
    return math.hypot(seg.x2 - seg.x1, seg.y2 - seg.y1)


def _to_trace_segment(seg: RouteSegment, width_mm: float, net_id: str, layer: str) -> TraceSegment:
    return TraceSegment(
        layer=layer,
        start=(seg.x1, seg.y1),
        end=(seg.x2, seg.y2),
        width=width_mm,
        net_id=net_id,
    )


def _point_segment_distance(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    denom = dx * dx + dy * dy
    if denom <= 0.0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / denom))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def _segment_distance(a: TraceSegment, b: TraceSegment) -> float:
    return min(
        _point_segment_distance(a.start, b.start, b.end),
        _point_segment_distance(a.end, b.start, b.end),
        _point_segment_distance(b.start, a.start, a.end),
        _point_segment_distance(b.end, a.start, a.end),
    )


def _dogleg_route_x(x1: float, y1: float, x2: float, y2: float, net_name: str, offset: float) -> list[RouteSegment]:
    segments: list[RouteSegment] = []
    if _is_zero_length(x1, y1, x2, y2):
        return segments
    if math.isclose(x1, x2, abs_tol=_ZERO_LENGTH_TOLERANCE_MM) or math.isclose(
        y1, y2, abs_tol=_ZERO_LENGTH_TOLERANCE_MM
    ):
        _append_segment_if_nonzero(segments, x1, y1, x2, y2, net_name)
        return segments
    x_lane = (x1 + x2) / 2.0 + offset
    _append_segment_if_nonzero(segments, x1, y1, x_lane, y1, net_name)
    _append_segment_if_nonzero(segments, x_lane, y1, x_lane, y2, net_name)
    _append_segment_if_nonzero(segments, x_lane, y2, x2, y2, net_name)
    return segments


def _dogleg_route_y(x1: float, y1: float, x2: float, y2: float, net_name: str, offset: float) -> list[RouteSegment]:
    segments: list[RouteSegment] = []
    if _is_zero_length(x1, y1, x2, y2):
        return segments
    if math.isclose(x1, x2, abs_tol=_ZERO_LENGTH_TOLERANCE_MM) or math.isclose(
        y1, y2, abs_tol=_ZERO_LENGTH_TOLERANCE_MM
    ):
        _append_segment_if_nonzero(segments, x1, y1, x2, y2, net_name)
        return segments
    y_lane = (y1 + y2) / 2.0 + offset
    _append_segment_if_nonzero(segments, x1, y1, x1, y_lane, net_name)
    _append_segment_if_nonzero(segments, x1, y_lane, x2, y_lane, net_name)
    _append_segment_if_nonzero(segments, x2, y_lane, x2, y2, net_name)
    return segments


def _route_edge_candidates(x1: float, y1: float, x2: float, y2: float, net_name: str) -> list[list[RouteSegment]]:
    preferred = _prefer_vertical_first(net_name)
    candidates = [
        _route_manhattan_edge(x1, y1, x2, y2, net_name, vertical_first=preferred),
        _route_manhattan_edge(x1, y1, x2, y2, net_name, vertical_first=not preferred),
    ]
    for offset in (-1.2, -0.8, -0.4, 0.4, 0.8, 1.2):
        candidates.append(_dogleg_route_x(x1, y1, x2, y2, net_name, offset))
        candidates.append(_dogleg_route_y(x1, y1, x2, y2, net_name, offset))
    return [candidate for candidate in candidates if candidate]


def _segment_endpoints(segment: RouteSegment | TraceSegment) -> tuple[tuple[float, float], tuple[float, float]]:
    if isinstance(segment, RouteSegment):
        return (segment.x1, segment.y1), (segment.x2, segment.y2)
    return segment.start, segment.end


def _shared_endpoint(
    first: RouteSegment | TraceSegment,
    second: RouteSegment | TraceSegment,
) -> tuple[float, float] | None:
    first_start, first_end = _segment_endpoints(first)
    second_start, second_end = _segment_endpoints(second)
    for first_point in (first_start, first_end):
        for second_point in (second_start, second_end):
            if math.dist(first_point, second_point) < 0.001:
                return first_point
    return None


def _other_endpoint(
    segment: RouteSegment | TraceSegment,
    shared: tuple[float, float],
) -> tuple[float, float]:
    start, end = _segment_endpoints(segment)
    return end if math.dist(shared, start) < 0.001 else start


def _right_angle_joint(
    first: RouteSegment | TraceSegment,
    second: RouteSegment | TraceSegment,
    shared: tuple[float, float],
) -> bool:
    first_other = _other_endpoint(first, shared)
    second_other = _other_endpoint(second, shared)
    first_vector = (first_other[0] - shared[0], first_other[1] - shared[1])
    second_vector = (second_other[0] - shared[0], second_other[1] - shared[1])
    first_norm = math.hypot(*first_vector)
    second_norm = math.hypot(*second_vector)
    if min(first_norm, second_norm) < 0.3:
        return False
    cosine = ((first_vector[0] * second_vector[0]) + (first_vector[1] * second_vector[1])) / (first_norm * second_norm)
    return abs(cosine) <= 0.0175


def _candidate_junction_right_angles(
    candidate: list[RouteSegment], existing_traces: list[TraceSegment], net_id: str
) -> int:
    count = 0
    candidate_traces = [_to_trace_segment(seg, 0.2, net_id, "F.Cu") for seg in candidate]
    for trace in candidate_traces:
        for existing in existing_traces:
            if existing.net_id != net_id or existing.layer != trace.layer:
                continue
            shared = _shared_endpoint(trace, existing)
            if shared is not None and _right_angle_joint(trace, existing, shared):
                count += 1
    return count


def _candidate_internal_right_angles(candidate: list[RouteSegment]) -> int:
    count = 0
    for index, first in enumerate(candidate):
        for second in candidate[index + 1 :]:
            shared = _shared_endpoint(first, second)
            if shared is not None and _right_angle_joint(first, second, shared):
                count += 1
    return count


def _score_route_candidate(
    candidate: list[RouteSegment],
    existing_traces: list[TraceSegment],
    *,
    width_mm: float,
    net_id: str,
    layer: str,
    clearance_mm: float,
) -> float:
    score = sum(_route_segment_length(seg) for seg in candidate) * 0.05
    score += len(candidate) * 2.0
    score += _candidate_junction_right_angles(candidate, existing_traces, net_id) * 250.0
    score += _candidate_internal_right_angles(candidate) * 80.0
    candidate_traces = [_to_trace_segment(seg, width_mm, net_id, layer) for seg in candidate]
    for trace in candidate_traces:
        for existing in existing_traces:
            if existing.layer != layer or existing.net_id == net_id:
                continue
            gap = _segment_distance(trace, existing) - (trace.width / 2.0) - (existing.width / 2.0)
            if gap < clearance_mm:
                score += 500.0 + (clearance_mm - gap) * 2000.0
            elif gap < clearance_mm + 0.15:
                score += (clearance_mm + 0.15 - gap) * 250.0
    return score


def _route_edge_costed(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    net_name: str,
    *,
    existing_traces: list[TraceSegment],
    width_mm: float,
    net_id: str,
    layer: str,
    clearance_mm: float,
) -> list[RouteSegment]:
    candidates = _route_edge_candidates(x1, y1, x2, y2, net_name)
    if not candidates:
        return []
    return min(
        candidates,
        key=lambda candidate: _score_route_candidate(
            candidate, existing_traces, width_mm=width_mm, net_id=net_id, layer=layer, clearance_mm=clearance_mm
        ),
    )


def _next_mst_edge(positions: list[tuple[float, float]], in_mst: list[bool]) -> tuple[int, int]:
    best_distance = float("inf")
    best_i, best_j = 0, 1
    for i, first_in_tree in enumerate(in_mst):
        if not first_in_tree:
            continue
        for j, second_in_tree in enumerate(in_mst):
            if second_in_tree:
                continue
            dx = positions[i][0] - positions[j][0]
            dy = positions[i][1] - positions[j][1]
            distance = math.sqrt(dx**2 + dy**2)
            if distance < best_distance:
                best_distance, best_i, best_j = distance, i, j
    return best_i, best_j


def _prim_mst_edges(positions: list[tuple[float, float]]) -> list[tuple[int, int]]:
    in_mst = [False] * len(positions)
    in_mst[0] = True
    edges: list[tuple[int, int]] = []
    for _ in range(len(positions) - 1):
        edge = _next_mst_edge(positions, in_mst)
        edges.append(edge)
        in_mst[edge[1]] = True
    return edges


def _route_mst_edge(
    positions: list[tuple[float, float]],
    edge: tuple[int, int],
    net_name: str,
    *,
    routed_traces: list[TraceSegment],
    existing_traces: list[TraceSegment] | None,
    width_mm: float,
    net_id: str,
    layer: str,
    clearance_mm: float,
) -> list[RouteSegment]:
    first, second = edge
    x1, y1 = positions[first]
    x2, y2 = positions[second]
    if existing_traces is None:
        return _route_manhattan_edge(x1, y1, x2, y2, net_name)
    return _route_edge_costed(
        x1,
        y1,
        x2,
        y2,
        net_name,
        existing_traces=routed_traces,
        width_mm=width_mm,
        net_id=net_id,
        layer=layer,
        clearance_mm=clearance_mm,
    )


def _route_net_mst(
    positions: list[tuple[float, float]],
    net_name: str,
    *,
    existing_traces: list[TraceSegment] | None = None,
    width_mm: float = 0.2,
    net_id: str | None = None,
    layer: str = "F.Cu",
    clearance_mm: float = 0.2,
) -> list[RouteSegment]:
    """Build MST via Prim's algorithm, route each edge as Manhattan L-shape."""
    if len(positions) < 2:
        return []

    segments: list[RouteSegment] = []
    routed_traces = list(existing_traces or [])
    route_net_id = net_id or net_name
    for edge in _prim_mst_edges(positions):
        edge_segments = _route_mst_edge(
            positions,
            edge,
            net_name,
            routed_traces=routed_traces,
            existing_traces=existing_traces,
            width_mm=width_mm,
            net_id=route_net_id,
            layer=layer,
            clearance_mm=clearance_mm,
        )
        segments.extend(edge_segments)
        routed_traces.extend(_to_trace_segment(seg, width_mm, route_net_id, layer) for seg in edge_segments)
    return segments


def _has_clearance_debt(
    new_segs: list[RouteSegment],
    existing_segs: list[RouteSegment],
    clearance_mm: float,
) -> bool:
    """Return True if any new segment is estimated to be within *clearance_mm*
    of an existing segment (using axis-aligned bounding-box overlap check).

    This is a conservative approximation — it only detects obvious cases and
    does not replace a full DRC check.
    """
    if not existing_segs or clearance_mm <= 0.0:
        return False

    # Build bounding boxes for existing segments (inflated by clearance)
    def bbox(seg: RouteSegment, margin: float) -> tuple[float, float, float, float]:
        x_min = min(seg.x1, seg.x2) - margin
        x_max = max(seg.x1, seg.x2) + margin
        y_min = min(seg.y1, seg.y2) - margin
        y_max = max(seg.y1, seg.y2) + margin
        return (x_min, x_max, y_min, y_max)

    existing_boxes = [bbox(s, clearance_mm) for s in existing_segs]

    for ns in new_segs:
        nx1, nx2 = min(ns.x1, ns.x2), max(ns.x1, ns.x2)
        ny1, ny2 = min(ns.y1, ns.y2), max(ns.y1, ns.y2)
        for ex_min, ex_max, ey_min, ey_max in existing_boxes:
            if nx1 <= ex_max and nx2 >= ex_min and ny1 <= ey_max and ny2 >= ey_min:
                return True
    return False


# ---------------------------------------------------------------------------
# Net-class-aware routing — extends route_nets with EE knowledge
# ---------------------------------------------------------------------------


@dataclass
class _NetEscapeResolution:
    positions: list[tuple[float, float]]
    fallback_refs: list[str]
    fallback_reasons: list[str]


@dataclass
class _SmartRoutingState:
    segments: list[RouteSegment]
    traces: list[TraceSegment]
    routed: int = 0
    total: int = 0
    total_length: float = 0.0
    unrouted: list[str] = field(default_factory=list)


def _resolve_smart_net_escapes(
    net: Net,
    component_by_ref: dict[str, Component],
    ref_positions: dict[str, tuple[float, float]],
    scorecard: RouteEvidenceScorecard,
) -> _NetEscapeResolution:
    positions: list[tuple[float, float]] = []
    fallback_refs: list[str] = []
    fallback_reasons: list[str] = []
    for node in net.nodes:
        component_position = ref_positions.get(node.component_ref)
        if component_position is None:
            continue
        component = component_by_ref.get(node.component_ref)
        if component is None:
            positions.append(component_position)
            fallback_refs.append(node.component_ref)
            fallback_reasons.append("component not found in design")
            continue
        escape = compute_escape_point(component, node.pin_name, component_position)
        positions.append(escape.escape_point)
        scorecard.increment_pad_type(escape.pad_type)
        if escape.is_fallback:
            fallback_refs.append(node.component_ref)
            fallback_reasons.append(escape.fallback_reason)
    return _NetEscapeResolution(positions, fallback_refs, fallback_reasons)


def _route_smart_net_segments(
    design: Design,
    net: Net,
    positions: list[tuple[float, float]],
    traces: list[TraceSegment],
    kb: KnowledgeBase,
    layer: str,
) -> tuple[list[RouteSegment], list[TraceSegment], float, float]:
    rule = kb.get_rule(get_net_class(design, net.id))
    segments = _route_net_mst(
        positions,
        net.name,
        existing_traces=traces,
        width_mm=rule.trace_width,
        net_id=net.id,
        layer=layer,
        clearance_mm=rule.clearance,
    )
    for segment in segments:
        segment.width_mm = rule.trace_width
    new_traces = [_to_trace_segment(segment, rule.trace_width, net.id, layer) for segment in segments]
    length = sum(math.dist(trace.start, trace.end) for trace in new_traces)
    return segments, new_traces, length, rule.clearance


def _process_smart_net(
    design: Design,
    net: Net,
    component_by_ref: dict[str, Component],
    ref_positions: dict[str, tuple[float, float]],
    state: _SmartRoutingState,
    scorecard: RouteEvidenceScorecard,
    kb: KnowledgeBase,
    layer: str,
) -> None:
    resolution = _resolve_smart_net_escapes(net, component_by_ref, ref_positions, scorecard)
    if len(resolution.positions) < 2:
        return
    state.total += 1
    if resolution.fallback_refs:
        scorecard.record_escape_fallback(net.id, net.name, resolution.fallback_refs, resolution.fallback_reasons)
    try:
        segments, traces, length, clearance = _route_smart_net_segments(
            design, net, resolution.positions, state.traces, kb, layer
        )
    except Exception:
        logger.warning("Failed to route net %s; marking unrouted", net.name, exc_info=True)
        state.unrouted.append(net.name)
        scorecard.record_route_failure(net.id, net.name, "MST routing exception")
        return

    previous_segments = list(state.segments)
    state.segments.extend(segments)
    state.traces.extend(traces)
    state.total_length += length
    if _has_clearance_debt(segments, previous_segments, clearance):
        scorecard.record_clearance_debt(
            net.id,
            net.name,
            f"estimated clearance < {clearance}mm on one or more segments",
        )
    state.routed += 1


def _build_smart_results(
    state: _SmartRoutingState,
    scorecard: RouteEvidenceScorecard,
    layer: str,
) -> tuple[RoutingResult, RouteResult, RouteEvidenceScorecard]:
    rounded_length = round(state.total_length, 3)
    scorecard.total_nets = state.total
    scorecard.routed_nets = state.routed
    scorecard.total_length_mm = rounded_length
    return (
        RoutingResult(
            segments=state.segments,
            routed_nets=state.routed,
            total_nets=state.total,
            unrouted_nets=state.unrouted,
        ),
        RouteResult(
            traces=state.traces,
            vias=[],
            layers_used=[layer],
            total_trace_length_mm=rounded_length,
            net_count=state.total,
            routed_net_count=state.routed,
        ),
        scorecard,
    )


def route_design_smart(
    design: Design,
    positions: dict[str, tuple[float, float]],
    kb: KnowledgeBase | None = None,
    layer: str = "F.Cu",
) -> tuple[RoutingResult, RouteResult, RouteEvidenceScorecard]:
    """Route all nets with net-class-aware trace widths and pad escape points."""
    knowledge = kb if kb is not None else KnowledgeBase()
    classify_design(design)
    component_by_ref, ref_positions = _route_component_lookups(design, positions)
    scorecard = RouteEvidenceScorecard(
        non_claims=[
            "route evidence is for engineering review only",
            "not fabrication-ready",
            "DRC debt counts are estimates pending KiCad oracle validation",
        ]
    )
    state = _SmartRoutingState(segments=[], traces=[])
    for net in design.nets.values():
        _process_smart_net(
            design,
            net,
            component_by_ref,
            ref_positions,
            state,
            scorecard,
            knowledge,
            layer,
        )
    return _build_smart_results(state, scorecard, layer)
