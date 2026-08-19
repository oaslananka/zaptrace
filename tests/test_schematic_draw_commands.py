"""Characterization tests for schematic SVG draw commands."""

from __future__ import annotations

import pytest

from zaptrace.core.models import DrawCommand
from zaptrace.ee.schematic.engine import _draw_command_to_svg, _line_command_to_svg


def test_line_renderer_preserves_offsets_defaults_and_class() -> None:
    assert _line_command_to_svg({"x1": 1, "y1": 2, "x2": 3, "y2": 4}, 10, 20, "sym-body") == (
        '<line class="sym-body" x1="11.0" y1="22.0" x2="13.0" y2="24.0" stroke="#222"/>'
    )


@pytest.mark.parametrize(
    ("command", "cx", "cy", "expected"),
    [
        (
            DrawCommand(type="line", params={"x1": 1, "y1": 2, "x2": 3, "y2": 4, "fill": "white"}),
            10,
            20,
            '<line class="sym-fill" x1="11.0" y1="22.0" x2="13.0" y2="24.0" stroke="#222"/>',
        ),
        (
            DrawCommand(type="rect", params={"x": -1, "y": 2, "width": 8, "height": 9, "stroke": "red"}),
            3,
            4,
            '<rect x="2.0" y="6.0" width="8.0" height="9.0" stroke="red" fill="none"/>',
        ),
        (
            DrawCommand(type="circle", params={"cx": 1, "cy": -2, "radius": 7, "fill": "blue"}),
            3,
            4,
            '<circle cx="4.0" cy="2.0" r="7.0" stroke="#222" fill="blue"/>',
        ),
        (
            DrawCommand(type="text", params={"x": 1, "y": 2, "text": '<A&B>"', "font_size": 9}),
            3,
            4,
            '<text x="4.0" y="6.0" font-size="9" fill="#222">&lt;A&amp;B&gt;"</text>',
        ),
        (
            DrawCommand(type="polygon", params={"points": [(0, 0), (1.25, -2)], "fill": "white"}),
            3,
            4,
            '<polygon class="sym-fill" points="3.0,4.0 4.2,2.0" fill="white" stroke="#222"/>',
        ),
        (DrawCommand(type="polygon", params={"points": []}), 3, 4, ""),
        (DrawCommand(type="arc", params={"radius": 0}), 3, 4, ""),
        (DrawCommand(type="unknown", params={"x": 1}), 3, 4, ""),
    ],
)
def test_draw_command_svg_preserves_existing_primitive_contracts(
    command: DrawCommand,
    cx: float,
    cy: float,
    expected: str,
) -> None:
    assert _draw_command_to_svg(command, cx, cy) == expected


def test_positive_arc_renders_path_and_degenerate_arc_is_empty() -> None:
    rendered = _draw_command_to_svg(
        DrawCommand(type="arc", params={"x1": 0, "y1": 0, "x2": 10, "y2": 0, "radius": 10}),
        0,
        0,
    )
    assert rendered.startswith('<path class="sym-body" d="')
    assert rendered.endswith("/>")

    degenerate = DrawCommand(type="arc", params={"x1": 2, "y1": 3, "x2": 2, "y2": 3, "radius": 5})
    assert _draw_command_to_svg(degenerate, 0, 0) == ""
