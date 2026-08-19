"""DRC execution and current evidence API routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from zaptrace.agent._tool_impls import tool_drc_get_result, tool_drc_run
from zaptrace.api.routes._session import authorize_tool, resolve_session_id

router = APIRouter()


@router.post("/run/{design_name}", responses={404: {"description": "Design not found"}})
def run_drc(
    design_name: str,
    session: Annotated[str, Depends(authorize_tool("drc_run"))],
    fab_profile: str | None = None,
) -> dict[str, Any]:
    """Run DRC and bind the result to the current release-relevant design state."""
    try:
        return tool_drc_run(session_id=session, design_name=design_name, fab_profile=fab_profile)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/result/{design_name}")
def get_drc_result(
    design_name: str,
    session: Annotated[str, Depends(resolve_session_id)],
) -> dict[str, Any]:
    """Return the latest DRC summary and its current evidence metadata."""
    return tool_drc_get_result(session_id=session, design_name=design_name)
