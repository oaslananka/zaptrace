"""Pipeline API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from zaptrace.agent._tool_impls import (
    tool_list_synthesis_templates,
    tool_pipeline_run,
    tool_pipeline_run_stage,
    tool_pipeline_status,
    tool_synthesize_design,
)
from zaptrace.api.routes._responses import _BAD_REQUEST_RESPONSE, _NOT_FOUND_RESPONSE
from zaptrace.api.routes._session import authorize_tool, resolve_session_id

router = APIRouter()


@router.post("/run", responses=_BAD_REQUEST_RESPONSE)
def run_pipeline(
    source: str | None = None,
    intent: str | None = None,
    output_dir: str | None = None,
    session: str = Depends(authorize_tool("pipeline_run")),
) -> dict[str, Any]:
    """Run the full design pipeline from file or intent."""
    try:
        return tool_pipeline_run(
            session_id=session,
            source=source,
            intent=intent,
            output_dir=output_dir,
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@router.post("/stage", responses=_BAD_REQUEST_RESPONSE)
def run_stage(
    stage: str,
    source: str | None = None,
    intent: str | None = None,
    design_name: str | None = None,
    output_dir: str | None = None,
    session: str = Depends(authorize_tool("pipeline_run_stage")),
) -> dict[str, Any]:
    """Run a single pipeline stage."""
    try:
        return tool_pipeline_run_stage(
            session_id=session,
            stage=stage,
            source=source,
            intent=intent,
            design_name=design_name,
            output_dir=output_dir,
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@router.get("/status/{design_name}", responses=_NOT_FOUND_RESPONSE)
def pipeline_status(
    design_name: str,
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """Get pipeline processing status for a design."""
    try:
        return tool_pipeline_status(
            session_id=session,
            design_name=design_name,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/synthesize", responses=_BAD_REQUEST_RESPONSE)
def synthesize_design_endpoint(
    intent: str,
    session: str = Depends(authorize_tool("synthesize_design")),
) -> dict[str, Any]:
    """Synthesize a design from intent."""
    try:
        return tool_synthesize_design(session_id=session, intent=intent)
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@router.get("/templates")
def list_synthesis_templates_endpoint() -> list[dict[str, Any]]:
    """List available synthesis templates."""
    return tool_list_synthesis_templates()
