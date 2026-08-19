"""DRC (Design Rule Checking) engine.

Performs automated design-rule checks on a :class:`~zaptrace.core.models.Design`
after placement and routing. Each check produces :class:`~zaptrace.core.models.DRCViolation`
objects grouped into a :class:`~zaptrace.core.models.DRCResult`.

Rules implemented:

+--------------+------------------------------------------------+--------+
| Rule ID      | Description                                    | Severity |
+==============+================================================+==========+
| ERC-001      | Unconnected net (0 or 1 node)                  | WARNING  |
| DRC-001      | Clearance violation between traces             | ERROR    |
| DRC-002      | Trace width below net-class minimum            | ERROR    |
| DRC-003      | Right-angle (90°) trace corners                | WARNING  |
| DRC-004      | Stub trace (unconnected end)                   | WARNING  |
| DRC-005      | Net not routed (no traces)                     | ERROR    |
| DRC-006      | Via count exceeds net-class limit              | ERROR    |
| DRC-007      | Annular ring below minimum                     | WARNING  |
| DRC-008      | Overlapping traces on different layers         | INFO     |
| DRC-009      | Solder mask sliver below minimum               | WARNING  |
| DRC-010      | Net missing net-class classification           | INFO     |
| DRC-011      | Component placed outside board boundary        | ERROR    |
| DRC-012      | IPC-2152 current-capacity: trace too narrow    | ERROR    |
| DRC-013      | Hole-to-hole wall clearance below IPC-2221     | ERROR    |
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from zaptrace.core.models import (
    Design,
    DRCResult,
    DRCSeverity,
    DRCViolation,
    Net,
    NetClass,
    RouteResult,
    TraceSegment,
)
from zaptrace.core.net_identity import canonical_routing_net_ids
from zaptrace.ee.classifier import classify_design, get_net_class

if TYPE_CHECKING:
    from zaptrace.fab.profile import FabProfile
from zaptrace.ee.knowledge import KnowledgeBase

# ---------------------------------------------------------------------------
# Type alias for a DRC check function
# ---------------------------------------------------------------------------

DRCCheck = Callable[[Design, KnowledgeBase, DRCResult], list[DRCViolation]]


@dataclass
class DRCEngine:
    """DRC engine — runs configurable checks on a design.

    Usage::

        engine = DRCEngine()
        result = engine.run(design)

    Checks can be selectively enabled/disabled via ``enabled_rules``.
    """

    knowledge_base: KnowledgeBase = field(default_factory=KnowledgeBase)
    enabled_rules: set[str] | None = None
    """If set, only run checks with these rule IDs. ``None`` = run all."""
    fab_profile: FabProfile | None = None
    """If set, DRC also reports fab-profile-specific violations (min trace/space/
    drill/annular ring, via and board limits) from the selected manufacturer
    profile — not just generic clearance. ``None`` = generic geometric DRC only."""

    def run(self, design: Design) -> DRCResult:
        """Run all enabled DRC checks on the design.

        Returns a :class:`DRCResult` with all violations found.
        The result is also stored on ``design.drc_result``.
        """
        result = DRCResult(design_name=design.meta.name)

        # Ensure nets are classified
        if not design.net_classes:
            classify_design(design)

        all_violations: list[DRCViolation] = []

        for check_func in _ALL_CHECKS:
            rule_id = _rule_id(check_func)
            if self.enabled_rules is not None and rule_id not in self.enabled_rules:
                continue
            try:
                violations = check_func(design, self.knowledge_base, result)
                all_violations.extend(violations)
            except Exception as exc:
                all_violations.append(
                    DRCViolation(
                        rule_id=rule_id,
                        severity=DRCSeverity.ERROR,
                        message=f"DRC check crashed: {exc}",
                    )
                )

        # Fold in fab-profile-specific violations (reuses the DFM checker so the
        # profile geometry rules live in one place) when a profile is selected.
        if self.fab_profile is not None:
            from zaptrace.fab.dfm import DFMChecker

            dfm_result = DFMChecker(self.fab_profile).check(design)
            all_violations.extend(dfm_result.to_drc_violations())

        # Sort by severity (errors first)
        severity_order = {DRCSeverity.ERROR: 0, DRCSeverity.WARNING: 1, DRCSeverity.INFO: 2}
        all_violations.sort(key=lambda v: severity_order.get(v.severity, 99))

        result.violations = all_violations
        result.total_violations = len(all_violations)
        result.errors = sum(1 for v in all_violations if v.severity == DRCSeverity.ERROR)
        result.warnings = sum(1 for v in all_violations if v.severity == DRCSeverity.WARNING)
        result.info = sum(1 for v in all_violations if v.severity == DRCSeverity.INFO)
        result.passed = result.errors == 0

        design.drc_result = result
        return result


def _rule_id(func: DRCCheck) -> str:
    """Extract rule ID from a check function's docstring first line."""
    doc = (func.__doc__ or "").strip()
    if doc:
        first_line = doc.split("\n")[0].strip()
        # First line is like: "ERC-001 — Unconnected net ..."
        parts = first_line.split(" ", 1)
        if parts:
            return parts[0].strip("- ")
    return func.__name__


def list_drc_rules() -> list[dict[str, str]]:
    """Return metadata for every registered DRC check."""
    rules: list[dict[str, str]] = []
    for check_func in _ALL_CHECKS:
        first_line = ((check_func.__doc__ or "").strip().splitlines() or [check_func.__name__])[0]
        _, _, description = first_line.partition(" — ")
        rules.append(
            {
                "id": _rule_id(check_func),
                "description": description or first_line,
                "severity": "varies",
            }
        )
    return rules


# ===================================================================
# Individual check implementations
# ===================================================================


def check_unconnected_nets(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """ERC-001 — Unconnected net (0 or 1 node)."""
    vio: list[DRCViolation] = []
    for net_id, net in design.nets.items():
        node_count = len(net.nodes)
        if node_count == 0:
            vio.append(
                DRCViolation(
                    rule_id="ERC-001",
                    severity=DRCSeverity.WARNING,
                    message=f"Net '{net.name}' ({net_id}) has no connected nodes",
                    net_id=net_id,
                )
            )
        elif node_count == 1:
            vio.append(
                DRCViolation(
                    rule_id="ERC-001",
                    severity=DRCSeverity.INFO,
                    message=f"Net '{net.name}' ({net_id}) has only 1 node (unconnected end)",
                    net_id=net_id,
                )
            )
    return vio


# ------------------------------------------------------------------


def _trace_segments(design: Design) -> list[TraceSegment]:
    """Get all trace segments from the design routing result."""
    if design.routing is None:
        return []
    return design.routing.traces


def _vec(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """Vector from a to b."""
    return (b[0] - a[0], b[1] - a[1])


def _dot(u: tuple[float, float], v: tuple[float, float]) -> float:
    return u[0] * v[0] + u[1] * v[1]


def _norm(u: tuple[float, float]) -> float:
    return math.sqrt(u[0] ** 2 + u[1] ** 2)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)


def _segment_min_distance(s1: TraceSegment, s2: TraceSegment) -> float:
    """Minimum distance between two trace segments (center-to-center)."""
    # Simplified: distance between line segments using closest-point approach
    p1, p2 = s1.start, s1.end
    q1, q2 = s2.start, s2.end
    return _segment_segment_distance(p1, p2, q1, q2)


def _segment_segment_distance(
    p1: tuple[float, float],
    p2: tuple[float, float],
    q1: tuple[float, float],
    q2: tuple[float, float],
) -> float:
    """Minimum distance between two 2D line segments using parameter-based approach."""
    # Direction vectors
    u = _vec(p1, p2)
    v = _vec(q1, q2)
    w = _vec(p1, q1)

    a = _dot(u, u)
    b = _dot(u, v)
    c = _dot(v, v)
    d = _dot(u, w)
    e = _dot(v, w)
    D = a * c - b * b

    # Handle parallel segments
    if abs(D) < 1e-12:
        # Compute distance between point p1 and segment (q1,q2), etc.
        d1 = _point_segment_dist(p1, q1, q2)
        d2 = _point_segment_dist(p2, q1, q2)
        d3 = _point_segment_dist(q1, p1, p2)
        d4 = _point_segment_dist(q2, p1, p2)
        return min(d1, d2, d3, d4)

    # Compute the line parameters of the two closest points
    sc = (b * e - c * d) / D
    tc = (a * e - b * d) / D

    # Clamp to segment bounds
    sc = max(0.0, min(1.0, sc))
    tc = max(0.0, min(1.0, tc))

    # Compute closest points
    p_close = (p1[0] + sc * u[0], p1[1] + sc * u[1])
    q_close = (q1[0] + tc * v[0], q1[1] + tc * v[1])

    return _dist(p_close, q_close)


def _point_segment_dist(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Minimum distance from point p to line segment (a,b)."""
    ab = _vec(a, b)
    ap = _vec(a, p)
    t = _dot(ap, ab) / _dot(ab, ab) if _dot(ab, ab) > 0 else 0
    t = max(0.0, min(1.0, t))
    proj = (a[0] + t * ab[0], a[1] + t * ab[1])
    return _dist(p, proj)


def _format_trace_location(seg: TraceSegment) -> str:
    return f"{seg.net_id} ({seg.start[0]:.2f},{seg.start[1]:.2f}) -> ({seg.end[0]:.2f},{seg.end[1]:.2f})"


def _trace_pairs(segments: list[TraceSegment]) -> Iterator[tuple[TraceSegment, TraceSegment]]:
    """Yield trace pairs in the same deterministic order as the legacy nested loops."""
    for index, first in enumerate(segments):
        for second in segments[index + 1 :]:
            yield first, second


def _shared_endpoint(first: TraceSegment, second: TraceSegment) -> tuple[float, float] | None:
    """Return the first shared endpoint using the historical comparison order."""
    for first_point in (first.start, first.end):
        for second_point in (second.start, second.end):
            if _dist(first_point, second_point) < 0.001:
                return first_point
    return None


def _trace_pair_clearance(first: TraceSegment, second: TraceSegment) -> float:
    distance = _segment_min_distance(first, second)
    return distance - (first.width / 2) - (second.width / 2)


def _clearance_contact_key(
    first: TraceSegment,
    second: TraceSegment,
) -> tuple[tuple[str, str], str, float, float] | None:
    shared_contact = _shared_endpoint(first, second)
    if shared_contact is None:
        return None
    ordered_nets = sorted((first.net_id, second.net_id))
    return (
        (ordered_nets[0], ordered_nets[1]),
        first.layer,
        round(shared_contact[0], 3),
        round(shared_contact[1], 3),
    )


def _clearance_violation(
    first: TraceSegment,
    second: TraceSegment,
    *,
    min_clearance: float,
    reported_contacts: set[tuple[tuple[str, str], str, float, float]],
) -> DRCViolation | None:
    if first.net_id == second.net_id or first.layer != second.layer:
        return None
    clearance = _trace_pair_clearance(first, second)
    if clearance >= min_clearance:
        return None
    contact_key = _clearance_contact_key(first, second)
    if contact_key is not None and contact_key in reported_contacts:
        return None
    if contact_key is not None:
        reported_contacts.add(contact_key)
    return DRCViolation(
        rule_id="DRC-001",
        severity=DRCSeverity.ERROR,
        message=(
            f"Clearance violation: net '{first.net_id}' and '{second.net_id}' "
            f"are {clearance:.3f}mm apart (min {min_clearance}mm)"
        ),
        location=f"{first.layer}: {_format_trace_location(first)} | {_format_trace_location(second)}",
        net_id=first.net_id,
    )


def _group_segments_by_net_layer(
    segments: list[TraceSegment],
) -> dict[tuple[str, str], list[TraceSegment]]:
    groups: dict[tuple[str, str], list[TraceSegment]] = defaultdict(list)
    for segment in segments:
        groups[(segment.net_id, segment.layer)].append(segment)
    return groups


def _endpoint_key(net_id: str, layer: str, point: tuple[float, float]) -> tuple[str, str, float, float]:
    return (net_id, layer, round(point[0], 6), round(point[1], 6))


def _endpoint_degrees(
    groups: dict[tuple[str, str], list[TraceSegment]],
) -> dict[tuple[str, str, float, float], int]:
    degrees: dict[tuple[str, str, float, float], int] = defaultdict(int)
    for (net_id, layer), segments in groups.items():
        for segment in segments:
            degrees[_endpoint_key(net_id, layer, segment.start)] += 1
            degrees[_endpoint_key(net_id, layer, segment.end)] += 1
    return degrees


def _vector_from_joint(segment: TraceSegment, shared: tuple[float, float]) -> tuple[float, float]:
    endpoint = segment.end if _dist(shared, segment.start) < 0.001 else segment.start
    return _vec(shared, endpoint)


def _joint_angle_degrees(
    first: TraceSegment,
    second: TraceSegment,
    shared: tuple[float, float],
    *,
    min_segment_length: float,
) -> float | None:
    first_vector = _vector_from_joint(first, shared)
    second_vector = _vector_from_joint(second, shared)
    first_norm = _norm(first_vector)
    second_norm = _norm(second_vector)
    if min(first_norm, second_norm) < min_segment_length:
        return None
    cosine = _dot(first_vector, second_vector) / (first_norm * second_norm)
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


def _simple_trace_joints(
    net_id: str,
    layer: str,
    segments: list[TraceSegment],
    endpoint_degrees: dict[tuple[str, str, float, float], int],
    *,
    min_segment_length: float,
) -> Iterator[tuple[tuple[float, float], float]]:
    for first, second in _trace_pairs(segments):
        shared = _shared_endpoint(first, second)
        if shared is None:
            continue
        if endpoint_degrees[_endpoint_key(net_id, layer, shared)] > 2:
            continue
        angle = _joint_angle_degrees(
            first,
            second,
            shared,
            min_segment_length=min_segment_length,
        )
        if angle is not None:
            yield shared, angle


def check_clearance(design: Design, kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-001 — Clearance violation between traces of different nets."""
    segments = _trace_segments(design)
    min_clearance = design.board.min_clearance_mm if design.board else 0.2
    reported_contacts: set[tuple[tuple[str, str], str, float, float]] = set()
    return [
        violation
        for first, second in _trace_pairs(segments)
        if (
            violation := _clearance_violation(
                first,
                second,
                min_clearance=min_clearance,
                reported_contacts=reported_contacts,
            )
        )
        is not None
    ]


def check_trace_width(design: Design, kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-002 — Trace width below net-class minimum."""
    vio: list[DRCViolation] = []
    for seg in _trace_segments(design):
        nc = get_net_class(design, seg.net_id)
        rule = kb.get_rule(nc)
        if seg.width < rule.trace_width - 0.001:  # small tolerance
            vio.append(
                DRCViolation(
                    rule_id="DRC-002",
                    severity=DRCSeverity.ERROR,
                    message=f"Trace width {seg.width:.3f}mm below {nc.value} minimum "
                    f"{rule.trace_width:.3f}mm on net '{seg.net_id}'",
                    net_id=seg.net_id,
                    location=f"({seg.start[0]:.1f}, {seg.start[1]:.1f}) → ({seg.end[0]:.1f}, {seg.end[1]:.1f})",
                )
            )
    return vio


def check_right_angle(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-003 — Right-angle (90°) trace corners (use 45° or arc)."""
    groups = _group_segments_by_net_layer(_trace_segments(design))
    endpoint_degrees = _endpoint_degrees(groups)
    violations: list[DRCViolation] = []
    for (net_id, layer), segments in groups.items():
        for shared, angle_deg in _simple_trace_joints(
            net_id,
            layer,
            segments,
            endpoint_degrees,
            min_segment_length=0.3,
        ):
            if 89.0 <= abs(angle_deg) <= 91.0:
                violations.append(
                    DRCViolation(
                        rule_id="DRC-003",
                        severity=DRCSeverity.WARNING,
                        message=f"Right-angle corner ({angle_deg:.1f}°) on net '{net_id}' layer {layer}",
                        net_id=net_id,
                        location=f"({shared[0]:.1f}, {shared[1]:.1f})",
                    )
                )
    return violations


def check_unrouted_nets(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-005 — Net not routed (no trace segments)."""
    vio: list[DRCViolation] = []
    if design.routing is None:
        for net_id, net in design.nets.items():
            if len(net.nodes) >= 2:
                vio.append(
                    DRCViolation(
                        rule_id="DRC-005",
                        severity=DRCSeverity.ERROR,
                        message=f"Net '{net.name}' ({net_id}) has no routing traces",
                        net_id=net_id,
                    )
                )
        return vio

    canonical_routing_net_ids(design, design.routing)
    routed_nets = {s.net_id for s in design.routing.traces}
    for net_id, net in design.nets.items():
        if len(net.nodes) >= 2 and net_id not in routed_nets:
            vio.append(
                DRCViolation(
                    rule_id="DRC-005",
                    severity=DRCSeverity.ERROR,
                    message=f"Net '{net.name}' ({net_id}) not routed (no trace segments)",
                    net_id=net_id,
                )
            )
    return vio


def check_via_count(design: Design, kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-006 — Via count exceeds net-class limit."""
    vio: list[DRCViolation] = []
    if design.routing is None:
        return vio

    # Count vias per net
    via_count: dict[str, int] = {}
    for seg in design.routing.traces:
        if seg.via:
            via_count[seg.net_id] = via_count.get(seg.net_id, 0) + 1

    for net_id, count in via_count.items():
        nc = get_net_class(design, net_id)
        rule = kb.get_rule(nc)
        if count > rule.max_vias:
            net_name = design.nets.get(net_id)
            vio.append(
                DRCViolation(
                    rule_id="DRC-006",
                    severity=DRCSeverity.ERROR,
                    message=f"Net '{net_name}' ({net_id}) has {count} vias, "
                    f"exceeds {nc.value} limit of {rule.max_vias}",
                    net_id=net_id,
                )
            )
    return vio


def check_missing_net_class(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-010 — Net missing net-class classification."""
    vio: list[DRCViolation] = []
    if design.net_classes is None:
        return vio
    for net_id, net in design.nets.items():
        if net_id not in design.net_classes:
            vio.append(
                DRCViolation(
                    rule_id="DRC-010",
                    severity=DRCSeverity.INFO,
                    message=f"Net '{net.name}' ({net_id}) has no net-class assignment",
                    net_id=net_id,
                )
            )
    return vio


def check_min_annular_ring(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-020 — Via annular ring below minimum."""
    vio: list[DRCViolation] = []
    if design.routing is None:
        return vio

    min_annular_ring = 0.13
    if design.board_def and design.board_def.constraints:
        min_annular_ring = design.board_def.constraints.min_annular_ring

    for seg in design.routing.traces:
        if seg.via:
            annular_ring = (seg.via_diameter - seg.via_hole) / 2.0
            if annular_ring < min_annular_ring - 0.001:
                vio.append(
                    DRCViolation(
                        rule_id="DRC-020",
                        severity=DRCSeverity.ERROR,
                        message=f"Via annular ring {annular_ring:.3f}mm below minimum "
                        f"{min_annular_ring:.3f}mm on net '{seg.net_id}'",
                        net_id=seg.net_id,
                        location=f"({seg.start[0]:.1f}, {seg.start[1]:.1f})",
                    )
                )
    return vio


def _board_edge_outline(design: Design) -> list[tuple[float, float]]:
    if design.board_def and design.board_def.outline:
        return design.board_def.outline
    board_width = design.board.width_mm if hasattr(design.board, "width_mm") else 100.0
    board_height = design.board.height_mm if hasattr(design.board, "height_mm") else 80.0
    return [(0.0, 0.0), (board_width, 0.0), (board_width, board_height), (0.0, board_height)]


def _rectangular_edge_distance(
    point: tuple[float, float],
    outline: list[tuple[float, float]],
) -> float | None:
    if len(outline) != 4:
        return None
    min_x = min(outline_point[0] for outline_point in outline)
    max_x = max(outline_point[0] for outline_point in outline)
    min_y = min(outline_point[1] for outline_point in outline)
    max_y = max(outline_point[1] for outline_point in outline)
    x_distance = min(abs(point[0] - min_x), abs(point[0] - max_x))
    y_distance = min(abs(point[1] - min_y), abs(point[1] - max_y))
    return min(x_distance, y_distance)


def _board_edge_violation(
    segment: TraceSegment,
    outline: list[tuple[float, float]],
    min_clearance: float,
) -> DRCViolation | None:
    for point in (segment.start, segment.end):
        distance = _rectangular_edge_distance(point, outline)
        if distance is None or distance >= min_clearance - 0.001:
            continue
        return DRCViolation(
            rule_id="DRC-021",
            severity=DRCSeverity.ERROR,
            message=(
                f"Trace to board edge clearance {distance:.3f}mm below minimum "
                f"{min_clearance:.3f}mm on net '{segment.net_id}'"
            ),
            net_id=segment.net_id,
            location=f"({point[0]:.1f}, {point[1]:.1f})",
        )
    return None


def check_board_edge_clearance(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-021 — Copper to board edge clearance below minimum."""
    outline = _board_edge_outline(design)
    if len(outline) < 3:
        return []
    min_clearance = 0.3
    return [
        violation
        for segment in _trace_segments(design)
        if (violation := _board_edge_violation(segment, outline, min_clearance)) is not None
    ]


def _solder_mask_limits(design: Design) -> tuple[float, float]:
    min_sliver = 0.1
    if design.board_def and design.board_def.constraints:
        min_sliver = design.board_def.constraints.min_solder_mask_sliver
    min_copper_clearance = design.board.min_clearance_mm if design.board else 0.2
    return min_sliver, min_copper_clearance


def _solder_mask_sliver_violation(
    first: TraceSegment,
    second: TraceSegment,
    *,
    min_sliver: float,
    min_copper_clearance: float,
) -> DRCViolation | None:
    if first.net_id == second.net_id or first.layer != second.layer:
        return None
    distance = _segment_min_distance(first, second)
    clearance = distance - (first.width / 2) - (second.width / 2)
    if clearance < min_copper_clearance:
        return None
    if clearance <= 0.001 or clearance >= min_sliver - 0.001:
        return None
    return DRCViolation(
        rule_id="DRC-022",
        severity=DRCSeverity.ERROR,
        message=(
            f"Solder-mask sliver {clearance:.3f}mm below minimum {min_sliver:.3f}mm "
            f"between nets '{first.net_id}' and '{second.net_id}'"
        ),
        location=f"layer={first.layer}",
    )


def _solder_mask_sliver_violations(
    segments: list[TraceSegment],
    *,
    min_sliver: float,
    min_copper_clearance: float,
) -> list[DRCViolation]:
    violations: list[DRCViolation] = []
    for index, first in enumerate(segments):
        for second in segments[index + 1 :]:
            violation = _solder_mask_sliver_violation(
                first,
                second,
                min_sliver=min_sliver,
                min_copper_clearance=min_copper_clearance,
            )
            if violation is not None:
                violations.append(violation)
    return violations


def check_solder_mask_sliver(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-022 — Solder-mask sliver below minimum."""
    segments = _trace_segments(design)
    if len(segments) < 2:
        return []
    min_sliver, min_copper_clearance = _solder_mask_limits(design)
    return _solder_mask_sliver_violations(
        segments,
        min_sliver=min_sliver,
        min_copper_clearance=min_copper_clearance,
    )


def check_acid_trap(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-023 — Acid-trap (sharp inner-angle copper) detection."""
    groups = _group_segments_by_net_layer(_trace_segments(design))
    endpoint_degrees = _endpoint_degrees(groups)
    violations: list[DRCViolation] = []
    for (net_id, layer), segments in groups.items():
        for shared, angle_deg in _simple_trace_joints(
            net_id,
            layer,
            segments,
            endpoint_degrees,
            min_segment_length=0.001,
        ):
            if 1.0 <= angle_deg < 85.0:
                violations.append(
                    DRCViolation(
                        rule_id="DRC-023",
                        severity=DRCSeverity.ERROR,
                        message=f"Acid-trap (sharp angle {angle_deg:.1f}°) on net '{net_id}' layer {layer}",
                        net_id=net_id,
                        location=f"({shared[0]:.1f}, {shared[1]:.1f})",
                    )
                )
    return violations


def _high_voltage_min_clearance(design: Design) -> float:
    if design.board_def and design.board_def.constraints:
        return design.board_def.constraints.min_clearance_high_voltage
    return 0.3


def _high_voltage_net_ids(design: Design) -> set[str]:
    return {net_id for net_id, net_class in (design.net_classes or {}).items() if net_class == NetClass.POWER_HIGH}


def _high_voltage_clearance_violation(
    first: TraceSegment,
    second: TraceSegment,
    *,
    high_voltage_nets: set[str],
    min_clearance: float,
) -> DRCViolation | None:
    if first.net_id == second.net_id or first.layer != second.layer:
        return None
    if first.net_id not in high_voltage_nets and second.net_id not in high_voltage_nets:
        return None
    clearance = _trace_pair_clearance(first, second)
    if clearance >= min_clearance - 0.001:
        return None
    return DRCViolation(
        rule_id="DRC-024",
        severity=DRCSeverity.ERROR,
        message=(
            f"High-voltage clearance violation: nets '{first.net_id}' and '{second.net_id}' "
            f"are {clearance:.3f}mm apart (min {min_clearance:.3f}mm)"
        ),
        location=f"layer={first.layer}",
        net_id=first.net_id,
    )


def check_high_voltage_clearance(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-024 — Creepage/clearance for high-voltage / PoE nets."""
    high_voltage_nets = _high_voltage_net_ids(design)
    if not high_voltage_nets:
        return []
    min_clearance = _high_voltage_min_clearance(design)
    return [
        violation
        for first, second in _trace_pairs(_trace_segments(design))
        if (
            violation := _high_voltage_clearance_violation(
                first,
                second,
                high_voltage_nets=high_voltage_nets,
                min_clearance=min_clearance,
            )
        )
        is not None
    ]


def check_copper_balance(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-025 — Copper-balance / large-unpoured-area warning."""
    vio: list[DRCViolation] = []

    # If the design is completely empty, don't warn about missing copper pours
    if not design.components and not design.nets:
        return vio

    wants_pour = False
    if design.board_def:
        wants_pour = design.board_def.copper_pour_gnd
    elif design.board:
        wants_pour = design.board.copper_pour_gnd

    if wants_pour and not design.copper_pours:
        vio.append(
            DRCViolation(
                rule_id="DRC-025",
                severity=DRCSeverity.INFO,
                message="Copper-balance: Board requests GND pour, but no copper pours are defined",
            )
        )
    return vio


def _component_placement_limits(
    design: Design,
) -> tuple[tuple[float, float, float, float], str] | None:
    margin = 2.0
    if design.board_def is not None:
        outline = design.board_def.outline
        if not outline:
            return None
        bounds = (
            min(point[0] for point in outline) - margin,
            max(point[0] for point in outline) + margin,
            min(point[1] for point in outline) - margin,
            max(point[1] for point in outline) + margin,
        )
        return bounds, "outside board outline"
    board_width = design.board.width_mm if hasattr(design.board, "width_mm") else 100.0
    board_height = design.board.height_mm if hasattr(design.board, "height_mm") else 80.0
    return (
        (-margin, board_width + margin, -margin, board_height + margin),
        f"outside board ({board_width:.0f}×{board_height:.0f}mm)",
    )


def _component_outside_violation(
    design: Design,
    component_id: str,
    position: tuple[float, float],
    bounds: tuple[float, float, float, float],
    outside_description: str,
) -> DRCViolation | None:
    x, y = position
    min_x, max_x, min_y, max_y = bounds
    if min_x <= x <= max_x and min_y <= y <= max_y:
        return None
    component = design.components.get(component_id)
    reference = component.ref if component else component_id
    return DRCViolation(
        rule_id="DRC-011",
        severity=DRCSeverity.ERROR,
        message=f"Component '{reference}' placed at ({x:.1f}, {y:.1f}) {outside_description}",
        component_id=component_id,
    )


def check_component_outside_board(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-011 — Component placed outside board boundary."""
    limits = _component_placement_limits(design)
    if limits is None:
        return []
    bounds, outside_description = limits
    return [
        violation
        for component_id, position in (design.placement or {}).items()
        if (
            violation := _component_outside_violation(
                design,
                component_id,
                position,
                bounds,
                outside_description,
            )
        )
        is not None
    ]


# IPC-2152 external-conductor current capacity constants.
# I = _IPC2152_K * ΔT^0.44 * (width_mm * thickness_oz * 25.4)^0.725
# where thickness is in oz/ft² converted to mils via 1 oz ≈ 1.37 mils.
_IPC2152_K_EXTERNAL = 0.048  # external conductor
_IPC2152_DEFAULT_DELTA_T = 10.0  # °C temperature rise above ambient
_IPC2152_OZ_TO_MILS = 1.37  # 1 oz/ft² ≈ 1.37 mil thick


def _ipc2152_min_width_mm(
    current_a: float,
    copper_oz: float = 1.0,
    delta_t_c: float = _IPC2152_DEFAULT_DELTA_T,
) -> float:
    """Return the minimum trace width in mm for *current_a* amps per IPC-2152.

    Uses the external-conductor formula (conservative; inner-layer k is lower).
    """
    thickness_mils = copper_oz * _IPC2152_OZ_TO_MILS
    area_mils2 = (current_a / (_IPC2152_K_EXTERNAL * (delta_t_c**0.44))) ** (1.0 / 0.725)
    width_mils = area_mils2 / thickness_mils
    return width_mils * 0.0254  # mils → mm


def _high_current_min_width(net: Net) -> float | None:
    constraints = net.constraints
    if constraints is None or not constraints.is_high_current:
        return None
    return constraints.min_trace_width_mm or _ipc2152_min_width_mm(1.0)


def _high_current_net_violations(
    net_id: str,
    net: Net,
    segments: list[TraceSegment],
    min_width_mm: float,
) -> list[DRCViolation]:
    violations: list[DRCViolation] = []
    for segment in segments:
        width = getattr(segment, "width", None)
        if width is None or width >= min_width_mm - 0.001:
            continue
        violations.append(
            DRCViolation(
                rule_id="DRC-012",
                severity=DRCSeverity.ERROR,
                message=(
                    f"High-current net '{net.name}' trace width {width:.3f}mm "
                    f"below IPC-2152 minimum {min_width_mm:.3f}mm"
                ),
                net_id=net_id,
            )
        )
    return violations


def check_high_current_trace_width(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-012 — IPC-2152 current-capacity: trace too narrow for rated current."""
    routing = design.routing
    if routing is None:
        return []

    traces_by_net: dict[str, list[TraceSegment]] = {}
    for segment in routing.traces:
        traces_by_net.setdefault(segment.net_id, []).append(segment)

    violations: list[DRCViolation] = []
    for net_id, net in design.nets.items():
        min_width_mm = _high_current_min_width(net)
        if min_width_mm is None:
            continue
        violations.extend(
            _high_current_net_violations(
                net_id,
                net,
                traces_by_net.get(net_id, []),
                min_width_mm,
            )
        )
    return violations


_IPC_MIN_HOLE_WALL_MM = 0.25
DrilledHole = tuple[float, float, float, str]


def _routing_drilled_holes(routing: RouteResult) -> list[DrilledHole]:
    holes: list[DrilledHole] = []
    for via in routing.vias:
        if len(via) < 4:
            continue
        net_id = str(via[4]) if len(via) > 4 else ""
        holes.append((float(via[0]), float(via[1]), float(via[3]), net_id))
    holes.extend(
        (segment.start[0], segment.start[1], segment.via_hole, segment.net_id)
        for segment in routing.traces
        if segment.via
    )
    return holes


def _hole_clearance_violation(first: DrilledHole, second: DrilledHole) -> DRCViolation | None:
    x1, y1, diameter1, net1 = first
    x2, y2, diameter2, net2 = second
    distance = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    wall_clearance = distance - (diameter1 + diameter2) / 2.0
    if wall_clearance >= _IPC_MIN_HOLE_WALL_MM - 0.001:
        return None
    return DRCViolation(
        rule_id="DRC-013",
        severity=DRCSeverity.ERROR,
        message=(
            f"Via hole-to-hole wall clearance {wall_clearance:.3f}mm "
            f"below IPC-2221 minimum {_IPC_MIN_HOLE_WALL_MM}mm "
            f"(nets '{net1}' and '{net2}')"
        ),
        net_id=net1 or None,
    )


def check_hole_to_hole_clearance(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-013 — Via/drill hole-to-hole spacing below IPC-2221 minimum.

    IPC-2221 class A requires ≥ 0.25 mm between drill holes (wall-to-wall).
    For PTH to PTH, the wall clearance is (centre-to-centre − (d1+d2)/2).
    (drill/hole-to-hole checks.)
    """
    routing = design.routing
    if routing is None:
        return []

    holes = _routing_drilled_holes(routing)
    violations: list[DRCViolation] = []
    for index, first in enumerate(holes):
        for second in holes[index + 1 :]:
            violation = _hole_clearance_violation(first, second)
            if violation is not None:
                violations.append(violation)
    return violations


# ===================================================================
# Registry of all checks
# ===================================================================

_ALL_CHECKS: list[DRCCheck] = [
    check_unconnected_nets,
    check_clearance,
    check_trace_width,
    check_right_angle,
    check_unrouted_nets,
    check_via_count,
    check_missing_net_class,
    check_component_outside_board,
    check_min_annular_ring,
    check_board_edge_clearance,
    check_solder_mask_sliver,
    check_acid_trap,
    check_high_voltage_clearance,
    check_copper_balance,
    check_high_current_trace_width,
    check_hole_to_hole_clearance,
]
