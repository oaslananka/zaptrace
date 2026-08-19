"""Declarative pipeline tool registry fragment."""

# ruff: noqa: E501

from __future__ import annotations

from .pipeline import tool_patch_suggest, tool_pipeline_run, tool_pipeline_run_stage, tool_pipeline_status
from .registry_shared import (
    _DESIGN_DESCRIPTION,
    _SESSION_DESCRIPTION,
)

PIPELINE_REGISTRY: dict[str, dict[str, object]] = {
    "pipeline_run": {
        "name": "pipeline_run",
        "description": "Run the full design pipeline from file or intent",
        "fn": tool_pipeline_run,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "source": {"type": "string", "description": "Design file path"},
            "intent": {"type": "string", "description": "Synthesis intent"},
            "output_dir": {"type": "string", "description": "Output directory"},
        },
    },
    "pipeline_run_stage": {
        "name": "pipeline_run_stage",
        "description": "Run a single pipeline stage",
        "fn": tool_pipeline_run_stage,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "stage": {"type": "string", "description": "Stage name"},
            "source": {"type": "string", "description": "Design file path"},
            "intent": {"type": "string", "description": "Synthesis intent"},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "output_dir": {"type": "string", "description": "Output directory"},
        },
    },
    "pipeline_status": {
        "name": "pipeline_status",
        "description": "Get pipeline processing status for a design",
        "fn": tool_pipeline_status,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
    "patch_suggest": {
        "name": "patch_suggest",
        "description": "Suggest auto-patches for fixable ERC violations",
        "fn": tool_patch_suggest,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
        },
    },
}

__all__ = ["PIPELINE_REGISTRY"]
