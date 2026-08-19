"""Synthesis agent tool implementations."""

from __future__ import annotations

from .deps import Any, list_templates, synthesize_with_provenance
from .runtime import _get_erc_runner_type, _get_session, _persist_design, _require_release_gate, _validate_path
from .verification import tool_drc_run, tool_erc_validate


def tool_synthesize_design(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Select the best-matching pre-built template for an intent (template selection).

    This is not from-scratch circuit synthesis: no topology or component values
    are generated. The returned ``selection`` records which template was loaded.
    """
    design, selection = synthesize_with_provenance(intent)
    session = _get_session(session_id)
    session["designs"][design.meta.name] = design
    return {
        "design_name": design.meta.name,
        "component_count": len(design.components),
        "net_count": len(design.nets),
        "description": design.meta.description,
        "method": selection.method,
        "selection": {
            "template_id": selection.template_id,
            "template_name": selection.template_name,
            "match_score": selection.match_score,
        },
        "note": (
            "Loaded the closest pre-built template by keyword match; this is "
            "template selection, not from-scratch circuit synthesis."
        ),
    }


def tool_list_synthesis_templates() -> list[dict[str, str]]:
    """List available synthesis templates."""
    return list_templates()


def tool_requirements_parse(intent: str) -> dict[str, Any]:
    """Extract requirements, the constraints they imply, a coverage matrix, and assumptions."""
    from zaptrace.synthesis.requirements import (
        classify_risk,
        freeze_requirements,
        parse_requirements,
        requirements_assumptions,
        requirements_conflicts,
        requirements_coverage,
        requirements_to_constraints,
        review_assumptions,
    )

    requirements = parse_requirements(intent)
    return {
        "intent": intent,
        "requirements": requirements.to_dict(),
        "constraints": requirements_to_constraints(requirements).model_dump(),
        "coverage": requirements_coverage(requirements),
        "assumptions": requirements_assumptions(requirements),
        "conflicts": requirements_conflicts(requirements),
        "freeze": freeze_requirements(requirements),
        "assumption_review": review_assumptions(requirements),
        "risk": classify_risk(requirements),
    }


def tool_requirements_review(intent: str, approvals: dict[str, str] | None = None) -> dict[str, Any]:
    """Approve a design's unspecified assumptions and gate on any still pending.

    ``approvals`` maps an assumption ``field`` to the reviewer's decision for it;
    the gate is ``approved`` only when no assumption remains pending. Bound to the
    requirements freeze hash, so a later requirement change re-opens the gate.
    """
    from zaptrace.synthesis.requirements import parse_requirements, review_assumptions

    requirements = parse_requirements(intent)
    return {
        "intent": intent,
        "review": review_assumptions(requirements, approvals),
    }


def tool_power_tree_plan(intent: str) -> dict[str, Any]:
    """Plan a justified power tree (sources, charger, power-path, per-rail regulators) from an intent."""
    from zaptrace.synthesis.power_tree import plan_power_tree
    from zaptrace.synthesis.requirements import parse_requirements

    requirements = parse_requirements(intent)
    return {"intent": intent, "power_tree": plan_power_tree(requirements)}


def tool_synthesize_power_tree(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Emit a real netlist (components + nets) for an intent's power tree and store it in the session."""
    from zaptrace.synthesis.power_tree import build_power_tree_design, plan_power_tree
    from zaptrace.synthesis.requirements import parse_requirements

    requirements = parse_requirements(intent)
    plan = plan_power_tree(requirements)
    design = build_power_tree_design(requirements)
    session = _get_session(session_id)
    session["designs"][design.meta.name] = design
    unrealized = [s for s in plan["stages"] if s["stage"] == "regulator" and s["topology"] == "boost"]
    return {
        "intent": intent,
        "design_name": design.meta.name,
        "component_count": len(design.components),
        "net_count": len(design.nets),
        "blocks": [b.name for b in design.blocks],
        "unrealized_stages": unrealized,
        "method": "rule_based_power_tree_synthesis",
    }


def tool_synthesize_and_check(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Synthesize an intent's power tree into a netlist and run ERC on it in one step.

    Closes the intent -> netlist -> verification loop: builds the power-tree
    `Design`, stores it in the session, then validates it with the full ERC rule
    set so the agent can immediately see what its own synthesis produced.
    """
    synth = tool_synthesize_power_tree(intent, session_id=session_id)
    session = _get_session(session_id)
    design = session["designs"][synth["design_name"]]
    result = _get_erc_runner_type()().run(design)
    session["erc_results"] = {**session.get("erc_results", {}), synth["design_name"]: result}
    return {
        "intent": intent,
        "design_name": synth["design_name"],
        "component_count": synth["component_count"],
        "net_count": synth["net_count"],
        "blocks": synth["blocks"],
        "unrealized_stages": synth["unrealized_stages"],
        "erc": {
            "passed": result.passed,
            "total_errors": result.total_errors,
            "total_warnings": result.total_warnings,
            "violations": [
                {"rule_id": v.rule_id, "severity": v.severity.value, "message": v.message} for v in result.violations
            ],
        },
    }


def tool_board_plan(intent: str) -> dict[str, Any]:
    """Plan a justified board block graph (power + interface support) from an intent."""
    from zaptrace.synthesis.architecture import plan_architecture
    from zaptrace.synthesis.requirements import parse_requirements

    requirements = parse_requirements(intent)
    return {"intent": intent, "architecture": plan_architecture(requirements).to_dict()}


def tool_synthesize_board(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Emit a real netlist (power + interface blocks) for an intent's board and store it.

    Generalizes power-tree synthesis to the whole board via block composition:
    each regulator provides a rail, each interface support block requires one,
    and unrealized/unmet items are reported instead of silently dropped.
    """
    from zaptrace.synthesis.architecture import build_architecture_design
    from zaptrace.synthesis.requirements import parse_requirements

    requirements = parse_requirements(intent)
    design, plan, log = build_architecture_design(requirements)
    session = _get_session(session_id)
    session["designs"][design.meta.name] = design
    return {
        "intent": intent,
        "design_name": design.meta.name,
        "component_count": len(design.components),
        "net_count": len(design.nets),
        "blocks": [b.name for b in design.blocks],
        "unrealized_blocks": [b.block_id for b in plan.unrealized_blocks],
        "unmet_requirements": [{"block_id": u.block_id, "token": u.token} for u in plan.unmet],
        "decisions": log.to_dicts(),
        "method": "block_composition_synthesis",
    }


def tool_synthesize_board_and_check(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Synthesize an intent's full board into a netlist and run ERC on it in one step.

    Closes the intent -> block graph -> netlist -> verification loop for the whole
    board, not just the power tree.
    """
    synth = tool_synthesize_board(intent, session_id=session_id)
    session = _get_session(session_id)
    design = session["designs"][synth["design_name"]]
    result = _get_erc_runner_type()().run(design)
    session["erc_results"] = {**session.get("erc_results", {}), synth["design_name"]: result}
    return {
        "intent": intent,
        "design_name": synth["design_name"],
        "component_count": synth["component_count"],
        "net_count": synth["net_count"],
        "blocks": synth["blocks"],
        "unrealized_blocks": synth["unrealized_blocks"],
        "unmet_requirements": synth["unmet_requirements"],
        "erc": {
            "passed": result.passed,
            "total_errors": result.total_errors,
            "total_warnings": result.total_warnings,
            "violations": [
                {"rule_id": v.rule_id, "severity": v.severity.value, "message": v.message} for v in result.violations
            ],
        },
    }


def tool_synthesize_board_repair(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Synthesize a board, run the convergent ERC -> patch -> re-verify loop, and store it.

    Closes the full self-correction loop: build the block-composition netlist, then
    repair every auto-fixable ERC violation (e.g. missing footprints) until a fixed
    point, reporting what was patched and what still needs a human (e.g. single-pin
    nets that require a real connector).
    """
    from zaptrace.synthesis.repair import synthesize_and_repair

    out = synthesize_and_repair(intent)
    design = out["design"]
    plan = out["plan"]
    repair = out["repair"]
    footprints = out["footprints"]
    session = _get_session(session_id)
    session["designs"][design.meta.name] = design
    return {
        "intent": intent,
        "design_name": design.meta.name,
        "component_count": len(design.components),
        "net_count": len(design.nets),
        "converged": repair.converged,
        "fully_clean": repair.fully_clean,
        "patch_count": len(repair.patches),
        "patches": [p.to_dict() for p in repair.patches],
        "remaining": repair.remaining,
        "unrealized_blocks": [b.block_id for b in plan.unrealized_blocks],
        "footprints": footprints.to_dict(),
        "method": "block_composition_synthesis_with_self_repair",
    }


def tool_resolve_footprints(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Attach real IPC-7351 pad geometry to a stored design's components.

    The manufacturing exporters need `footprint_def` geometry, not just a name.
    Components whose package has no generator yet (e.g. an MCU module) are
    reported as unresolved — a visible fabrication blocker, never faked.
    """
    from zaptrace.synthesis.footprint_resolver import resolve_footprints

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    resolution = resolve_footprints(design)
    return {"design": design_name, **resolution.to_dict()}


def tool_dc_bias_check(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Check power-rail bias on a stored design (always available, no ngspice).

    Assigns each power net its nominal DC voltage and flags any rail that loads
    depend on but no regulator drives (a floating-rail bug ERC cannot catch).
    """
    from zaptrace.analysis.dc_bias import resolve_dc_bias

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    return {"design": design_name, **resolve_dc_bias(design).to_dict()}


def tool_simulation_gate(design_name: str, strict: bool = False, session_id: str = "default") -> dict[str, Any]:
    """Run the DC operating-point simulation gate on a stored design.

    Returns a blocking verdict. Rail references are derived from the design's
    power-rail net names. When ngspice is unavailable the gate is `skipped`
    (recorded as evidence, never a silent pass); with `strict=True` a skip blocks.
    """
    from zaptrace.analysis.sim_gate import run_simulation_gate

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    result = run_simulation_gate(design, strict=strict)
    return {"design": design_name, **result.to_dict()}


def tool_synthesis_benchmark() -> dict[str, Any]:
    """Synthesize a fixed corpus of board types and report aggregate completeness.

    Measures the engine, not one board: mean score, per-dimension pass rates, the
    weakest dimension, and the worst case — a deterministic, regression-catching
    snapshot of how finished synthesis is across representative intents.
    """
    from zaptrace.synthesis.benchmark import run_benchmark

    return run_benchmark().to_dict()


def tool_synthesize_board_score(intent: str, session_id: str = "default") -> dict[str, Any]:
    """Synthesize a board end to end and score its completeness (0-100).

    Runs the full flow (block composition + functional core + sensors + repair +
    footprint geometry), stores the design, and returns a weighted completeness
    score across functional-core, composition, electrical, and manufacturability
    dimensions. The score tracks how finished the *automated* steps are — it is
    not a correctness or safety claim; human review still applies.
    """
    from zaptrace.analysis.dc_bias import resolve_dc_bias
    from zaptrace.synthesis.repair import synthesize_and_repair
    from zaptrace.synthesis.scorecard import score_board

    out = synthesize_and_repair(intent)
    design = out["design"]
    session = _get_session(session_id)
    session["designs"][design.meta.name] = design
    card = score_board(design, out["plan"], out["repair"], out["footprints"], resolve_dc_bias(design))
    return {
        "intent": intent,
        "design_name": design.meta.name,
        "component_count": len(design.components),
        **card.to_dict(),
    }


def tool_synthesize_board_manufacture(
    intent: str,
    output_dir: str,
    approval_id: str | None = None,
    fab_profile: str | None = None,
    fab_profile_skip_reason: str | None = None,
    fab_profile_skip_approval_id: str | None = None,
    risky_package_reviewed: bool = False,
    risky_package_approval_id: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Synthesize, validate, approve, and emit a manufacturing bundle.

    The exact routed design is stored in the session, checked with ERC and DRC,
    bound to the standard release gate, and only then written to the workspace.
    """
    from zaptrace.synthesis.fab import build_manufacturing_result, route_synthesized_design

    if not approval_id or not approval_id.strip():
        raise ValueError("approval_id is required for release-export operations")
    out_path = _validate_path(output_dir)

    design, synthesis_output = route_synthesized_design(intent)
    session = _get_session(session_id)
    design_name = design.meta.name
    session["designs"][design_name] = design
    _persist_design(session, design_name)

    tool_erc_validate(design_name=design_name, session_id=session_id)
    tool_drc_run(design_name=design_name, fab_profile=fab_profile, session_id=session_id)
    release_gate = _require_release_gate(
        session,
        design_name,
        approval_id,
        session_id=session_id,
        fab_profile_skip_reason=fab_profile_skip_reason,
        fab_profile_skip_approval_id=fab_profile_skip_approval_id,
        risky_package_reviewed=risky_package_reviewed,
        risky_package_approval_id=risky_package_approval_id,
    )
    drc_result = session["drc_results"][design_name]

    policy = release_gate["fab_profile_policy"]
    result = build_manufacturing_result(
        intent,
        design,
        synthesis_output,
        out_path,
        drc_result=drc_result,
        fab_profile=str(policy.get("fab_profile") or ""),
        approved_dfm_skip_reason=str(policy.get("skip_reason") or ""),
        approved_dfm_skip_id=str(policy.get("skip_approval_id") or ""),
    ).to_dict()
    from zaptrace.fab.readiness import require_dfm_release_ready

    readiness = result.get("dfm_readiness", {})
    require_dfm_release_ready(
        str(readiness.get("status") or "") if isinstance(readiness, dict) else "",
        report_path=str(readiness.get("path") or "") if isinstance(readiness, dict) else "",
    )
    result["release_gate"] = release_gate
    return result


def tool_compliance_checklist(intent: str) -> dict[str, Any]:
    """Produce a product-class compliance pre-check checklist for a design intent.

    Evidence-ready, not certified — items flag where a manual lab test is
    required.
    """
    from zaptrace.analysis.compliance import compliance_checklist
    from zaptrace.synthesis.requirements import parse_requirements

    requirements = parse_requirements(intent)
    items = compliance_checklist(requirements)
    return {"intent": intent, "item_count": len(items), "items": [i.to_dict() for i in items]}


__all__ = [
    "tool_synthesize_design",
    "tool_list_synthesis_templates",
    "tool_requirements_parse",
    "tool_requirements_review",
    "tool_power_tree_plan",
    "tool_synthesize_power_tree",
    "tool_synthesize_and_check",
    "tool_board_plan",
    "tool_synthesize_board",
    "tool_synthesize_board_and_check",
    "tool_synthesize_board_repair",
    "tool_resolve_footprints",
    "tool_dc_bias_check",
    "tool_simulation_gate",
    "tool_synthesis_benchmark",
    "tool_synthesize_board_score",
    "tool_synthesize_board_manufacture",
    "tool_compliance_checklist",
]
