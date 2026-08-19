"""Declarative design tool registry fragment."""

# ruff: noqa: E501

from __future__ import annotations

from .design import (
    tool_board_update,
    tool_component_add,
    tool_component_remove,
    tool_design_diff,
    tool_design_inspect,
    tool_design_list_nets,
    tool_design_parse_file,
    tool_design_parse_str,
)
from .registry_shared import (
    _DESIGN_DESCRIPTION,
    _SESSION_DESCRIPTION,
)

DESIGN_REGISTRY: dict[str, dict[str, object]] = {
    "design_parse_file": {
        "name": "design_parse_file",
        "description": "Parse a design YAML file into a Design object",
        "fn": tool_design_parse_file,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "path": {"type": "string", "description": "Path to design YAML file"},
        },
    },
    "design_parse_str": {
        "name": "design_parse_str",
        "description": "Parse a YAML string into a Design object",
        "fn": tool_design_parse_str,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "yaml_content": {"type": "string", "description": "YAML content string"},
        },
    },
    "design_inspect": {
        "name": "design_inspect",
        "description": "Inspect a parsed design and return its full details",
        "fn": tool_design_inspect,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "design_list_nets": {
        "name": "design_list_nets",
        "description": "List all nets in a design with their connections",
        "fn": tool_design_list_nets,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "design_diff": {
        "name": "design_diff",
        "description": "Diff two designs and report changes",
        "fn": tool_design_diff,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_a_name": {"type": "string", "description": "First design name"},
            "design_b_name": {"type": "string", "description": "Second design name"},
        },
    },
    "board_update": {
        "name": "board_update",
        "description": "Update board configuration parameters",
        "fn": tool_board_update,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "width_mm": {"type": "number", "description": "Board width in mm"},
            "height_mm": {"type": "number", "description": "Board height in mm"},
            "layers": {"type": "integer", "description": "Number of copper layers"},
        },
    },
    "component_add": {
        "name": "component_add",
        "description": "Add a new component to a design",
        "fn": tool_component_add,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "component_id": {"type": "string", "description": "Component ID"},
            "ref": {"type": "string", "description": "Reference designator (e.g. R1, U1)"},
            "type_name": {"type": "string", "description": "Component type"},
            "value": {"type": "string", "description": "Component value"},
            "footprint": {"type": "string", "description": "Footprint name"},
        },
    },
    "component_remove": {
        "name": "component_remove",
        "description": "Remove a component from a design",
        "fn": tool_component_remove,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "component_id": {"type": "string", "description": "Component ID to remove"},
        },
    },
}

__all__ = ["DESIGN_REGISTRY"]
