from __future__ import annotations

import math

from zaptrace.core.models import Design


def render_schematic_svg(
    design: Design,
    positions: dict[str, tuple[float, float]] | None = None,
    width_px: int = 1200,
    height_px: int = 900,
) -> str:
    """
    Render a schematic overview as SVG.

    Each component is drawn as a labeled rectangle.
    Nets are drawn as lines between connected components.
    If positions not provided, grid layout is used.
    """
    comps = list(design.components.values())
    if not comps:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200"><text x="20" y="30">No components</text></svg>'  # noqa: E501

    if positions is None:
        positions = _grid_positions(comps, width_px, height_px)

    ref_positions = {comp.ref: positions[key] for comp in comps for key in (comp.id, comp.ref) if key in positions}

    COMP_W, COMP_H = 120, 50
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg"',
        f' width="{width_px}" height="{height_px}"',
        f' viewBox="0 0 {width_px} {height_px}">',
        "<defs><style>",
        ".comp-box{fill:#f0f4ff;stroke:#334;stroke-width:1.5;rx:6}",
        ".comp-ref{font:bold 12px sans-serif;fill:#334}",
        ".comp-type{font:10px sans-serif;fill:#668}",
        ".net-line{stroke:#6699cc;stroke-width:1;opacity:0.6}",
        "</style></defs>",
        f'<rect width="{width_px}" height="{height_px}" fill="#fafafa"/>',
        f'<text x="20" y="28" style="font:bold 16px sans-serif;fill:#334">{design.meta.name}</text>',
    ]

    for net in design.nets.values():
        nodes_pos: list[tuple[float, float]] = []
        for node in net.nodes:
            if node.component_ref in ref_positions:
                cx, cy = ref_positions[node.component_ref]
                nodes_pos.append((cx + COMP_W / 2, cy + COMP_H / 2))
        for i in range(len(nodes_pos) - 1):
            x1, y1 = nodes_pos[i]
            x2, y2 = nodes_pos[i + 1]
            lines.append(f'<line class="net-line" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')

    for comp in comps:
        if comp.id not in positions:
            continue
        x, y = positions[comp.id]
        lines.append(f'<rect class="comp-box" x="{x:.1f}" y="{y:.1f}" width="{COMP_W}" height="{COMP_H}" rx="4"/>')
        lines.append(f'<text class="comp-ref" x="{x + 8:.1f}" y="{y + 18:.1f}">{comp.ref}</text>')
        lines.append(f'<text class="comp-type" x="{x + 8:.1f}" y="{y + 33:.1f}">{comp.type[:18]}</text>')

    lines.append("</svg>")
    return "\n".join(lines)


def _grid_positions(comps: list, width_px: int, height_px: int) -> dict[str, tuple[float, float]]:
    n = len(comps)
    cols = max(1, math.ceil(math.sqrt(n * width_px / height_px)))
    margin = 30
    cell_w = (width_px - 2 * margin) / cols
    cell_h = max(80.0, (height_px - 60) / max(1, math.ceil(n / cols)))
    result: dict[str, tuple[float, float]] = {}
    for i, comp in enumerate(comps):
        col = i % cols
        row = i // cols
        result[comp.id] = (margin + col * cell_w, 50 + row * cell_h)
    return result
