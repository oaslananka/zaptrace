"""Declarative synthesis tool registry fragment."""

# ruff: noqa: E501

from __future__ import annotations

from .deps import copy
from .registry_shared import (
    _DESIGN_DESCRIPTION,
    _INTENT_DESCRIPTION,
    _RELEASE_EVIDENCE_PARAM_SCHEMA,
    _SESSION_DESCRIPTION,
)
from .synthesis import (
    tool_board_plan,
    tool_compliance_checklist,
    tool_dc_bias_check,
    tool_list_synthesis_templates,
    tool_power_tree_plan,
    tool_requirements_parse,
    tool_requirements_review,
    tool_resolve_footprints,
    tool_simulation_gate,
    tool_synthesis_benchmark,
    tool_synthesize_and_check,
    tool_synthesize_board,
    tool_synthesize_board_and_check,
    tool_synthesize_board_manufacture,
    tool_synthesize_board_repair,
    tool_synthesize_board_score,
    tool_synthesize_design,
    tool_synthesize_power_tree,
)

SYNTHESIS_REGISTRY: dict[str, dict[str, object]] = {
    "synthesize_design": {
        "name": "synthesize_design",
        "description": (
            "Select and load the best-matching pre-built design template for an intent string "
            "(template selection by keyword match, not from-scratch circuit synthesis)"
        ),
        "fn": tool_synthesize_design,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
        },
    },
    "list_synthesis_templates": {
        "name": "list_synthesis_templates",
        "description": "List available synthesis templates",
        "fn": tool_list_synthesis_templates,
        "params": {},
    },
    "requirements_parse": {
        "name": "requirements_parse",
        "description": "Extract structured, machine-readable requirements from a design intent",
        "fn": tool_requirements_parse,
        "params": {
            "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
        },
    },
    "requirements_review": {
        "name": "requirements_review",
        "description": "Approve a design's unspecified assumptions and gate on any still pending",
        "fn": tool_requirements_review,
        "params": {
            "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
            "approvals": {
                "type": "object",
                "description": 'Map of assumption field -> reviewer decision, e.g. {"rails_v": "3.3V"}',
            },
        },
    },
    "power_tree_plan": {
        "name": "power_tree_plan",
        "description": "Plan a justified power tree (sources, charger, power-path, per-rail regulators) from an intent",
        "fn": tool_power_tree_plan,
        "params": {
            "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
        },
    },
    "synthesize_power_tree": {
        "name": "synthesize_power_tree",
        "description": "Emit a real netlist (USB-C CC, regulators, I2C pull-ups) for an intent's power tree",
        "fn": tool_synthesize_power_tree,
        "params": {
            "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
        },
    },
    "synthesize_and_check": {
        "name": "synthesize_and_check",
        "description": "Synthesize an intent's power tree into a netlist and run ERC on it in one step",
        "fn": tool_synthesize_and_check,
        "params": {
            "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
        },
    },
    "board_plan": {
        "name": "board_plan",
        "description": "Plan a justified board block graph (power + interface support) from an intent",
        "fn": tool_board_plan,
        "params": {
            "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
        },
    },
    "synthesize_board": {
        "name": "synthesize_board",
        "description": "Emit a real netlist for an intent's whole board via block composition and store it",
        "fn": tool_synthesize_board,
        "params": {
            "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
        },
    },
    "synthesize_board_and_check": {
        "name": "synthesize_board_and_check",
        "description": "Synthesize an intent's whole board into a netlist and run ERC on it in one step",
        "fn": tool_synthesize_board_and_check,
        "params": {
            "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
        },
    },
    "synthesize_board_repair": {
        "name": "synthesize_board_repair",
        "description": "Synthesize a board then run the convergent ERC -> patch -> re-verify self-correction loop",
        "fn": tool_synthesize_board_repair,
        "params": {
            "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
        },
    },
    "synthesize_board_manufacture": {
        "name": "synthesize_board_manufacture",
        "description": "Synthesize a board from intent and emit a manufacturing bundle, evidence, and review checklist",
        "fn": tool_synthesize_board_manufacture,
        "params": {
            "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
            "output_dir": {"type": "string", "description": "Directory to write manufacturing artifacts"},
            "approval_id": {"type": "string", "description": "External approval identifier bound to current evidence"},
            "fab_profile": {
                "type": "string",
                "description": "Manufacturer fabrication profile used for release DRC",
            },
            **copy.deepcopy(_RELEASE_EVIDENCE_PARAM_SCHEMA),
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
        },
    },
    "synthesis_benchmark": {
        "name": "synthesis_benchmark",
        "description": "Synthesize a fixed corpus of board types and report aggregate completeness across the engine",
        "fn": tool_synthesis_benchmark,
        "params": {},
    },
    "synthesize_board_score": {
        "name": "synthesize_board_score",
        "description": "Synthesize a board end to end and score its completeness (0-100) across four dimensions",
        "fn": tool_synthesize_board_score,
        "params": {
            "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
        },
    },
    "resolve_footprints": {
        "name": "resolve_footprints",
        "description": "Attach real IPC-7351 pad geometry to a stored design's components (reports gaps)",
        "fn": tool_resolve_footprints,
        "params": {
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
        },
    },
    "dc_bias_check": {
        "name": "dc_bias_check",
        "description": "Check power-rail DC bias on a stored design and flag undriven rails (always available)",
        "fn": tool_dc_bias_check,
        "params": {
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
        },
    },
    "simulation_gate": {
        "name": "simulation_gate",
        "description": "Run the DC operating-point simulation gate on a stored design (skip-aware, strict-blocking)",
        "fn": tool_simulation_gate,
        "params": {
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "strict": {"type": "boolean", "description": "Treat a skipped simulation as blocking"},
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
        },
    },
    "compliance_checklist": {
        "name": "compliance_checklist",
        "description": "Produce a product-class compliance pre-check checklist for a design intent",
        "fn": tool_compliance_checklist,
        "params": {
            "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
        },
    },
}

__all__ = ["SYNTHESIS_REGISTRY"]
