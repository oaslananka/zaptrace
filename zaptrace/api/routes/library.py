"""Component library API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from zaptrace.agent._tool_impls import (
    tool_library_get,
    tool_library_list_categories,
    tool_library_search,
)
from zaptrace.api.routes._responses import _NOT_FOUND_RESPONSE
from zaptrace.core.exceptions import LibraryError

router = APIRouter()


@router.get("/search")
def search_library(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search the component library by keyword."""
    return tool_library_search(query=query, max_results=max_results)


@router.get("/categories")
def list_categories() -> dict[str, Any]:
    """List all component library categories."""
    return tool_library_list_categories()


@router.get("/{component_id}", responses=_NOT_FOUND_RESPONSE)
def get_component(component_id: str) -> dict[str, Any]:
    """Get full details for a library component."""
    try:
        return tool_library_get(component_id=component_id)
    except LibraryError as e:
        raise HTTPException(404, str(e)) from e
