"""Assembled public agent tool registry and secure dispatch surface."""

from __future__ import annotations

from typing import Any

from zaptrace.security.policy import (
    TOOL_PATH_POLICIES,
    required_tool_capability,
    validate_tool_capability_inventory,
)

from .registry_calculators import CALCULATORS_REGISTRY
from .registry_design import DESIGN_REGISTRY
from .registry_exports import EXPORTS_REGISTRY
from .registry_interop import INTEROP_REGISTRY
from .registry_library import LIBRARY_REGISTRY
from .registry_pipeline import PIPELINE_REGISTRY
from .registry_proof import PROOF_REGISTRY
from .registry_routing import ROUTING_REGISTRY
from .registry_synthesis import SYNTHESIS_REGISTRY
from .registry_transactions import TRANSACTIONS_REGISTRY
from .registry_verification import VERIFICATION_REGISTRY

_TOOL_ORDER = [
    "design_parse_file",
    "design_parse_str",
    "design_inspect",
    "design_list_nets",
    "synthesize_design",
    "list_synthesis_templates",
    "erc_validate",
    "erc_get_result",
    "erc_list_rules",
    "place_components",
    "route_nets",
    "library_search",
    "library_get",
    "library_list_categories",
    "export_bom_csv",
    "export_bom_json",
    "export_report",
    "export_svg",
    "export_kicad",
    "kicad_import_project",
    "design_diff",
    "kicad_to_easyeda_pro",
    "pipeline_run",
    "pipeline_run_stage",
    "pipeline_status",
    "patch_suggest",
    "board_update",
    "component_add",
    "component_remove",
    "export_gerber",
    "export_excellon",
    "drc_run",
    "drc_get_result",
    "drc_list_rules",
    "mechanical_review",
    "security_review",
    "testability_report",
    "electrical_analysis",
    "requirements_parse",
    "requirements_review",
    "power_tree_plan",
    "synthesize_power_tree",
    "synthesize_and_check",
    "board_plan",
    "synthesize_board",
    "synthesize_board_and_check",
    "synthesize_board_repair",
    "synthesize_board_manufacture",
    "synthesis_benchmark",
    "synthesize_board_score",
    "resolve_footprints",
    "dc_bias_check",
    "simulation_gate",
    "compliance_checklist",
    "board_classify_nets",
    "board_summarize_nets",
    "design_route_smart",
    "design_classify_nets",
    "footprint_search",
    "footprint_get",
    "design_snapshot",
    "design_rollback",
    "design_list_snapshots",
    "design_commit",
    "design_transaction_preview",
    "design_transaction_validate",
    "design_transaction_commit",
    "design_transaction_rollback",
    "design_transaction_list",
    "board_export",
    "schematic_render",
    "footprint_generate",
    "footprint_list_packages",
    "export_manufacturing",
    "export_pick_and_place",
    "proof_run",
    "proof_run_design",
    "proof_list_checks",
    "audit_list_events",
    "export_spice",
    "calc_led_resistor",
    "calc_voltage_divider",
    "calc_rc_filter",
    "calc_i2c_pullup",
    "calc_e_series",
    "calc_usb_c_cc",
    "calc_decoupling",
    "calc_lipo_charge",
    "calc_buck_lc",
    "easyeda_std_roundtrip",
    "altium_import_fidelity",
    "kicad_3d_model_coverage",
    "kicad_step_export",
]
_REGISTRY_FRAGMENTS = (
    DESIGN_REGISTRY,
    SYNTHESIS_REGISTRY,
    VERIFICATION_REGISTRY,
    ROUTING_REGISTRY,
    LIBRARY_REGISTRY,
    EXPORTS_REGISTRY,
    INTEROP_REGISTRY,
    PIPELINE_REGISTRY,
    TRANSACTIONS_REGISTRY,
    PROOF_REGISTRY,
    CALCULATORS_REGISTRY,
)

_ALL_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {}
for _fragment in _REGISTRY_FRAGMENTS:
    _overlap = set(_ALL_TOOL_DEFINITIONS) & set(_fragment)
    if _overlap:
        raise RuntimeError(f"Duplicate agent tool definitions: {sorted(_overlap)}")
    _ALL_TOOL_DEFINITIONS.update(_fragment)

_missing = set(_TOOL_ORDER) - set(_ALL_TOOL_DEFINITIONS)
_extra = set(_ALL_TOOL_DEFINITIONS) - set(_TOOL_ORDER)
if _missing or _extra:
    raise RuntimeError(f"Agent tool registry assembly mismatch: missing={sorted(_missing)}, extra={sorted(_extra)}")

TOOL_REGISTRY: dict[str, dict[str, Any]] = {name: _ALL_TOOL_DEFINITIONS[name] for name in _TOOL_ORDER}


def _validated_path_policy(tool_name: str, parameter_name: str, path_policy: dict[str, Any]) -> dict[str, Any]:
    """Return validated path-policy metadata for one public tool parameter."""
    policy_name = f"{tool_name}.{parameter_name}"
    if path_policy.get("root") != "workspace":
        raise RuntimeError(f"Unsupported path-policy root for {policy_name}")
    if path_policy.get("access") not in {"input", "output"}:
        raise RuntimeError(f"Unsupported path-policy access for {policy_name}")
    if not isinstance(path_policy.get("must_exist"), bool):
        raise RuntimeError(f"Invalid must_exist policy for {policy_name}")

    suffixes = path_policy.get("path_suffixes")
    valid_suffixes = (
        isinstance(suffixes, list)
        and bool(suffixes)
        and all(isinstance(suffix, str) and suffix.startswith(".") for suffix in suffixes)
    )
    if suffixes is not None and not valid_suffixes:
        raise RuntimeError(f"Invalid path_suffixes policy for {policy_name}")
    return dict(path_policy)


def _attach_tool_path_policies() -> None:
    """Attach validated filesystem policy metadata to registered tool parameters."""
    for tool_name, parameter_policies in TOOL_PATH_POLICIES.items():
        tool_def = TOOL_REGISTRY.get(tool_name)
        if tool_def is None:
            raise RuntimeError(f"Path policy references unknown tool: {tool_name}")
        params = tool_def.get("params", {})
        for parameter_name, path_policy in parameter_policies.items():
            param_spec = params.get(parameter_name)
            if param_spec is None:
                raise RuntimeError(f"Path policy references unknown parameter: {tool_name}.{parameter_name}")
            param_spec["path_policy"] = _validated_path_policy(tool_name, parameter_name, path_policy)


def _apply_tool_capabilities() -> None:
    """Validate and attach explicit capability and path policy metadata."""
    validate_tool_capability_inventory(TOOL_REGISTRY)
    for tool_name, tool_def in TOOL_REGISTRY.items():
        tool_def["capability"] = required_tool_capability(tool_name)
    _attach_tool_path_policies()


def get_tool(name: str) -> dict[str, Any]:
    """Get a tool definition by name."""
    if name not in TOOL_REGISTRY:
        raise KeyError(f"Tool '{name}' not found. Available: {list(TOOL_REGISTRY)}")
    return TOOL_REGISTRY[name]


def list_tools() -> list[dict[str, Any]]:
    """List all registered tools (without the function reference)."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "params": t["params"],
            "capability": t["capability"],
        }
        for t in TOOL_REGISTRY.values()
    ]


def call_tool(name: str, /, **kwargs: Any) -> Any:
    """Call a tool by name with keyword arguments.

    Sandbox checks are applied before execution:
    - Tool-call budget (call count & duration)
    - Dangerous-action classification
    - Prompt-injection detection on string params
    - Secret redaction on params
    Each call is recorded to the replayable session log.
    """
    import time

    from zaptrace.security.replay import record_tool_call
    from zaptrace.security.sandbox import (
        check_tool_budget,
        classify_tool_call,
        detect_prompt_injection,
        redact_secrets,
    )

    session_id = kwargs.get("session_id", "default")

    # ---- 1. Tool-call budget check ----
    check_tool_budget(session_id, name)

    # ---- 2. Scan user-controlled content for prompt injection ----
    # ``session_id`` is an opaque cryptographic identifier, not model content.
    # URL-safe random tokens can legitimately contain short substrings such as
    # "DAN", so scanning this identifier creates nondeterministic false positives.
    for param_key, param_val in kwargs.items():
        if param_key == "session_id":
            continue
        if isinstance(param_val, str):
            findings = detect_prompt_injection(param_val)
            if findings:
                patterns = [f["pattern"] for f in findings]
                raise ValueError(
                    f"Prompt injection detected in parameter '{param_key}' (patterns: {patterns}). Tool call blocked."
                )

    # ---- 3. Classify action risk ----
    risk = classify_tool_call(session_id, name, kwargs)

    # ---- 4. Redact secrets from kwargs (for logging) ----
    safe_params = {}
    for k, v in kwargs.items():
        safe_params[k] = redact_secrets(v) if isinstance(v, str) else v

    # ---- 5. Execute the tool ----
    tool_def = get_tool(name)
    t0 = time.perf_counter()
    try:
        result = tool_def["fn"](**kwargs)
    except Exception as exc:
        # Record failed call too
        elapsed = (time.perf_counter() - t0) * 1000
        record_tool_call(
            session_id,
            name,
            safe_params,
            result={"error": str(exc)},
            duration_ms=elapsed,
            risk=risk.value,
        )
        raise

    elapsed = (time.perf_counter() - t0) * 1000

    # ---- 6. Record to replay log ----
    record_tool_call(
        session_id,
        name,
        safe_params,
        result=result,
        duration_ms=elapsed,
        risk=risk.value,
    )

    return result


_apply_tool_capabilities()

__all__ = ["TOOL_REGISTRY", "call_tool", "get_tool", "list_tools"]
