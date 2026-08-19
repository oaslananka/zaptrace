"""Declarative transactions tool registry fragment."""

# ruff: noqa: E501

from __future__ import annotations

from .registry_shared import (
    _APPROVAL_DESCRIPTION,
    _DESIGN_DESCRIPTION,
    _SESSION_DESCRIPTION,
    _TRANSACTION_ID_DESCRIPTION,
)
from .transactions import (
    tool_audit_list_events,
    tool_design_commit,
    tool_design_list_snapshots,
    tool_design_rollback,
    tool_design_snapshot,
    tool_design_transaction_commit,
    tool_design_transaction_list,
    tool_design_transaction_preview,
    tool_design_transaction_rollback,
    tool_design_transaction_validate,
)

TRANSACTIONS_REGISTRY: dict[str, dict[str, object]] = {
    "design_snapshot": {
        "name": "design_snapshot",
        "description": "Capture a point-in-time snapshot of a design for later rollback",
        "fn": tool_design_snapshot,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": "Design name to snapshot"},
            "label": {"type": "string", "description": "Optional label for the snapshot (auto-generated if omitted)"},
        },
    },
    "design_rollback": {
        "name": "design_rollback",
        "description": "Restore a design from a named snapshot (reverts all mutations)",
        "fn": tool_design_rollback,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": "Design name to rollback"},
            "label": {"type": "string", "description": "Snapshot label to restore from"},
        },
    },
    "design_list_snapshots": {
        "name": "design_list_snapshots",
        "description": "List available snapshots for a design (or all designs in session)",
        "fn": tool_design_list_snapshots,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": "Optional design name filter"},
        },
    },
    "design_commit": {
        "name": "design_commit",
        "description": "Confirm design changes by clearing snapshots for a design",
        "fn": tool_design_commit,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": "Design name to commit"},
            "label": {"type": "string", "description": "Optional snapshot label to commit (omitting clears all)"},
        },
    },
    "design_transaction_preview": {
        "name": "design_transaction_preview",
        "description": "Preview a design mutation as an isolated transaction without committing it",
        "fn": tool_design_transaction_preview,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "design_name": {"type": "string", "description": _DESIGN_DESCRIPTION},
            "operation": {"type": "string", "description": "Operation: board_update, component_add, component_remove"},
            "params": {"type": "object", "description": "Operation parameters"},
            "reason": {"type": "string", "description": "Why this transaction is proposed"},
        },
    },
    "design_transaction_validate": {
        "name": "design_transaction_validate",
        "description": "Validate a preview transaction without mutating primary state",
        "fn": tool_design_transaction_validate,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "transaction_id": {"type": "string", "description": _TRANSACTION_ID_DESCRIPTION},
        },
    },
    "design_transaction_commit": {
        "name": "design_transaction_commit",
        "description": "Commit a validated transaction after explicit approval",
        "fn": tool_design_transaction_commit,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "transaction_id": {"type": "string", "description": _TRANSACTION_ID_DESCRIPTION},
            "approval_id": {"type": "string", "description": _APPROVAL_DESCRIPTION},
        },
    },
    "design_transaction_rollback": {
        "name": "design_transaction_rollback",
        "description": "Reject or roll back a preview transaction without changing primary state",
        "fn": tool_design_transaction_rollback,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "transaction_id": {"type": "string", "description": _TRANSACTION_ID_DESCRIPTION},
        },
    },
    "design_transaction_list": {
        "name": "design_transaction_list",
        "description": "List transactions for a session",
        "fn": tool_design_transaction_list,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
        },
    },
    "audit_list_events": {
        "name": "audit_list_events",
        "description": "List recent security/audit events for a session",
        "fn": tool_audit_list_events,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "limit": {"type": "integer", "description": "Maximum number of events to return"},
        },
    },
}

__all__ = ["TRANSACTIONS_REGISTRY"]
