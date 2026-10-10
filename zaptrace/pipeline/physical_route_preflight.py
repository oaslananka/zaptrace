"""Conservative evidence gate for routing against verified physical footprints.

Neither the grid router's graph success count nor this inexpensive check is
fabrication acceptance. An insufficient/violating candidate is never exported
as though it were routed copper; native KiCad DRC remains authoritative.
"""

from __future__ import annotations

import math
from collections import defaultdict

from zaptrace.core.models import Design, LayerSet, NetClass, Pad, RouteResult
from zaptrace.ee.classifier import get_net_class
from zaptrace.ee.drc.engine import DRCEngine


def _pad_contains_endpoint(pad: Pad, center: tuple[float, float], endpoint: tuple[float, float]) -> bool:
    """Reject approximated pad escapes that never actually reach pad copper.

    Deliberately use a *conservative* interior rectangular envelope for
    circles/ovals/rounded rectangles. It may reject a valid tangent connection,
    but cannot promote an unsupported connection merely due to copper width.
    """
    angle = math.radians(pad.rotation)
    dx, dy = endpoint[0] - center[0], endpoint[1] - center[1]
    local_x = dx * math.cos(angle) + dy * math.sin(angle)
    local_y = -dx * math.sin(angle) + dy * math.cos(angle)
    epsilon = 1e-6
    return abs(local_x) <= pad.size[0] / 2 + epsilon and abs(local_y) <= pad.size[1] / 2 + epsilon


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
            for pad in matching:
                center = (location[0] + pad.position[0], location[1] + pad.position[1])
                if not any(
                    _trace_layer_compatible(pad, layer) and _pad_contains_endpoint(pad, center, endpoint)
                    for layer, endpoint in endpoint_by_net[net.id]
                ):
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
    if not candidate.traces or not _physical_pad_terminal_coverage(design, candidate, positions):
        return False
    trial = design.model_copy(deep=True)
    trial.placement = dict(positions)
    trial.routing = candidate
    return DRCEngine().run(trial).passed
