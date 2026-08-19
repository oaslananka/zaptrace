"""Pipeline agent tool implementations."""

from __future__ import annotations

from .deps import Any, Autopilot, PipelineContext, PipelineStage, suggest_patches
from .runtime import _get_autopilot, _get_session, _validate_path


def tool_pipeline_run(
    source: str | None = None, intent: str | None = None, output_dir: str | None = None, session_id: str = "default"
) -> dict[str, Any]:  # noqa: E501
    """Run the full design pipeline from file or intent."""
    out_dir = _validate_path(output_dir) if output_dir else None
    autopilot = Autopilot(output_dir=out_dir) if out_dir else _get_autopilot()
    if source:
        src = _validate_path(source, must_exist=True)
        ctx = autopilot.run_from_file(src)
    elif intent:
        ctx = autopilot.run_from_intent(intent)
    else:
        raise ValueError("Provide either 'source' (file path) or 'intent' (synthesis)")
    session = _get_session(session_id)
    if ctx.design:
        session["designs"][ctx.design.meta.name] = ctx.design
    if ctx.design and ctx.erc_result:
        session["erc_results"] = {
            **session.get("erc_results", {}),
            ctx.design.meta.name: ctx.erc_result,
        }
    return {
        "stages_completed": len(ctx.results),
        "all_successful": ctx.all_successful,
        "duration_seconds": round(ctx.duration, 2),
        "stages": {s.value: {"success": r.success, "error": r.error} for s, r in ctx.results.items()},
    }


def tool_pipeline_run_stage(
    stage: str,
    source: str | None = None,
    intent: str | None = None,
    design_name: str | None = None,
    output_dir: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:  # noqa: E501
    """Run a single pipeline stage."""
    out_dir = _validate_path(output_dir) if output_dir else None
    autopilot = Autopilot(output_dir=out_dir) if out_dir else _get_autopilot()
    stage_enum = PipelineStage(stage)
    ctx = PipelineContext(output_dir=autopilot._output_dir)

    if design_name:
        session = _get_session(session_id)
        ctx.design = session.get("designs", {}).get(design_name)
    elif source:
        ctx.source = str(_validate_path(source, must_exist=True))
    elif intent:
        ctx.source = intent
    else:
        raise ValueError("Provide one of: design_name, source, intent")

    ctx = autopilot.run_stage(ctx, stage_enum)
    result = ctx.results.get(stage_enum)
    if result is None:
        raise RuntimeError(f"Stage {stage} did not produce a result")
    return {
        "stage": stage,
        "success": result.success,
        "error": result.error,
        "duration_ms": result.duration_ms,
    }


def tool_pipeline_status(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Get pipeline processing status for a design."""
    session = _get_session(session_id)
    has_design = design_name in session.get("designs", {})
    has_erc = design_name in session.get("erc_results", {})
    has_positions = design_name in session.get("positions", {})
    has_routing = design_name in session.get("routing", {})
    stages_done: list[str] = []
    if has_design:
        stages_done.append("parse/synthesize")
    if has_erc:
        stages_done.append("validate")
    if has_positions:
        stages_done.append("place")
    if has_routing:
        stages_done.append("route")
    return {
        "design": design_name,
        "exists": has_design,
        "stages_completed": stages_done,
        "erc_done": has_erc,
        "placement_done": has_positions,
        "routing_done": has_routing,
    }


def tool_patch_suggest(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Suggest auto-patches for fixable ERC violations."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    erc_result = session.get("erc_results", {}).get(design_name)
    if erc_result is None:
        raise ValueError(f"No ERC result for '{design_name}'")
    patches = suggest_patches(design, erc_result)
    return {"design": design_name, "patches": patches}


__all__ = ["tool_pipeline_run", "tool_pipeline_run_stage", "tool_pipeline_status", "tool_patch_suggest"]
