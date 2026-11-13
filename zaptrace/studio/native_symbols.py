"""Render allowlisted installed KiCad Device library shapes without shell or XML.

These are native KiCad library primitives with an explicit source-defined
P1/P2 mapping; they are not independently verified physical pinouts.
"""

from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path

from zaptrace.io.sexp import SexpNode, parse

_SUPPORTED = frozenset({"R", "C"})


def _entries(node: SexpNode, kind: str) -> list[list[SexpNode]]:
    if not isinstance(node, list):
        return []
    return [entry for entry in node if isinstance(entry, list) and entry and entry[0] == kind]


def _number(raw: SexpNode) -> float:
    value = float(raw) if isinstance(raw, str) else float("nan")
    if not math.isfinite(value) or abs(value) > 100:
        raise ValueError("Invalid native KiCad symbol coordinate")
    return value


def _fmt(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def _render_native_svg(library_source: str, symbol_name: str) -> bytes | None:
    """Render only R/C rectangle, polyline and two verified 1/2 line pins."""
    if symbol_name not in _SUPPORTED:
        return None
    root = parse(library_source)
    symbols = [entry for entry in _entries(root, "symbol") if len(entry) > 1 and entry[1] == symbol_name]
    if len(symbols) != 1:
        return None
    shapes: list[str] = []
    points: list[tuple[float, float]] = []
    pins: set[str] = set()
    try:
        for unit in _entries(symbols[0], "symbol"):
            for item in unit:
                if not isinstance(item, list) or not item:
                    continue
                if item[0] == "rectangle":
                    start = _entries(item, "start")
                    end = _entries(item, "end")
                    if len(start) != 1 or len(end) != 1:
                        return None
                    x1, y1 = _number(start[0][1]), -_number(start[0][2])
                    x2, y2 = _number(end[0][1]), -_number(end[0][2])
                    left, top = min(x1, x2), min(y1, y2)
                    width, height = abs(x2 - x1), abs(y2 - y1)
                    points.extend(((x1, y1), (x2, y2)))
                    shapes.append(
                        f'<rect x="{_fmt(left)}" y="{_fmt(top)}" width="{_fmt(width)}" height="{_fmt(height)}" />'
                    )
                elif item[0] == "polyline":
                    groups = _entries(item, "pts")
                    if len(groups) != 1:
                        return None
                    coords: list[tuple[float, float]] = []
                    for xy in _entries(groups[0], "xy"):
                        coords.append((_number(xy[1]), -_number(xy[2])))
                    if len(coords) < 2:
                        return None
                    points.extend(coords)
                    joined = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in coords)
                    shapes.append(f'<polyline points="{joined}" />')
                elif item[0] == "pin":
                    at = _entries(item, "at")
                    length = _entries(item, "length")
                    number = _entries(item, "number")
                    if len(at) != 1 or len(length) != 1 or len(number) != 1:
                        return None
                    value = number[0][1]
                    if value not in {"1", "2"} or value in pins:
                        return None
                    pins.add(value)
                    x = _number(at[0][1])
                    y = -_number(at[0][2])
                    angle = at[0][3]
                    span = _number(length[0][1])
                    if angle not in {"90", "270"} or not 0 < span < 12:
                        return None
                    # KiCad pin angles: 270 points from the top toward the body,
                    # 90 points from the bottom toward the body.
                    end_y = y + (span if angle == "270" else -span)
                    points.extend(((x, y), (x, end_y)))
                    shapes.append(f'<line x1="{_fmt(x)}" y1="{_fmt(y)}" x2="{_fmt(x)}" y2="{_fmt(end_y)}" />')
    except (TypeError, ValueError, IndexError):
        return None
    if pins != {"1", "2"} or not points or len(shapes) > 12:
        return None
    xmin = min(x for x, _ in points) - 0.5
    xmax = max(x for x, _ in points) + 0.5
    ymin = min(y for _, y in points) - 0.5
    ymax = max(y for _, y in points) + 0.5
    width, height = xmax - xmin, ymax - ymin
    rendered = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{_fmt(xmin)} {_fmt(ymin)} {_fmt(width)} {_fmt(height)}">'
        '<g fill="none" stroke="#000" stroke-width="0.23" '
        'stroke-linecap="round" stroke-linejoin="round">' + "".join(shapes) + "</g></svg>"
    )
    return rendered.encode("utf-8")


@lru_cache(maxsize=2)
def native_svg_for(symbol: str) -> bytes | None:
    """Read only the installed KiCad Device library; do not vendor its assets."""
    if symbol not in _SUPPORTED:
        return None
    symbol_dir = (
        os.environ.get("KICAD10_SYMBOL_DIR") or os.environ.get("KICAD_SYMBOL_DIR") or "/usr/share/kicad/symbols"
    )
    library = Path(symbol_dir) / "Device.kicad_sym"
    if not library.is_file() or library.stat().st_size > 6_000_000:
        return None
    try:
        return _render_native_svg(library.read_text(encoding="utf-8"), symbol)
    except (OSError, UnicodeError, ValueError):
        return None
