"""Declarative verification tool registry fragment."""

# ruff: noqa: E501

from __future__ import annotations

from .registry_shared import (
    _DESIGN_DESCRIPTION,
    _SESSION_DESCRIPTION,
)
from .verification import (
    tool_drc_get_result,
    tool_drc_list_rules,
    tool_drc_run,
    tool_electrical_analysis,
    tool_erc_get_result,
    tool_erc_list_rules,
    tool_erc_validate,
    tool_mechanical_review,
    tool_security_review,
    tool_testability_report,
)

VERIFICATION_REGISTRY: dict[str, dict[str, object]] = {
    "erc_validate": {
        "name": "erc_validate",
        "description": "Run all ERC rules on a design",
        "fn": tool_erc_validate,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "erc_get_result": {
        "name": "erc_get_result",
        "description": "Get the latest ERC result summary for a design",
        "fn": tool_erc_get_result,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "erc_list_rules": {
        "name": "erc_list_rules",
        "description": "List all registered ERC rules with descriptions",
        "fn": tool_erc_list_rules,
        "params": {},
    },
    "drc_run": {
        "name": "drc_run",
        "description": "Run Design Rule Check on a design, optionally against a manufacturer fab profile",
        "fn": tool_drc_run,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "fab_profile": {
                "type": "string",
                "description": "Optional fab profile name (e.g. 'jlcpcb-2layer') for profile-specific DRC",
            },
        },
    },
    "drc_get_result": {
        "name": "drc_get_result",
        "description": "Get the latest DRC result for a design",
        "fn": tool_drc_get_result,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "drc_list_rules": {
        "name": "drc_list_rules",
        "description": "List all DRC rules with descriptions",
        "fn": tool_drc_list_rules,
        "params": {},
    },
    "mechanical_review": {
        "name": "mechanical_review",
        "description": "Review mounting holes vs board size and edges (mechanical / enclosure)",
        "fn": tool_mechanical_review,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "security_review": {
        "name": "security_review",
        "description": "Review hardware-security exposure (debug access, secure element, etc.)",
        "fn": tool_security_review,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "testability_report": {
        "name": "testability_report",
        "description": "Assess test-point coverage, debug/reset access, and a bring-up checklist",
        "fn": tool_testability_report,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "electrical_analysis": {
        "name": "electrical_analysis",
        "description": "Heuristic SI/PI/thermal pre-check (impedance, length-match, PDN, thermal)",
        "fn": tool_electrical_analysis,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
}

__all__ = ["VERIFICATION_REGISTRY"]
