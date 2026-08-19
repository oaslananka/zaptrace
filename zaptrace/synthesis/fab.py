"""End-to-end: intent → fabricable package + evidence.

Chains block-composition synthesis through the existing place / route / export
pipeline so an agent can go from one sentence to a manufacturing bundle (Gerber,
drill, BOM, pick-and-place, ZIP) in a single call — the "Prompt-to-Fab" thesis,
on the composition synthesizer rather than template selection.

Crucially it returns the **evidence** alongside the artifacts: the completeness
scorecard, the DC bias check, and an explicit human-review checklist of what is
*not* finished (parts with no copper, ERC left for review, undriven rails,
unrealized blocks, a skipped simulation). The bundle is never presented as
fabrication-ready — the checklist is the honest hand-off to a reviewer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zaptrace.analysis.dc_bias import DcBiasResult
    from zaptrace.core.models import Design
    from zaptrace.synthesis.footprint_resolver import FootprintResolution
    from zaptrace.synthesis.repair import RepairResult


@dataclass
class FabResult:
    """The fabrication package plus the evidence and review checklist."""

    intent: str
    design_name: str
    component_count: int
    net_count: int
    scorecard: dict[str, Any]
    dc_bias: dict[str, Any]
    drc: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    review_checklist: list[str] = field(default_factory=list)
    dfm_readiness: dict[str, Any] = field(default_factory=dict)
    output_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "design_name": self.design_name,
            "component_count": self.component_count,
            "net_count": self.net_count,
            "scorecard": self.scorecard,
            "dc_bias": self.dc_bias,
            "drc": self.drc,
            "artifacts": self.artifacts,
            "review_checklist": self.review_checklist,
            "dfm_readiness": self.dfm_readiness,
            "output_dir": self.output_dir,
        }


def _review_checklist(
    repair: RepairResult,
    footprints: FootprintResolution,
    dc_bias: DcBiasResult,
    unrealized_blocks: list[str],
    drc_errors: int,
) -> list[str]:
    """The honest hand-off: everything a human must still resolve."""
    items: list[str] = []
    if dc_bias.undriven_rails:
        items.append(f"Power: undriven rail(s) {', '.join(dc_bias.undriven_rails)} — add the missing regulator.")
    for unresolved in footprints.unresolved:
        items.append(
            f"Footprint: {unresolved['ref']} ({unresolved['footprint'] or 'unnamed'}) has no pad geometry — "
            "no copper will be emitted for it until a land pattern is supplied."
        )
    if repair.remaining:
        items.append(f"ERC: {len(repair.remaining)} violation(s) left for review (e.g. connector/strapping nets).")
    if drc_errors:
        items.append(
            f"Routing: {drc_errors} DRC error(s) — the algorithmic router does not yet produce a "
            "clean professional layout; manual or improved routing is required."
        )
    for block_id in unrealized_blocks:
        items.append(f"Synthesis: block {block_id} was planned but not realized — complete it by hand.")
    items.append("Run a full ERC/DRC and a real simulation, and have a qualified engineer review before fabrication.")
    return items


def route_synthesized_design(intent: str, *, name: str = "SynthesizedBoard") -> tuple[Design, dict[str, Any]]:
    """Synthesize a board from intent and place, route, and ground-pour it.

    Returns the routed :class:`~zaptrace.core.models.Design` plus the raw
    synthesis output (``plan``, ``repair``, ``footprints``). Shared by the
    manufacturing bundler and the proof-pack generator so both verify the
    identical physical design.
    """
    from zaptrace.algo.copper_pour import CopperPourGenerator
    from zaptrace.algo.grid_router import GridRouter
    from zaptrace.algo.placer import place_components
    from zaptrace.algo.router import route_design_smart
    from zaptrace.core.models import NetClass
    from zaptrace.ee.classifier import classify_design, get_net_class
    from zaptrace.synthesis.repair import synthesize_and_repair

    out = synthesize_and_repair(intent, name=name)
    design = out["design"]

    positions = place_components(design)
    for ref, pos in positions.items():
        if ref in design.components:
            design.components[ref].position = tuple(pos) if not isinstance(pos, tuple) else pos
    design.placement = dict(positions)
    classify_design(design)  # set power/ground/signal net classes before routing
    # Obstacle-aware A* grid router for collision-free, manufacturable traces;
    # the MST/L-shape router is only a fallback when A* routes nothing.
    placement = {c.ref: c.position for c in design.components.values() if c.position}
    grid_result = GridRouter().route(design, placement)
    if grid_result.routed_net_count > 0:
        design.routing = grid_result
    else:
        _, design.routing, _sc = route_design_smart(design, placement)

    # Flood the ground net as a copper pour (the router leaves GND for the plane),
    # so every ground pin is connected through the fill. Identify it by net class
    # (what the router uses), not the raw type field.
    ground = next((n for n in design.nets.values() if get_net_class(design, n.id) == NetClass.GROUND), None)
    if ground is not None:
        pour = CopperPourGenerator().generate_ground_pour(design, placement, layer="F.Cu", net_id=ground.id)
        design.copper_pours[f"F.Cu_{ground.name}"] = pour

    return design, out


def build_manufacturing_result(
    intent: str,
    design: Design,
    synthesis_output: dict[str, Any],
    output_dir: str | Path,
    *,
    drc_result: Any | None = None,
    fab_profile: str = "",
    approved_dfm_skip_reason: str = "",
    approved_dfm_skip_id: str = "",
) -> FabResult:
    """Emit a manufacturing bundle for an already routed design plus evidence."""
    from zaptrace.analysis.dc_bias import resolve_dc_bias
    from zaptrace.ee.drc.engine import DRCEngine
    from zaptrace.export.manufacturing import generate_manufacturing_bundle
    from zaptrace.synthesis.scorecard import score_board

    drc = drc_result if drc_result is not None else DRCEngine().run(design)
    out_path = Path(output_dir)
    bundle = generate_manufacturing_bundle(
        design,
        out_path,
        fab_profile=fab_profile or None,
        approved_dfm_skip_reason=approved_dfm_skip_reason,
        approved_dfm_skip_id=approved_dfm_skip_id,
    )
    artifacts = sorted(p.name for p in out_path.iterdir() if p.is_file())

    bias = resolve_dc_bias(design)
    card = score_board(
        design,
        synthesis_output["plan"],
        synthesis_output["repair"],
        synthesis_output["footprints"],
        bias,
    )
    checklist = _review_checklist(
        synthesis_output["repair"],
        synthesis_output["footprints"],
        bias,
        [block.block_id for block in synthesis_output["plan"].unrealized_blocks],
        drc.errors,
    )

    return FabResult(
        intent=intent,
        design_name=design.meta.name,
        component_count=len(design.components),
        net_count=len(design.nets),
        scorecard=card.to_dict(),
        dc_bias=bias.to_dict(),
        drc={
            "passed": drc.passed,
            "errors": drc.errors,
            "warnings": drc.warnings,
            "violations": drc.total_violations,
        },
        artifacts=artifacts,
        review_checklist=checklist,
        dfm_readiness={
            "path": str(bundle.get("dfm_readiness", "")),
            "status": str(bundle.get("dfm_readiness_status", "human-review-required")),
        },
        output_dir=str(out_path),
    )


def synthesize_to_manufacturing(intent: str, output_dir: str | Path, *, name: str = "SynthesizedBoard") -> FabResult:
    """Synthesize a board from intent and emit a manufacturing bundle plus evidence."""
    design, synthesis_output = route_synthesized_design(intent, name=name)
    return build_manufacturing_result(intent, design, synthesis_output, output_dir)
