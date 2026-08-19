"""Arc fillet post-processor for PCB traces.

Turns sharp 45°/90° routing corners into smooth circular arcs,
improving signal integrity, manufacturability, and aesthetic quality.

Usage::

    from zaptrace.algo.fillet import apply_fillets

    result.traces = apply_fillets(
        result.traces,
        default_radius=0.5,    # global max fillet radius
        segments_per_arc=8,    # polyline approximation quality
    )
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from zaptrace.core.models import TraceSegment

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ANGLE_EPSILON = math.radians(10)  # skip near-straight joints
_MIN_RADIUS_MM = 0.05  # below this, fillet is skipped
_TANGENT_CLIP_RATIO = 0.40  # max tangent-dist as fraction of segment length


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_fillets(
    traces: list[TraceSegment],
    default_radius: float = 0.5,
    segments_per_arc: int = 8,
    min_radius: float = _MIN_RADIUS_MM,
    max_radius: float | None = None,
    radius_scale: float = 2.5,
    min_angle_deg: float = 15.0,
) -> list[TraceSegment]:
    """Apply arc fillets to every corner in the given traces.

    Parameters
    ----------
    traces:
        Input trace segments (typically from ``RouteResult.traces``).
    default_radius:
        Maximum fillet radius in mm.  Actual radius may be smaller
        if the corner is too tight or the segments too short.
    segments_per_arc:
        Number of linear segments used to approximate each arc.  Higher
        values create smoother curves.
    min_radius:
        Skip corners where the computed radius would be below this
        threshold.
    max_radius:
        Absolute maximum radius override. If ``None``, uses
        *default_radius*.
    radius_scale:
        Fillet radius as a multiple of the trace width at the corner.
        The actual radius is ``min(default_radius, width * radius_scale)``.
    min_angle_deg:
        Minimum corner angle in degrees.  Corners sharper than this
        (i.e., with an internal angle below *min_angle_deg*) are filleted;
        near-straight joints are left as-is.

    Returns
    -------
    list[TraceSegment]:
        New trace list with fillets applied.  Original segments may be
        shortened and new arc-approximation segments inserted.
    """
    if not traces:
        return []

    if max_radius is None:
        max_radius = default_radius

    # Group traces by net and layer for connected-path analysis
    groups: dict[str, list[TraceSegment]] = defaultdict(list)
    for t in traces:
        groups[t.net_id].append(t)

    result: list[TraceSegment] = []
    for _net_id, group in groups.items():
        # Build connection graph: endpoint -> list of trace indices
        endpoint_map: dict[tuple[float, float, str], list[int]] = defaultdict(list)
        for idx, seg in enumerate(group):
            if not seg.net_id:
                continue
            sig = (round(seg.start[0], 6), round(seg.start[1], 6), seg.layer)
            endpoint_map[sig].append(idx)
            eig = (round(seg.end[0], 6), round(seg.end[1], 6), seg.layer)
            endpoint_map[eig].append(idx)

        processed: set[int] = set()

        for idx, _seg in enumerate(group):
            if idx in processed:
                continue

            # Walk the segment chain
            chain = _walk_chain(group, idx, endpoint_map, processed)
            filleted = _fillet_chain(
                chain,
                default_radius=default_radius,
                segments_per_arc=segments_per_arc,
                min_radius=min_radius,
                max_radius=max_radius,
                radius_scale=radius_scale,
                min_angle_deg=min_angle_deg,
            )
            result.extend(filleted)

    return result


# ---------------------------------------------------------------------------
# Chain walking
# ---------------------------------------------------------------------------


def _walk_chain(
    group: list[TraceSegment],
    start_idx: int,
    endpoint_map: dict[tuple[float, float, str], list[int]],
    processed: set[int],
) -> list[TraceSegment]:
    """Walk a connected chain of trace segments starting at *start_idx*.

    Returns the chain as an ordered list of segments (head-to-tail).
    """
    chain: list[TraceSegment] = []
    visited: set[int] = {start_idx}
    queue: list[int] = [start_idx]

    while queue:
        idx = queue.pop(0)
        if idx in processed:
            continue
        processed.add(idx)
        chain.append(group[idx])

        for end_key in [
            (
                round(group[idx].start[0], 6),
                round(group[idx].start[1], 6),
                group[idx].layer,
            ),
            (
                round(group[idx].end[0], 6),
                round(group[idx].end[1], 6),
                group[idx].layer,
            ),
        ]:
            for nidx in endpoint_map.get(end_key, []):
                if nidx not in visited and nidx not in processed:
                    visited.add(nidx)
                    queue.append(nidx)

    # Sort chain into head-to-tail order
    if len(chain) <= 1:
        return chain

    return _order_chain(chain)


def _endpoint_key(point: tuple[float, float], layer: str) -> tuple[float, float, str]:
    return (round(point[0], 6), round(point[1], 6), layer)


def _chain_endpoint_info(
    chain: list[TraceSegment],
) -> dict[tuple[float, float, str], list[tuple[int, bool]]]:
    endpoint_info: dict[tuple[float, float, str], list[tuple[int, bool]]] = defaultdict(list)
    for index, segment in enumerate(chain):
        endpoint_info[_endpoint_key(segment.start, segment.layer)].append((index, True))
        endpoint_info[_endpoint_key(segment.end, segment.layer)].append((index, False))
    return endpoint_info


def _chain_start(
    endpoint_info: dict[tuple[float, float, str], list[tuple[int, bool]]],
) -> tuple[int, bool]:
    for connections in endpoint_info.values():
        if len(connections) == 1:
            return connections[0]
    return 0, True


def _next_chain_segment(
    chain: list[TraceSegment],
    used: set[int],
    current_end: tuple[float, float, str],
) -> tuple[int, TraceSegment, tuple[float, float, str]] | None:
    for index, segment in enumerate(chain):
        if index in used:
            continue
        start_key = _endpoint_key(segment.start, segment.layer)
        end_key = _endpoint_key(segment.end, segment.layer)
        if start_key == current_end:
            return index, segment, end_key
        if end_key == current_end:
            return index, _reversed_seg(segment), start_key
    return None


def _order_chain(chain: list[TraceSegment]) -> list[TraceSegment]:
    """Topological sort of connected segments into a continuous path.

    Works for simple chains (no branches). For branched nets, each branch is
    handled independently by the caller via the endpoint map.
    """
    if len(chain) <= 1:
        return chain

    start_index, forward = _chain_start(_chain_endpoint_info(chain))
    first = chain[start_index] if forward else _reversed_seg(chain[start_index])
    ordered = [first]
    used = {start_index}
    current_end = _endpoint_key(first.end, first.layer)

    while len(ordered) < len(chain):
        next_segment = _next_chain_segment(chain, used, current_end)
        if next_segment is None:
            break
        index, segment, current_end = next_segment
        ordered.append(segment)
        used.add(index)

    return ordered


def _reversed_seg(s: TraceSegment) -> TraceSegment:
    """Return a copy of *s* with start/end swapped."""
    return TraceSegment(
        layer=s.layer,
        start=s.end,
        end=s.start,
        width=s.width,
        net_id=s.net_id,
    )


@dataclass(frozen=True)
class _FilletGeometry:
    tangent_in: tuple[float, float]
    tangent_out: tuple[float, float]
    center: tuple[float, float]
    radius: float
    trace_width: float


def _fillet_joint_vectors(
    previous: TraceSegment,
    segment: TraceSegment,
) -> tuple[tuple[float, float], tuple[float, float], float, float] | None:
    incoming = (previous.end[0] - previous.start[0], previous.end[1] - previous.start[1])
    outgoing = (segment.end[0] - segment.start[0], segment.end[1] - segment.start[1])
    incoming_length = math.sqrt(incoming[0] ** 2 + incoming[1] ** 2)
    outgoing_length = math.sqrt(outgoing[0] ** 2 + outgoing[1] ** 2)
    if incoming_length < 1e-9 or outgoing_length < 1e-9:
        return None
    incoming_unit = (incoming[0] / incoming_length, incoming[1] / incoming_length)
    outgoing_unit = (outgoing[0] / outgoing_length, outgoing[1] / outgoing_length)
    return incoming_unit, outgoing_unit, incoming_length, outgoing_length


@dataclass(frozen=True)
class _FilletJoint:
    point: tuple[float, float]
    incoming_unit: tuple[float, float]
    outgoing_unit: tuple[float, float]
    inverse_incoming: tuple[float, float]
    incoming_length: float
    outgoing_length: float
    internal_angle: float


def _eligible_fillet_joint(
    previous: TraceSegment,
    segment: TraceSegment,
    min_angle_rad: float,
) -> _FilletJoint | None:
    if previous.layer != segment.layer:
        return None
    point = (round(previous.end[0], 6), round(previous.end[1], 6))
    if point != (round(segment.start[0], 6), round(segment.start[1], 6)):
        return None
    vectors = _fillet_joint_vectors(previous, segment)
    if vectors is None:
        return None
    incoming_unit, outgoing_unit, incoming_length, outgoing_length = vectors
    inverse_incoming = (-incoming_unit[0], -incoming_unit[1])
    cosine = inverse_incoming[0] * outgoing_unit[0] + inverse_incoming[1] * outgoing_unit[1]
    theta = math.acos(max(-1.0, min(1.0, cosine)))
    if theta < min_angle_rad or theta > math.pi - min_angle_rad:
        return None
    internal_angle = math.pi - theta
    if internal_angle < math.radians(5):
        return None
    return _FilletJoint(
        point, incoming_unit, outgoing_unit, inverse_incoming, incoming_length, outgoing_length, internal_angle
    )


def _fillet_radius_tangent(
    previous: TraceSegment,
    segment: TraceSegment,
    joint: _FilletJoint,
    *,
    default_radius: float,
    min_radius: float,
    max_radius: float,
    radius_scale: float,
) -> tuple[float, float, float] | None:
    trace_width = max(previous.width, segment.width, 0.01)
    radius = min(default_radius, trace_width * radius_scale)
    radius = min(radius, max_radius)
    tangent_half = math.tan(joint.internal_angle / 2.0)
    if tangent_half < 1e-9:
        return None
    tangent_distance = radius / tangent_half
    ratio = min(
        (joint.incoming_length * _TANGENT_CLIP_RATIO) / tangent_distance,
        (joint.outgoing_length * _TANGENT_CLIP_RATIO) / tangent_distance,
        1.0,
    )
    if ratio < 0.01:
        return None
    tangent_distance *= ratio
    radius *= ratio
    if radius < min_radius:
        return None
    return radius, tangent_distance, trace_width


def _fillet_center_geometry(
    previous: TraceSegment,
    segment: TraceSegment,
    joint: _FilletJoint,
    radius: float,
    tangent_distance: float,
    trace_width: float,
) -> _FilletGeometry | None:
    tangent_in = (
        previous.end[0] - joint.incoming_unit[0] * tangent_distance,
        previous.end[1] - joint.incoming_unit[1] * tangent_distance,
    )
    tangent_out = (
        segment.start[0] + joint.outgoing_unit[0] * tangent_distance,
        segment.start[1] + joint.outgoing_unit[1] * tangent_distance,
    )
    bisector = (
        joint.inverse_incoming[0] + joint.outgoing_unit[0],
        joint.inverse_incoming[1] + joint.outgoing_unit[1],
    )
    bisector_length = math.sqrt(bisector[0] ** 2 + bisector[1] ** 2)
    if bisector_length < 1e-9:
        return None
    bisector_unit = (bisector[0] / bisector_length, bisector[1] / bisector_length)
    sine_half = math.sin(joint.internal_angle / 2.0)
    center_distance = radius / sine_half if sine_half > 1e-9 else 0.0
    center = (
        joint.point[0] + bisector_unit[0] * center_distance,
        joint.point[1] + bisector_unit[1] * center_distance,
    )
    return _FilletGeometry(tangent_in, tangent_out, center, radius, trace_width)


def _fillet_geometry(
    previous: TraceSegment,
    segment: TraceSegment,
    *,
    default_radius: float,
    min_radius: float,
    max_radius: float,
    radius_scale: float,
    min_angle_rad: float,
) -> _FilletGeometry | None:
    joint = _eligible_fillet_joint(previous, segment, min_angle_rad)
    if joint is None:
        return None
    radius_tangent = _fillet_radius_tangent(
        previous,
        segment,
        joint,
        default_radius=default_radius,
        min_radius=min_radius,
        max_radius=max_radius,
        radius_scale=radius_scale,
    )
    if radius_tangent is None:
        return None
    radius, tangent_distance, trace_width = radius_tangent
    return _fillet_center_geometry(previous, segment, joint, radius, tangent_distance, trace_width)


def _emit_fillet_segments(
    previous: TraceSegment,
    segment: TraceSegment,
    geometry: _FilletGeometry,
    segments_per_arc: int,
) -> list[TraceSegment]:
    emitted: list[TraceSegment] = []
    if math.dist(previous.start, geometry.tangent_in) > 1e-6:
        emitted.append(
            TraceSegment(
                layer=previous.layer,
                start=previous.start,
                end=geometry.tangent_in,
                width=previous.width,
                net_id=previous.net_id,
            )
        )
    emitted.extend(
        _approx_arc(
            center=geometry.center,
            t1=geometry.tangent_in,
            t2=geometry.tangent_out,
            r=geometry.radius,
            n_segments=segments_per_arc,
            width=geometry.trace_width,
            net_id=previous.net_id,
            layer=previous.layer,
        )
    )
    emitted.append(
        TraceSegment(
            layer=segment.layer,
            start=geometry.tangent_out,
            end=segment.end,
            width=segment.width,
            net_id=segment.net_id,
        )
    )
    return emitted


# ---------------------------------------------------------------------------
# Fillet computation
# ---------------------------------------------------------------------------


def _fillet_chain(
    chain: list[TraceSegment],
    default_radius: float = 0.5,
    segments_per_arc: int = 8,
    min_radius: float = _MIN_RADIUS_MM,
    max_radius: float = 0.5,
    radius_scale: float = 2.5,
    min_angle_deg: float = 15.0,
) -> list[TraceSegment]:
    """Apply fillets to all corners in a single trace chain."""
    if not chain:
        return []
    result: list[TraceSegment] = []
    previous: TraceSegment | None = None
    min_angle_rad = math.radians(min_angle_deg)
    for segment in chain:
        if previous is None:
            previous = segment
            continue
        geometry = _fillet_geometry(
            previous,
            segment,
            default_radius=default_radius,
            min_radius=min_radius,
            max_radius=max_radius,
            radius_scale=radius_scale,
            min_angle_rad=min_angle_rad,
        )
        if geometry is None:
            result.append(previous)
            previous = segment
            continue
        result.extend(_emit_fillet_segments(previous, segment, geometry, segments_per_arc))
        previous = None
    if previous is not None:
        result.append(previous)
    return result


# ---------------------------------------------------------------------------
# Arc approximation
# ---------------------------------------------------------------------------


def _approx_arc(
    center: tuple[float, float],
    t1: tuple[float, float],
    t2: tuple[float, float],
    r: float,
    n_segments: int,
    width: float,
    net_id: str,
    layer: str,
) -> list[TraceSegment]:
    """Approximate a circular arc as *n_segments* linear segments."""
    rel1 = (t1[0] - center[0], t1[1] - center[1])
    rel2 = (t2[0] - center[0], t2[1] - center[1])

    a1 = math.atan2(rel1[1], rel1[0])
    a2 = math.atan2(rel2[1], rel2[0])

    # Compute shortest-arc sweep from T1 to T2.
    # The arc centre lies on the inside of the corner (via the bisector),
    # so the shortest angular path from T1 to T2 is the correct fillet arc.
    sweep = (a2 - a1) % (2.0 * math.pi)
    if sweep > math.pi:
        sweep -= 2.0 * math.pi
    if abs(sweep) < 1e-6:
        return []

    segments: list[TraceSegment] = []
    n = max(n_segments, 2)

    for i in range(n):
        frac = (i + 1) / n
        angle = a1 + sweep * frac
        px = center[0] + r * math.cos(angle)
        py = center[1] + r * math.sin(angle)

        prev_frac = i / n
        prev_angle = a1 + sweep * prev_frac
        ppx = center[0] + r * math.cos(prev_angle)
        ppy = center[1] + r * math.sin(prev_angle)

        if math.dist((ppx, ppy), (px, py)) > 1e-6:
            segments.append(
                TraceSegment(
                    layer=layer,
                    start=(round(ppx, 3), round(ppy, 3)),
                    end=(round(px, 3), round(py, 3)),
                    width=width,
                    net_id=net_id,
                )
            )

    return segments
