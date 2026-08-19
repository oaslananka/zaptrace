from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Any

from zaptrace.algo.grid_router import GridRouter
from zaptrace.algo.placer import place_components
from zaptrace.algo.router import RoutingResult, route_design_smart
from zaptrace.core.models import Design
from zaptrace.core.parser import parse_file, parse_str
from zaptrace.erc.models import ERCResult
from zaptrace.erc.patches import suggest_patches
from zaptrace.erc.runner import ERCRunner
from zaptrace.export.bom import generate_bom_csv, generate_bom_json
from zaptrace.export.kicad import export_kicad
from zaptrace.export.report import generate_report
from zaptrace.export.svg import render_schematic_svg
from zaptrace.synthesis.engine import list_templates, synthesize


class PipelineStage(StrEnum):
    """All pipeline stages in execution order."""

    PARSE = "parse"
    SYNTHESIZE = "synthesize"
    VALIDATE = "validate"
    PLACE = "place"
    ROUTE = "route"
    BOM = "bom"
    REPORT = "report"
    SVG = "svg"
    KICAD = "kicad"
    PATCH = "patch"

    @classmethod
    def ordered(cls) -> list[PipelineStage]:
        return [
            cls.PARSE,
            cls.SYNTHESIZE,
            cls.VALIDATE,
            cls.PLACE,
            cls.ROUTE,
            cls.BOM,
            cls.REPORT,
            cls.SVG,
            cls.KICAD,
            cls.PATCH,
        ]


@dataclass
class StageResult:
    """Result of a single pipeline stage."""

    stage: PipelineStage
    success: bool
    data: Any = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class PipelineContext:
    """Holds all state accumulated across pipeline stages."""

    design: Design | None = None
    source: str | None = None
    synthesis: dict[str, Any] | None = None
    positions: dict[str, tuple[float, float]] | None = None
    routing: RoutingResult | None = None
    erc_result: ERCResult | None = None
    patches: list[dict[str, str]] | None = None
    bom_csv: str | None = None
    bom_json: str | None = None
    report: str | None = None
    svg: str | None = None
    kicad_files: dict[str, Path] | None = None
    output_dir: Path | None = None
    results: dict[PipelineStage, StageResult] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    started_monotonic: float | None = field(default=None, repr=False)
    finished_monotonic: float | None = field(default=None, repr=False)

    @property
    def duration(self) -> float:
        if self.started_monotonic is not None and self.finished_monotonic is not None:
            return self.finished_monotonic - self.started_monotonic
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0

    @property
    def all_successful(self) -> bool:
        return all(r.success for r in self.results.values())


class Autopilot:
    """11-stage autonomous design pipeline orchestrator.

    Stages (in order):
      1. PARSE      — Load design from file or string
      2. SYNTHESIZE — Generate design from intent (if no design provided)
      3. VALIDATE   — Run all 29 ERC rules
      4. PLACE      — Component placement (grid + force-directed)
      5. ROUTE      — Manhattan MST routing
      6. BOM        — Generate bill of materials (CSV + JSON)
      7. REPORT     — Generate Markdown design report
      8. SVG        — Render schematic SVG
      9. KICAD      — Export KiCad files
     10. PATCH      — Generate ERC auto-patch suggestions
    """

    def __init__(self, output_dir: str | Path | None = None) -> None:
        self._erc_runner = ERCRunner()
        self._output_dir = Path(output_dir) if output_dir else Path.cwd()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_from_file(self, path: str | Path) -> PipelineContext:
        """Run the full pipeline starting from a design file."""
        ctx = PipelineContext(
            source=str(path),
            output_dir=self._output_dir,
            started_at=datetime.now(UTC),
            started_monotonic=perf_counter(),
        )
        self._run_stage(ctx, PipelineStage.PARSE)
        if ctx.results.get(PipelineStage.PARSE, StageResult(PipelineStage.PARSE, False)).success:
            self._run_remaining(ctx, PipelineStage.SYNTHESIZE)
        return ctx

    def run_from_intent(self, intent: str) -> PipelineContext:
        """Run the full pipeline starting from a synthesis intent."""
        ctx = PipelineContext(
            source=intent,
            output_dir=self._output_dir,
            started_at=datetime.now(UTC),
            started_monotonic=perf_counter(),
        )
        self._run_stage(ctx, PipelineStage.SYNTHESIZE)
        if ctx.results.get(PipelineStage.SYNTHESIZE, StageResult(PipelineStage.SYNTHESIZE, False)).success:
            self._run_remaining(ctx, PipelineStage.VALIDATE)
        return ctx

    def run_from_design(self, design: Design) -> PipelineContext:
        """Run the full pipeline from an already-loaded Design object."""
        ctx = PipelineContext(
            design=design,
            output_dir=self._output_dir,
            started_at=datetime.now(UTC),
            started_monotonic=perf_counter(),
        )
        ctx.results[PipelineStage.PARSE] = StageResult(
            PipelineStage.PARSE,
            True,
            data="design",
        )
        self._run_remaining(ctx, PipelineStage.VALIDATE)
        return ctx

    def run_stage(self, ctx: PipelineContext, stage: PipelineStage) -> PipelineContext:
        """Run a single stage on an existing context."""
        self._run_stage(ctx, stage)
        return ctx

    def run_stages(
        self,
        ctx: PipelineContext,
        stages: list[PipelineStage],
    ) -> PipelineContext:
        """Run a list of stages in order on an existing context."""
        for stage in stages:
            self._run_stage(ctx, stage)
            if not ctx.results.get(stage, StageResult(stage, False)).success:
                break
        return ctx

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_remaining(self, ctx: PipelineContext, start: PipelineStage) -> None:
        """Run all stages from *start* through to PATCH."""
        ordered = PipelineStage.ordered()
        try:
            idx = ordered.index(start)
        except ValueError:
            return
        for stage in ordered[idx:]:
            self._run_stage(ctx, stage)

        ctx.finished_monotonic = perf_counter()
        ctx.finished_at = datetime.now(UTC)

    def _run_stage(self, ctx: PipelineContext, stage: PipelineStage) -> None:
        """Execute a single pipeline stage and record the result."""
        t0 = perf_counter()
        try:
            method_name = _STAGE_MAP[stage]
            method = getattr(self, method_name)
            method(ctx)
            elapsed = (perf_counter() - t0) * 1000
            ctx.results[stage] = StageResult(stage, True, duration_ms=round(elapsed, 1))
        except PipelineHaltError as exc:
            elapsed = (perf_counter() - t0) * 1000
            ctx.results[stage] = StageResult(
                stage,
                False,
                error=str(exc),
                duration_ms=round(elapsed, 1),
            )

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    def _stage_parse(self, ctx: PipelineContext) -> None:
        if ctx.design is not None:
            return  # already loaded
        src = ctx.source
        if not src:
            raise PipelineHaltError("No source provided for parse stage")
        path = Path(src)
        if path.exists() and path.is_file():
            ctx.design = parse_file(path)
        else:
            ctx.design = parse_str(src, source="<pipeline>")

    def _stage_synthesize(self, ctx: PipelineContext) -> None:
        if ctx.design is not None:
            return
        intent = ctx.source
        if not intent:
            raise PipelineHaltError("No intent provided for synthesis stage")
        # Prefer from-scratch composition synthesis (block graph → topology →
        # values → bounded ERC repair); it carries net types, footprints, and
        # provenance the legacy template selector cannot. Fall back to template
        # selection only when composition composes nothing for this intent.
        from zaptrace.synthesis.repair import synthesize_and_repair

        result = synthesize_and_repair(intent)
        design = result["design"]
        if design.components:
            ctx.design = design
            ctx.synthesis = result
        else:
            ctx.design = synthesize(intent)

    def _stage_validate(self, ctx: PipelineContext) -> None:
        design = ctx.design
        if design is None:
            raise PipelineHaltError("No design to validate")
        ctx.erc_result = self._erc_runner.run(design)
        if not ctx.erc_result.passed:
            # Validation failures are informational — continue the pipeline
            pass

    def _stage_place(self, ctx: PipelineContext) -> None:
        design = ctx.design
        if design is None:
            raise PipelineHaltError("No design to place")
        ctx.positions = place_components(design)
        design.placement = dict(ctx.positions)

    def _stage_route(self, ctx: PipelineContext) -> None:
        design = ctx.design
        if design is None:
            raise PipelineHaltError("No design to route")
        positions = ctx.positions
        if positions is None:
            raise PipelineHaltError("No placement data — run place stage first")
        # Prefer the obstacle-aware A* grid router so the pipeline emits
        # collision-free, multi-layer, manufacturable traces. The MST/L-shape
        # router (route_design_smart) ignores obstacles and overlaps freely, so
        # it is kept only as a fallback when A* routes nothing (e.g. a
        # degenerate board where every terminal collapses onto one grid cell).
        route_result = GridRouter().route(design, positions)
        if route_result.routed_net_count > 0:
            ctx.routing = RoutingResult(
                segments=[],
                routed_nets=route_result.routed_net_count,
                total_nets=route_result.net_count,
                unrouted_nets=[],
            )
            design.routing = route_result
        else:
            ctx.routing, design.routing, _ = route_design_smart(design, positions)
        if ctx.routing.routed_nets > 0 and not design.routing.traces:
            raise PipelineHaltError("Routing reported routed nets but produced no design.routing traces")

    def _stage_bom(self, ctx: PipelineContext) -> None:
        design = ctx.design
        if design is None:
            raise PipelineHaltError("No design for BOM generation")
        ctx.bom_csv = generate_bom_csv(design)
        ctx.bom_json = generate_bom_json(design)

    def _stage_report(self, ctx: PipelineContext) -> None:
        design = ctx.design
        if design is None:
            raise PipelineHaltError("No design for report generation")
        ctx.report = generate_report(design, erc_result=ctx.erc_result)

        report_path = self._output_dir / f"{design.meta.name}_report.md"
        self._output_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(ctx.report, encoding="utf-8")

    def _stage_svg(self, ctx: PipelineContext) -> None:
        design = ctx.design
        if design is None:
            raise PipelineHaltError("No design for SVG rendering")
        ctx.svg = render_schematic_svg(design, positions=ctx.positions)

        svg_path = self._output_dir / f"{design.meta.name}_schematic.svg"
        self._output_dir.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(ctx.svg, encoding="utf-8")

    def _stage_kicad(self, ctx: PipelineContext) -> None:
        design = ctx.design
        if design is None:
            raise PipelineHaltError("No design for KiCad export")
        kicad_dir = self._output_dir / "kicad"
        ctx.kicad_files = export_kicad(design, kicad_dir)
        pcb = ctx.kicad_files.get("pcb")
        if design.routing is not None and design.routing.traces and pcb is not None:
            text = pcb.read_text(encoding="utf-8")
            if "(segment" not in text:
                raise PipelineHaltError("KiCad PCB export omitted routed trace segments")

    def _stage_patch(self, ctx: PipelineContext) -> None:
        design = ctx.design
        if design is None:
            raise PipelineHaltError("No design for patch generation")
        erc_result = ctx.erc_result
        if erc_result is None:
            ctx.patches = []
            return
        ctx.patches = suggest_patches(design, erc_result)

    def list_templates(self) -> list[dict[str, str]]:
        """Convenience access to synthesis templates."""
        return list_templates()


class PipelineHaltError(Exception):
    """Raised to halt the pipeline with an error message."""


# Stage dispatch table — populated after class definition
_STAGE_MAP: dict[PipelineStage, str] = {
    PipelineStage.PARSE: "_stage_parse",
    PipelineStage.SYNTHESIZE: "_stage_synthesize",
    PipelineStage.VALIDATE: "_stage_validate",
    PipelineStage.PLACE: "_stage_place",
    PipelineStage.ROUTE: "_stage_route",
    PipelineStage.BOM: "_stage_bom",
    PipelineStage.REPORT: "_stage_report",
    PipelineStage.SVG: "_stage_svg",
    PipelineStage.KICAD: "_stage_kicad",
    PipelineStage.PATCH: "_stage_patch",
}
