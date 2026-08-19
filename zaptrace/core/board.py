"""Canonical board-model access helpers.

``Design.board_def`` is the canonical board model for geometry and
manufacturing constraints. ``Design.board`` remains a legacy compatibility
source for older YAML files and API calls.
"""

from __future__ import annotations

from zaptrace.core.models import BoardDefinition, Design


def canonical_board_definition(design: Design) -> BoardDefinition:
    """Return a canonical ``BoardDefinition`` for *design*.

    Existing ``design.board_def`` wins. Legacy ``design.board`` is converted at
    the boundary so downstream exporters/checkers do not need to branch on both
    models.
    """
    if design.board_def is not None:
        return design.board_def
    board = design.board
    return BoardDefinition(width=board.width_mm, height=board.height_mm, layers=board.layers)


def sync_legacy_board_from_definition(design: Design) -> None:
    """Mirror canonical board dimensions into the legacy ``Design.board`` field."""
    bd = canonical_board_definition(design)
    design.board.width_mm = bd.width
    design.board.height_mm = bd.height
    design.board.layers = bd.layers
