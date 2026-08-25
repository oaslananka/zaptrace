"""Multi-board system and panel array generation package."""

from __future__ import annotations

from zaptrace.multiboard.models import (
    BoardInstance,
    FiducialSpec,
    PanelConfig,
    PanelResult,
    PanelSeparationMethod,
    PlacedBoard,
    RouteTab,
    ToolingHoleSpec,
    VScoreLine,
)
from zaptrace.multiboard.panel import (
    consolidate_panel_bom,
    generate_panel,
    render_panel_svg,
)

__all__ = [
    "BoardInstance",
    "FiducialSpec",
    "PanelConfig",
    "PanelResult",
    "PanelSeparationMethod",
    "PlacedBoard",
    "RouteTab",
    "ToolingHoleSpec",
    "VScoreLine",
    "consolidate_panel_bom",
    "generate_panel",
    "render_panel_svg",
]
