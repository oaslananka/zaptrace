"""Declarative proof tool registry fragment."""

# ruff: noqa: E501

from __future__ import annotations

from .proof import tool_proof_list_checks, tool_proof_run, tool_proof_run_design
from .registry_shared import (
    _SESSION_DESCRIPTION,
)

PROOF_REGISTRY: dict[str, dict[str, object]] = {
    "proof_run": {
        "name": "proof_run",
        "description": "Run a Proof Pack from a proof.yaml file or directory to validate a design",
        "fn": tool_proof_run,
        "params": {
            "path": {"type": "string", "description": "Path to proof.yaml or directory containing proof.yaml"},
        },
    },
    "proof_run_design": {
        "name": "proof_run_design",
        "description": "Run proof checks directly against a design in the current session (no proof.yaml needed)",
        "fn": tool_proof_run_design,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": "Name of the design to validate"},
            "checks": {
                "type": "array",
                "description": "Optional check definitions (name, type, severity, params). Default: structural checks",
            },
        },
    },
    "proof_list_checks": {
        "name": "proof_list_checks",
        "description": "List all checks defined in a Proof Pack without running them",
        "fn": tool_proof_list_checks,
        "params": {
            "path": {"type": "string", "description": "Path to proof.yaml or directory containing proof.yaml"},
        },
    },
}

__all__ = ["PROOF_REGISTRY"]
