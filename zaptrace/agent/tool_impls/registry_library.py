"""Declarative library tool registry fragment."""

# ruff: noqa: E501

from __future__ import annotations

from .library import (
    tool_footprint_generate,
    tool_footprint_get,
    tool_footprint_list_packages,
    tool_footprint_search,
    tool_library_get,
    tool_library_list_categories,
    tool_library_search,
    tool_schematic_render,
)
from .registry_shared import (
    _DESIGN_DESCRIPTION,
    _SESSION_DESCRIPTION,
)

LIBRARY_REGISTRY: dict[str, dict[str, object]] = {
    "library_search": {
        "name": "library_search",
        "description": "Search the component library by keyword",
        "fn": tool_library_search,
        "params": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results"},
        },
    },
    "library_get": {
        "name": "library_get",
        "description": "Get full details for a library component",
        "fn": tool_library_get,
        "params": {
            "component_id": {"type": "string", "description": "Component ID"},
        },
    },
    "library_list_categories": {
        "name": "library_list_categories",
        "description": "List all component library categories",
        "fn": tool_library_list_categories,
        "params": {},
    },
    "footprint_search": {
        "name": "footprint_search",
        "description": "Search for footprints in the library by keyword",
        "fn": tool_footprint_search,
        "params": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results (default 10)"},
        },
    },
    "footprint_get": {
        "name": "footprint_get",
        "description": "Get footprint details for a library component",
        "fn": tool_footprint_get,
        "params": {
            "component_id": {"type": "string", "description": "Component ID"},
        },
    },
    "schematic_render": {
        "name": "schematic_render",
        "description": "Render a design as an SVG schematic",
        "fn": tool_schematic_render,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "footprint_generate": {
        "name": "footprint_generate",
        "description": "Generate a parametric footprint for a given package name",
        "fn": tool_footprint_generate,
        "params": {
            "package": {"type": "string", "description": "Package name (e.g. 0603, SOIC-8, QFN-32)"},
            "layer": {"type": "string", "description": "Layer (top or bottom, default top)"},
        },
    },
    "footprint_list_packages": {
        "name": "footprint_list_packages",
        "description": "List all supported package names for footprint generation",
        "fn": tool_footprint_list_packages,
        "params": {},
    },
}

__all__ = ["LIBRARY_REGISTRY"]
