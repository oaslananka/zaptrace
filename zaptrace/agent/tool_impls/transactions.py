"""Transactions agent tool implementations."""

from __future__ import annotations

from .deps import Any, Component, copy, design_state_hash, diff_designs
from .runtime import (
    _delete_persistent_record,
    _delete_persistent_records,
    _get_erc_runner_type,
    _get_session,
    _persist_snapshot,
    _persist_transaction,
    _persist_transaction_history,
    _set_design,
)


def tool_design_snapshot(
    design_name: str,
    label: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Capture a point-in-time snapshot of a design for later rollback.

    Snapshots are stored per-design in the session.  Use a unique *label*
    to distinguish multiple snapshots; auto-generates a timestamp-based
    label if omitted.
    """
    import copy
    import time

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")

    snapshot_label = label or f"snap-{int(time.time() * 1000)}"
    session.setdefault("snapshots", {}).setdefault(design_name, {})[snapshot_label] = copy.deepcopy(design)

    # Also snapshot ancillary state
    ancillary = {
        "positions": copy.deepcopy(session.get("positions", {}).get(design_name)),
        "erc_results": copy.deepcopy(session.get("erc_results", {}).get(design_name)),
        "drc_results": copy.deepcopy(session.get("drc_results", {}).get(design_name)),
        "routing_results": copy.deepcopy(session.get("routing_results", {}).get(design_name)),
    }
    session.setdefault("snapshots_ancillary", {}).setdefault(design_name, {})[snapshot_label] = ancillary
    _persist_snapshot(session_id, design_name, snapshot_label, design, ancillary)

    return {
        "design": design_name,
        "snapshot": snapshot_label,
        "component_count": len(design.components),
        "net_count": len(design.nets),
    }


def tool_design_rollback(
    design_name: str,
    label: str,
    session_id: str = "default",
) -> dict[str, Any]:
    """Restore a design (and ancillary state) from a named snapshot.

    Raises ``ValueError`` if the snapshot does not exist.
    """
    session = _get_session(session_id)
    snapshots = session.get("snapshots", {}).get(design_name, {})
    if label not in snapshots:
        available = list(snapshots.keys())
        raise ValueError(f"Snapshot '{label}' not found for design '{design_name}'. Available: {available}")

    # Restore design
    _set_design(session, design_name, copy.deepcopy(snapshots[label]), operation="snapshot-rollback")

    # Restore ancillary state
    ancillary = session.get("snapshots_ancillary", {}).get(design_name, {}).get(label, {})
    for key, value in ancillary.items():
        if value is not None:
            session.setdefault(key, {})[design_name] = value
        else:
            session.get(key, {}).pop(design_name, None)

    return {
        "design": design_name,
        "restored_from": label,
        "component_count": len(snapshots[label].components),
        "net_count": len(snapshots[label].nets),
    }


def tool_design_list_snapshots(
    design_name: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """List available snapshots for a design (or all designs)."""
    session = _get_session(session_id)
    all_snaps = session.get("snapshots", {})

    if design_name:
        snaps = all_snaps.get(design_name, {})
        return {
            "design": design_name,
            "snapshots": [
                {
                    "label": label,
                    "component_count": len(d.components),
                    "net_count": len(d.nets),
                }
                for label, d in snaps.items()
            ],
            "count": len(snaps),
        }

    result = {}
    for dname, snaps in all_snaps.items():
        result[dname] = [
            {
                "label": label,
                "component_count": len(d.components),
                "net_count": len(d.nets),
            }
            for label, d in snaps.items()
        ]
    return {"snapshots_by_design": result, "total_snapshots": sum(len(v) for v in all_snaps.values())}


def tool_design_commit(
    design_name: str,
    label: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Confirm design changes by removing old snapshots.

    If *label* is provided, only that snapshot is removed (confirming the
    state at that point).  If *label* is None, all snapshots for the
    design are cleared.
    """
    session = _get_session(session_id)
    snaps = session.get("snapshots", {}).get(design_name, {})
    anc = session.get("snapshots_ancillary", {}).get(design_name, {})

    if label:
        removed = snaps.pop(label, None)
        anc.pop(label, None)
        if removed is None:
            available = list(snaps.keys())
            raise ValueError(f"Snapshot '{label}' not found for '{design_name}'. Available: {available}")
        removed_count = 1
        _delete_persistent_record(session_id, "snapshot", f"{design_name}:{label}")
    else:
        removed_count = len(snaps)
        session["snapshots"][design_name] = {}
        session["snapshots_ancillary"][design_name] = {}
        _delete_persistent_records(session_id, "snapshot", design_name=design_name)

    return {
        "design": design_name,
        "removed_snapshots": removed_count,
        "remaining_snapshots": len(session.get("snapshots", {}).get(design_name, {})),
    }


def _apply_board_update(design: Any, params: dict[str, Any]) -> None:
    """Apply bounded board geometry updates to a candidate design."""
    if params.get("width_mm") is not None:
        design.board.width_mm = float(params["width_mm"])
    if params.get("height_mm") is not None:
        design.board.height_mm = float(params["height_mm"])
    if params.get("layers") is not None:
        design.board.layers = int(params["layers"])


def _apply_component_add(design: Any, params: dict[str, Any]) -> None:
    """Add one component to a candidate design."""
    import uuid

    component_id = str(params.get("component_id") or str(uuid.uuid4())[:8])
    component = Component(
        id=component_id,
        ref=str(params["ref"]),
        type=str(params["type_name"]),
        value=params.get("value"),
        footprint=str(params.get("footprint") or ""),
    )
    design.components[component.id] = component


def _apply_component_remove(design: Any, params: dict[str, Any]) -> None:
    """Remove one component and any nets left without nodes."""
    component_id = str(params["component_id"])
    if component_id not in design.components:
        raise ValueError(f"Component '{component_id}' not in design")
    component_ref = design.components[component_id].ref
    del design.components[component_id]

    empty_nets: list[str] = []
    for net_id, net in design.nets.items():
        net.nodes = [node for node in net.nodes if node.component_ref != component_ref]
        if not net.nodes:
            empty_nets.append(net_id)
    for net_id in empty_nets:
        del design.nets[net_id]


def _apply_transaction_operation(design: Any, operation: str, params: dict[str, Any]) -> None:
    """Apply a supported transaction operation to a candidate design copy."""
    operations = {
        "board_update": _apply_board_update,
        "component_add": _apply_component_add,
        "component_remove": _apply_component_remove,
    }
    handler = operations.get(operation)
    if handler is None:
        raise ValueError(f"Unsupported transaction operation: {operation}")
    handler(design, params)


def _semantic_diff_records(entries: list[Any]) -> list[dict[str, Any]]:
    """Return JSON-safe semantic diff records."""
    return [
        {
            "type": entry.type.value if hasattr(entry.type, "value") else str(entry.type),
            "ref": entry.ref,
            "detail": entry.detail,
            "old_value": entry.old_value,
            "new_value": entry.new_value,
        }
        for entry in entries
    ]


def _transaction_public_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a serializable transaction record without candidate object internals."""
    hidden = {"candidate_design"}
    return {k: v for k, v in record.items() if k not in hidden}


def tool_design_transaction_preview(
    design_name: str,
    operation: str,
    params: dict[str, Any],
    reason: str = "",
    session_id: str = "default",
) -> dict[str, Any]:
    """Preview a design mutation as an isolated transaction without committing it."""
    from secrets import token_urlsafe

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")

    candidate = copy.deepcopy(design)
    _apply_transaction_operation(candidate, operation, params)
    entries = diff_designs(design, candidate)
    tx_id = f"tx-{token_urlsafe(24)}"
    record = {
        "transaction_id": tx_id,
        "session_id": session_id,
        "design_name": design_name,
        "operation": operation,
        "params": params,
        "state": "previewed",
        "reason": reason,
        "parent_state_hash": design_state_hash(design),
        "preview_state_hash": design_state_hash(candidate),
        "changed_entities": [entry.ref for entry in entries],
        "semantic_diff": _semantic_diff_records(entries),
        "validation": {"status": "not_run", "required_before_commit": True},
        "candidate_design": candidate,
    }
    session.setdefault("transactions", {})[tx_id] = record
    _persist_transaction(session_id, record)
    return _transaction_public_record(record)


def tool_design_transaction_validate(transaction_id: str, session_id: str = "default") -> dict[str, Any]:
    """Run validation against a transaction candidate without mutating primary state."""
    session = _get_session(session_id)
    record = session.get("transactions", {}).get(transaction_id)
    if record is None:
        raise ValueError(f"Transaction '{transaction_id}' not found")
    if record["state"] not in {"previewed", "validated"}:
        raise ValueError(f"Transaction '{transaction_id}' cannot be validated from state {record['state']}")

    candidate = record["candidate_design"]
    runner = _get_erc_runner_type()()
    result = runner.run(candidate)
    validation = {
        "status": "passed" if result.passed else "failed",
        "erc_errors": result.total_errors,
        "erc_warnings": result.total_warnings,
        "erc_info": result.total_info,
    }
    record["validation"] = validation
    record["state"] = "validated" if result.passed else "rejected"
    _persist_transaction(session_id, record)
    return _transaction_public_record(record)


def tool_design_transaction_commit(
    transaction_id: str,
    approval_id: str,
    session_id: str = "default",
) -> dict[str, Any]:
    """Commit a validated transaction after explicit approval."""
    if not approval_id or not approval_id.strip():
        raise ValueError("approval_id is required to commit a transaction")

    session = _get_session(session_id)
    record = session.get("transactions", {}).get(transaction_id)
    if record is None:
        raise ValueError(f"Transaction '{transaction_id}' not found")
    if record["state"] != "validated":
        raise ValueError(f"Transaction '{transaction_id}' must be validated before commit")
    if record.get("validation", {}).get("status") != "passed":
        raise ValueError(f"Transaction '{transaction_id}' validation did not pass")

    design_name = record["design_name"]
    previous = session.get("designs", {}).get(design_name)
    candidate = record["candidate_design"]
    if previous is None:
        raise ValueError(f"Design '{design_name}' not found")
    if design_state_hash(previous) != record["parent_state_hash"]:
        record["state"] = "rejected"
        _persist_transaction(session_id, record)
        raise ValueError("Primary design state changed since preview; re-preview is required")

    _set_design(session, design_name, copy.deepcopy(candidate), operation="transaction-commit")
    record["state"] = "committed"
    record["approval_id"] = approval_id
    record["committed_state_hash"] = design_state_hash(candidate)
    public_record = _transaction_public_record(record)
    session.setdefault("transaction_history", []).append(public_record)
    _persist_transaction(session_id, record)
    _persist_transaction_history(session_id, public_record)
    return public_record


def tool_design_transaction_rollback(transaction_id: str, session_id: str = "default") -> dict[str, Any]:
    """Reject or roll back a preview transaction without changing primary state."""
    session = _get_session(session_id)
    record = session.get("transactions", {}).get(transaction_id)
    if record is None:
        raise ValueError(f"Transaction '{transaction_id}' not found")
    if record["state"] == "committed":
        raise ValueError("Committed transactions cannot be rolled back by preview rollback")
    record["state"] = "rolled_back"
    public_record = _transaction_public_record(record)
    session.setdefault("transaction_history", []).append(public_record)
    _persist_transaction(session_id, record)
    _persist_transaction_history(session_id, public_record)
    return public_record


def tool_design_transaction_list(session_id: str = "default") -> dict[str, Any]:
    """List transactions for a session."""
    session = _get_session(session_id)
    transactions = [_transaction_public_record(r) for r in session.get("transactions", {}).values()]
    return {"session_id": session_id, "transactions": transactions, "count": len(transactions)}


def tool_audit_list_events(session_id: str = "default", limit: int = 50) -> dict[str, Any]:
    """List recent security/audit events for a session."""
    session = _get_session(session_id)
    events = list(session.get("audit_events", []))
    if limit < 1:
        limit = 1
    return {"session_id": session_id, "count": len(events), "events": events[-limit:]}


__all__ = [
    "tool_design_snapshot",
    "tool_design_rollback",
    "tool_design_list_snapshots",
    "tool_design_commit",
    "_apply_transaction_operation",
    "_semantic_diff_records",
    "_transaction_public_record",
    "tool_design_transaction_preview",
    "tool_design_transaction_validate",
    "tool_design_transaction_commit",
    "tool_design_transaction_rollback",
    "tool_design_transaction_list",
    "tool_audit_list_events",
]
