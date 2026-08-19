"""Export (BOM, report, SVG, KiCad) API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from zaptrace.agent._tool_impls import (
    tool_design_diff,
    tool_export_bom_csv,
    tool_export_bom_json,
    tool_export_kicad,
    tool_export_report,
    tool_export_svg,
    tool_place_components,
    tool_route_nets,
)
from zaptrace.api.routes._responses import _BAD_REQUEST_OR_NOT_FOUND_RESPONSES, _NOT_FOUND_RESPONSE
from zaptrace.api.routes._session import authorize_tool, resolve_session_id

router = APIRouter()


@router.get("/{design_name}/bom/csv", response_class=PlainTextResponse, responses=_NOT_FOUND_RESPONSE)
def export_bom_csv(
    design_name: str,
    session: str = Depends(resolve_session_id),
) -> str:
    """Generate Bill of Materials as CSV."""
    try:
        result = tool_export_bom_csv(session_id=session, design_name=design_name)
        return result["csv"]
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/{design_name}/bom/json", responses=_NOT_FOUND_RESPONSE)
def export_bom_json(
    design_name: str,
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """Generate Bill of Materials as JSON."""
    try:
        return tool_export_bom_json(session_id=session, design_name=design_name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/{design_name}/report", responses=_NOT_FOUND_RESPONSE)
def export_report(
    design_name: str,
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """Generate a Markdown design report."""
    try:
        return tool_export_report(session_id=session, design_name=design_name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/{design_name}/svg", responses=_NOT_FOUND_RESPONSE)
def export_svg(
    design_name: str,
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """Render a schematic overview as SVG."""
    try:
        return tool_export_svg(session_id=session, design_name=design_name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/{design_name}/kicad", responses=_BAD_REQUEST_OR_NOT_FOUND_RESPONSES)
def export_kicad(
    design_name: str,
    output_dir: str,
    approval_id: str,
    session: str = Depends(authorize_tool("export_kicad")),
) -> dict[str, Any]:
    """Export design to KiCad files."""
    try:
        return tool_export_kicad(
            session_id=session,
            design_name=design_name,
            output_dir=output_dir,
            approval_id=approval_id,
        )
    except ValueError as e:
        status = 400 if "Path outside workspace" in str(e) else 404
        raise HTTPException(status, str(e)) from e


@router.post("/{design_name}/place", responses=_NOT_FOUND_RESPONSE)
def place_design(
    design_name: str,
    session: str = Depends(authorize_tool("place_components")),
) -> dict[str, Any]:
    """Place components on the board."""
    try:
        return tool_place_components(session_id=session, design_name=design_name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/{design_name}/route", responses=_NOT_FOUND_RESPONSE)
def route_design(
    design_name: str,
    session: str = Depends(authorize_tool("route_nets")),
) -> dict[str, Any]:
    """Route all nets."""
    try:
        return tool_route_nets(session_id=session, design_name=design_name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/diff/{design_a}/{design_b}", responses=_NOT_FOUND_RESPONSE)
def diff_designs_endpoint(
    design_a: str,
    design_b: str,
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """Diff two designs."""
    try:
        return tool_design_diff(
            session_id=session,
            design_a_name=design_a,
            design_b_name=design_b,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
