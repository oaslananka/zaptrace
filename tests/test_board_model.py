from __future__ import annotations

from zaptrace.core.board import canonical_board_definition, sync_legacy_board_from_definition
from zaptrace.core.models import BoardConfig, BoardDefinition, Design, DesignMeta


def test_canonical_board_definition_prefers_board_def() -> None:
    design = Design(
        meta=DesignMeta(name="BoardCanonical"),
        board=BoardConfig(width_mm=10, height_mm=20, layers=2),
        board_def=BoardDefinition(width=30, height=40, layers=4),
    )
    board = canonical_board_definition(design)
    assert board.width == 30
    assert board.height == 40
    assert board.layers == 4


def test_canonical_board_definition_converts_legacy_board_config() -> None:
    design = Design(meta=DesignMeta(name="LegacyBoard"), board=BoardConfig(width_mm=11, height_mm=22, layers=2))
    board = canonical_board_definition(design)
    assert board.width == 11
    assert board.height == 22
    assert board.layers == 2


def test_sync_legacy_board_from_definition() -> None:
    design = Design(meta=DesignMeta(name="SyncBoard"), board_def=BoardDefinition(width=55, height=44, layers=6))
    sync_legacy_board_from_definition(design)
    assert design.board.width_mm == 55
    assert design.board.height_mm == 44
    assert design.board.layers == 6
