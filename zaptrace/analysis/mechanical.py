"""Mechanical / enclosure review and MCAD export.

Catches the mechanical mistakes that are cheap on a drawing and expensive on a
fabricated board: missing mounting holes, too few of them on a large board, and
holes that sit off the board or too close to its edge to be usable.

Also provides MCAD integration output: a component position table that can be
consumed by mechanical CAD tools (Fusion 360, SolidWorks, FreeCAD) to position
3-D component models on the PCB reference plane.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from io import StringIO
from typing import Any

from zaptrace.core.models import Design, MountingHole

# Boards with any dimension above this should have several mounting points.
_LARGE_BOARD_MM = 50.0
# Clearance a hole needs from the board edge beyond its own radius.
_EDGE_CLEARANCE_MM = 1.5


@dataclass
class MechanicalFinding:
    topic: str
    severity: str  # "info" | "warning"
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _board_dimensions(design: Design) -> tuple[float, float]:
    if design.board_def is not None:
        return design.board_def.width, design.board_def.height
    return design.board.width_mm, design.board.height_mm


def _mounting_holes(design: Design) -> list[MountingHole]:
    return list(design.board_def.mounting_holes) if design.board_def is not None else []


def mechanical_review(design: Design) -> list[MechanicalFinding]:
    """Return mechanical findings (mounting holes vs board size and edges)."""
    width, height = _board_dimensions(design)
    holes = _mounting_holes(design)
    findings: list[MechanicalFinding] = []

    if not holes:
        findings.append(
            MechanicalFinding(
                topic="mounting-holes",
                severity="warning",
                detail="No mounting holes — the board cannot be fastened into an enclosure.",
            )
        )
        return findings

    if max(width, height) > _LARGE_BOARD_MM and len(holes) < 4:
        findings.append(
            MechanicalFinding(
                topic="mounting-holes",
                severity="info",
                detail=f"Only {len(holes)} mounting hole(s) on a {width:g}x{height:g} mm board; 4 is typical.",
            )
        )

    for index, hole in enumerate(holes):
        x, y = hole.position
        margin = hole.diameter / 2.0 + _EDGE_CLEARANCE_MM
        if x < margin or y < margin or x > width - margin or y > height - margin:
            findings.append(
                MechanicalFinding(
                    topic="hole-edge-clearance",
                    severity="warning",
                    detail=f"Mounting hole {index + 1} at ({x:g}, {y:g}) is off-board or too close to the edge.",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# MCAD component position table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class McadComponentRow:
    """One row of a MCAD component position table."""

    ref: str
    value: str
    footprint: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    side: str  # "top" | "bottom"
    step_model: str  # 3-D model hint (e.g. "Capacitor_SMD:C_0603.step")


@dataclass
class McadPositionTable:
    """MCAD-ready component position table for a PCB design.

    The table gives MCAD tools enough information to place 3-D component
    bodies on the PCB reference plane. Coordinates are in mm relative to
    the board origin (lower-left corner).

    Attributes:
        board_width_mm: Board X extent.
        board_height_mm: Board Y extent.
        rows: One :class:`McadComponentRow` per placed component.
        non_claims: Caveats — heights, keepouts, and flex zones must be
            verified in the MCAD tool; ZapTrace does not generate .STEP bodies.
    """

    board_width_mm: float
    board_height_mm: float
    rows: list[McadComponentRow] = field(default_factory=list)
    non_claims: list[str] = field(
        default_factory=lambda: [
            "ZapTrace does not generate 3-D STEP/IGES bodies; use step_model hints with your MCAD library.",
            "Component heights and keep-out zones must be verified in the MCAD tool.",
            "Coordinate origin is assumed to be the lower-left corner of the board outline.",
        ]
    )

    def to_csv(self) -> str:
        """Render the table as a CSV string (compatible with IDF/IPC-7351 centroid format)."""
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Ref", "Value", "Footprint", "PosX(mm)", "PosY(mm)", "Rotation(deg)", "Side", "3D_Model"])
        for row in self.rows:
            writer.writerow(
                [
                    row.ref,
                    row.value,
                    row.footprint,
                    f"{row.x_mm:.4f}",
                    f"{row.y_mm:.4f}",
                    f"{row.rotation_deg:.2f}",
                    row.side,
                    row.step_model,
                ]
            )
        return buf.getvalue()

    def to_json(self) -> str:
        """Render as a JSON dict."""
        return json.dumps(
            {
                "board_width_mm": self.board_width_mm,
                "board_height_mm": self.board_height_mm,
                "component_count": len(self.rows),
                "rows": [
                    {
                        "ref": r.ref,
                        "value": r.value,
                        "footprint": r.footprint,
                        "x_mm": r.x_mm,
                        "y_mm": r.y_mm,
                        "rotation_deg": r.rotation_deg,
                        "side": r.side,
                        "step_model": r.step_model,
                    }
                    for r in self.rows
                ],
                "non_claims": self.non_claims,
            },
            indent=2,
        )

    def to_idf_placement(self) -> str:
        """Render the .PLACE section of an IDF 2.0 board file (text output only).

        The IDF placement section lists each component reference, package, side,
        x/y location, and rotation so that MCAD tools can import it directly.
        """
        lines = [".PLACE"]
        for row in self.rows:
            side_idf = "TOP" if row.side == "top" else "BOTTOM"
            lines.append(
                f'"{row.ref}" "{row.footprint}" {row.x_mm:.4f} {row.y_mm:.4f} 0.0 {row.rotation_deg:.2f} {side_idf}'
            )
        lines.append(".END_PLACE")
        return "\n".join(lines)


def _infer_side(comp: Any) -> str:
    """Determine component placement side (top/bottom)."""
    props = getattr(comp, "properties", None) or {}
    if props.get("side") in ("top", "bottom"):
        return props["side"]
    fp = getattr(comp, "footprint_def", None)
    if fp and hasattr(fp, "pads"):
        pads_bottom = sum(
            1
            for p in fp.pads
            if getattr(p, "layer", None) and getattr(p.layer, "value", str(getattr(p, "layer", ""))) == "bottom"
        )
        pads_top = sum(
            1
            for p in fp.pads
            if getattr(p, "layer", None) and getattr(p.layer, "value", str(getattr(p, "layer", ""))) == "top"
        )
        if pads_bottom > pads_top:
            return "bottom"
    return "top"


def _infer_step_model(comp: Any) -> str:
    """Guess a STEP model filename from the component footprint."""
    footprint = getattr(comp, "footprint", "") or ""
    if not footprint:
        return ""
    # KiCad-style: Library:Footprint → Library:Footprint.step
    if ":" in footprint:
        lib, fp_name = footprint.split(":", 1)
        return f"{lib}:{fp_name}.step"
    return f"{footprint}.step"


def _component_position(
    comp: Any,
    pos_map: dict[str, tuple[float, float]],
) -> tuple[float, float]:
    position = pos_map.get(comp.id) or pos_map.get(comp.ref)
    if position is None:
        raw_position = getattr(comp, "position", None)
        if raw_position is not None:
            position = (float(raw_position[0]), float(raw_position[1]))
    if position is None:
        return 0.0, 0.0
    return float(position[0]), float(position[1])


def _component_rotation(comp: Any) -> float:
    properties = getattr(comp, "properties", None) or {}
    return float(properties.get("rotation", 0.0))


def _mcad_component_row(
    comp: Any,
    pos_map: dict[str, tuple[float, float]],
) -> McadComponentRow:
    x_mm, y_mm = _component_position(comp, pos_map)
    return McadComponentRow(
        ref=comp.ref,
        value=getattr(comp, "value", "") or "",
        footprint=getattr(comp, "footprint", "") or "",
        x_mm=round(x_mm, 4),
        y_mm=round(y_mm, 4),
        rotation_deg=round(_component_rotation(comp), 2),
        side=_infer_side(comp),
        step_model=_infer_step_model(comp),
    )


def mcad_component_table(
    design: Design,
    placement: dict[str, tuple[float, float]] | None = None,
) -> McadPositionTable:
    """Build a MCAD component position table from a design.

    Args:
        design: The ZapTrace design to export.
        placement: Optional ``component_id → (x_mm, y_mm)`` placement dict.
            If ``None``, falls back to ``design.placement`` or zeroes.

    Returns:
        A :class:`McadPositionTable` ready to export as CSV, JSON, or IDF.
    """
    width, height = _board_dimensions(design)
    pos_map = placement or design.placement or {}
    rows = [
        _mcad_component_row(comp, pos_map)
        for comp in sorted(design.components.values(), key=lambda component: component.ref)
        if not getattr(comp, "dnp", False)
    ]
    return McadPositionTable(board_width_mm=width, board_height_mm=height, rows=rows)
