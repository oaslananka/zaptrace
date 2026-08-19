"""Deny-by-default capability policy and audit events.

The policy is intentionally small and dependency-free so it can be shared by
REST, MCP, tests, and proof-pack integrations.  Read-only tools are public by
process policy; mutating/exporting tools require explicit capability grants.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

CAPABILITY_LEVELS: tuple[str, ...] = (
    "read",
    "preview-write",
    "sandbox-write",
    "approved-commit",
    "release-export",
)

CAPABILITY_RANK = {name: idx for idx, name in enumerate(CAPABILITY_LEVELS)}


@dataclass(frozen=True)
class AuditEvent:
    """A structured audit record for a policy decision or mutating operation."""

    event_id: str
    timestamp: str
    surface: str
    session_id: str
    actor: str
    tool: str
    capability: str
    decision: str
    reason: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def granted_capabilities_from_header(raw: str | None) -> set[str]:
    """Parse a comma/space-separated capability header into a normalized set."""
    if not raw:
        return set()
    tokens = raw.replace(",", " ").split()
    return {token.strip().lower() for token in tokens if token.strip() in CAPABILITY_RANK}


def authorize_capability(required: str, granted: set[str]) -> tuple[bool, str]:
    """Return (allowed, reason) for a required capability and explicit grants.

    `read` is intentionally allowed without a grant because read-only inspection
    is not a mutating operation. All other capabilities are deny-by-default.
    Higher capability grants imply lower-risk write levels.
    """
    if required == "read":
        return True, "read-only operation"
    required_rank = CAPABILITY_RANK.get(required)
    if required_rank is None:
        return False, f"unknown required capability: {required}"
    if not granted:
        return False, f"missing required capability: {required}"
    if any(CAPABILITY_RANK.get(cap, -1) >= required_rank for cap in granted):
        return True, f"capability grant satisfies {required}"
    return False, f"requires {required}; granted {sorted(granted)}"


def record_audit_event(
    session: dict[str, Any],
    *,
    surface: str,
    session_id: str,
    actor: str,
    tool: str,
    capability: str,
    decision: str,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append an audit event to a session and return it as a dict."""
    event = AuditEvent(
        event_id=str(uuid4()),
        timestamp=datetime.now(UTC).isoformat(),
        surface=surface,
        session_id=session_id,
        actor=actor,
        tool=tool,
        capability=capability,
        decision=decision,
        reason=reason,
        metadata=metadata or {},
    ).to_dict()
    session.setdefault("audit_events", []).append(event)
    from zaptrace.agent.tool_impls.runtime import _persist_audit_event

    _persist_audit_event(event)
    return event


# Every public TOOL_REGISTRY entry must have an explicit capability here.
# Exact registry-policy equality is validated during agent tool import.
TOOL_CAPABILITIES: dict[str, str] = {
    "design_parse_file": "preview-write",
    "design_parse_str": "preview-write",
    "design_inspect": "read",
    "design_list_nets": "read",
    "synthesize_design": "preview-write",
    "list_synthesis_templates": "read",
    "erc_validate": "sandbox-write",
    "erc_get_result": "read",
    "erc_list_rules": "read",
    "place_components": "sandbox-write",
    "route_nets": "sandbox-write",
    "library_search": "read",
    "library_get": "read",
    "library_list_categories": "read",
    "export_bom_csv": "read",
    "export_bom_json": "read",
    "export_report": "sandbox-write",
    "export_svg": "sandbox-write",
    "export_kicad": "release-export",
    "kicad_import_project": "preview-write",
    "design_diff": "read",
    "kicad_to_easyeda_pro": "sandbox-write",
    "pipeline_run": "preview-write",
    "pipeline_run_stage": "preview-write",
    "pipeline_status": "read",
    "patch_suggest": "read",
    "board_update": "sandbox-write",
    "component_add": "sandbox-write",
    "component_remove": "sandbox-write",
    "export_gerber": "release-export",
    "export_excellon": "release-export",
    "drc_run": "sandbox-write",
    "drc_get_result": "read",
    "drc_list_rules": "read",
    "mechanical_review": "read",
    "security_review": "read",
    "testability_report": "read",
    "electrical_analysis": "read",
    "requirements_parse": "read",
    "requirements_review": "read",
    "power_tree_plan": "read",
    "synthesize_power_tree": "preview-write",
    "synthesize_and_check": "preview-write",
    "board_plan": "read",
    "synthesize_board": "preview-write",
    "synthesize_board_and_check": "preview-write",
    "synthesize_board_repair": "preview-write",
    "synthesize_board_manufacture": "release-export",
    "synthesis_benchmark": "read",
    "synthesize_board_score": "preview-write",
    "resolve_footprints": "sandbox-write",
    "dc_bias_check": "read",
    "simulation_gate": "sandbox-write",
    "compliance_checklist": "read",
    "board_classify_nets": "sandbox-write",
    "board_summarize_nets": "read",
    "design_route_smart": "sandbox-write",
    "design_classify_nets": "sandbox-write",
    "footprint_search": "read",
    "footprint_get": "read",
    "design_snapshot": "sandbox-write",
    "design_rollback": "sandbox-write",
    "design_list_snapshots": "read",
    "design_commit": "approved-commit",
    "design_transaction_preview": "preview-write",
    "design_transaction_validate": "sandbox-write",
    "design_transaction_commit": "approved-commit",
    "design_transaction_rollback": "sandbox-write",
    "design_transaction_list": "read",
    "board_export": "read",
    "schematic_render": "read",
    "footprint_generate": "read",
    "footprint_list_packages": "read",
    "export_manufacturing": "release-export",
    "export_pick_and_place": "release-export",
    "proof_run": "sandbox-write",
    "proof_run_design": "sandbox-write",
    "proof_list_checks": "read",
    "audit_list_events": "read",
    "export_spice": "read",
    "calc_led_resistor": "read",
    "calc_voltage_divider": "read",
    "calc_rc_filter": "read",
    "calc_i2c_pullup": "read",
    "calc_e_series": "read",
    "calc_usb_c_cc": "read",
    "calc_decoupling": "read",
    "calc_lipo_charge": "read",
    "calc_buck_lc": "read",
    "easyeda_std_roundtrip": "read",
    "altium_import_fidelity": "read",
    "kicad_3d_model_coverage": "read",
    "kicad_step_export": "sandbox-write",
}


# Filesystem parameters are explicit policy metadata, never inferred from names.
TOOL_PATH_POLICIES: dict[str, dict[str, dict[str, Any]]] = {
    "design_parse_file": {
        "path": {"root": "workspace", "access": "input", "must_exist": True},
    },
    "export_report": {
        "output_path": {"root": "workspace", "access": "output", "must_exist": False},
    },
    "export_svg": {
        "output_path": {"root": "workspace", "access": "output", "must_exist": False},
    },
    "export_kicad": {
        "output_dir": {"root": "workspace", "access": "output", "must_exist": False},
    },
    "kicad_import_project": {
        "project_path": {"root": "workspace", "access": "input", "must_exist": True},
    },
    "kicad_to_easyeda_pro": {
        "project_path": {"root": "workspace", "access": "input", "must_exist": True},
        "output_path": {"root": "workspace", "access": "output", "must_exist": False},
    },
    "pipeline_run": {
        "source": {"root": "workspace", "access": "input", "must_exist": True},
        "output_dir": {"root": "workspace", "access": "output", "must_exist": False},
    },
    "pipeline_run_stage": {
        "source": {"root": "workspace", "access": "input", "must_exist": True},
        "output_dir": {"root": "workspace", "access": "output", "must_exist": False},
    },
    "export_gerber": {
        "output_dir": {"root": "workspace", "access": "output", "must_exist": False},
    },
    "export_excellon": {
        "output_dir": {"root": "workspace", "access": "output", "must_exist": False},
    },
    "drc_run": {
        "fab_profile": {
            "root": "workspace",
            "access": "input",
            "must_exist": True,
            "path_suffixes": [".yaml", ".yml"],
        },
    },
    "synthesize_board_manufacture": {
        "output_dir": {"root": "workspace", "access": "output", "must_exist": False},
    },
    "export_manufacturing": {
        "output_dir": {"root": "workspace", "access": "output", "must_exist": False},
    },
    "proof_run": {
        "path": {"root": "workspace", "access": "input", "must_exist": True},
    },
    "proof_list_checks": {
        "path": {"root": "workspace", "access": "input", "must_exist": True},
    },
}

# Non-registry REST/review operations use a separate namespace so the
# public tool inventory can be checked for exact equality.
OPERATION_CAPABILITIES: dict[str, str] = {
    "artifact_create": "preview-write",
    "artifact_delete": "sandbox-write",
    "artifact_cleanup": "sandbox-write",
    "review_start": "sandbox-write",
    "review_approve": "sandbox-write",
    "review_reject": "sandbox-write",
    "review_waive": "preview-write",
    "review_decide": "approved-commit",
}


def required_tool_capability(tool_name: str) -> str:
    """Return the explicit capability for a public agent tool."""
    try:
        return TOOL_CAPABILITIES[tool_name]
    except KeyError:
        raise KeyError(f"No explicit capability policy for public tool '{tool_name}'") from None


def required_operation_capability(operation_name: str) -> str:
    """Return capability for REST/review operations or registered tools."""
    if operation_name in OPERATION_CAPABILITIES:
        return OPERATION_CAPABILITIES[operation_name]
    return required_tool_capability(operation_name)


def validate_tool_capability_inventory(tool_names: Collection[str]) -> None:
    """Fail startup when registry and capability policy drift apart."""
    registered = set(tool_names)
    declared = set(TOOL_CAPABILITIES)
    missing = sorted(registered - declared)
    extra = sorted(declared - registered)
    invalid = {
        name: capability for name, capability in sorted(TOOL_CAPABILITIES.items()) if capability not in CAPABILITY_RANK
    }
    if missing or extra or invalid:
        raise RuntimeError(
            f"Tool capability inventory mismatch: missing={missing or []}; extra={extra or []}; invalid={invalid or {}}"
        )
