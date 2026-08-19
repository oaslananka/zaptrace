"""Agent tool definitions and registry.

Provides 27 agent-callable tools covering design, synthesis, ERC,
placement/routing, library, export, diff, pipeline, and component operations.
"""

from __future__ import annotations

from typing import Any

from zaptrace.agent._tool_impls import (
    TOOL_REGISTRY,
    call_tool,
    get_tool,
    list_tools,
)

__all__ = [
    "TOOL_REGISTRY",
    "call_tool",
    "get_tool",
    "list_tools",
]


def tool_names() -> list[str]:
    """Return the list of registered tool names."""
    return list(TOOL_REGISTRY.keys())


def tool_info(name: str) -> dict[str, Any]:
    """Return metadata for a specific tool (name, description, params)."""
    return get_tool(name)
