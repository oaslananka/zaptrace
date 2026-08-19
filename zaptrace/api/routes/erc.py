"""ERC validation and rules API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from zaptrace.agent._tool_impls import (
    tool_erc_get_result,
    tool_erc_list_rules,
    tool_erc_validate,
    tool_patch_suggest,
)
from zaptrace.api.routes._responses import _NOT_FOUND_RESPONSE
from zaptrace.api.routes._session import resolve_session_id

router = APIRouter()


@router.post("/validate/{design_name}", responses=_NOT_FOUND_RESPONSE)
def validate_design(
    design_name: str,
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """Run all ERC rules on a design."""
    try:
        return tool_erc_validate(session_id=session, design_name=design_name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/result/{design_name}", responses=_NOT_FOUND_RESPONSE)
def get_erc_result(
    design_name: str,
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """Get the latest ERC result summary."""
    try:
        return tool_erc_get_result(session_id=session, design_name=design_name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/rules")
def list_erc_rules() -> dict[str, Any]:
    """List all registered ERC rules."""
    return tool_erc_list_rules()


@router.get("/patches/{design_name}", responses=_NOT_FOUND_RESPONSE)
def suggest_erc_patches(
    design_name: str,
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """Suggest auto-patches for fixable ERC violations."""
    try:
        return tool_patch_suggest(session_id=session, design_name=design_name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
