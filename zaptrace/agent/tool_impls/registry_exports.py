"""Declarative exports tool registry fragment."""

# ruff: noqa: E501

from __future__ import annotations

from .deps import copy
from .exports import (
    tool_export_bom_csv,
    tool_export_bom_json,
    tool_export_excellon,
    tool_export_gerber,
    tool_export_kicad,
    tool_export_manufacturing,
    tool_export_pick_and_place,
    tool_export_report,
    tool_export_spice,
    tool_export_svg,
)
from .registry_shared import (
    _APPROVAL_DESCRIPTION,
    _DESIGN_DESCRIPTION,
    _RELEASE_EVIDENCE_PARAM_SCHEMA,
    _SESSION_DESCRIPTION,
)

EXPORTS_REGISTRY: dict[str, dict[str, object]] = {
    "export_bom_csv": {
        "name": "export_bom_csv",
        "description": "Generate Bill of Materials as CSV",
        "fn": tool_export_bom_csv,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "export_bom_json": {
        "name": "export_bom_json",
        "description": "Generate Bill of Materials as JSON",
        "fn": tool_export_bom_json,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "export_report": {
        "name": "export_report",
        "description": "Generate a Markdown design report",
        "fn": tool_export_report,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "output_path": {"type": "string", "description": "Optional output path"},
        },
    },
    "export_svg": {
        "name": "export_svg",
        "description": "Render a schematic overview as SVG",
        "fn": tool_export_svg,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "output_path": {"type": "string", "description": "Optional output path"},
        },
    },
    "export_kicad": {
        "name": "export_kicad",
        "description": "Export design to KiCad-compatible files",
        "fn": tool_export_kicad,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "output_dir": {"type": "string", "description": "Output directory"},
            "approval_id": {"type": "string", "description": _APPROVAL_DESCRIPTION},
            **copy.deepcopy(_RELEASE_EVIDENCE_PARAM_SCHEMA),
        },
    },
    "export_gerber": {
        "name": "export_gerber",
        "description": "Generate Gerber RS-274X files for a design",
        "fn": tool_export_gerber,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "output_dir": {"type": "string", "description": "Optional output directory for Gerber files"},
            "approval_id": {"type": "string", "description": _APPROVAL_DESCRIPTION},
            **copy.deepcopy(_RELEASE_EVIDENCE_PARAM_SCHEMA),
        },
    },
    "export_excellon": {
        "name": "export_excellon",
        "description": "Generate Excellon drill files for a design",
        "fn": tool_export_excellon,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "output_dir": {"type": "string", "description": "Optional output directory for drill files"},
            "approval_id": {"type": "string", "description": _APPROVAL_DESCRIPTION},
            **copy.deepcopy(_RELEASE_EVIDENCE_PARAM_SCHEMA),
        },
    },
    "export_manufacturing": {
        "name": "export_manufacturing",
        "description": "Generate a complete manufacturing package (Gerber + drill + BOM + PnP ZIP)",
        "fn": tool_export_manufacturing,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "output_dir": {"type": "string", "description": "Output directory for manufacturing files"},
            "approval_id": {"type": "string", "description": _APPROVAL_DESCRIPTION},
            **copy.deepcopy(_RELEASE_EVIDENCE_PARAM_SCHEMA),
        },
    },
    "export_pick_and_place": {
        "name": "export_pick_and_place",
        "description": "Generate a pick-and-place (centroid) CSV for assembly",
        "fn": tool_export_pick_and_place,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "approval_id": {"type": "string", "description": _APPROVAL_DESCRIPTION},
            **copy.deepcopy(_RELEASE_EVIDENCE_PARAM_SCHEMA),
        },
    },
    "export_spice": {
        "name": "export_spice",
        "description": "Export a design as a SPICE netlist string (foundation for simulation)",
        "fn": tool_export_spice,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
}

__all__ = ["EXPORTS_REGISTRY"]
