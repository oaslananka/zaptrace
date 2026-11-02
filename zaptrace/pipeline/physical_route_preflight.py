"""Conservative evidence gate for routing against verified physical footprints.

Neither the grid router's graph success count nor this inexpensive check is
fabrication acceptance. An insufficient/violating candidate is never exported
as though it were routed copper; native KiCad DRC remains authoritative.
"""

from __future__ import annotations

import math
from collections import defaultdict

from zaptrace.algo.grid_router import GridRouter
from zaptrace.algo.pad_copper import point_in_pad_copper, rotated_offset
from zaptrace.core.models import Design, LayerSet, NetClass, Pad, RouteResult, TraceSegment
from zaptrace.ee.classifier import get_net_class
from zaptrace.ee.drc.engine import DRCEngine


def _trace_layer_compatible(pad: Pad, layer: str) -> bool:
    if pad.drill is not None or pad.drill_slot is not None or pad.layer == LayerSet.ALL:
        return True
    if pad.layer == LayerSet.TOP:
        return layer in {"F.Cu", "top", "layer_0"}
    if pad.layer == LayerSet.BOTTOM:
        return layer in {"B.Cu", "bottom", "layer_1"}
    return False


def _physical_pad_terminal_coverage(
    design: Design,
    routed: RouteResult,
    positions: dict[str, tuple[float, float]],
) -> bool:
    """Every non-ground net terminal must touch each represented pad region."""
    endpoint_by_net: dict[str, list[tuple[str, tuple[float, float]]]] = defaultdict(list)
    for trace in routed.traces:
        endpoint_by_net[trace.net_id].extend(((trace.layer, trace.start), (trace.layer, trace.end)))

    components_by_ref = {comp.ref: comp for comp in design.components.values()}
    for net in design.nets.values():
        if len(net.nodes) < 2 or get_net_class(design, net.id) == NetClass.GROUND:
            continue
        if not endpoint_by_net.get(net.id):
            return False
        for node in net.nodes:
            comp = components_by_ref.get(node.component_ref)
            if comp is None or comp.footprint_def is None:
                return False
            location = positions.get(comp.id) or positions.get(comp.ref) or comp.position
            if location is None:
                return False
            matching = [
                pad
                for pad in comp.footprint_def.pads
                if (comp.package_pin_map.get(pad.id, pad.id) if comp.package_pin_map else pad.id) == node.pin_name
            ]
            if not matching:
                return False
            footprint_rotation = GridRouter._footprint_rotation(design, comp)
            for pad in matching:
                offset = rotated_offset(*pad.position, footprint_rotation)
                center = (location[0] + offset[0], location[1] + offset[1])
                if not any(
                    _trace_layer_compatible(pad, layer)
                    and point_in_pad_copper(pad, center, endpoint, footprint_rotation)
                    for layer, endpoint in endpoint_by_net[net.id]
                ):
                    return False
    return True


def _root(parents: list[int], index: int) -> int:
    while parents[index] != index:
        parents[index] = parents[parents[index]]
        index = parents[index]
    return index


def _join(parents: list[int], first: int, second: int) -> None:
    parents[_root(parents, first)] = _root(parents, second)


def _physical_net_continuity(
    design: Design,
    routed: RouteResult,
    positions: dict[str, tuple[float, float]],
) -> bool:
    """Require all real terminal pads on each net to join one copper island.

    Counting a touched endpoint on each pad is not enough: two isolated
    stubs can touch different pads yet never connect to one another.
    This conservative graph only joins trace endpoints with identical
    layer/coordinates, contacts on the *same physical pad*, and explicit
    correctly owned via coordinates. Unsupported mid-segment T-junctions
    remain unverified until native KiCad can confirm them.
    """
    by_net: dict[str, list[TraceSegment]] = defaultdict(list)
    for trace in routed.traces:
        by_net[trace.net_id].append(trace)

    components_by_ref = {comp.ref: comp for comp in design.components.values()}
    for net in design.nets.values():
        if len(net.nodes) < 2 or get_net_class(design, net.id) == NetClass.GROUND:
            continue
        traces = by_net.get(net.id, [])
        if not traces:
            return False

        parents = list(range(len(traces)))

        # A segment connects its own two ends; different segments connect
        # only where actual endpoints meet on the same copper layer.
        endpoints: dict[tuple[str, float, float], int] = {}
        for index, trace in enumerate(traces):
            for point in (trace.start, trace.end):
                if not all(math.isfinite(value) for value in point):
                    return False
                layer = trace.layer
                if layer in {"layer_0", "top"}:
                    layer = "F.Cu"
                elif layer in {"layer_1", "bottom"}:
                    layer = "B.Cu"
                key = (layer, point[0], point[1])
                other = endpoints.setdefault(key, index)
                _join(parents, index, other)

        # A via must be actual, net-owned physical copper. Merely sharing
        # (x,y) between two layers is not an electrical connection.
        for via in routed.vias:
            if len(via) != 5 or via[4] != net.id:
                continue
            vx, vy, diameter, drill, _ = via
            if not all(math.isfinite(value) for value in (vx, vy, diameter, drill)):
                return False
            if drill <= 0 or diameter <= drill:
                return False
            touched = [index for (layer, x, y), index in endpoints.items() if (x, y) == (vx, vy)]
            if touched:
                for other in touched[1:]:
                    _join(parents, touched[0], other)

        contact_roots: list[int] = []
        for node in net.nodes:
            comp = components_by_ref.get(node.component_ref)
            if comp is None or comp.footprint_def is None:
                return False
            location = positions.get(comp.id) or positions.get(comp.ref) or comp.position
            if location is None:
                return False
            rotation = GridRouter._footprint_rotation(design, comp)
            matching = [
                pad
                for pad in comp.footprint_def.pads
                if (comp.package_pin_map.get(pad.id, pad.id) if comp.package_pin_map else pad.id) == node.pin_name
            ]
            if not matching:
                return False
            for pad in matching:
                offset = rotated_offset(*pad.position, rotation)
                center = (location[0] + offset[0], location[1] + offset[1])
                touched = [
                    index
                    for index, trace in enumerate(traces)
                    if _trace_layer_compatible(pad, trace.layer)
                    and (
                        point_in_pad_copper(pad, center, trace.start, rotation)
                        or point_in_pad_copper(pad, center, trace.end, rotation)
                    )
                ]
                if not touched:
                    return False
                for other in touched[1:]:
                    _join(parents, touched[0], other)
                contact_roots.append(touched[0])
        if not contact_roots or len({_root(parents, index) for index in contact_roots}) != 1:
            return False
        # Dangling disconnected copper from this net is not complete routing,
        # even when a different copper island joins every required pad.
        if any(_root(parents, index) != _root(parents, contact_roots[0]) for index in range(len(traces))):
            return False
    return True


def verified_route_candidate_safe(
    design: Design,
    candidate: RouteResult,
    positions: dict[str, tuple[float, float]],
) -> bool:
    """Fail closed if physical terminals or local DRC evidence are incomplete.

    This is a rejection predicate, NOT clearance/fabricability certification.
    Native KiCad may reveal extra conflicts; those always remain blocking.
    """
    if (
        not candidate.traces
        or not _physical_pad_terminal_coverage(design, candidate, positions)
        or not _physical_net_continuity(design, candidate, positions)
    ):
        return False
    trial = design.model_copy(deep=True)
    trial.placement = dict(positions)
    trial.routing = candidate
    return DRCEngine().run(trial).passed
