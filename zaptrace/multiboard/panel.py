# ruff: noqa: E501

"""Panel array generation, V-scoring, breakout tabs, and SVG visualization."""

from __future__ import annotations

import html
from typing import Any

from zaptrace.multiboard.models import (
    FiducialSpec,
    PanelConfig,
    PanelResult,
    PanelSeparationMethod,
    PlacedBoard,
    RouteTab,
    ToolingHoleSpec,
    VScoreLine,
)


def generate_panel(config: PanelConfig) -> PanelResult:
    """Compute deterministic panel layout from specification."""
    rail = config.rail_width_mm
    spacing = config.spacing_mm
    placed_boards: list[PlacedBoard] = []
    v_scores: list[VScoreLine] = []
    tabs: list[RouteTab] = []

    # Current cursor inside the active area
    cursor_x = rail
    cursor_y = rail
    board_idx = 0
    total_board_area = 0.0

    for bi in config.boards:
        bw = bi.width_mm
        bh = bi.height_mm
        for row in range(bi.count_y):
            for col in range(bi.count_x):
                bx = cursor_x + col * (bw + spacing)
                by = cursor_y + row * (bh + spacing)
                placed_boards.append(
                    PlacedBoard(
                        board_id=bi.board_id,
                        index=board_idx,
                        x=round(bx, 3),
                        y=round(by, 3),
                        width_mm=bw,
                        height_mm=bh,
                        rotation=bi.rotation,
                    )
                )
                board_idx += 1
                total_board_area += bw * bh

                # Breakout tabs if tab-routing
                if config.separation == PanelSeparationMethod.TAB_ROUTE:
                    # Top tab
                    tabs.append(RouteTab(x=bx + bw / 2, y=by, width_mm=4.0))
                    # Bottom tab
                    tabs.append(RouteTab(x=bx + bw / 2, y=by + bh, width_mm=4.0))
                    # Left tab
                    tabs.append(RouteTab(x=bx, y=by + bh / 2, width_mm=4.0))
                    # Right tab
                    tabs.append(RouteTab(x=bx + bw, y=by + bh / 2, width_mm=4.0))

        # Generate V-scores across the grid if V-score method
        if config.separation == PanelSeparationMethod.V_SCORE:
            # Vertical cut lines
            for col in range(bi.count_x + 1):
                cut_x = cursor_x + col * (bw + spacing) - (spacing / 2 if col > 0 and col < bi.count_x else 0)
                v_scores.append(
                    VScoreLine(
                        orientation="vertical",
                        position_mm=round(cut_x, 3),
                        start_mm=0.0,
                        end_mm=config.panel_height_mm,
                    )
                )
            # Horizontal cut lines
            for row in range(bi.count_y + 1):
                cut_y = cursor_y + row * (bh + spacing) - (spacing / 2 if row > 0 and row < bi.count_y else 0)
                v_scores.append(
                    VScoreLine(
                        orientation="horizontal",
                        position_mm=round(cut_y, 3),
                        start_mm=0.0,
                        end_mm=config.panel_width_mm,
                    )
                )

        cursor_x += bi.count_x * (bw + spacing)

    # Standard 3 fiducials (asymmetric on rails for PnP camera orientation)
    fiducials: list[FiducialSpec] = []
    if config.auto_fiducials:
        pw = config.panel_width_mm
        ph = config.panel_height_mm
        fiducials = [
            FiducialSpec(x=rail / 2, y=rail / 2),
            FiducialSpec(x=pw - rail / 2, y=rail / 2),
            FiducialSpec(x=rail / 2, y=ph - rail / 2),
        ]

    # Standard 4 tooling holes in rail corners
    tooling_holes: list[ToolingHoleSpec] = []
    if config.auto_tooling_holes:
        pw = config.panel_width_mm
        ph = config.panel_height_mm
        offset = rail / 2
        tooling_holes = [
            ToolingHoleSpec(x=offset, y=offset),
            ToolingHoleSpec(x=pw - offset, y=offset),
            ToolingHoleSpec(x=offset, y=ph - offset),
            ToolingHoleSpec(x=pw - offset, y=ph - offset),
        ]

    panel_area = config.panel_width_mm * config.panel_height_mm
    util_pct = (total_board_area / panel_area * 100.0) if panel_area > 0 else 0.0

    return PanelResult(
        config=config,
        panel_width_mm=config.panel_width_mm,
        panel_height_mm=config.panel_height_mm,
        total_boards=len(placed_boards),
        placed_boards=placed_boards,
        v_scores=v_scores,
        tabs=tabs,
        fiducials=fiducials,
        tooling_holes=tooling_holes,
        utilization_pct=round(util_pct, 2),
    )


def render_panel_svg(panel: PanelResult, scale: float = 4.0) -> str:
    """Render panel layout as clean SVG diagram."""
    pw = panel.panel_width_mm
    ph = panel.panel_height_mm
    width = int(pw * scale) + 40
    height = int(ph * scale) + 60
    ox, oy = 20, 30

    body: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg"',
        f' width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs><style>",
        ".rail{fill:#1e293b;stroke:#475569;stroke-width:1.5}",
        ".board{fill:#064e3b;stroke:#34d399;stroke-width:1.5;rx:3}",
        ".vscore{stroke:#ef4444;stroke-dasharray:4,4;stroke-width:1.2}",
        ".tab{fill:#f59e0b;stroke:#b45309;stroke-width:1}",
        ".fiducial{fill:#eab308;stroke:#ca8a04;stroke-width:1}",
        ".tooling{fill:#0f172a;stroke:#94a3b8;stroke-width:1.5}",
        ".label{font:11px sans-serif;fill:#f8fafc}",
        ".title{font:13px sans-serif;font-weight:bold;fill:#60a5fa}",
        "</style></defs>",
        f'<text class="title" x="20" y="20">{html.escape(panel.config.name)} ({pw}x{ph}mm, {panel.total_boards} boards, {panel.utilization_pct}% area)</text>',
        # Panel frame / rails
        f'<rect class="rail" x="{ox}" y="{oy}" width="{pw * scale:.1f}" height="{ph * scale:.1f}" rx="6"/>',
    ]

    # Placed boards
    for b in panel.placed_boards:
        bx = ox + b.x * scale
        by = oy + b.y * scale
        bw = b.width_mm * scale
        bh = b.height_mm * scale
        body.append(f'<rect class="board" x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}"/>')
        body.append(
            f'<text class="label" x="{bx + 6:.1f}" y="{by + 16:.1f}">{html.escape(b.board_id)} #{b.index + 1}</text>'
        )

    # V-score lines
    for vs in panel.v_scores:
        if vs.orientation == "vertical":
            vx = ox + vs.position_mm * scale
            body.append(
                f'<line class="vscore" x1="{vx:.1f}" y1="{oy}" x2="{vx:.1f}" y2="{oy + ph * scale:.1f}"><title>V-Score X={vs.position_mm}mm</title></line>'
            )
        else:
            vy = oy + vs.position_mm * scale
            body.append(
                f'<line class="vscore" x1="{ox}" y1="{vy:.1f}" x2="{ox + pw * scale:.1f}" y2="{vy:.1f}"><title>V-Score Y={vs.position_mm}mm</title></line>'
            )

    # Breakout tabs
    for t in panel.tabs:
        tx = ox + t.x * scale - (t.width_mm * scale / 2)
        ty = oy + t.y * scale - 2
        body.append(f'<rect class="tab" x="{tx:.1f}" y="{ty:.1f}" width="{t.width_mm * scale:.1f}" height="4"/>')

    # Tooling holes
    for th in panel.tooling_holes:
        hx = ox + th.x * scale
        hy = oy + th.y * scale
        hr = (th.diameter_mm * scale) / 2
        body.append(
            f'<circle class="tooling" cx="{hx:.1f}" cy="{hy:.1f}" r="{hr:.1f}"><title>Tooling Hole dia={th.diameter_mm}mm</title></circle>'
        )

    # Fiducials
    for fd in panel.fiducials:
        fx = ox + fd.x * scale
        fy = oy + fd.y * scale
        fr = (fd.copper_diameter_mm * scale) / 2
        body.append(
            f'<circle class="fiducial" cx="{fx:.1f}" cy="{fy:.1f}" r="{fr:.1f}"><title>Fiducial</title></circle>'
        )

    body.append("</svg>")
    return "\n".join(body)


def consolidate_panel_bom(
    panel: PanelResult,
    board_boms: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Consolidate BOM items across all boards in panel multiplied by instance count."""
    merged: dict[str, dict[str, Any]] = {}

    for b in panel.placed_boards:
        items = board_boms.get(b.board_id, [])
        for it in items:
            key = f"{it.get('mpn', '')}|{it.get('value', '')}|{it.get('footprint', '')}"
            if key not in merged:
                merged[key] = {
                    "mpn": it.get("mpn", ""),
                    "value": it.get("value", ""),
                    "footprint": it.get("footprint", ""),
                    "manufacturer": it.get("manufacturer", ""),
                    "quantity": 0,
                    "refs": [],
                }
            merged[key]["quantity"] += int(it.get("quantity", 1))
            ref = it.get("ref", "")
            if ref:
                merged[key]["refs"].append(f"{b.board_id}#{b.index + 1}.{ref}")

    return sorted(merged.values(), key=lambda x: x["mpn"] or x["value"])
