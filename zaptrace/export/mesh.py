"""3D Mesh (Wavefront OBJ and STL) exporters for PCB geometry and enclosures."""

from __future__ import annotations

from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Design

# Estimated component package heights in mm
_PACKAGE_HEIGHT_MM: dict[str, float] = {
    "0402": 0.35,
    "0603": 0.45,
    "0805": 0.55,
    "1206": 0.65,
    "SOT-23": 1.1,
    "SOIC-8": 1.5,
    "SOIC-14": 1.5,
    "SOIC-16": 1.5,
    "TSSOP-8": 1.0,
    "TSSOP-14": 1.0,
    "TSSOP-16": 1.0,
    "QFN-16": 0.85,
    "QFN-32": 0.9,
    "QFN-48": 0.9,
    "LQFP-48": 1.4,
    "LQFP-64": 1.4,
    "LQFP-100": 1.4,
    "DIP-8": 4.5,
    "DIP-14": 4.5,
    "DIP-16": 4.5,
    "BGA-48": 1.2,
    "BGA-64": 1.2,
    "HEADER": 8.5,
    "USB-C": 3.2,
    "USB-A": 5.8,
    "JST-PH": 6.0,
}


def _estimate_height(footprint: str) -> float:
    fp_upper = footprint.upper()
    for pkg, h in _PACKAGE_HEIGHT_MM.items():
        if pkg in fp_upper:
            return h
    return 1.0  # Default 1.0mm


def export_pcb_obj(design: Design, board_thickness_mm: float = 1.6) -> str:
    """Export PCB substrate and placed component bodies as Wavefront OBJ file."""
    bd = canonical_board_definition(design)
    bw, bh = bd.width, bd.height
    bt = board_thickness_mm

    lines = [
        "# ZapTrace PCB 3D Model (Wavefront OBJ)",
        f"# Design: {design.meta.name}",
        f"# Dimensions: {bw:.2f} x {bh:.2f} x {bt:.2f} mm",
        "",
        "o Substrate_FR4",
    ]

    v_idx = 1

    # 1. Substrate Box (8 vertices)
    # Centered at (0, 0), substrate between z = -bt and z = 0
    hw, hh = bw / 2, bh / 2
    sub_vertices = [
        (-hw, -hh, -bt),  # 1: Bottom left-bottom
        (hw, -hh, -bt),   # 2: Bottom right-bottom
        (hw, hh, -bt),    # 3: Top right-bottom
        (-hw, hh, -bt),   # 4: Top left-bottom
        (-hw, -hh, 0.0),  # 5: Bottom left-top
        (hw, -hh, 0.0),   # 6: Bottom right-top
        (hw, hh, 0.0),    # 7: Top right-top
        (-hw, hh, 0.0),   # 8: Top left-top
    ]
    for x, y, z in sub_vertices:
        lines.append(f"v {x:.4f} {y:.4f} {z:.4f}")

    # Substrate faces (6 quad faces -> each quad is two triangles or 4-index)
    lines.append(f"f {v_idx} {v_idx+1} {v_idx+2} {v_idx+3}")  # Bottom
    lines.append(f"f {v_idx+4} {v_idx+7} {v_idx+6} {v_idx+5}")  # Top
    lines.append(f"f {v_idx} {v_idx+4} {v_idx+5} {v_idx+1}")  # Front
    lines.append(f"f {v_idx+1} {v_idx+5} {v_idx+6} {v_idx+2}")  # Right
    lines.append(f"f {v_idx+2} {v_idx+6} {v_idx+7} {v_idx+3}")  # Back
    lines.append(f"f {v_idx+3} {v_idx+7} {v_idx+4} {v_idx}")  # Left
    v_idx += 8

    # 2. Components as 3D bounding boxes
    positions = design.placement or {}
    for ref, comp in sorted(design.components.items()):
        pos = positions.get(ref)
        if pos is None:
            continue
        cx, cy = pos
        # Transform from board origin (0,0 bottom-left) to centered coords
        ox = cx - hw
        oy = cy - hh
        h = _estimate_height(comp.footprint)
        cw, ch = 3.0, 3.0  # default size

        lines.append("")
        lines.append(f"o Comp_{ref}_{comp.footprint}")
        comp_vertices = [
            (ox - cw/2, oy - ch/2, 0.0),
            (ox + cw/2, oy - ch/2, 0.0),
            (ox + cw/2, oy + ch/2, 0.0),
            (ox - cw/2, oy + ch/2, 0.0),
            (ox - cw/2, oy - ch/2, h),
            (ox + cw/2, oy - ch/2, h),
            (ox + cw/2, oy + ch/2, h),
            (ox - cw/2, oy + ch/2, h),
        ]
        for x, y, z in comp_vertices:
            lines.append(f"v {x:.4f} {y:.4f} {z:.4f}")

        lines.append(f"f {v_idx} {v_idx+1} {v_idx+2} {v_idx+3}")
        lines.append(f"f {v_idx+4} {v_idx+7} {v_idx+6} {v_idx+5}")
        lines.append(f"f {v_idx} {v_idx+4} {v_idx+5} {v_idx+1}")
        lines.append(f"f {v_idx+1} {v_idx+5} {v_idx+6} {v_idx+2}")
        lines.append(f"f {v_idx+2} {v_idx+6} {v_idx+7} {v_idx+3}")
        lines.append(f"f {v_idx+3} {v_idx+7} {v_idx+4} {v_idx}")
        v_idx += 8

    return "\n".join(lines)


def export_pcb_stl(design: Design, board_thickness_mm: float = 1.6) -> str:
    """Export PCB substrate as ASCII STL format."""
    bd = canonical_board_definition(design)
    bw, bh = bd.width, bd.height
    bt = board_thickness_mm
    hw, hh = bw / 2, bh / 2

    # 12 triangles for substrate box
    triangles = [
        # Top face (+Z)
        ((0, 0, 1), ((-hw, -hh, 0), (hw, -hh, 0), (hw, hh, 0))),
        ((0, 0, 1), ((-hw, -hh, 0), (hw, hh, 0), (-hw, hh, 0))),
        # Bottom face (-Z)
        ((0, 0, -1), ((-hw, -hh, -bt), (hw, hh, -bt), (hw, -hh, -bt))),
        ((0, 0, -1), ((-hw, -hh, -bt), (-hw, hh, -bt), (hw, hh, -bt))),
        # Front (-Y)
        ((0, -1, 0), ((-hw, -hh, -bt), (hw, -hh, -bt), (hw, -hh, 0))),
        ((0, -1, 0), ((-hw, -hh, -bt), (hw, -hh, 0), (-hw, -hh, 0))),
        # Back (+Y)
        ((0, 1, 0), ((-hw, hh, -bt), (hw, hh, 0), (hw, hh, -bt))),
        ((0, 1, 0), ((-hw, hh, -bt), (-hw, hh, 0), (hw, hh, 0))),
        # Left (-X)
        ((-1, 0, 0), ((-hw, -hh, -bt), (-hw, -hh, 0), (-hw, hh, 0))),
        ((-1, 0, 0), ((-hw, -hh, -bt), (-hw, hh, 0), (-hw, hh, -bt))),
        # Right (+X)
        ((1, 0, 0), ((hw, -hh, -bt), (hw, hh, 0), (hw, -hh, 0))),
        ((1, 0, 0), ((hw, -hh, -bt), (hw, hh, -bt), (hw, hh, 0))),
    ]

    lines = [f"solid {design.meta.name}"]
    for (nx, ny, nz), ((ax, ay, az), (bx, by, bz), (cx, cy, cz)) in triangles:
        lines.append(f"  facet normal {nx} {ny} {nz}")
        lines.append("    outer loop")
        lines.append(f"      vertex {ax:.4f} {ay:.4f} {az:.4f}")
        lines.append(f"      vertex {bx:.4f} {by:.4f} {bz:.4f}")
        lines.append(f"      vertex {cx:.4f} {cy:.4f} {cz:.4f}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {design.meta.name}")

    return "\n".join(lines)
