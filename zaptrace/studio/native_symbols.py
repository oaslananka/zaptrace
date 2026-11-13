"""Optional KiCad 10 installed-library symbol SVG for source-mapped passives.

Only fixed KiCad Device:R and Device:C identifiers are ever exported. The
native diagram is a reference drawing, not board/copper or ERC/DRC evidence.
No user-provided program, symbol name, or filesystem path enters a command.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

_SVG_NS = "http://www.w3.org/2000/svg"
_ALLOWED_TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}
_ALLOWED_ATTRIBUTES = {
    "xmlns",
    "version",
    "width",
    "height",
    "viewBox",
    "transform",
    "style",
    "class",
    "d",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "points",
    "fill",
    "stroke",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "fill-opacity",
    "stroke-opacity",
}
_SYMBOLS = {"R": "R", "C": "C"}


def _svg_element_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _sanitize_cli_svg(raw: bytes) -> bytes | None:
    """Retain only KiCad-rendered shape geometry and safe SVG attributes."""
    if len(raw) > 128_000 or b"<!ENTITY" in raw or b"<script" in raw.lower():
        return None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    if _svg_element_name(root.tag) != "svg":
        return None

    def clean(element: ET.Element) -> None:
        for child in list(element):
            name = _svg_element_name(child.tag)
            if name not in _ALLOWED_TAGS or child.get("class") == "stroked-text":
                element.remove(child)
            else:
                clean(child)
        for key in list(element.attrib):
            if _svg_element_name(key) not in _ALLOWED_ATTRIBUTES or "url(" in element.attrib[key].lower():
                del element.attrib[key]

    clean(root)
    ET.register_namespace("", _SVG_NS)
    return ET.tostring(root, encoding="utf-8", xml_declaration=False)


@lru_cache(maxsize=2)
def native_svg_for(symbol: str) -> bytes | None:
    """Export one allowlisted symbol if KiCad and its local Device library exist."""
    if symbol not in _SYMBOLS:
        return None
    command = shutil.which("kicad-cli")
    symbol_dir = (
        os.environ.get("KICAD10_SYMBOL_DIR") or os.environ.get("KICAD_SYMBOL_DIR") or "/usr/share/kicad/symbols"
    )
    library = Path(symbol_dir) / "Device.kicad_sym"
    if not command or not library.is_file():
        return None
    with tempfile.TemporaryDirectory(prefix="zaptrace-symbol-") as temporary:
        try:
            subprocess.run(
                [
                    command,
                    "sym",
                    "export",
                    "svg",
                    "--symbol",
                    _SYMBOLS[symbol],
                    "--black-and-white",
                    "--output",
                    temporary,
                    str(library),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=9,
            )
            exported = Path(temporary) / f"{symbol}_unit1.svg"
            if not exported.is_file() or exported.stat().st_size > 128_000:
                return None
            return _sanitize_cli_svg(exported.read_bytes())
        except (OSError, subprocess.SubprocessError):
            return None
