"""Completeness scorecard for a synthesized board.

Turns the artifacts of the synthesis flow — the block graph, the self-correction
result, and the footprint resolution — into a single, honest measure of *how
finished* a board is, across four dimensions:

* **Functional core** — is the requested MCU placed and realized?
* **Composition** — were all planned blocks realized, with no unmet requirement?
* **Electrical** — did the repair loop converge to a clean ERC, or is there an
  escalation list a human must still resolve?
* **Manufacturability** — does every part carry real footprint geometry, or are
  some packages still ungenerated?

The score is a number to track over time, not a fitness claim: a 100 means the
*automated* steps are complete, never that the board is correct or safe — that
still needs human review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zaptrace.analysis.dc_bias import DcBiasResult
    from zaptrace.core.models import Design
    from zaptrace.synthesis.architecture import ArchitecturePlan
    from zaptrace.synthesis.footprint_resolver import FootprintResolution
    from zaptrace.synthesis.repair import RepairResult

# (dimension key, weight). Weights sum to 1.0.
_WEIGHTS: dict[str, float] = {
    "functional_core": 0.25,
    "composition": 0.25,
    "electrical": 0.30,
    "manufacturability": 0.20,
}


@dataclass(frozen=True)
class Dimension:
    """One scored axis of board completeness."""

    name: str
    score: float  # 0.0 .. 1.0
    status: str  # "pass" | "partial" | "fail" | "n/a"
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "score": round(self.score, 3), "status": self.status, "detail": self.detail}


@dataclass
class BoardScorecard:
    """The weighted completeness score plus its per-dimension breakdown."""

    score: int  # 0 .. 100
    grade: str
    dimensions: list[Dimension] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "grade": self.grade,
            "dimensions": [d.to_dict() for d in self.dimensions],
        }


def _status(score: float) -> str:
    if score >= 0.999:
        return "pass"
    if score <= 0.001:
        return "fail"
    return "partial"


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _functional_core(design: Design, plan: ArchitecturePlan) -> Dimension:
    core_blocks = [b for b in plan.blocks if b.kind == "mcu"]
    if not core_blocks:
        return Dimension("functional_core", 1.0, "n/a", "no MCU requested")
    realized = [b for b in core_blocks if b.realized]
    has_part = any(c.type == "mcu" for c in design.components.values())
    score = 1.0 if (realized and has_part) else 0.0
    detail = "MCU placed and wired" if score else "MCU requested but no library part"
    return Dimension("functional_core", score, _status(score), detail)


def _composition(plan: ArchitecturePlan) -> Dimension:
    total = len(plan.blocks)
    if total == 0:
        return Dimension("composition", 0.0, "fail", "no blocks planned")
    unrealized = len(plan.unrealized_blocks)
    unmet = len(plan.unmet)
    score = max(0.0, (total - unrealized) / total - 0.1 * unmet)
    detail = f"{total - unrealized}/{total} blocks realized, {unmet} unmet requirement(s)"
    return Dimension("composition", score, _status(score), detail)


def _electrical(repair: RepairResult, dc_bias: DcBiasResult | None) -> Dimension:
    # A floating rail (loads depend on it, no regulator drives it) is a hard
    # defect that outranks ERC convergence.
    if dc_bias is not None and dc_bias.undriven_rails:
        rails = ", ".join(dc_bias.undriven_rails)
        return Dimension("electrical", 0.2, "fail", f"undriven rail(s): {rails}")
    if not repair.converged:
        return Dimension("electrical", 0.2, "fail", "repair loop did not converge")
    # Info-level items (test-point / pull-up *suggestions*) do not make a board
    # electrically unsound; only errors and warnings count against this dimension.
    hard = [v for v in repair.remaining if v.get("severity") in ("error", "warning")]
    advisories = len(repair.remaining) - len(hard)
    if not hard:
        detail = "no ERC errors or warnings" + (f"; {advisories} advisory note(s)" if advisories else "")
        return Dimension("electrical", 1.0, "pass", detail)
    return Dimension("electrical", 0.6, "partial", f"{len(hard)} error/warning(s) for review")


def _manufacturability(design: Design, footprints: FootprintResolution) -> Dimension:
    total = len(design.components)
    if total == 0:
        return Dimension("manufacturability", 0.0, "fail", "no components")
    resolved = len(footprints.resolved)
    score = resolved / total
    detail = f"{resolved}/{total} parts have footprint geometry"
    return Dimension("manufacturability", score, _status(score), detail)


def score_board(
    design: Design,
    plan: ArchitecturePlan,
    repair: RepairResult,
    footprints: FootprintResolution,
    dc_bias: DcBiasResult | None = None,
) -> BoardScorecard:
    """Score a synthesized board's completeness from its synthesis artifacts."""
    dims = [
        _functional_core(design, plan),
        _composition(plan),
        _electrical(repair, dc_bias),
        _manufacturability(design, footprints),
    ]
    by_key = {
        "functional_core": dims[0],
        "composition": dims[1],
        "electrical": dims[2],
        "manufacturability": dims[3],
    }
    total = round(100 * sum(_WEIGHTS[key] * dim.score for key, dim in by_key.items()))
    return BoardScorecard(score=total, grade=_grade(total), dimensions=dims)
