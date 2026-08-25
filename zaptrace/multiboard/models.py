"""Data models for PCB panelization and multi-board arrays."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PanelSeparationMethod(StrEnum):
    V_SCORE = "v_score"
    TAB_ROUTE = "tab_route"
    STAMP_HOLES = "stamp_holes"


class BoardInstance(BaseModel):
    """Placement specification for a PCB design within a panel."""

    model_config = ConfigDict(strict=False)

    board_id: str
    design_path: str = ""
    width_mm: float = 50.0
    height_mm: float = 40.0
    count_x: int = Field(default=2, ge=1)
    count_y: int = Field(default=2, ge=1)
    rotation: float = 0.0


class FiducialSpec(BaseModel):
    """Optical alignment fiducial marker placed on panel rails."""

    model_config = ConfigDict(strict=False)

    x: float
    y: float
    copper_diameter_mm: float = 1.0
    mask_clearance_mm: float = 2.0


class ToolingHoleSpec(BaseModel):
    """Mechanical tooling / mounting hole on panel rails."""

    model_config = ConfigDict(strict=False)

    x: float
    y: float
    diameter_mm: float = 3.2
    plated: bool = False


class VScoreLine(BaseModel):
    """V-score groove line across panel."""

    model_config = ConfigDict(strict=False)

    orientation: str  # "horizontal" | "vertical"
    position_mm: float
    start_mm: float
    end_mm: float


class RouteTab(BaseModel):
    """Breakout tab with perforation / mouse-bites."""

    model_config = ConfigDict(strict=False)

    x: float
    y: float
    width_mm: float = 5.0
    mouse_bites: bool = True
    hole_count: int = 5
    hole_diameter_mm: float = 0.5


class PanelConfig(BaseModel):
    """Complete specification for panel array fabrication."""

    model_config = ConfigDict(strict=False)

    name: str = "panel-array"
    panel_width_mm: float = 200.0
    panel_height_mm: float = 150.0
    rail_width_mm: float = 5.0
    spacing_mm: float = 2.0
    separation: PanelSeparationMethod = PanelSeparationMethod.V_SCORE
    boards: list[BoardInstance] = Field(default_factory=list)
    auto_rails: bool = True
    auto_fiducials: bool = True
    auto_tooling_holes: bool = True


class PlacedBoard(BaseModel):
    """Individual placed board on panel with coordinates."""

    model_config = ConfigDict(strict=False)

    board_id: str
    index: int
    x: float
    y: float
    width_mm: float
    height_mm: float
    rotation: float = 0.0


class PanelResult(BaseModel):
    """Computed panel layout result ready for visualization and export."""

    model_config = ConfigDict(strict=False)

    config: PanelConfig
    panel_width_mm: float
    panel_height_mm: float
    total_boards: int
    placed_boards: list[PlacedBoard] = Field(default_factory=list)
    v_scores: list[VScoreLine] = Field(default_factory=list)
    tabs: list[RouteTab] = Field(default_factory=list)
    fiducials: list[FiducialSpec] = Field(default_factory=list)
    tooling_holes: list[ToolingHoleSpec] = Field(default_factory=list)
    utilization_pct: float = 0.0
