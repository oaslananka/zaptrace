"""Design CRUD and inspection API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from zaptrace.agent._tool_impls import (
    _get_session,
    tool_board_update,
    tool_component_add,
    tool_component_remove,
    tool_design_inspect,
    tool_design_list_nets,
    tool_design_parse_file,
    tool_design_parse_str,
    tool_design_transaction_commit,
    tool_design_transaction_list,
    tool_design_transaction_preview,
    tool_design_transaction_rollback,
    tool_design_transaction_validate,
)
from zaptrace.api.models import TransactionCommitRequest, TransactionPreviewRequest
from zaptrace.api.routes._responses import _BAD_REQUEST_RESPONSE, _NOT_FOUND_RESPONSE
from zaptrace.api.routes._session import authorize_tool, resolve_session_id

router = APIRouter()


def _get_design_or_404(name: str, session: str = "api-default") -> Any:
    sess = _get_session(session)
    design = sess.get("designs", {}).get(name)
    if design is None:
        raise HTTPException(404, f"Design '{name}' not found")
    return design


@router.post("/parse/file", responses=_BAD_REQUEST_RESPONSE)
def parse_design_file(
    path: str,
    session: str = Depends(authorize_tool("design_parse_file")),
) -> dict[str, Any]:
    """Parse a design from a YAML file."""
    try:
        return tool_design_parse_file(session_id=session, path=path)
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@router.post("/parse/str", responses=_BAD_REQUEST_RESPONSE)
def parse_design_str(
    yaml_content: str,
    session: str = Depends(authorize_tool("design_parse_str")),
) -> dict[str, Any]:
    """Parse a design from a YAML string."""
    try:
        return tool_design_parse_str(session_id=session, yaml_content=yaml_content)
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@router.get("/{name}", responses=_NOT_FOUND_RESPONSE)
def inspect_design(
    name: str,
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """Inspect a parsed design."""
    try:
        return tool_design_inspect(session_id=session, design_name=name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/{name}/nets", responses=_NOT_FOUND_RESPONSE)
def list_nets(
    name: str,
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """List all nets in a design."""
    try:
        return tool_design_list_nets(session_id=session, design_name=name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/{name}/components", responses=_NOT_FOUND_RESPONSE)
def add_component(
    name: str,
    component_id: str,
    ref: str,
    type_name: str,
    value: str | None = None,
    footprint: str = "",
    session: str = Depends(authorize_tool("component_add")),
) -> dict[str, Any]:
    """Add a component to a design."""
    try:
        return tool_component_add(
            session_id=session,
            design_name=name,
            component_id=component_id,
            ref=ref,
            type_name=type_name,
            value=value,
            footprint=footprint,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.delete("/{name}/components/{component_id}", responses=_NOT_FOUND_RESPONSE)
def remove_component(
    name: str,
    component_id: str,
    session: str = Depends(authorize_tool("component_remove")),
) -> dict[str, Any]:
    """Remove a component from a design."""
    try:
        return tool_component_remove(
            session_id=session,
            design_name=name,
            component_id=component_id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.patch("/{name}/board", responses=_NOT_FOUND_RESPONSE)
def update_board(
    name: str,
    width_mm: float | None = None,
    height_mm: float | None = None,
    layers: int | None = None,
    session: str = Depends(authorize_tool("board_update")),
) -> dict[str, Any]:
    """Update board configuration."""
    try:
        return tool_board_update(
            session_id=session,
            design_name=name,
            width_mm=width_mm,
            height_mm=height_mm,
            layers=layers,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/{name}/transactions/preview", responses=_BAD_REQUEST_RESPONSE)
def preview_transaction(
    name: str,
    request: TransactionPreviewRequest,
    session: str = Depends(authorize_tool("design_transaction_preview")),
) -> dict[str, Any]:
    """Preview a transaction-safe design mutation without committing it."""
    try:
        return tool_design_transaction_preview(
            session_id=session,
            design_name=name,
            operation=request.operation,
            params=request.params,
            reason=request.reason,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/transactions/{transaction_id}/validate", responses=_BAD_REQUEST_RESPONSE)
def validate_transaction(
    transaction_id: str,
    session: str = Depends(authorize_tool("design_transaction_validate")),
) -> dict[str, Any]:
    """Validate a preview transaction without mutating the primary design."""
    try:
        return tool_design_transaction_validate(session_id=session, transaction_id=transaction_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/transactions/{transaction_id}/commit", responses=_BAD_REQUEST_RESPONSE)
def commit_transaction(
    transaction_id: str,
    request: TransactionCommitRequest,
    session: str = Depends(authorize_tool("design_transaction_commit")),
) -> dict[str, Any]:
    """Commit a validated transaction after explicit approval."""
    try:
        return tool_design_transaction_commit(
            session_id=session,
            transaction_id=transaction_id,
            approval_id=request.approval_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/transactions/{transaction_id}/rollback", responses=_BAD_REQUEST_RESPONSE)
def rollback_transaction(
    transaction_id: str,
    session: str = Depends(authorize_tool("design_transaction_rollback")),
) -> dict[str, Any]:
    """Reject or roll back a preview transaction without mutating primary state."""
    try:
        return tool_design_transaction_rollback(session_id=session, transaction_id=transaction_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/transactions/list")
def list_transactions(
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """List transaction records for the current session."""
    return tool_design_transaction_list(session_id=session)
