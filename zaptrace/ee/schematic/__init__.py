"""Schematic engine — symbol generation, auto-placement, and SVG rendering."""

from __future__ import annotations

from zaptrace.ee.schematic.engine import SchematicEngine, render_schematic_svg
from zaptrace.ee.schematic.symbols import generate_symbol

__all__ = [
    "SchematicEngine",
    "generate_symbol",
    "render_schematic_svg",
]
