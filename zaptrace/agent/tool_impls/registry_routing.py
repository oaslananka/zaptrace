"""Declarative routing tool registry fragment."""

# ruff: noqa: E501

from __future__ import annotations

from .registry_shared import (
    _DESIGN_DESCRIPTION,
    _SESSION_DESCRIPTION,
)
from .routing import (
    tool_board_classify_nets,
    tool_board_export,
    tool_board_summarize_nets,
    tool_design_classify_nets,
    tool_design_route_smart,
    tool_place_components,
    tool_route_nets,
)

ROUTING_REGISTRY: dict[str, dict[str, object]] = {
    "place_components": {
        "name": "place_components",
        "description": "Place all components on the board",
        "fn": tool_place_components,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "route_nets": {
        "name": "route_nets",
        "description": "Route all nets using Manhattan MST routing",
        "fn": tool_route_nets,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "board_classify_nets": {
        "name": "board_classify_nets",
        "description": "Classify all nets in a design using EE knowledge",
        "fn": tool_board_classify_nets,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "board_summarize_nets": {
        "name": "board_summarize_nets",
        "description": "Get a summary of all nets and their classifications",
        "fn": tool_board_summarize_nets,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "design_route_smart": {
        "name": "design_route_smart",
        "description": "Route all nets with net-class-aware trace widths",
        "fn": tool_design_route_smart,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "layer": {"type": "string", "description": "Layer name (default: F.Cu)"},
        },
    },
    "design_classify_nets": {
        "name": "design_classify_nets",
        "description": "Classify all nets in a design by name and pin type",
        "fn": tool_design_classify_nets,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "board_export": {
        "name": "board_export",
        "description": "Export the board definition for a design as a JSON description",
        "fn": tool_board_export,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
}

__all__ = ["ROUTING_REGISTRY"]
