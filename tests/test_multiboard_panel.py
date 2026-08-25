"""Tests for multi-board panel array generation and BOM consolidation."""

from __future__ import annotations

from zaptrace.multiboard.models import (
    BoardInstance,
    PanelConfig,
    PanelResult,
    PanelSeparationMethod,
)
from zaptrace.multiboard.panel import (
    consolidate_panel_bom,
    generate_panel,
    render_panel_svg,
)


class TestPanelGeneration:
    """Test deterministic panel array math and layout generation."""

    def test_vscore_panel_grid(self) -> None:
        config = PanelConfig(
            name="sensor-2x3-panel",
            panel_width_mm=160.0,
            panel_height_mm=120.0,
            rail_width_mm=5.0,
            spacing_mm=2.0,
            separation=PanelSeparationMethod.V_SCORE,
            boards=[
                BoardInstance(
                    board_id="sensor_node",
                    width_mm=45.0,
                    height_mm=30.0,
                    count_x=3,
                    count_y=3,
                )
            ],
        )
        result = generate_panel(config)
        assert isinstance(result, PanelResult)
        assert result.total_boards == 9
        assert len(result.placed_boards) == 9
        assert len(result.v_scores) > 0
        assert len(result.fiducials) == 3
        assert len(result.tooling_holes) == 4
        assert result.utilization_pct > 50.0

    def test_tab_route_panel(self) -> None:
        config = PanelConfig(
            name="tab-panel",
            panel_width_mm=120.0,
            panel_height_mm=100.0,
            separation=PanelSeparationMethod.TAB_ROUTE,
            boards=[
                BoardInstance(
                    board_id="mcu_board",
                    width_mm=40.0,
                    height_mm=40.0,
                    count_x=2,
                    count_y=2,
                )
            ],
        )
        result = generate_panel(config)
        assert result.total_boards == 4
        # 4 tabs per board = 16 tabs
        assert len(result.tabs) == 16
        assert len(result.v_scores) == 0

    def test_render_panel_svg(self) -> None:
        config = PanelConfig(
            name="preview-panel",
            panel_width_mm=100.0,
            panel_height_mm=80.0,
            boards=[
                BoardInstance(
                    board_id="test_board",
                    width_mm=30.0,
                    height_mm=20.0,
                    count_x=2,
                    count_y=2,
                )
            ],
        )
        result = generate_panel(config)
        svg = render_panel_svg(result)
        assert svg.startswith("<svg")
        assert "</svg>" in svg
        assert "preview-panel" in svg
        assert "test_board" in svg

    def test_consolidate_panel_bom(self) -> None:
        config = PanelConfig(
            name="bom-test-panel",
            boards=[
                BoardInstance(
                    board_id="board_a",
                    width_mm=20.0,
                    height_mm=20.0,
                    count_x=2,
                    count_y=2,  # 4 boards
                )
            ],
        )
        result = generate_panel(config)
        board_boms = {
            "board_a": [
                {"mpn": "RC0402FR-0710KL", "value": "10k", "footprint": "0402", "quantity": 2, "ref": "R1"},
                {"mpn": "ESP32-C3", "value": "ESP32", "footprint": "QFN-32", "quantity": 1, "ref": "U1"},
            ]
        }
        consolidated = consolidate_panel_bom(result, board_boms)
        assert len(consolidated) == 2
        r_item = next(it for it in consolidated if it["value"] == "10k")
        # 2 per board * 4 boards = 8
        assert r_item["quantity"] == 8
        assert len(r_item["refs"]) == 4

    def test_render_vscore_panel_svg(self) -> None:
        config = PanelConfig(
            name="vscore-svg-panel",
            panel_width_mm=120.0,
            panel_height_mm=100.0,
            separation=PanelSeparationMethod.V_SCORE,
            boards=[
                BoardInstance(
                    board_id="b1",
                    width_mm=30.0,
                    height_mm=30.0,
                    count_x=2,
                    count_y=2,
                )
            ],
        )
        result = generate_panel(config)
        svg = render_panel_svg(result)
        assert "vscore" in svg
        assert "V-Score X=" in svg
        assert "V-Score Y=" in svg
        assert "tooling" in svg
        assert "fiducial" in svg
