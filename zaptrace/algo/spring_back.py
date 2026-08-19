"""Spring-back shove behavior and benchmark evidence (issue #139).

Extends the walkaround shove router with spring-back: after a detour path
is accepted, a post-processing pass attempts to retract each segment back
toward the original rubber-band straight line.  When a retracted segment
passes DRC, it replaces the detoured segment.

A benchmark function compares the shove router against a Freerouting baseline
stub and reports completion rate, DRC-clean rate, total wirelength, via count,
runtime, and fallback usage.

Architecture
------------
1. **route_shove_springback** — wraps ``route_shove`` + iterative spring-back.
2. **ShoveSpringbackResult** — evidence dataclass (superset of ShoveResult).
3. **benchmark_shove_vs_freerouting** — runs both engines, returns comparison
   dict; Freerouting path is SKIPPED when Freerouting is unavailable.

DRC check
---------
The lightweight DRC check here mirrors the acceptance gate used by the
Freerouting stubs: a segment is DRC-clean if its axis-aligned bounding box
does not overlap any obstacle bounding box by more than the clearance margin.
This is a *stub* DRC sufficient for CI evidence; a full KiCad-Oracle DRC gate
would be added in a separate step.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from zaptrace.algo.shove import ShoveResult, route_shove

SPRINGBACK_EVIDENCE_SCHEMA = "springback-v1"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SpringbackSegment:
    """One trace segment with DRC and retraction evidence."""

    coords: tuple[float, float, float, float]
    retracted: bool = False
    drc_clean: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "coords": list(self.coords),
            "retracted": self.retracted,
            "drc_clean": self.drc_clean,
        }


@dataclass
class ShoveSpringbackResult:
    """Extended shove result with spring-back evidence.

    Attributes
    ----------
    net_id:
        Net or connection identifier.
    provenance:
        Resolution strategy token from the underlying shove.
    resolved:
        True if the connection has an obstacle-free path.
    segments:
        Final accepted trace segments (after spring-back).
    springback_segments:
        Detailed per-segment spring-back evidence.
    retracted_count:
        Number of segments that were successfully retracted.
    drc_clean:
        True if all final segments pass the stub DRC check.
    elapsed_ms:
        Wall time for this connection in milliseconds.
    """

    net_id: str
    provenance: str
    resolved: bool
    segments: list[tuple[float, float, float, float]] = field(default_factory=list)
    springback_segments: list[SpringbackSegment] = field(default_factory=list)
    retracted_count: int = 0
    drc_clean: bool = True
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "net_id": self.net_id,
            "provenance": self.provenance,
            "resolved": self.resolved,
            "segments": [list(s) for s in self.segments],
            "springback_segments": [s.to_dict() for s in self.springback_segments],
            "retracted_count": self.retracted_count,
            "drc_clean": self.drc_clean,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class ShoveBenchmarkResult:
    """Comparison evidence: shove vs Freerouting baseline.

    Attributes
    ----------
    shove_completion_rate:
        Fraction of connections resolved (0.0–1.0).
    shove_drc_clean_rate:
        Fraction of shove routes that pass stub DRC.
    shove_total_wirelength_mm:
        Sum of all segment lengths from shove (mm).
    shove_retracted_count:
        Total segments spring-backed to shorter paths.
    shove_elapsed_ms:
        Total shove runtime (ms).
    freerouting_status:
        ``"skipped"`` when Freerouting is unavailable; ``"pass"``/``"fail"``
        from the FreeroutingResult otherwise.
    freerouting_completion_rate:
        Freerouting completion rate from SES import, or ``None`` if skipped.
    fallback_usage:
        Number of connections that used Python fallback (0 if Rust available).
    evidence_schema:
        Schema version string for evidence consumers.
    """

    shove_completion_rate: float
    shove_drc_clean_rate: float
    shove_total_wirelength_mm: float
    shove_retracted_count: int
    shove_elapsed_ms: float
    freerouting_status: str = "skipped"
    freerouting_completion_rate: float | None = None
    fallback_usage: int = 0
    evidence_schema: str = SPRINGBACK_EVIDENCE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "shove_completion_rate": self.shove_completion_rate,
            "shove_drc_clean_rate": self.shove_drc_clean_rate,
            "shove_total_wirelength_mm": round(self.shove_total_wirelength_mm, 3),
            "shove_retracted_count": self.shove_retracted_count,
            "shove_elapsed_ms": round(self.shove_elapsed_ms, 1),
            "freerouting_status": self.freerouting_status,
            "freerouting_completion_rate": self.freerouting_completion_rate,
            "fallback_usage": self.fallback_usage,
            "evidence_schema": self.evidence_schema,
        }


# ---------------------------------------------------------------------------
# DRC stub
# ---------------------------------------------------------------------------


def _stub_drc_segment(
    sx1: float,
    sy1: float,
    sx2: float,
    sy2: float,
    obstacles: list[tuple[float, float, float, float]],
    clearance: float,
) -> bool:
    """Return True if segment clears all obstacles by at least clearance."""
    margin = clearance * 0.5
    for ox1, oy1, ox2, oy2 in obstacles:
        if (
            min(sx1 - margin, sx2 + margin) < max(ox1, ox2)
            and max(sx1 - margin, sx2 + margin) > min(ox1, ox2)
            and min(sy1 - margin, sy2 + margin) < max(oy1, oy2)
            and max(sy1 - margin, sy2 + margin) > min(oy1, oy2)
        ):
            return False
    return True


# ---------------------------------------------------------------------------
# Spring-back logic
# ---------------------------------------------------------------------------


def _try_retract_segment(
    sx1: float,
    sy1: float,
    sx2: float,
    sy2: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    obstacles: list[tuple[float, float, float, float]],
    clearance: float,
) -> tuple[float, float, float, float] | None:
    """Attempt to retract one segment toward the original straight line.

    Tries a bilinear interpolation between the detoured segment and the
    straight rubber-band endpoint.  Returns the retracted coords if DRC
    passes; None otherwise.
    """
    mid_x1 = (sx1 + x1) * 0.5
    mid_y1 = (sy1 + y1) * 0.5
    mid_x2 = (sx2 + x2) * 0.5
    mid_y2 = (sy2 + y2) * 0.5

    if _stub_drc_segment(mid_x1, mid_y1, mid_x2, mid_y2, obstacles, clearance):
        return (mid_x1, mid_y1, mid_x2, mid_y2)
    return None


def _segment_length(x1: float, y1: float, x2: float, y2: float) -> float:
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def route_shove_springback(
    connections: list[tuple[float, float, float, float, str]],
    obstacles: list[tuple[float, float, float, float]],
    clearance: float = 0.2,
    *,
    force_python: bool = False,
) -> list[ShoveSpringbackResult]:
    """Route connections with shove + spring-back pass.

    Parameters
    ----------
    connections:
        List of ``(x1, y1, x2, y2, net_id)`` rubber-band tuples.
    obstacles:
        List of ``(x1, y1, x2, y2)`` obstacle bounding boxes in mm.
    clearance:
        Minimum clearance from any obstacle wall in mm.
    force_python:
        If True, skip the Rust extension.

    Returns
    -------
    list[ShoveSpringbackResult]
        One entry per connection with full spring-back evidence.
    """
    if clearance < 0.0:
        raise ValueError(f"clearance must be non-negative, got {clearance}")

    shove_results: list[ShoveResult] = route_shove(connections, obstacles, clearance, force_python=force_python)

    results: list[ShoveSpringbackResult] = []

    for (x1, y1, x2, y2, net_id), sr in zip(connections, shove_results, strict=True):
        t0 = time.monotonic()

        springback_segs: list[SpringbackSegment] = []
        final_segs: list[tuple[float, float, float, float]] = []
        retracted_count = 0
        drc_clean = True

        for seg in sr.segments:
            sx1, sy1, sx2, sy2 = seg
            retracted = _try_retract_segment(
                sx1,
                sy1,
                sx2,
                sy2,
                x1,
                y1,
                x2,
                y2,
                obstacles,
                clearance,
            )
            if retracted is not None:
                final_segs.append(retracted)
                seg_drc = _stub_drc_segment(*retracted, obstacles, clearance)
                springback_segs.append(SpringbackSegment(coords=retracted, retracted=True, drc_clean=seg_drc))
                retracted_count += 1
            else:
                final_segs.append(seg)
                seg_drc = _stub_drc_segment(sx1, sy1, sx2, sy2, obstacles, clearance)
                springback_segs.append(SpringbackSegment(coords=seg, retracted=False, drc_clean=seg_drc))
            if not springback_segs[-1].drc_clean:
                drc_clean = False

        elapsed_ms = (time.monotonic() - t0) * 1000

        results.append(
            ShoveSpringbackResult(
                net_id=net_id,
                provenance=sr.provenance,
                resolved=sr.resolved,
                segments=final_segs,
                springback_segments=springback_segs,
                retracted_count=retracted_count,
                drc_clean=drc_clean,
                elapsed_ms=elapsed_ms,
            )
        )

    return results


def benchmark_shove_vs_freerouting(
    connections: list[tuple[float, float, float, float, str]],
    obstacles: list[tuple[float, float, float, float]],
    clearance: float = 0.2,
    design_name: str = "benchmark",
) -> ShoveBenchmarkResult:
    """Run shove+spring-back and compare against the Freerouting baseline.

    Freerouting path is SKIPPED when the Freerouting binary is unavailable;
    the shove path always runs.

    Parameters
    ----------
    connections:
        List of ``(x1, y1, x2, y2, net_id)`` rubber-band tuples.
    obstacles:
        List of ``(x1, y1, x2, y2)`` obstacle bounding boxes.
    clearance:
        Minimum clearance in mm.
    design_name:
        Name used in Freerouting evidence.

    Returns
    -------
    ShoveBenchmarkResult
        Comparison evidence dict.
    """
    t0 = time.monotonic()
    shove_results = route_shove_springback(connections, obstacles, clearance)
    shove_elapsed = (time.monotonic() - t0) * 1000

    total = len(shove_results)
    resolved = sum(1 for r in shove_results if r.resolved)
    drc_clean = sum(1 for r in shove_results if r.drc_clean)
    total_wl = sum(_segment_length(sx1, sy1, sx2, sy2) for r in shove_results for sx1, sy1, sx2, sy2 in r.segments)
    retracted = sum(r.retracted_count for r in shove_results)
    fallback = sum(1 for r in shove_results if "fallback" in r.provenance)

    # Freerouting delegation (SKIPPED if unavailable)
    fr_status = "skipped"
    fr_completion: float | None = None
    try:
        from zaptrace.algo.freerouting import FreeroutingConfig, run_freerouting

        fr_result = run_freerouting(
            design_name,
            net_count=len(connections),
            component_count=max(4, len(connections)),
            config=FreeroutingConfig(timeout_s=30),
        )
        fr_status = fr_result.status
        if fr_result.ses_import is not None:
            fr_completion = fr_result.ses_import.coverage_pct / 100.0
    except Exception:  # noqa: BLE001
        fr_status = "skipped"

    return ShoveBenchmarkResult(
        shove_completion_rate=resolved / total if total > 0 else 0.0,
        shove_drc_clean_rate=drc_clean / total if total > 0 else 0.0,
        shove_total_wirelength_mm=total_wl,
        shove_retracted_count=retracted,
        shove_elapsed_ms=shove_elapsed,
        freerouting_status=fr_status,
        freerouting_completion_rate=fr_completion,
        fallback_usage=fallback,
    )
