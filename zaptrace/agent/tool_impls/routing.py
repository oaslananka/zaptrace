"""Routing agent tool implementations."""

from __future__ import annotations

from .deps import Any
from .runtime import _get_session


def tool_place_components(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Place all components on the board using grid + force-directed layout."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    from zaptrace.algo.placer import place_components as _place

    positions = _place(design)
    session["positions"] = {**session.get("positions", {}), design_name: positions}
    return {
        "design": design_name,
        "component_count": len(positions),
        "positions": {k: list(v) for k, v in positions.items()},
    }


def tool_route_nets(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Route all nets using Manhattan MST routing."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    positions = session.get("positions", {}).get(design_name)
    from zaptrace.algo.router import route_nets as _route

    result = _route(design, positions or {})
    session["routing"] = {**session.get("routing", {}), design_name: result}
    return {
        "design": design_name,
        "routed_nets": result.routed_nets,
        "total_nets": result.total_nets,
        "coverage_pct": result.coverage_pct,
        "unrouted": result.unrouted_nets,
        "segment_count": len(result.segments),
    }


def tool_board_classify_nets(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Classify all nets in a design using EE knowledge."""
    from zaptrace.ee.classifier import classify_design, summarize_classification

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    classify_design(design)
    summary = summarize_classification(design)
    return {"design": design_name, "classification": summary}


def tool_board_export(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Export the board definition for a design as a JSON description."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    board = design.board
    return {
        "design": design_name,
        "board": {
            "width_mm": board.width_mm,
            "height_mm": board.height_mm,
            "layers": board.layers,
            "copper_pour_gnd": board.copper_pour_gnd,
            "min_trace_width_mm": board.min_trace_width_mm,
            "min_clearance_mm": board.min_clearance_mm,
            "min_via_diameter_mm": board.min_via_diameter_mm,
        },
        "component_count": len(design.components),
        "net_count": len(design.nets),
    }


def tool_board_summarize_nets(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Get a summary of all nets and their classifications."""
    from zaptrace.ee.classifier import get_net_class, summarize_classification

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    net_list = []
    for net_id, net in design.nets.items():
        nc = get_net_class(design, net_id)
        net_list.append({"net_id": net_id, "name": net.name, "class": nc.value, "nodes": len(net.nodes)})
    summary = summarize_classification(design)
    return {"design": design_name, "nets": net_list, "classification_summary": summary}


def tool_design_route_smart(design_name: str, layer: str = "F.Cu", session_id: str = "default") -> dict[str, Any]:
    """Route all nets with net-class-aware trace widths."""
    from zaptrace.algo.router import route_design_smart
    from zaptrace.ee.knowledge import KnowledgeBase

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    positions = session.get("positions", {}).get(design_name)
    if not positions:
        raise ValueError(f"No placement positions found for '{design_name}'. Run place_components first.")
    kb = KnowledgeBase()
    routing_result, route_result, _sc = route_design_smart(design, positions, kb=kb, layer=layer)
    session.setdefault("routing_results", {})[design_name] = route_result
    return {
        "design": design_name,
        "routed_nets": routing_result.routed_nets,
        "total_nets": routing_result.total_nets,
        "unrouted_nets": routing_result.unrouted_nets,
        "coverage_pct": routing_result.coverage_pct,
        "total_trace_length_mm": route_result.total_trace_length_mm,
        "trace_count": len(route_result.traces),
    }


def tool_design_classify_nets(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Classify a single net or all nets in a design."""
    from zaptrace.ee.classifier import classify_design

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    classify_design(design)
    net_classes = {}
    for nid, nc in (design.net_classes or {}).items():
        net = design.nets.get(nid)
        net_classes[nid] = {"name": net.name if net else "?", "class": nc.value}
    return {"design": design_name, "nets_classified": len(net_classes), "classifications": net_classes}


__all__ = [
    "tool_place_components",
    "tool_route_nets",
    "tool_board_classify_nets",
    "tool_board_export",
    "tool_board_summarize_nets",
    "tool_design_route_smart",
    "tool_design_classify_nets",
]
