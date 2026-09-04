"""Deterministic task-oriented views over the authoritative agent tool registry."""

from __future__ import annotations

from collections.abc import Mapping

from .tool_impls.registry import TOOL_REGISTRY

MCP_TOOL_SURFACE_ENV = "ZAPTRACE_MCP_TOOL_SURFACE"
SUPPORTED_TOOL_SURFACES = ("expert", "inspect", "design", "verify", "repair", "release")

_SURFACE_MEMBERS: Mapping[str, frozenset[str]] = {
    "inspect": frozenset(
        {
            "design_inspect",
            "design_list_nets",
            "design_diff",
            "pipeline_status",
            "library_search",
            "library_get",
            "library_list_categories",
            "erc_get_result",
            "erc_list_rules",
            "drc_get_result",
            "drc_list_rules",
            "mechanical_review",
            "security_review",
            "testability_report",
            "electrical_analysis",
            "requirements_parse",
            "requirements_review",
            "power_tree_plan",
            "board_plan",
            "dc_bias_check",
            "compliance_checklist",
            "board_summarize_nets",
            "footprint_search",
            "footprint_get",
            "design_list_snapshots",
            "design_transaction_list",
            "board_export",
            "schematic_render",
            "footprint_generate",
            "footprint_list_packages",
            "proof_list_checks",
            "audit_list_events",
            "export_spice",
            "kicad_3d_model_coverage",
        }
    ),
    "design": frozenset(
        {
            "design_parse_file",
            "design_parse_str",
            "design_inspect",
            "design_list_nets",
            "synthesize_design",
            "list_synthesis_templates",
            "place_components",
            "route_nets",
            "library_search",
            "library_get",
            "library_list_categories",
            "board_update",
            "component_add",
            "component_remove",
            "requirements_parse",
            "requirements_review",
            "power_tree_plan",
            "synthesize_power_tree",
            "synthesize_and_check",
            "board_plan",
            "synthesize_board",
            "synthesize_board_and_check",
            "synthesize_board_score",
            "resolve_footprints",
            "board_classify_nets",
            "board_summarize_nets",
            "design_route_smart",
            "design_classify_nets",
            "footprint_search",
            "footprint_get",
            "footprint_generate",
            "footprint_list_packages",
            "design_snapshot",
            "design_rollback",
            "design_list_snapshots",
            "design_commit",
            "design_transaction_preview",
            "design_transaction_validate",
            "design_transaction_commit",
            "design_transaction_rollback",
            "design_transaction_list",
            "schematic_render",
            "calc_led_resistor",
            "calc_voltage_divider",
            "calc_rc_filter",
            "calc_i2c_pullup",
            "calc_e_series",
            "calc_usb_c_cc",
            "calc_decoupling",
            "calc_lipo_charge",
            "calc_buck_lc",
        }
    ),
    "verify": frozenset(
        {
            "design_inspect",
            "design_list_nets",
            "erc_validate",
            "erc_get_result",
            "erc_list_rules",
            "drc_run",
            "drc_get_result",
            "drc_list_rules",
            "mechanical_review",
            "security_review",
            "testability_report",
            "electrical_analysis",
            "requirements_review",
            "dc_bias_check",
            "simulation_gate",
            "compliance_checklist",
            "board_summarize_nets",
            "proof_run",
            "proof_run_design",
            "proof_list_checks",
            "audit_list_events",
            "export_spice",
            "kicad_3d_model_coverage",
        }
    ),
    "repair": frozenset(
        {
            "design_inspect",
            "design_list_nets",
            "erc_validate",
            "erc_get_result",
            "drc_run",
            "drc_get_result",
            "patch_suggest",
            "board_update",
            "component_add",
            "component_remove",
            "synthesize_board_repair",
            "resolve_footprints",
            "board_classify_nets",
            "board_summarize_nets",
            "design_route_smart",
            "design_classify_nets",
            "design_snapshot",
            "design_rollback",
            "design_list_snapshots",
            "design_commit",
            "design_transaction_preview",
            "design_transaction_validate",
            "design_transaction_commit",
            "design_transaction_rollback",
            "design_transaction_list",
            "proof_run_design",
            "audit_list_events",
        }
    ),
    "release": frozenset(
        {
            "design_inspect",
            "erc_validate",
            "erc_get_result",
            "drc_run",
            "drc_get_result",
            "mechanical_review",
            "security_review",
            "testability_report",
            "electrical_analysis",
            "requirements_review",
            "dc_bias_check",
            "simulation_gate",
            "compliance_checklist",
            "design_commit",
            "export_bom_csv",
            "export_bom_json",
            "export_report",
            "export_svg",
            "export_kicad",
            "export_gerber",
            "export_excellon",
            "board_export",
            "schematic_render",
            "export_manufacturing",
            "export_pick_and_place",
            "synthesize_board_manufacture",
            "proof_run",
            "proof_run_design",
            "proof_list_checks",
            "audit_list_events",
            "export_spice",
            "kicad_3d_model_coverage",
            "kicad_step_export",
        }
    ),
}


def _validate_surface_membership() -> None:
    registry_names = set(TOOL_REGISTRY)
    for surface in SUPPORTED_TOOL_SURFACES[1:]:
        members = _SURFACE_MEMBERS.get(surface)
        if not members:
            raise RuntimeError(f"MCP tool surface has no members: {surface}")
        unknown = members - registry_names
        if unknown:
            raise RuntimeError(f"MCP tool surface {surface!r} references unknown tools: {sorted(unknown)}")
        if len(members) >= len(registry_names):
            raise RuntimeError(f"Reduced MCP tool surface is not reduced: {surface}")


def resolve_tool_surface(value: str | None) -> str:
    """Normalize one configured MCP tool surface and fail closed on unknown values."""
    normalized = (value or "expert").strip().lower() or "expert"
    if normalized not in SUPPORTED_TOOL_SURFACES:
        supported = ", ".join(SUPPORTED_TOOL_SURFACES)
        raise ValueError(f"Unsupported MCP tool surface {value!r}; expected one of: {supported}")
    return normalized


def surface_tool_names(surface: str) -> tuple[str, ...]:
    """Return one surface's registry tools in authoritative registry order."""
    normalized = resolve_tool_surface(surface)
    if normalized == "expert":
        return tuple(TOOL_REGISTRY)
    members = _SURFACE_MEMBERS[normalized]
    return tuple(name for name in TOOL_REGISTRY if name in members)


_validate_surface_membership()

__all__ = [
    "MCP_TOOL_SURFACE_ENV",
    "SUPPORTED_TOOL_SURFACES",
    "resolve_tool_surface",
    "surface_tool_names",
]
