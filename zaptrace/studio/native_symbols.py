"""Source-checked native KiCad library artwork for an allowlist of components.

The original local KiCad S-expression library supplies symbol shapes and pin
identities. Source YAML supplies the visible net assignment. Neither is an
electrical verification, and unmatched mappings never gain a native badge.
No shell, downloaded artwork, or new XML parser is involved.
"""

from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from zaptrace.io.sexp import SexpNode, parse

# Stable identifiers, not filesystem paths or user-supplied library names.
_LIBRARY_IDS = {
    "R": ("Device", "R"),
    "C": ("Device", "C"),
    "RF_Module.ESP32-WROOM-32": ("RF_Module", "ESP32-WROOM-32"),
    "Sensor.BME280": ("Sensor", "BME280"),
    "Regulator_Linear.AMS1117-3.3": ("Regulator_Linear", "AMS1117-3.3"),
}
KNOWN_NATIVE_SYMBOLS = frozenset(_LIBRARY_IDS)

_TYPES = {
    "RES": "R",
    "CAP": "C",
    "ESP32-WROOM-32": "RF_Module.ESP32-WROOM-32",
    "BME280": "Sensor.BME280",
    "AMS1117-3.3": "Regulator_Linear.AMS1117-3.3",
}
# Verified differences between sample logical names and *installed* KiCad pin names.
_ALIASES = {
    "RF_Module.ESP32-WROOM-32": {"GPIO21": "IO21", "GPIO22": "IO22", "VCC": "VDD"},
    "Sensor.BME280": {"SDA": "SDI"},
    "Regulator_Linear.AMS1117-3.3": {"INPUT": "VI", "OUTPUT": "VO"},
}


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


def _read_symbol(source: str, name: str) -> list[list[SexpNode]] | None:
    root = parse(source)
    symbols = [entry for entry in _entries(root, "symbol") if len(entry) > 1 and entry[1] == name]
    if len(symbols) != 1:
        return None
    chosen = symbols[0]
    inherits = _entries(chosen, "extends")
    if inherits:
        if len(inherits) != 1 or len(inherits[0]) != 2 or _entries(chosen, "symbol"):
            return None
        base = inherits[0][1]
        if not isinstance(base, str):
            return None
        ancestors = [entry for entry in _entries(root, "symbol") if len(entry) > 1 and entry[1] == base]
        if len(ancestors) != 1 or _entries(ancestors[0], "extends"):
            return None
        chosen = ancestors[0]
    units = _entries(chosen, "symbol")
    return units if 0 < len(units) <= 8 else None


@lru_cache(maxsize=5)
def _installed_units(symbol: str) -> list[list[SexpNode]] | None:
    item = _LIBRARY_IDS.get(symbol)
    if item is None:
        return None
    directory = os.environ.get("KICAD10_SYMBOL_DIR") or os.environ.get("KICAD_SYMBOL_DIR") or "/usr/share/kicad/symbols"
    library = Path(directory) / (item[0] + ".kicad_sym")
    if not library.is_file() or library.stat().st_size > 6_000_000:
        return None
    try:
        return _read_symbol(library.read_text(encoding="utf-8"), item[1])
    except (OSError, UnicodeError, ValueError):
        return None


def _pins_from_units(units: list[list[SexpNode]]) -> dict[str, str] | None:
    pins: dict[str, str] = {}
    for unit in units:
        for pin in _entries(unit, "pin"):
            numbers, names = _entries(pin, "number"), _entries(pin, "name")
            if len(numbers) != 1 or len(numbers[0]) < 2 or len(names) > 1:
                return None
            if names and len(names[0]) < 2:
                return None
            pad = numbers[0][1]
            label = names[0][1] if names else ""
            if not isinstance(pad, str) or not isinstance(label, str) or pad in pins or len(pad) > 12:
                return None
            pins[pad] = label
    return pins if 0 < len(pins) <= 64 else None


def native_match(component_type: str, mapping: dict[str, str]) -> dict[str, Any] | None:
    """Match every source-assigned package pad to actual local KiCad pin data."""
    symbol = _TYPES.get(component_type)
    if symbol is None or not mapping:
        return None
    units = _installed_units(symbol)
    if units is None:
        return None
    pins = _pins_from_units(units)
    if pins is None or len(mapping) > len(pins):
        return None
    matches = []
    aliases = _ALIASES.get(symbol, {})
    for pad, logical in sorted(mapping.items(), key=lambda item: int(item[0]) if item[0].isdigit() else -1):
        library_name = pins.get(pad)
        expected = (
            ("P" + pad if symbol in {"R", "C"} else aliases.get(logical, logical)) if isinstance(logical, str) else None
        )
        if library_name is None or expected is None:
            return None
        invalid_passive = symbol in {"R", "C"} and (pad not in {"1", "2"} or logical != expected or bool(library_name))
        invalid_active = symbol not in {"R", "C"} and library_name != expected
        if invalid_passive or invalid_active:
            return None
        matches.append({"pad": pad, "source_pin": logical, "library_pin": library_name or expected})
    if symbol in {"R", "C"} and len(matches) != 2:
        return None
    return {
        "id": symbol,
        "library": _LIBRARY_IDS[symbol][0],
        "symbol": _LIBRARY_IDS[symbol][1],
        "mapped_pads": len(matches),
        "library_pins": len(pins),
        "matches": matches,
    }


def _render_units(units: list[list[SexpNode]]) -> bytes | None:
    pins = _pins_from_units(units)
    if pins is None:
        return None
    shapes: list[str] = []
    coords: list[tuple[float, float]] = []
    try:
        for unit in units:
            for item in unit:
                if not isinstance(item, list) or not item:
                    continue
                if item[0] == "rectangle":
                    start, end = _entries(item, "start"), _entries(item, "end")
                    if len(start) != 1 or len(end) != 1:
                        return None
                    x1, y1 = _number(start[0][1]), -_number(start[0][2])
                    x2, y2 = _number(end[0][1]), -_number(end[0][2])
                    coords.extend(((x1, y1), (x2, y2)))
                    shapes.append(
                        f'<rect x="{_fmt(min(x1, x2))}" y="{_fmt(min(y1, y2))}" '
                        f'width="{_fmt(abs(x2 - x1))}" height="{_fmt(abs(y2 - y1))}" />'
                    )
                elif item[0] == "polyline":
                    groups = _entries(item, "pts")
                    if len(groups) != 1:
                        return None
                    points = [(_number(x[1]), -_number(x[2])) for x in _entries(groups[0], "xy")]
                    if len(points) < 2 or len(points) > 50:
                        return None
                    coords.extend(points)
                    shapes.append('<polyline points="' + " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in points) + '" />')
                elif item[0] == "pin":
                    at, lengths = _entries(item, "at"), _entries(item, "length")
                    if len(at) != 1 or len(lengths) != 1:
                        return None
                    x, y = _number(at[0][1]), -_number(at[0][2])
                    angle, span = at[0][3], _number(lengths[0][1])
                    if angle not in {"0", "90", "180", "270"} or not 0 < span < 12:
                        return None
                    end_x = x + (span if angle == "0" else -span if angle == "180" else 0)
                    end_y = y + (span if angle == "270" else -span if angle == "90" else 0)
                    coords.extend(((x, y), (end_x, end_y)))
                    shapes.append(f'<line x1="{_fmt(x)}" y1="{_fmt(y)}" x2="{_fmt(end_x)}" y2="{_fmt(end_y)}" />')
    except (TypeError, ValueError, IndexError):
        return None
    if not coords or len(shapes) > 128:
        return None
    xmin, xmax = min(x for x, _ in coords) - 0.6, max(x for x, _ in coords) + 0.6
    ymin, ymax = min(y for _, y in coords) - 0.6, max(y for _, y in coords) + 0.6
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{_fmt(xmin)} {_fmt(ymin)} {_fmt(xmax - xmin)} {_fmt(ymax - ymin)}">'
        '<g fill="none" stroke="#000" stroke-width="0.23" '
        'stroke-linecap="round" stroke-linejoin="round">' + "".join(shapes) + "</g></svg>"
    )
    return svg.encode("utf-8")


def _render_native_svg(library_source: str, symbol_name: str) -> bytes | None:
    """Legacy Device:R/C unit test helper: same safe native shape renderer."""
    if symbol_name not in {"R", "C"}:
        return None
    units = _read_symbol(library_source, symbol_name)
    if units is None:
        return None
    pins = _pins_from_units(units)
    if pins is None or set(pins) != {"1", "2"}:
        return None
    return _render_units(units)


@lru_cache(maxsize=5)
def native_svg_for(symbol: str) -> bytes | None:
    """Return an SVG derived solely from fixed locally installed library IDs."""
    units = _installed_units(symbol)
    if units is None:
        return None
    pins = _pins_from_units(units)
    if pins is None or (symbol in {"R", "C"} and set(pins) != {"1", "2"}):
        return None
    return _render_units(units)
