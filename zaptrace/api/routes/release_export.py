"""Release-class export API routes with complete evidence inputs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from zaptrace.agent._tool_impls import tool_export_kicad
from zaptrace.api.routes._session import authorize_tool

router = APIRouter()


@router.post(
    "/{design_name}/kicad",
    responses={
        400: {"description": "Release evidence or output path is invalid"},
        404: {"description": "Design not found"},
    },
)
def export_kicad_release(
    design_name: str,
    output_dir: str,
    approval_id: str,
    session: Annotated[str, Depends(authorize_tool("export_kicad"))],
    fab_profile_skip_reason: str | None = None,
    fab_profile_skip_approval_id: str | None = None,
    risky_package_reviewed: bool = False,
    risky_package_approval_id: str | None = None,
) -> dict[str, Any]:
    """Export KiCad files only after the complete current release gate passes."""
    try:
        return tool_export_kicad(
            session_id=session,
            design_name=design_name,
            output_dir=output_dir,
            approval_id=approval_id,
            fab_profile_skip_reason=fab_profile_skip_reason,
            fab_profile_skip_approval_id=fab_profile_skip_approval_id,
            risky_package_reviewed=risky_package_reviewed,
            risky_package_approval_id=risky_package_approval_id,
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 400
        raise HTTPException(status, message) from exc
