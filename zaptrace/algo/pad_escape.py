"""Pad-aware escape routing: compute legal pad endpoints and DRC evidence.

This module provides utilities for computing route endpoints from pad geometry
rather than component centers, and for recording DRC debt (escape failures,
clearance violations, and unrouted nets) in a machine-readable scorecard.

Design goals
------------
- Every route endpoint is computed from ``Component.footprint_def`` pad geometry
  when available; fallback to component center is explicit and recorded.
- Route evidence distinguishes three failure modes:
  * ``route_failure``: A* / MST could not find any path.
  * ``escape_failure``: No footprint/pad data → endpoint fell back to component center.
  * ``clearance_debt``: Route exists but estimated clearance is below threshold.
- A :class:`RouteEvidenceScorecard` aggregates all evidence for proof-pack use.
"""

from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from zaptrace.core.models import Component, FootprintDef, Pad

# ---------------------------------------------------------------------------
# Pad type classification
# ---------------------------------------------------------------------------

PadType = Literal["smd", "tht", "thermal", "connector", "unknown"]


def classify_pad(pad: Pad) -> PadType:
    """Return the functional type of a pad.

    ``pad`` must be a :class:`~zaptrace.core.models.Pad` instance.
    """
    drill = pad.drill
    layer: Any = pad.layer
    thermal = pad.id

    layer_name = str(layer.value if hasattr(layer, "value") else layer).lower()

    if drill is not None and drill > 0:
        return "tht"

    # Thermal pads sit on all copper layers (layer == "all")
    if "all" in layer_name or str(thermal).lower() in {"gnd", "ep", "epad", "thermal"}:
        return "thermal"

    # Connector pads are often wide and have a drill OR special naming
    ref = str(pad.id).upper()
    if ref.startswith(("J", "CON")):
        return "connector"

    # Everything else is SMD
    return "smd"


# ---------------------------------------------------------------------------
# Escape-point computation
# ---------------------------------------------------------------------------


@dataclass
class PadEscapePoint:
    """The computed route start/end for a single pad."""

    pad_type: PadType
    component_ref: str
    pin_name: str
    pad_id: str
    # Absolute board coordinates of the pad centre.
    pad_center: tuple[float, float]
    # Absolute board coordinates of the escape point (outside courtyard).
    escape_point: tuple[float, float]
    # Whether this fell back to the component centre.
    is_fallback: bool = False
    fallback_reason: str = ""


def compute_escape_point(
    comp: Component,
    pin_name: str,
    comp_pos: tuple[float, float],
    *,
    escape_margin_mm: float = 0.25,
) -> PadEscapePoint:
    """Compute a legal pad escape point for *pin_name* on *comp*.

    Parameters
    ----------
    comp:
        A :class:`~zaptrace.core.models.Component` instance.
    pin_name:
        The logical pin name to find a matching pad for.
    comp_pos:
        Absolute (x, y) placement position of the component centre in mm.
    escape_margin_mm:
        Clearance to add beyond the courtyard edge for the escape wire.

    Returns
    -------
    PadEscapePoint
        If no footprint/pad data is found the returned point is at *comp_pos*
        with ``is_fallback=True``.
    """
    cx, cy = comp_pos
    comp_ref = comp.ref
    fp: FootprintDef | None = comp.footprint_def

    fallback_center = _synthetic_pin_escape_point(comp_ref, pin_name, comp_pos)
    fallback = PadEscapePoint(
        pad_type="unknown",
        component_ref=comp_ref,
        pin_name=pin_name,
        pad_id="?",
        pad_center=fallback_center,
        escape_point=fallback_center,
        is_fallback=True,
        fallback_reason="no footprint_def; synthetic pin escape used",
    )

    if fp is None:
        return fallback

    pad = _find_pad(fp, pin_name)
    if pad is None:
        fallback.fallback_reason = f"pin '{pin_name}' not found in footprint pads"
        return fallback

    pad_type = classify_pad(pad)
    dx, dy = float(pad.position[0]), float(pad.position[1])
    pad_center = (cx + dx, cy + dy)

    # Courtyard half-extents
    half_cx = max(float(fp.courtyard[0]) / 2.0, 0.0)
    half_cy = max(float(fp.courtyard[1]) / 2.0, 0.0)

    escape_point = _escape_outside_courtyard(
        comp_center=(cx, cy),
        pad_offset=(dx, dy),
        courtyard_half=(half_cx, half_cy),
        margin=escape_margin_mm,
    )

    return PadEscapePoint(
        pad_type=pad_type,
        component_ref=comp_ref,
        pin_name=pin_name,
        pad_id=str(pad.id),
        pad_center=pad_center,
        escape_point=escape_point,
        is_fallback=False,
    )


def _synthetic_pin_escape_point(
    comp_ref: str,
    pin_name: str,
    comp_pos: tuple[float, float],
    *,
    radius_mm: float = 2.5,
) -> tuple[float, float]:
    """Return a deterministic synthetic escape point when pad geometry is absent.

    Falling back to the component centre collapses every pin on the component to
    the same physical point, which creates artificial cross-net overlaps in DRC
    and proof-pack clearance checks.  This synthetic fallback keeps the explicit
    ``is_fallback`` evidence but spreads common pin names around the component so
    router output remains inspectable and less pessimistic until real footprint
    geometry is available.
    """
    cx, cy = comp_pos
    key = pin_name.strip().lower()
    semantic_angles = {
        "gnd": -135.0,
        "ground": -135.0,
        "vss": -90.0,
        "vbus": 180.0,
        "vin": 180.0,
        "input": 180.0,
        "vcc": 90.0,
        "vdd": 90.0,
        "output": 0.0,
        "vout": 0.0,
        "en": 45.0,
        "enable": 45.0,
        "sda": -160.0,
        "scl": 45.0,
        "sck": 45.0,
        "mosi": 0.0,
        "miso": 180.0,
        "cs": 90.0,
        "csb": 90.0,
        "sdO".lower(): -135.0,
    }
    if key in semantic_angles:
        angle_deg = semantic_angles[key]
    else:
        # Stable, dependency-free hash distributed over 16 compass directions.
        seed = sum((idx + 1) * ord(ch) for idx, ch in enumerate(f"{comp_ref}:{pin_name}"))
        angle_deg = (seed % 16) * 22.5

    angle = math.radians(angle_deg)
    return (cx + math.cos(angle) * radius_mm, cy + math.sin(angle) * radius_mm)


def _find_pad(fp: FootprintDef, pin_name: str) -> Pad | None:
    """Return the pad in *fp* whose id matches *pin_name* (case-insensitive)."""
    aliases = {pin_name.strip().lower(), pin_name.strip()}
    # Numeric pin names may also appear as integers
    with contextlib.suppress(ValueError):
        aliases.add(str(int(pin_name.strip())))
    for pad in fp.pads:
        if str(pad.id).strip().lower() in aliases:
            return pad
    return None


def _pad_is_outside_courtyard(
    pad_offset: tuple[float, float],
    courtyard_half: tuple[float, float],
) -> bool:
    dx, dy = pad_offset
    half_w, half_h = courtyard_half
    outside_x = abs(dx) >= half_w if half_w > 0 else True
    outside_y = abs(dy) >= half_h if half_h > 0 else True
    return outside_x or outside_y


def _nudge_pad_outward(
    comp_center: tuple[float, float],
    pad_offset: tuple[float, float],
    margin: float,
) -> tuple[float, float]:
    cx, cy = comp_center
    dx, dy = pad_offset
    abs_x, abs_y = cx + dx, cy + dy
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (abs_x + margin, abs_y)
    return (abs_x + (dx / length) * margin, abs_y + (dy / length) * margin)


def _courtyard_edge_scale(
    pad_offset: tuple[float, float],
    courtyard_half: tuple[float, float],
) -> float:
    dx, dy = pad_offset
    half_w, half_h = courtyard_half
    if half_w > 0 and half_h > 0:
        scale_x = half_w / abs(dx) if abs(dx) > 1e-9 else float("inf")
        scale_y = half_h / abs(dy) if abs(dy) > 1e-9 else float("inf")
        return min(scale_x, scale_y)
    if half_w > 0:
        return half_w / abs(dx) if abs(dx) > 1e-9 else 1.0
    return half_h / abs(dy) if abs(dy) > 1e-9 else 1.0


def _project_to_courtyard_edge(
    comp_center: tuple[float, float],
    pad_offset: tuple[float, float],
    courtyard_half: tuple[float, float],
    margin: float,
) -> tuple[float, float]:
    cx, cy = comp_center
    dx, dy = pad_offset
    half_w, half_h = courtyard_half
    if half_w > 0 and half_h > 0 and abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return (cx + half_w + margin, cy)
    scale = _courtyard_edge_scale(pad_offset, courtyard_half)
    edge_x, edge_y = cx + dx * scale, cy + dy * scale
    length = math.hypot(edge_x - cx, edge_y - cy) or 1.0
    return (
        edge_x + ((edge_x - cx) / length) * margin,
        edge_y + ((edge_y - cy) / length) * margin,
    )


def _escape_outside_courtyard(
    comp_center: tuple[float, float],
    pad_offset: tuple[float, float],
    courtyard_half: tuple[float, float],
    margin: float,
) -> tuple[float, float]:
    """Project a pad position outwards until it clears the courtyard."""
    cx, cy = comp_center
    dx, dy = pad_offset
    half_w, half_h = courtyard_half
    if half_w <= 0.0 and half_h <= 0.0:
        return (cx + dx, cy + dy)
    if _pad_is_outside_courtyard(pad_offset, courtyard_half):
        return _nudge_pad_outward(comp_center, pad_offset, margin)
    return _project_to_courtyard_edge(comp_center, pad_offset, courtyard_half, margin)


# ---------------------------------------------------------------------------
# DRC debt tracking
# ---------------------------------------------------------------------------

FailureKind = Literal["route_failure", "escape_failure", "clearance_debt"]


@dataclass
class RouteFailureRecord:
    """Evidence record for one net that failed or has DRC debt."""

    net_id: str
    net_name: str
    kind: FailureKind
    detail: str = ""
    component_refs: list[str] = field(default_factory=list)


@dataclass
class RouteEvidenceScorecard:
    """Aggregated routing evidence for DRC / proof-pack use.

    Fields
    ------
    total_nets:
        All nets considered for routing.
    routed_nets:
        Nets successfully routed.
    unrouted_nets:
        Count of nets that could not be routed (route_failure).
    escape_fallback_nets:
        Count of nets where at least one endpoint fell back to component centre.
    clearance_debt_nets:
        Count of routed nets with an estimated clearance violation.
    via_count:
        Total number of vias placed.
    total_length_mm:
        Total routed trace length.
    failures:
        Per-net failure evidence records.
    pad_type_counts:
        How many escape points were computed per pad type.
    non_claims:
        Explicit non-claims about this evidence.
    """

    total_nets: int = 0
    routed_nets: int = 0
    unrouted_nets: int = 0
    escape_fallback_nets: int = 0
    clearance_debt_nets: int = 0
    via_count: int = 0
    total_length_mm: float = 0.0
    failures: list[RouteFailureRecord] = field(default_factory=list)
    pad_type_counts: dict[str, int] = field(default_factory=dict)
    non_claims: list[str] = field(default_factory=list)

    def record_route_failure(self, net_id: str, net_name: str, detail: str = "") -> None:
        self.unrouted_nets += 1
        self.failures.append(RouteFailureRecord(net_id=net_id, net_name=net_name, kind="route_failure", detail=detail))

    def record_escape_fallback(self, net_id: str, net_name: str, comp_refs: list[str], reasons: list[str]) -> None:
        self.escape_fallback_nets += 1
        detail = "; ".join(f"{r}: {m}" for r, m in zip(comp_refs, reasons, strict=False) if m)
        self.failures.append(
            RouteFailureRecord(
                net_id=net_id,
                net_name=net_name,
                kind="escape_failure",
                detail=detail or "fallback to component center",
                component_refs=comp_refs,
            )
        )

    def record_clearance_debt(self, net_id: str, net_name: str, detail: str = "") -> None:
        self.clearance_debt_nets += 1
        self.failures.append(RouteFailureRecord(net_id=net_id, net_name=net_name, kind="clearance_debt", detail=detail))

    def increment_pad_type(self, pad_type: str) -> None:
        self.pad_type_counts[pad_type] = self.pad_type_counts.get(pad_type, 0) + 1

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "total_nets": self.total_nets,
            "routed_nets": self.routed_nets,
            "unrouted_nets": self.unrouted_nets,
            "escape_fallback_nets": self.escape_fallback_nets,
            "clearance_debt_nets": self.clearance_debt_nets,
            "via_count": self.via_count,
            "total_length_mm": round(self.total_length_mm, 3),
            "pad_type_counts": dict(sorted(self.pad_type_counts.items())),
            "failures": [
                {
                    "net_id": f.net_id,
                    "net_name": f.net_name,
                    "kind": f.kind,
                    "detail": f.detail,
                    "component_refs": f.component_refs,
                }
                for f in self.failures
            ],
            "non_claims": self.non_claims,
        }
