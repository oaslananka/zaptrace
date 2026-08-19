"""Characterization coverage for Excellon hole collection and rendering."""

from zaptrace.core.models import (
    BoardDefinition,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    MountingHole,
    Pad,
    RouteResult,
)
from zaptrace.export.excellon import _collect_drill_holes, _render_drill_file


def test_collect_drill_holes_preserves_source_order_and_plating() -> None:
    design = Design(
        meta=DesignMeta(name="HelperCoverage"),
        components={
            "j1": Component(
                id="j1",
                ref="J1",
                type="connector",
                position=(10.0, 20.0),
                footprint_def=FootprintDef(
                    pads=[
                        Pad(id="1", position=(1.0, 2.0), drill=0.8, plated=True),
                        Pad(id="2", position=(-1.0, 0.5), drill=1.0, plated=False),
                        Pad(id="3", position=(0.0, 0.0), drill=None),
                        Pad(id="4", position=(0.0, 0.0), drill=0.0),
                    ]
                ),
            ),
            "unplaced": Component(
                id="unplaced",
                ref="J2",
                type="connector",
                footprint_def=FootprintDef(pads=[Pad(id="1", drill=2.0)]),
            ),
            "no-footprint": Component(
                id="no-footprint",
                ref="J3",
                type="connector",
                position=(1.0, 1.0),
            ),
        },
        board_def=BoardDefinition(
            mounting_holes=[
                MountingHole(position=(3.0, 4.0), diameter=2.5, plated=True),
                MountingHole(position=(5.0, 6.0), diameter=3.0, plated=False),
            ]
        ),
        routing=RouteResult(vias=[(7.0, 8.0, 0.45, 0.2), (9.0, 10.0, 0.5, 0.25, "N1")]),
    )

    assert _collect_drill_holes(design) == [
        (11.0, 22.0, 0.8, True),
        (9.0, 20.5, 1.0, False),
        (3.0, 4.0, 2.5, True),
        (5.0, 6.0, 3.0, False),
        (7.0, 8.0, 0.2, True),
        (9.0, 10.0, 0.25, True),
    ]


def test_render_drill_file_preserves_tool_and_coordinate_order() -> None:
    content = _render_drill_file(
        [(2.0, 3.0, 1.0), (1.0, 1.0, 0.8), (4.0, 5.0, 0.8)],
        filename="demo.DRL",
        leader="ZapTrace generated Excellon drill file",
    )

    assert content == (
        "M48\n"
        "; ZapTrace generated Excellon drill file\n"
        ";FILE=demo.DRL\n"
        "METRIC,TZ\n"
        "%\n"
        "T01C0.8000\n"
        "T02C1.0000\n"
        "T01\n"
        "X1000000Y1000000\n"
        "X4000000Y5000000\n"
        "T02\n"
        "X2000000Y3000000\n"
        "M30\n"
    )
