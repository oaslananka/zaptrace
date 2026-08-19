"""Shared declarative registry parameter schemas."""

from __future__ import annotations

from typing import Any

_SESSION_DESCRIPTION = "Session identifier"
_DESIGN_DESCRIPTION = "Design name"
_INTENT_DESCRIPTION = "Design intent description"
_APPROVAL_DESCRIPTION = "External approval or release gate identifier"
_TRANSACTION_ID_DESCRIPTION = "Transaction identifier"
_E_SERIES_DESCRIPTION = "E-series to snap to (12 or 24)"

_RELEASE_EVIDENCE_PARAM_SCHEMA: dict[str, dict[str, Any]] = {
    "fab_profile_skip_reason": {
        "type": "string",
        "description": "Explicit approved reason when a manufacturer fabrication profile is not applicable",
    },
    "fab_profile_skip_approval_id": {
        "type": "string",
        "description": "Approval identifier authorizing the fabrication-profile skip reason",
    },
    "risky_package_reviewed": {
        "type": "boolean",
        "description": "Whether risky package footprint evidence received explicit human review",
    },
    "risky_package_approval_id": {
        "type": "string",
        "description": "Approval identifier for risky package footprint evidence",
    },
}

__all__ = [
    "_APPROVAL_DESCRIPTION",
    "_DESIGN_DESCRIPTION",
    "_E_SERIES_DESCRIPTION",
    "_INTENT_DESCRIPTION",
    "_RELEASE_EVIDENCE_PARAM_SCHEMA",
    "_SESSION_DESCRIPTION",
    "_TRANSACTION_ID_DESCRIPTION",
]
