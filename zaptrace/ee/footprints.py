"""Parametric footprint and symbol generators for common package types.

Every generator produces a ``FootprintDef`` (or ``SymbolDef``) that can be
attached to a ``Component`` and used downstream by the PCB / schematic engines.
"""

from __future__ import annotations

from typing import Any

from zaptrace.core.models import (
    DrawCommand,
    FootprintDef,
    LayerSet,
    Pad,
    PadShape,
    SymbolDef,
    SymbolPin,
)

# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _chip_pads(
    count: int,
    pitch: float,
    width: float,
    height: float,
    layer: LayerSet = LayerSet.TOP,
) -> list[Pad]:
    """Generate pads for a two-row chip component (resistor, capacitor, etc.)."""
    pads: list[Pad] = []
    y_span = (count // 2 - 1) * pitch
    for i in range(count // 2):
        y = -y_span / 2 + i * pitch
        pads.append(
            Pad(id=f"{i + 1}", layer=layer, shape=PadShape.RECT, position=(-pitch / 2, y), size=(width, height))
        )
    for i in range(count // 2):
        y = -y_span / 2 + i * pitch
        pads.append(
            Pad(id=f"{count - i}", layer=layer, shape=PadShape.RECT, position=(pitch / 2, y), size=(width, height))
        )
    return pads


def _make_outline(w: float, h: float) -> list[DrawCommand]:
    dw, dh = w / 2, h / 2
    return [
        DrawCommand(type="rect", params={"x": -dw, "y": -dh, "width": w, "height": h}),
    ]


# ---------------------------------------------------------------------------
#  Chip Resistor / Capacitor (2-pad)
# ---------------------------------------------------------------------------

# IPC-7351B dimensions (mm): (code, L, W, T, pad_w, pad_h, pad_gap)
_CHIP_DIMENSIONS: dict[str, tuple[float, float, float, float, float, float]] = {
    "0402": (1.0, 0.5, 0.35, 0.6, 0.7, 0.5),
    "0603": (1.6, 0.8, 0.45, 0.9, 1.0, 0.7),
    "0805": (2.0, 1.25, 0.5, 1.2, 1.4, 0.9),
    "1206": (3.2, 1.6, 0.55, 1.8, 1.6, 1.5),
    "1210": (3.2, 2.5, 0.55, 1.8, 2.6, 1.5),
    "1812": (4.5, 3.2, 0.6, 2.8, 3.3, 2.2),
    "2010": (5.0, 2.5, 0.6, 2.8, 2.6, 2.8),
    "2512": (6.4, 3.2, 0.6, 3.2, 3.3, 3.6),
}

_SOT_TH_DIMENSIONS: dict[str, tuple[int, float, float, float]] = {
    # (pins, pitch, pw, ph)
    "SOT-23": (3, 0.95, 0.6, 0.6),
    "SOT-23-3": (3, 0.95, 0.6, 0.6),
    "SOT-23-5": (5, 0.95, 0.6, 0.6),
    "SOT-23-6": (6, 0.95, 0.6, 0.6),
    "SOT-89": (4, 1.5, 0.8, 0.8),
    "SOT-223": (4, 2.3, 0.7, 0.9),
    "SOT-323": (3, 0.65, 0.4, 0.5),
    "SOT-363": (6, 0.65, 0.4, 0.5),
}

_IC_DIMENSIONS: dict[str, tuple[float, float, float, int]] = {
    # (body_w, body_h, pitch, pin_count)
    "SOIC-8": (3.9, 4.9, 1.27, 8),
    "SOIC-14": (3.9, 8.7, 1.27, 14),
    "SOIC-16": (3.9, 9.9, 1.27, 16),
    "SOIC-20": (7.5, 12.8, 1.27, 20),
    "TSSOP-8": (3.0, 3.0, 0.65, 8),
    "TSSOP-14": (4.4, 5.0, 0.65, 14),
    "TSSOP-16": (4.4, 5.0, 0.65, 16),
    "TSSOP-20": (4.4, 6.5, 0.65, 20),
    "TSSOP-28": (4.4, 9.7, 0.65, 28),
    "MSOP-8": (3.0, 3.0, 0.65, 8),
    "MSOP-10": (3.0, 3.0, 0.5, 10),
    "QFN-16": (3.0, 3.0, 0.5, 16),
    "QFN-20": (4.0, 4.0, 0.5, 20),
    "QFN-28": (4.0, 4.0, 0.5, 28),
    "QFN-32": (5.0, 5.0, 0.5, 32),
    "QFN-48": (7.0, 7.0, 0.5, 48),
    "QFN-56": (7.0, 7.0, 0.4, 56),
    "QFP-32": (7.0, 7.0, 0.8, 32),
    "LQFP-48": (7.0, 7.0, 0.5, 48),
    "LQFP-64": (10.0, 10.0, 0.5, 64),
    "LQFP-100": (14.0, 14.0, 0.5, 100),
    "QFP-44": (10.0, 10.0, 0.8, 44),
    "QFP-64": (10.0, 10.0, 0.5, 64),
    "QFP-100": (14.0, 14.0, 0.5, 100),
    "QFP-144": (20.0, 20.0, 0.5, 144),
    "DIP-8": (6.35, 9.27, 2.54, 8),
    "DIP-14": (6.35, 17.78, 2.54, 14),
    "DIP-16": (6.35, 19.05, 2.54, 16),
    "DIP-20": (6.35, 24.13, 2.54, 20),
    "DIP-28": (13.97, 34.04, 2.54, 28),
}

_DFN_DIMENSIONS: dict[str, tuple[float, float, float, int]] = {
    # (body_w, body_h, pitch, pin_count)
    "DFN-6": (2.0, 2.0, 0.65, 6),
    "DFN-8": (2.0, 3.0, 0.5, 8),
    "DFN-8-3X3": (3.0, 3.0, 0.65, 8),
    "DFN-10": (3.0, 3.0, 0.5, 10),
    "DFN-12": (3.0, 3.0, 0.45, 12),
    "DFN-14": (3.0, 4.0, 0.5, 14),
}

_BGA_DIMENSIONS: dict[str, tuple[int, int, float, float]] = {
    # (rows, cols, pitch, ball_diameter)
    "BGA-48": (6, 8, 0.8, 0.4),
    "BGA-64": (8, 8, 0.8, 0.4),
    "BGA-96": (8, 12, 0.8, 0.4),
    "BGA-100": (10, 10, 0.8, 0.4),
    "BGA-144": (12, 12, 0.8, 0.4),
    "BGA-256": (16, 16, 0.8, 0.4),
}

_WLCSP_DIMENSIONS: dict[str, tuple[int, int, float, float]] = {
    # (rows, cols, pitch, pad_diameter)
    "WLCSP-4": (2, 2, 0.4, 0.22),
    "WLCSP-6": (2, 3, 0.4, 0.22),
    "WLCSP-9": (3, 3, 0.4, 0.22),
    "WLCSP-12": (3, 4, 0.4, 0.22),
    "WLCSP-16": (4, 4, 0.4, 0.22),
    "WLCSP-20": (4, 5, 0.4, 0.22),
    "WLCSP-25": (5, 5, 0.4, 0.22),
}

_BGA_ROW_LETTERS: list[str] = [
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "J",
    "K",
    "L",
    "M",
    "N",
    "P",
    "R",
    "T",
    "U",
    "V",
    "W",
    "Y",
    "AA",
    "AB",
    "AC",
    "AD",
    "AE",
    "AF",
]


def _grid_pads(
    *,
    rows: int,
    cols: int,
    pitch: float,
    diameter: float,
    layer: LayerSet,
) -> tuple[list[Pad], float, float]:
    """Build a JEDEC-style grid of circular pads and return its spans."""
    pads: list[Pad] = []
    x_span = (cols - 1) * pitch
    y_span = (rows - 1) * pitch
    for row_index in range(rows):
        row_letter = _BGA_ROW_LETTERS[row_index] if row_index < len(_BGA_ROW_LETTERS) else f"R{row_index + 1}"
        y = y_span / 2 - row_index * pitch
        for column_index in range(cols):
            x = -x_span / 2 + column_index * pitch
            pads.append(
                Pad(
                    id=f"{row_letter}{column_index + 1}",
                    layer=layer,
                    shape=PadShape.CIRCLE,
                    position=(x, y),
                    size=(diameter, diameter),
                )
            )
    return pads, x_span, y_span


# Package alias map (user-friendly → canonical)
_PACKAGE_ALIASES: dict[str, str] = {
    # Resistor / capacitor packages
    "r0402": "0402",
    "c0402": "0402",
    "r0603": "0603",
    "c0603": "0603",
    "r0805": "0805",
    "c0805": "0805",
    "r1206": "1206",
    "c1206": "1206",
    "r2512": "2512",
    # IC packages
    "so8": "SOIC-8",
    "soic8": "SOIC-8",
    "so14": "SOIC-14",
    "soic14": "SOIC-14",
    "so16": "SOIC-16",
    "soic16": "SOIC-16",
    "tssop8": "TSSOP-8",
    "tssop14": "TSSOP-14",
    "tssop16": "TSSOP-16",
    "tssop20": "TSSOP-20",
    "msop8": "MSOP-8",
    "dfn6": "DFN-6",
    "dfn8": "DFN-8",
    "dfn10": "DFN-10",
    "qfn16": "QFN-16",
    "qfn32": "QFN-32",
    "qfn48": "QFN-48",
    "qfp32": "QFP-32",
    "qfp44": "QFP-44",
    "qfp64": "QFP-64",
    "dip8": "DIP-8",
    "dip14": "DIP-14",
    "dip16": "DIP-16",
    "dip28": "DIP-28",
    "sot23": "SOT-23",
    "bga48": "BGA-48",
    "bga64": "BGA-64",
    "bga96": "BGA-96",
    "wlcsp4": "WLCSP-4",
    "wlcsp16": "WLCSP-16",
}


def footprint_chip(package: str, layer: LayerSet = LayerSet.TOP) -> FootprintDef | None:
    """Generate a chip (2-pad SMD) footprint for a given IPC package code."""
    dims = _CHIP_DIMENSIONS.get(package.upper())
    if dims is None:
        return None
    L, W, _T, pad_w, pad_h, pad_gap = dims  # noqa: E741
    pad_center_offset = (pad_w + pad_gap) / 2.0
    pads = [
        Pad(id="1", layer=layer, shape=PadShape.RECT, position=(-pad_center_offset, 0.0), size=(pad_w, pad_h)),
        Pad(id="2", layer=layer, shape=PadShape.RECT, position=(pad_center_offset, 0.0), size=(pad_w, pad_h)),
    ]
    outline = _make_outline(L + 0.4, W + 0.4)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(L + 1.0, W + 1.0),
        description=f"Chip {package} footprint (IPC-7351B)",
        source="IPC-7351B",
    )


def footprint_sot(code: str, layer: LayerSet = LayerSet.TOP) -> FootprintDef | None:
    """Generate SOT-x package footprint."""
    dims = _SOT_TH_DIMENSIONS.get(code.upper())
    if dims is None:
        return None
    pin_count, pitch, pw, ph = dims
    # SOT has staggered pads: one row of 3 on each side
    pads: list[Pad] = []
    half = pin_count // 2
    for i in range(half):
        y = -(half - 1) * pitch / 2 + i * pitch
        pads.append(Pad(id=f"{i + 1}", layer=layer, shape=PadShape.RECT, position=(-pw / 2 - 0.5, y), size=(pw, ph)))
    for i in range(pin_count - half):
        y = -(pin_count - half - 1) * pitch / 2 + i * pitch
        pads.append(
            Pad(id=f"{pin_count - i}", layer=layer, shape=PadShape.RECT, position=(pw / 2 + 0.5, y), size=(pw, ph))
        )
    body_w = 1.6 if "89" in code else 1.3
    body_h = (pin_count // 2 - 1) * pitch + 1.0 if pin_count > 3 else 1.0
    outline = _make_outline(body_w, body_h)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(body_w + 1.0, body_h + 1.0),
        description=f"{code} footprint",
        source="IPC-7351B",
    )


def footprint_soic(
    package: str,
    layer: LayerSet = LayerSet.TOP,
) -> FootprintDef | None:
    """Generate SOIC / TSSOP / MSOP gull-wing footprint."""
    dims = _IC_DIMENSIONS.get(package.upper())
    if dims is None:
        return None
    body_w, body_h, pitch, pin_count = dims
    pads = _chip_pads(pin_count, pitch, 0.6, 1.6, layer=layer)
    outline = _make_outline(body_w + 0.6, body_h + 0.6)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(body_w + 1.5, body_h + 1.5),
        description=f"{package} footprint",
        source="IPC-7351B",
    )


def footprint_qfn(
    package: str,
    layer: LayerSet = LayerSet.TOP,
) -> FootprintDef | None:
    """Generate QFN (quad flat no-lead) footprint."""
    dims = _IC_DIMENSIONS.get(package.upper())
    if dims is None:
        return None
    body_w, body_h, pitch, pin_count = dims
    pads: list[Pad] = []
    pins_per_side = pin_count // 4
    pad_w, pad_l = 0.25, 0.8
    x_span = (pins_per_side - 1) * pitch
    y_span = (pins_per_side - 1) * pitch
    x_off = body_w / 2 + 0.05
    y_off = body_h / 2 + 0.05
    # Bottom row (pins 1..n)
    for i in range(pins_per_side):
        x = -x_span / 2 + i * pitch
        pads.append(Pad(id=f"{i + 1}", layer=layer, shape=PadShape.RECT, position=(x, -y_off), size=(pad_w, pad_l)))
    # Right column
    for i in range(pins_per_side):
        y = -y_span / 2 + i * pitch
        n = pins_per_side + i + 1
        pads.append(Pad(id=f"{n}", layer=layer, shape=PadShape.RECT, position=(x_off, y), size=(pad_l, pad_w)))
    # Top row (reversed)
    for i in range(pins_per_side):
        x = x_span / 2 - i * pitch
        n = 2 * pins_per_side + i + 1
        pads.append(Pad(id=f"{n}", layer=layer, shape=PadShape.RECT, position=(x, y_off), size=(pad_w, pad_l)))
    # Left column (reversed)
    for i in range(pins_per_side):
        y = y_span / 2 - i * pitch
        n = 3 * pins_per_side + i + 1
        pads.append(Pad(id=f"{n}", layer=layer, shape=PadShape.RECT, position=(-x_off, y), size=(pad_l, pad_w)))
    # Centre thermal pad
    centre_size = min(body_w, body_h) * 0.6
    pads.append(Pad(id="0", layer=layer, shape=PadShape.RECT, position=(0.0, 0.0), size=(centre_size, centre_size)))
    outline = _make_outline(body_w, body_h)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(body_w + 0.6, body_h + 0.6),
        thermal_pads=["0"],
        description=f"{package} footprint",
        source="IPC-7351B",
    )


def footprint_qfp(
    package: str,
    layer: LayerSet = LayerSet.TOP,
) -> FootprintDef | None:
    """Generate QFP (quad flat pack) footprint."""
    dims = _IC_DIMENSIONS.get(package.upper())
    if dims is None:
        return None
    body_w, body_h, pitch, pin_count = dims
    pads = _chip_pads(pin_count, pitch, 0.35, 1.8, layer=layer)
    outline = _make_outline(body_w + 0.8, body_h + 0.8)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(body_w + 2.0, body_h + 2.0),
        description=f"{package} footprint",
        source="IPC-7351B",
    )


def footprint_dip(
    package: str,
    layer: LayerSet = LayerSet.ALL,
) -> FootprintDef | None:
    """Generate DIP (dual inline package) through-hole footprint."""
    dims = _IC_DIMENSIONS.get(package.upper())
    if dims is None:
        return None
    body_w, body_h, pitch, pin_count = dims
    pads: list[Pad] = []
    y_span = (pin_count // 2 - 1) * pitch
    for i in range(pin_count // 2):
        y = -y_span / 2 + i * pitch
        pads.append(
            Pad(
                id=f"{i + 1}",
                layer=layer,
                shape=PadShape.OVAL,
                position=(-body_w / 2 - 0.5, y),
                size=(1.8, 0.8),
                drill=0.8,
                plated=True,
            )
        )
    for i in range(pin_count // 2):
        y = -y_span / 2 + i * pitch
        pads.append(
            Pad(
                id=f"{pin_count - i}",
                layer=layer,
                shape=PadShape.OVAL,
                position=(body_w / 2 + 0.5, y),
                size=(1.8, 0.8),
                drill=0.8,
                plated=True,
            )
        )
    outline = _make_outline(body_w, body_h)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(body_w + 3.0, body_h + 2.0),
        description=f"{package} footprint",
        source="IPC-7351B",
    )


def footprint_header(
    rows: int = 1,
    cols: int = 2,
    pitch: float = 2.54,
    layer: LayerSet = LayerSet.ALL,
) -> FootprintDef:
    """Generate a pin header footprint.

    Args:
        rows: Number of rows (1 or 2).
        cols: Number of pins per row.
        pitch: Pin pitch in mm.
    """
    pads: list[Pad] = []
    y_span = (cols - 1) * pitch
    for r in range(rows):
        for c in range(cols):
            x = r * pitch
            y = -y_span / 2 + c * pitch
            idx = c * rows + r + 1
            pads.append(
                Pad(
                    id=str(idx),
                    layer=layer,
                    shape=PadShape.OVAL,
                    position=(x, y),
                    size=(1.6, 1.6),
                    drill=0.8,
                    plated=True,
                )
            )
    body_w = (rows - 1) * pitch + 2.0
    body_h = (cols - 1) * pitch + 2.0
    outline = _make_outline(body_w, body_h)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(body_w + 1.0, body_h + 1.0),
        description=f"Pin header {rows}x{cols} ({pitch}mm)",
        source="generic",
    )


def footprint_usb_a(layer: LayerSet = LayerSet.ALL) -> FootprintDef:
    """USB Type-A through-hole footprint (4-pin)."""
    pads = [
        Pad(id="1", layer=layer, shape=PadShape.OVAL, position=(-3.5, -5.0), size=(1.6, 1.6), drill=1.0, plated=True),
        Pad(id="2", layer=layer, shape=PadShape.OVAL, position=(-3.5, 5.0), size=(1.6, 1.6), drill=1.0, plated=True),
        Pad(id="3", layer=layer, shape=PadShape.OVAL, position=(3.5, -5.0), size=(1.6, 1.6), drill=1.0, plated=True),
        Pad(id="4", layer=layer, shape=PadShape.OVAL, position=(3.5, 5.0), size=(1.6, 1.6), drill=1.0, plated=True),
        # Shield
        Pad(id="5", layer=layer, shape=PadShape.RECT, position=(0.0, -6.5), size=(8.0, 2.0)),
        Pad(id="6", layer=layer, shape=PadShape.RECT, position=(0.0, 6.5), size=(8.0, 2.0)),
    ]
    outline = _make_outline(12.0, 16.0)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(14.0, 18.0),
        description="USB Type-A through-hole",
        source="industry-standard",
    )


def footprint_usb_c(layer: LayerSet = LayerSet.ALL) -> FootprintDef:
    """USB Type-C SMD footprint (16-pin)."""
    pads: list[Pad] = []
    for i in range(8):
        x = -3.75 + i * 1.0
        pads.append(Pad(id=f"A{i + 1}", layer=LayerSet.TOP, shape=PadShape.RECT, position=(x, -4.5), size=(0.6, 1.0)))
    for i in range(8):
        x = -3.75 + i * 1.0
        pads.append(Pad(id=f"B{i + 1}", layer=LayerSet.TOP, shape=PadShape.RECT, position=(x, 4.5), size=(0.6, 1.0)))
    # Shield / mounting pads
    pads.append(Pad(id="SH1", layer=LayerSet.TOP, shape=PadShape.RECT, position=(-4.5, 0.0), size=(1.2, 5.0)))
    pads.append(Pad(id="SH2", layer=LayerSet.TOP, shape=PadShape.RECT, position=(4.5, 0.0), size=(1.2, 5.0)))
    outline = _make_outline(8.5, 6.0)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(10.0, 8.0),
        description="USB Type-C SMD 16-pin",
        source="USB-IF",
    )


def footprint_jst_ph(pins: int = 2, layer: LayerSet = LayerSet.ALL) -> FootprintDef:
    """JST-PH connector footprint."""
    pitch = 2.0
    pads: list[Pad] = []
    y_span = (pins - 1) * pitch
    for i in range(pins):
        y = -y_span / 2 + i * pitch
        pads.append(
            Pad(
                id=str(i + 1),
                layer=layer,
                shape=PadShape.OVAL,
                position=(0.0, y),
                size=(1.2, 1.2),
                drill=0.6,
                plated=True,
            )
        )
    body_w = 3.8
    body_h = (pins - 1) * pitch + 2.0
    outline = _make_outline(body_w, body_h)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(body_w + 1.0, body_h + 1.0),
        description=f"JST-PH {pins}-pin connector",
        source="JST",
    )


def footprint_crystal_smd(layer: LayerSet = LayerSet.TOP) -> FootprintDef:
    """SMD crystal footprint (HC-49S / 7x5mm)."""
    pads = [
        Pad(id="1", layer=layer, shape=PadShape.RECT, position=(-2.5, 0.0), size=(2.0, 1.6)),
        Pad(id="2", layer=layer, shape=PadShape.RECT, position=(2.5, 0.0), size=(2.0, 1.6)),
        Pad(id="3", layer=layer, shape=PadShape.RECT, position=(2.5, 0.0), size=(2.0, 1.6)),
        Pad(id="4", layer=layer, shape=PadShape.RECT, position=(-2.5, 0.0), size=(2.0, 1.6)),
    ]
    outline = _make_outline(7.0, 5.0)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(8.0, 6.0),
        description="SMD crystal HC-49S",
        source="generic",
    )


def footprint_solder_jumper(layer: LayerSet = LayerSet.TOP) -> FootprintDef:
    """Single 0-ohm / solder jumper footprint."""
    pads = [
        Pad(id="1", layer=layer, shape=PadShape.RECT, position=(-0.65, 0.0), size=(0.8, 0.8)),
        Pad(id="2", layer=layer, shape=PadShape.RECT, position=(0.65, 0.0), size=(0.8, 0.8)),
    ]
    outline = _make_outline(2.0, 1.0)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(2.5, 1.5),
        description="Solder jumper",
        source="generic",
    )


def footprint_test_pad(layer: LayerSet = LayerSet.TOP) -> FootprintDef:
    """Single test pad (via-like, for probing)."""
    pads = [
        Pad(id="1", layer=layer, shape=PadShape.CIRCLE, position=(0.0, 0.0), size=(1.5, 1.5)),
    ]
    outline = _make_outline(2.0, 2.0)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(2.5, 2.5),
        description="Test pad",
        source="generic",
    )


def footprint_dfn(
    package: str,
    layer: LayerSet = LayerSet.TOP,
) -> FootprintDef | None:
    """Generate DFN (Dual Flat No-lead) footprint with centre thermal pad."""
    dims = _DFN_DIMENSIONS.get(package.upper())
    if dims is None:
        return None
    body_w, body_h, pitch, pin_count = dims
    pins_per_side = pin_count // 2
    pad_w = 0.3 if pin_count > 8 else 0.4
    pad_l = 0.8
    pads: list[Pad] = []
    y_span = (pins_per_side - 1) * pitch
    x_off = body_w / 2 - pad_l / 2
    for i in range(pins_per_side):
        y = -y_span / 2 + i * pitch
        pads.append(Pad(id=f"{i + 1}", layer=layer, shape=PadShape.RECT, position=(-x_off, y), size=(pad_l, pad_w)))
    for i in range(pins_per_side):
        y = y_span / 2 - i * pitch
        n = pins_per_side + i + 1
        pads.append(Pad(id=f"{n}", layer=layer, shape=PadShape.RECT, position=(x_off, y), size=(pad_l, pad_w)))
    thermal_w = max(0.5, body_w - 2 * pad_l - 0.4)
    thermal_h = max(0.5, body_h - 0.8)
    pads.append(Pad(id="0", layer=layer, shape=PadShape.RECT, position=(0.0, 0.0), size=(thermal_w, thermal_h)))
    outline = _make_outline(body_w, body_h)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(body_w + 0.6, body_h + 0.6),
        thermal_pads=["0"],
        description=f"{package} footprint",
        source="IPC-7351B",
    )


def footprint_bga(
    package: str | None = None,
    *,
    rows: int | None = None,
    cols: int | None = None,
    pitch: float | None = None,
    ball_diameter: float | None = None,
    layer: LayerSet = LayerSet.TOP,
) -> FootprintDef | None:
    """Generate a Ball Grid Array (BGA) footprint with standard JEDEC alphanumeric IDs."""
    if package:
        dims = _BGA_DIMENSIONS.get(package.upper())
        if dims is not None:
            r, c, p, bd = dims
            rows = rows or r
            cols = cols or c
            pitch = pitch or p
            ball_diameter = ball_diameter or bd
        elif rows is None:
            return None

    r_count = rows or 8
    c_count = cols or 8
    p_val = pitch or 0.8
    b_diam = ball_diameter or 0.4

    pads, x_span, y_span = _grid_pads(
        rows=r_count,
        cols=c_count,
        pitch=p_val,
        diameter=b_diam,
        layer=layer,
    )

    body_w = x_span + 2.0
    body_h = y_span + 2.0
    outline = _make_outline(body_w, body_h)
    desc = f"BGA-{r_count * c_count} ({r_count}x{c_count}, {p_val}mm pitch)"
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(body_w + 1.0, body_h + 1.0),
        description=desc,
        source="JEDEC/IPC-7351",
    )


def footprint_wlcsp(
    package: str | None = None,
    *,
    rows: int | None = None,
    cols: int | None = None,
    pitch: float | None = None,
    pad_diameter: float | None = None,
    layer: LayerSet = LayerSet.TOP,
) -> FootprintDef | None:
    """Generate a Wafer-Level Chip Scale Package (WLCSP) footprint with JEDEC ball IDs."""
    if package:
        dims = _WLCSP_DIMENSIONS.get(package.upper())
        if dims is not None:
            r, c, p, pd = dims
            rows = rows or r
            cols = cols or c
            pitch = pitch or p
            pad_diameter = pad_diameter or pd
        elif rows is None:
            return None

    r_count = rows or 4
    c_count = cols or 4
    p_val = pitch or 0.4
    p_diam = pad_diameter or 0.22

    pads, x_span, y_span = _grid_pads(
        rows=r_count,
        cols=c_count,
        pitch=p_val,
        diameter=p_diam,
        layer=layer,
    )

    body_w = x_span + 0.6
    body_h = y_span + 0.6
    outline = _make_outline(body_w, body_h)
    desc = f"WLCSP-{r_count * c_count} ({r_count}x{c_count}, {p_val}mm pitch)"
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(body_w + 0.4, body_h + 0.4),
        description=desc,
        source="JEDEC",
    )


def footprint_module(
    width: float = 18.0,
    height: float = 25.5,
    pins_left: int = 19,
    pins_right: int = 19,
    pins_bottom: int = 0,
    pitch: float = 1.27,
    pad_w: float = 1.5,
    pad_h: float = 0.9,
    layer: LayerSet = LayerSet.TOP,
    description: str = "SMD castellation module",
) -> FootprintDef:
    """Generate perimeter castellation SMD module footprint (e.g. ESP32-WROOM, LoRa)."""
    pads: list[Pad] = []
    pad_num = 1

    if pins_left > 0:
        y_span = (pins_left - 1) * pitch
        x_pos = -width / 2 + pad_w / 2
        for i in range(pins_left):
            y_pos = y_span / 2 - i * pitch
            pads.append(
                Pad(id=f"{pad_num}", layer=layer, shape=PadShape.RECT, position=(x_pos, y_pos), size=(pad_w, pad_h))
            )
            pad_num += 1

    if pins_bottom > 0:
        x_span = (pins_bottom - 1) * pitch
        y_pos = -height / 2 + pad_w / 2
        for i in range(pins_bottom):
            x_pos = -x_span / 2 + i * pitch
            pads.append(
                Pad(id=f"{pad_num}", layer=layer, shape=PadShape.RECT, position=(x_pos, y_pos), size=(pad_h, pad_w))
            )
            pad_num += 1

    if pins_right > 0:
        y_span = (pins_right - 1) * pitch
        x_pos = width / 2 - pad_w / 2
        for i in range(pins_right):
            y_pos = -y_span / 2 + i * pitch
            pads.append(
                Pad(id=f"{pad_num}", layer=layer, shape=PadShape.RECT, position=(x_pos, y_pos), size=(pad_w, pad_h))
            )
            pad_num += 1

    outline = _make_outline(width, height)
    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(width + 1.0, height + 1.0),
        description=description,
        source="generic-module",
    )


# ---------------------------------------------------------------------------
#  Master dispatch
# ---------------------------------------------------------------------------


def _named_package_footprint(key: str, layer: LayerSet) -> FootprintDef | None:
    generators = (
        (("SOT",), footprint_sot),
        (("SOIC", "TSSOP", "MSOP", "SO"), footprint_soic),
        (("QFN",), footprint_qfn),
        (("QFP", "LQFP", "TQFP"), footprint_qfp),
        (("DIP",), footprint_dip),
    )
    for prefixes, generator in generators:
        if any(key.startswith(prefix) for prefix in prefixes):
            footprint = generator(key, layer=layer)
            if footprint is not None:
                return footprint
    return None


def generate_footprint(
    package: str,
    layer: LayerSet = LayerSet.TOP,
) -> FootprintDef | None:
    """Generate a ``FootprintDef`` for the given package name.

    Supports IPC chip codes (0402, 0603, …), SOT, SOIC, TSSOP, MSOP, QFN, QFP,
    DIP, DFN, BGA, WLCSP, header patterns, USB-A/USB-C, JST, crystal, and test probes.

    Returns ``None`` if the package is unknown.
    """
    key = package.strip().upper()
    # Alias resolution
    resolved = _PACKAGE_ALIASES.get(key.lower())
    if resolved:
        key = resolved.upper()
    chip = footprint_chip(key, layer=layer)
    if chip is not None:
        return chip
    named = _named_package_footprint(key, layer)
    if named is not None:
        return named
    if key.startswith("DFN"):
        return footprint_dfn(key, layer=layer)
    if key.startswith("BGA") and key != "BGA-256":
        return footprint_bga(key, layer=layer)
    if key.startswith("WLCSP"):
        return footprint_wlcsp(key, layer=layer)
    return None


def _import_lcsc_footprint(lcsc_id: str, layer: LayerSet) -> FootprintDef | None:
    from zaptrace.ee.imports import import_lcsc_component

    fp, _ = import_lcsc_component(lcsc_id)
    if fp is not None:
        for p in fp.pads:
            if p.layer == LayerSet.TOP and layer == LayerSet.BOTTOM:
                p.layer = LayerSet.BOTTOM
        return fp
    return None


def _match_header_footprint(ctype: str, pkg: str, pkg_lower: str) -> FootprintDef | None:
    is_header = "header" in ctype or "pin" in ctype or "pinhead" in pkg_lower or "header" in pkg_lower
    is_terminal = "terminal" in ctype or "terminal" in pkg_lower
    if not (is_header or is_terminal):
        return None
    import re

    m = re.search(r"(\d{1,4})x(\d{1,4})", pkg, re.IGNORECASE)
    if m:
        return footprint_header(rows=int(m.group(1)), cols=int(m.group(2)))
    m = re.search(r"(\d{1,4})p\b", pkg, re.IGNORECASE)
    if m:
        return footprint_header(rows=1, cols=int(m.group(1)))
    return None


def _match_special_footprint(ctype: str, pkg_lower: str, layer: LayerSet) -> FootprintDef | None:
    if "usb-a" in ctype or "usb_a" in ctype or "usb-a" in pkg_lower:
        return footprint_usb_a(layer)
    if "usb-c" in ctype or "usb_c" in ctype or "usb-c" in pkg_lower:
        return footprint_usb_c(layer)
    if "jst" in ctype or "ph" in ctype:
        return footprint_jst_ph()
    if "crystal" in ctype or "oscillator" in ctype:
        return footprint_crystal_smd(layer)
    if "jumper" in ctype or "0ohm" in ctype or "solder" in ctype:
        return footprint_solder_jumper(layer)
    if "test" in ctype or "probe" in ctype:
        return footprint_test_pad(layer)
    if pkg_lower in ("module", "smd-module", "castellated-module") or (
        ctype == "module" and "no-such" not in pkg_lower and "qfn" not in pkg_lower
    ):
        return footprint_module(layer=layer)
    return None


def generate_footprint_for_component(
    component_package: str,
    component_type: str = "",
    layer: LayerSet = LayerSet.TOP,
    lcsc_id: str | None = None,
) -> FootprintDef | None:
    """Generate a footprint for a component based on its package and type."""
    if lcsc_id:
        imported = _import_lcsc_footprint(lcsc_id, layer)
        if imported is not None:
            return imported

    pkg = component_package.strip().upper()
    ctype = component_type.strip().lower()
    pkg_lower = pkg.lower()

    header = _match_header_footprint(ctype, pkg, pkg_lower)
    if header is not None:
        return header

    special = _match_special_footprint(ctype, pkg_lower, layer)
    if special is not None:
        return special

    return generate_footprint(pkg, layer=layer)


# ---------------------------------------------------------------------------
#  Symbol generators (companion to footprints)
# ---------------------------------------------------------------------------


def symbol_from_pins(
    pins: dict[str, dict[str, str]],
    width: float = 40.0,
    height: float = 60.0,
) -> SymbolDef:
    """Generate a schematic symbol from a component's pin dictionary.

    Pins are distributed on left and right edges. Power/NC pins go to the top.
    """
    pin_items = sorted(pins.items(), key=lambda x: x[0])
    left_pins: list[tuple[str, str, str]] = []
    right_pins: list[tuple[str, str, str]] = []
    top_pins: list[tuple[str, str, str]] = []

    for name, attrs in pin_items:
        ptype = attrs.get("type", "passive")
        desc = attrs.get("description", "")
        if ptype in ("power",) or name.upper() in ("VCC", "VDD", "GND", "VSS"):
            top_pins.append((name, ptype, desc))
        elif int(name) % 2 == 0 if name.isdigit() else False:
            right_pins.append((name, ptype, desc))
        else:
            left_pins.append((name, ptype, desc))

    sym_pins: list[SymbolPin] = []
    w2, h2 = width / 2, height / 2
    left_count = len(left_pins)
    right_count = len(right_pins)
    top_count = len(top_pins)
    vert_count = max(left_count, right_count, 1)
    pin_spacing = (height - 10) / max(vert_count, 1)

    top_spacing = (width - 10) / max(top_count, 1) if top_count > 0 else 0

    for i, (name, ptype, _desc) in enumerate(left_pins):
        y = -((left_count - 1) * pin_spacing) / 2 + i * pin_spacing
        sym_pins.append(
            SymbolPin(
                id=name,
                name=name,
                position=(-w2, y),
                length=8.0,
                orientation="left",
                electrical_type=ptype,
            )
        )

    for i, (name, ptype, _desc) in enumerate(right_pins):
        y = -((right_count - 1) * pin_spacing) / 2 + i * pin_spacing
        sym_pins.append(
            SymbolPin(
                id=name,
                name=name,
                position=(w2, y),
                length=8.0,
                orientation="right",
                electrical_type=ptype,
            )
        )

    for i, (name, ptype, _desc) in enumerate(top_pins):
        x = -((top_count - 1) * top_spacing) / 2 + i * top_spacing
        sym_pins.append(
            SymbolPin(
                id=name,
                name=name,
                position=(x, h2),
                length=8.0,
                orientation="top",
                electrical_type=ptype,
            )
        )

    body = [
        DrawCommand(
            type="rect",
            params={
                "x": -w2,
                "y": -h2,
                "width": width,
                "height": height,
            },
        ),
    ]

    return SymbolDef(pins=sym_pins, body=body, origin=(0.0, 0.0), height=height, width=width)


# ---------------------------------------------------------------------------
#  Public registry / lookup
# ---------------------------------------------------------------------------


def list_supported_packages() -> list[str]:
    """Return a sorted list of all supported package names (canonical)."""
    keys: set[str] = set()

    # Chip packages
    keys.update(_CHIP_DIMENSIONS.keys())
    # SOT
    keys.update(_SOT_TH_DIMENSIONS.keys())
    # IC packages
    keys.update(_IC_DIMENSIONS)
    # DFN / BGA / WLCSP
    keys.update(_DFN_DIMENSIONS)
    keys.update(_BGA_DIMENSIONS)
    keys.update(_WLCSP_DIMENSIONS)

    # Explicit names
    keys.add("HEADER")
    keys.add("USB-A")
    keys.add("USB-C")
    keys.add("JST-PH")
    keys.add("CRYSTAL-SMD")
    keys.add("SOLDER-JUMPER")
    keys.add("TEST-PAD")
    keys.add("MODULE")

    return sorted(keys)


# ---------------------------------------------------------------------------
#  Register with the EE module
# ---------------------------------------------------------------------------

_PACKAGE_HANDLERS: dict[str, Any] = {
    "chip": _CHIP_DIMENSIONS,
    "sot": _SOT_TH_DIMENSIONS,
    "ic": _IC_DIMENSIONS,
    "dfn": _DFN_DIMENSIONS,
    "bga": _BGA_DIMENSIONS,
    "wlcsp": _WLCSP_DIMENSIONS,
    "specials": {
        "USB-A": footprint_usb_a,
        "USB-C": footprint_usb_c,
        "JST-PH": footprint_jst_ph,
        "CRYSTAL-SMD": footprint_crystal_smd,
        "SOLDER-JUMPER": footprint_solder_jumper,
        "TEST-PAD": footprint_test_pad,
        "MODULE": footprint_module,
    },
}
