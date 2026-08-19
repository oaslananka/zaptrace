"""Schematic symbol generators for standard electronic component types.

Each generator returns a :class:`~zaptrace.core.models.SymbolDef` with
pins and drawing primitives positioned in a local coordinate system
centered at ``(0, 0)``.

Supported types
---------------
- Resistor, capacitor, inductor, diode, LED, transistor (BJT, FET)
- Operational amplifier, logic gate, voltage regulator
- Crystal / oscillator, connector / header, IC (generic), fuse
- Ferrite bead, transformer, relay, speaker, microphone, antenna
- Potentiometer, photo-diode, photo-transistor, varactor, tunnel diode
- Thermistor, varistor
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from zaptrace.core.models import Component, DrawCommand, SymbolDef, SymbolPin

# ---------------------------------------------------------------------------


def _pin(
    pid: str,
    name: str,
    x: float,
    y: float,
    orientation: str = "left",
    etype: str = "passive",
) -> SymbolPin:
    return SymbolPin(id=pid, name=name, position=(x, y), orientation=orientation, electrical_type=etype)


def _line(x1: float, y1: float, x2: float, y2: float, **kw: Any) -> DrawCommand:
    params: dict[str, Any] = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
    params.update(kw)
    return DrawCommand(type="line", params=params)


def _rect(x: float, y: float, w: float, h: float, **kw: Any) -> DrawCommand:
    params: dict[str, Any] = {"x": x, "y": y, "width": w, "height": h}
    params.update(kw)
    return DrawCommand(type="rect", params=params)


def _circle(cx: float, cy: float, r: float, **kw: Any) -> DrawCommand:
    params: dict[str, Any] = {"cx": cx, "cy": cy, "radius": r}
    params.update(kw)
    return DrawCommand(type="circle", params=params)


def _text(x: float, y: float, txt: str, **kw: Any) -> DrawCommand:
    params: dict[str, Any] = {"x": x, "y": y, "text": txt}
    params.update(kw)
    return DrawCommand(type="text", params=params)


def _arc(x1: float, y1: float, x2: float, y2: float, radius: float, **kw: Any) -> DrawCommand:
    params: dict[str, Any] = {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "radius": radius}
    params.update(kw)
    return DrawCommand(type="arc", params=params)


# Pin spacing helpers
PIN_Y = 10.0  # vertical spacing between pins in schematic units
BODY_W = 30.0  # default body width
BODY_H = 40.0  # default body height


# ---------------------------------------------------------------------------
# Symbol generators
# ---------------------------------------------------------------------------


def _resistor() -> SymbolDef:
    """IEC-style resistor: rectangle body, pins on left/right."""
    w, h = 30.0, 14.0
    body = [
        _rect(-w / 2, -h / 2, w, h, stroke="black", fill="white"),
    ]
    pins = [
        _pin("1", "1", -w / 2 - 5, 0, "left"),
        _pin("2", "2", w / 2 + 5, 0, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 10)


def _capacitor() -> SymbolDef:
    """Two parallel plates."""
    gap = 4.0
    plate_h = 14.0
    body = [
        _line(-gap / 2, -plate_h / 2, -gap / 2, plate_h / 2, stroke="black"),
        _line(gap / 2, -plate_h / 2, gap / 2, plate_h / 2, stroke="black"),
    ]
    pins = [
        _pin("1", "1", -gap / 2 - 5, 0, "left"),
        _pin("2", "2", gap / 2 + 5, 0, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=plate_h + 10, width=20)


def _capacitor_polarized() -> SymbolDef:
    """Electrolytic / tantalum: plates + + marker."""
    gap = 4.0
    plate_h = 14.0
    body = [
        _line(-gap / 2, -plate_h / 2, -gap / 2, plate_h / 2, stroke="black"),
        _line(gap / 2, -plate_h / 2, gap / 2, plate_h / 2, stroke="black"),
        _rect(gap / 2 - 1, -plate_h / 2, 2, plate_h, fill="black"),
        _text(-gap / 2 - 8, 3, "+", font_size=8, fill="black"),
    ]
    pins = [
        _pin("1", "+", -gap / 2 - 5, 0, "left"),
        _pin("2", "-", gap / 2 + 5, 0, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=plate_h + 10, width=20)


def _inductor() -> SymbolDef:
    """Curved loops (simulated with arcs / lines)."""
    w, h = 24.0, 14.0
    seg = w / 4
    body = [
        _line(-w / 2 - seg / 2 - 5, 0, -w / 2 - seg / 2, 0, stroke="black"),
        _line(w / 2 + seg / 2, 0, w / 2 + seg / 2 + 5, 0, stroke="black"),
    ]
    for i in range(4):
        sx = -w / 2 + i * seg
        body.append(_arc(sx, -h / 2, sx + seg, -h / 2, seg / 2, stroke="black"))
    pins = [
        _pin("1", "1", -w / 2 - seg / 2 - 5, 0, "left"),
        _pin("2", "2", w / 2 + seg / 2 + 5, 0, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 20)


def _diode() -> SymbolDef:
    """Triangle + bar."""
    w, h = 20.0, 14.0
    body = [
        _line(-w / 2, -h / 2, -w / 2, h / 2, stroke="black"),
        _line(-w / 2, -h / 2, w / 2, 0, stroke="black"),
        _line(w / 2, 0, -w / 2, h / 2, stroke="black"),
        _line(w / 2 + 3, -h / 2, w / 2 + 3, h / 2, stroke="black"),
    ]
    pins = [
        _pin("A", "A", -w / 2 - 5, 0, "left", "passive"),
        _pin("K", "K", w / 2 + 8, 0, "right", "passive"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 15)


def _led() -> SymbolDef:
    """Diode + two arrows."""
    w, h = 20.0, 14.0
    body = [
        _line(-w / 2, -h / 2, -w / 2, h / 2, stroke="black"),
        _line(-w / 2, -h / 2, w / 2, 0, stroke="black"),
        _line(w / 2, 0, -w / 2, h / 2, stroke="black"),
        _line(w / 2 + 3, -h / 2, w / 2 + 3, h / 2, stroke="black"),
        # Light arrows
        _line(w / 2 + 8, -h / 2 - 4, w / 2 + 14, -h / 2 - 10, stroke="black"),
        _line(w / 2 + 8, -h / 2, w / 2 + 14, -h / 2 - 6, stroke="black"),
    ]
    pins = [
        _pin("A", "A", -w / 2 - 5, 0, "left", "passive"),
        _pin("K", "K", w / 2 + 8, 0, "right", "passive"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 25)


def _bjt_npn() -> SymbolDef:
    """NPN bipolar transistor."""
    body = [
        _line(0, -12, 0, 12, stroke="black"),
        _line(-8, -6, 8, 0, stroke="black"),
        _line(8, 0, -8, 6, stroke="black"),
        # Arrow on emitter
        _line(8, 0, 10, -2, stroke="black"),
    ]
    pins = [
        _pin("B", "B", -10, -6, "left", "input"),
        _pin("C", "C", 0, -16, "top", "output"),
        _pin("E", "E", 0, 16, "bottom", "passive"),
    ]
    return SymbolDef(pins=pins, body=body, height=36, width=24)


def _bjt_pnp() -> SymbolDef:
    """PNP bipolar transistor."""
    body = [
        _line(0, -12, 0, 12, stroke="black"),
        _line(-8, -6, 8, 0, stroke="black"),
        _line(8, 0, -8, 6, stroke="black"),
        # Arrow on emitter (reversed)
        _line(6, 0, 8, 2, stroke="black"),
    ]
    pins = [
        _pin("B", "B", -10, -6, "left", "input"),
        _pin("C", "C", 0, -16, "top", "output"),
        _pin("E", "E", 0, 16, "bottom", "passive"),
    ]
    return SymbolDef(pins=pins, body=body, height=36, width=24)


def _nmos() -> SymbolDef:
    """N-channel MOSFET."""
    body = [
        _line(-6, -12, -6, 12, stroke="black"),
        _line(-6, 0, 6, 0, stroke="black"),
        _line(6, -12, 6, 12, stroke="black"),
        # Arrow
        _line(6, 0, 8, -2, stroke="black"),
    ]
    pins = [
        _pin("G", "G", -10, 0, "left", "input"),
        _pin("D", "D", 0, -16, "top", "output"),
        _pin("S", "S", 0, 16, "bottom", "passive"),
    ]
    return SymbolDef(pins=pins, body=body, height=36, width=24)


def _pmos() -> SymbolDef:
    """P-channel MOSFET."""
    body = [
        _line(-6, -12, -6, 12, stroke="black"),
        _line(-6, 0, 6, 0, stroke="black"),
        _line(6, -12, 6, 12, stroke="black"),
        # Arrow (circle)
        _circle(7, 0, 2, stroke="black", fill="none"),
    ]
    pins = [
        _pin("G", "G", -10, 0, "left", "input"),
        _pin("D", "D", 0, -16, "top", "output"),
        _pin("S", "S", 0, 16, "bottom", "passive"),
    ]
    return SymbolDef(pins=pins, body=body, height=36, width=24)


def _opamp() -> SymbolDef:
    """Operational amplifier triangle."""
    w, h = 30.0, 24.0
    body = [
        _line(-w / 2, -h / 2, -w / 2, h / 2, stroke="black"),
        _line(-w / 2, -h / 2, w / 2, 0, stroke="black"),
        _line(w / 2, 0, -w / 2, h / 2, stroke="black"),
        # polarity marks
        _text(-w / 2 - 2, -6, "-", font_size=7, fill="black"),
        _text(-w / 2 - 2, 4, "+", font_size=7, fill="black"),
    ]
    pins = [
        _pin("IN-", "-", -w / 2 - 5, -8, "left", "input"),
        _pin("IN+", "+", -w / 2 - 5, 8, "left", "input"),
        _pin("OUT", "OUT", w / 2 + 5, 0, "right", "output"),
        _pin("V+", "V+", 0, -h / 2 - 5, "top", "power"),
        _pin("V-", "V-", 0, h / 2 + 5, "bottom", "power"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 16, width=w + 12)


def _connector() -> SymbolDef:
    """Generic 2-pin connector / header."""
    body = [
        _rect(-10, -8, 20, 16, stroke="black", fill="white"),
    ]
    pins = [
        _pin("1", "1", 0, -10, "top"),
        _pin("2", "2", 0, 10, "bottom"),
    ]
    return SymbolDef(pins=pins, body=body, height=24, width=24)


def _crystal() -> SymbolDef:
    """Quartz crystal / resonator."""
    body = [
        _rect(-8, -4, 16, 8, stroke="black", fill="white"),
        _line(-12, 0, -8, 0, stroke="black"),
        _line(8, 0, 12, 0, stroke="black"),
    ]
    pins = [
        _pin("1", "1", -12, 0, "left"),
        _pin("2", "2", 12, 0, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=12, width=28)


def _fuse() -> SymbolDef:
    """Fuse (IEC-style resistor with X through)."""
    w, h = 20.0, 10.0
    body = [
        _rect(-w / 2, -h / 2, w, h, stroke="black", fill="white"),
        _line(-w / 2, -h / 2, w / 2, h / 2, stroke="black"),
        _line(-w / 2, h / 2, w / 2, -h / 2, stroke="black"),
    ]
    pins = [
        _pin("1", "1", -w / 2 - 5, 0, "left"),
        _pin("2", "2", w / 2 + 5, 0, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 10)


def _ferrite_bead() -> SymbolDef:
    """Ferrite bead (inductor with straight core)."""
    w, h = 20.0, 10.0
    body = [
        _line(-w / 2, -h / 2, -w / 2, h / 2, stroke="black"),
        _line(-w / 2, -h / 2, w / 2, -h / 2, stroke="black"),
        _line(-w / 2, h / 2, w / 2, h / 2, stroke="black"),
        _line(w / 2, -h / 2, w / 2, h / 2, stroke="black"),
    ]
    pins = [
        _pin("1", "1", -w / 2 - 5, 0, "left"),
        _pin("2", "2", w / 2 + 5, 0, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 10)


def _regulator() -> SymbolDef:
    """3-pin voltage regulator."""
    w, h = 24.0, 20.0
    body = [
        _rect(-w / 2, -h / 2, w, h, stroke="black", fill="white"),
    ]
    pins = [
        _pin("IN", "IN", -w / 2 - 5, -8, "left", "power"),
        _pin("GND", "GND", -w / 2 - 5, 8, "left", "power"),
        _pin("OUT", "OUT", w / 2 + 5, 0, "right", "output"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 12)


def _transformer() -> SymbolDef:
    """Two coupled inductors."""
    w, h = 30.0, 30.0
    seg = w / 4
    body = []
    for side_x, side_y in [(-w / 2, -h / 4), (-w / 2, h / 4)]:
        for i in range(3):
            sx = side_x + i * seg
            body.append(_arc(sx, side_y - 5, sx + seg, side_y - 5, seg / 2, stroke="black"))
    # Core lines
    body.append(_line(-2, -h / 2, -2, h / 2, stroke="black"))
    body.append(_line(2, -h / 2, 2, h / 2, stroke="black"))
    pins = [
        _pin("P1", "P1", -w / 2 - 5, -h / 4, "left"),
        _pin("P2", "P2", -w / 2 - 5, h / 4, "left"),
        _pin("S1", "S1", w / 2 + 5, -h / 4, "right"),
        _pin("S2", "S2", w / 2 + 5, h / 4, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 12)


def _ic_sym(pin_names: list[tuple[str, str, str]]) -> SymbolDef:
    """Generic IC symbol from a list of ``(id, name, side)`` entries.

    *side* is ``"L"`` (left) or ``"R"`` (right).  Pins are evenly
    distributed along the body edges.
    """
    n = len(pin_names)
    n_left = sum(1 for _, _, s in pin_names if s == "L")
    n_right = n - n_left
    max_pins = max(n_left, n_right, 1)
    body_h = max(30.0, max_pins * PIN_Y)
    body_w = BODY_W

    body = [
        _rect(-body_w / 2, -body_h / 2, body_w, body_h, stroke="black", fill="white"),
    ]

    left_idx = 0
    right_idx = 0
    pins: list[SymbolPin] = []

    for pid, name, side in pin_names:
        if side == "L":
            frac = (left_idx + 1) / (n_left + 1) if n_left > 0 else 0.5
            y = -body_h / 2 + frac * body_h
            pins.append(_pin(pid, name, -body_w / 2 - 5, y, "left", "passive"))
            left_idx += 1
        else:
            frac = (right_idx + 1) / (n_right + 1) if n_right > 0 else 0.5
            y = -body_h / 2 + frac * body_h
            pins.append(_pin(pid, name, body_w / 2 + 5, y, "right", "passive"))
            right_idx += 1

    return SymbolDef(pins=pins, body=body, height=body_h + 10, width=body_w + 12)


def _relay() -> SymbolDef:
    """Relay coil + switch."""
    w, h = 40.0, 24.0
    body = [
        _rect(-w / 2, -h / 2, w - 10, h, stroke="black", fill="white"),
        # Coil
        _line(w / 2 - 12, -h / 3, w / 2 - 12, h / 3, stroke="black"),
        _line(w / 2 - 8, -h / 3, w / 2 - 8, h / 3, stroke="black"),
    ]
    pins = [
        _pin("COIL1", "COIL1", -w / 2 - 5, -h / 3, "left"),
        _pin("COIL2", "COIL2", -w / 2 - 5, h / 3, "left"),
        _pin("COM", "COM", w / 2 + 10, -h / 3, "right"),
        _pin("NO", "NO", w / 2 + 10, h / 3, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 18)


def _potentiometer() -> SymbolDef:
    """Variable resistor / pot."""
    w, h = 30.0, 20.0
    body = [
        _rect(-w / 2, -h / 2, w, h * 0.6, stroke="black", fill="white"),
        _line(-w / 2, -h / 2 + h * 0.6, w / 2, -h / 2 + h * 0.6, stroke="black"),
        # Arrow tap
        _line(0, -h / 2 + h * 0.6, 0, h / 2 + 5, stroke="black"),
        _line(-4, h / 2, 4, h / 2, stroke="black"),
    ]
    pins = [
        _pin("1", "1", -w / 2 - 5, -h / 2 + h * 0.3, "left"),
        _pin("2", "2", w / 2 + 5, -h / 2 + h * 0.3, "right"),
        _pin("W", "WIPER", 0, h / 2 + 8, "bottom"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 14, width=w + 12)


def _antenna() -> SymbolDef:
    """Antenna / whip."""
    body = [
        _line(0, 8, 0, -10, stroke="black"),
        _line(-5, -2, 5, -2, stroke="black"),
    ]
    pins = [
        _pin("SIG", "SIG", 0, 12, "bottom", "passive"),
    ]
    return SymbolDef(pins=pins, body=body, height=24, width=14)


def _microphone() -> SymbolDef:
    """Electret microphone."""
    body = [
        _rect(-6, -6, 12, 12, stroke="black", fill="white"),
        _text(-2, 1, "+", font_size=7, fill="black"),
        _text(1, -2, "-", font_size=7, fill="black"),
    ]
    pins = [
        _pin("SIG", "SIG", 0, 10, "bottom", "passive"),
    ]
    return SymbolDef(pins=pins, body=body, height=16, width=16)


def _speaker() -> SymbolDef:
    """Speaker / buzzer."""
    body = [
        _rect(-6, -6, 12, 12, stroke="black", fill="white"),
        _circle(0, 0, 3, stroke="black", fill="none"),
    ]
    pins = [
        _pin("+", "+", -8, 0, "left"),
        _pin("-", "-", 8, 0, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=16, width=20)


def _photo_diode() -> SymbolDef:
    """Photodiode (diode + inward arrows)."""
    w, h = 20.0, 14.0
    body = [
        _line(-w / 2, -h / 2, -w / 2, h / 2, stroke="black"),
        _line(-w / 2, -h / 2, w / 2, 0, stroke="black"),
        _line(w / 2, 0, -w / 2, h / 2, stroke="black"),
        _line(w / 2 + 3, -h / 2, w / 2 + 3, h / 2, stroke="black"),
        # Inward arrows (light arriving)
        _line(-w / 2 - 10, -h / 2 - 2, -w / 2 - 4, -h / 2 - 8, stroke="black"),
        _line(-w / 2 - 6, -h / 2, -w / 2, -h / 2 - 6, stroke="black"),
    ]
    pins = [
        _pin("A", "A", -w / 2 - 5, 0, "left"),
        _pin("K", "K", w / 2 + 8, 0, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 20)


def _photo_transistor() -> SymbolDef:
    """Phototransistor (NPN + inward arrows)."""
    body = [
        _line(0, -12, 0, 12, stroke="black"),
        _line(-8, -6, 8, 0, stroke="black"),
        _line(8, 0, -8, 6, stroke="black"),
        _line(8, 0, 10, -2, stroke="black"),
        # Inward arrows
        _line(-14, -10, -8, -16, stroke="black"),
        _line(-10, -8, -4, -14, stroke="black"),
    ]
    pins = [
        _pin("B", "B", -10, -6, "left", "input"),
        _pin("C", "C", 0, -16, "top", "output"),
        _pin("E", "E", 0, 16, "bottom", "passive"),
    ]
    return SymbolDef(pins=pins, body=body, height=36, width=28)


def _thermistor() -> SymbolDef:
    """Thermistor (resistor + temp arrow)."""
    w, h = 30.0, 14.0
    body = [
        _rect(-w / 2, -h / 2, w, h, stroke="black", fill="white"),
        _text(-4, 2, "T", font_size=8, fill="black"),
    ]
    pins = [
        _pin("1", "1", -w / 2 - 5, 0, "left"),
        _pin("2", "2", w / 2 + 5, 0, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 12)


def _varistor() -> SymbolDef:
    """Varistor (diode-like with arrows both ways)."""
    w, h = 20.0, 14.0
    body = [
        _line(-w / 2, -h / 2, -w / 2, h / 2, stroke="black"),
        _line(-w / 2, -h / 2, w / 2, 0, stroke="black"),
        _line(w / 2, 0, -w / 2, h / 2, stroke="black"),
        _line(-w / 2, -h / 2, w / 2, 0, stroke="black"),
    ]
    pins = [
        _pin("1", "1", -w / 2 - 5, 0, "left"),
        _pin("2", "2", w / 2 + 5, 0, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 12)


def _varactor() -> SymbolDef:
    """Varactor / varicap (diode + capacitor overlay)."""
    w, h = 20.0, 14.0
    body = [
        _line(-w / 2, -h / 2, -w / 2, h / 2, stroke="black"),
        _line(-w / 2, -h / 2, w / 2, 0, stroke="black"),
        _line(w / 2, 0, -w / 2, h / 2, stroke="black"),
        _line(w / 2 + 3, -h / 2, w / 2 + 3, h / 2, stroke="black"),
    ]
    pins = [
        _pin("A", "A", -w / 2 - 5, 0, "left"),
        _pin("K", "K", w / 2 + 8, 0, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 15)


def _tunnel_diode() -> SymbolDef:
    """Tunnel diode (diode with extra line)."""
    w, h = 20.0, 14.0
    body = [
        _line(-w / 2, -h / 2, -w / 2, h / 2, stroke="black"),
        _line(-w / 2, -h / 2, w / 2, 0, stroke="black"),
        _line(w / 2, 0, -w / 2, h / 2, stroke="black"),
        _line(w / 2 + 3, -h / 2 - 2, w / 2 + 3, h / 2 + 2, stroke="black"),
    ]
    pins = [
        _pin("A", "A", -w / 2 - 5, 0, "left"),
        _pin("K", "K", w / 2 + 8, 0, "right"),
    ]
    return SymbolDef(pins=pins, body=body, height=h + 10, width=w + 15)


def _triac() -> SymbolDef:
    """Triac (two diodes back-to-back with gate)."""
    body = [
        _line(-8, -10, -8, 10, stroke="black"),
        _line(-8, -10, 4, 0, stroke="black"),
        _line(4, 0, -8, 10, stroke="black"),
        _line(-4, -10, -4, 10, stroke="black"),
        _line(-4, -10, 8, 0, stroke="black"),
        _line(8, 0, -4, 10, stroke="black"),
        # Gate line
        _line(-6, 0, -14, 0, stroke="black"),
    ]
    pins = [
        _pin("MT1", "MT1", 12, 0, "right"),
        _pin("MT2", "MT2", -12, -10, "left"),
        _pin("G", "GATE", -14, 0, "left", "input"),
    ]
    return SymbolDef(pins=pins, body=body, height=24, width=28)


def _ic_generic() -> SymbolDef:
    """Generic IC symbol (default 8-pin layout)."""
    pins = [
        _pin("1", "1", -20, -15, "left"),
        _pin("2", "2", -20, -5, "left"),
        _pin("3", "3", -20, 5, "left"),
        _pin("4", "4", -20, 15, "left"),
        _pin("5", "5", 20, -15, "right"),
        _pin("6", "6", 20, -5, "right"),
        _pin("7", "7", 20, 5, "right"),
        _pin("8", "8", 20, 15, "right"),
    ]
    body = [
        _rect(-20, -20, 40, 40, stroke="black", fill="white"),
    ]
    return SymbolDef(pins=pins, body=body, height=44, width=44)


# ---------------------------------------------------------------------------
# Symbol registry
# ---------------------------------------------------------------------------

SYMBOL_REGISTRY: dict[str, Callable[[], SymbolDef]] = {
    "ic": _ic_generic,  # generic fallback
    "resistor": _resistor,
    "capacitor": _capacitor,
    "capacitor_polarized": _capacitor_polarized,
    "inductor": _inductor,
    "diode": _diode,
    "led": _led,
    "bjt_npn": _bjt_npn,
    "bjt_pnp": _bjt_pnp,
    "nmos": _nmos,
    "pmos": _pmos,
    "opamp": _opamp,
    "connector": _connector,
    "header": _connector,
    "crystal": _crystal,
    "oscillator": _crystal,
    "fuse": _fuse,
    "ferrite_bead": _ferrite_bead,
    "regulator": _regulator,
    "transformer": _transformer,
    "relay": _relay,
    "potentiometer": _potentiometer,
    "pot": _potentiometer,
    "antenna": _antenna,
    "microphone": _microphone,
    "speaker": _speaker,
    "buzzer": _speaker,
    "photo_diode": _photo_diode,
    "photo_transistor": _photo_transistor,
    "thermistor": _thermistor,
    "varistor": _varistor,
    "varactor": _varactor,
    "tunnel_diode": _tunnel_diode,
    "triac": _triac,
}

# Component type heuristics for symbol lookup
TYPE_ALIASES: dict[str, str] = {
    # Resistors
    "resistor": "resistor",
    "r": "resistor",
    "res": "resistor",
    "potentiometer": "potentiometer",
    "pot": "potentiometer",
    "trimmer": "potentiometer",
    "thermistor": "thermistor",
    "ntc": "thermistor",
    "ptc": "thermistor",
    "varistor": "varistor",
    "mov": "varistor",
    # Capacitors
    "capacitor": "capacitor",
    "c": "capacitor",
    "cap": "capacitor",
    "electrolytic": "capacitor_polarized",
    "tantalum": "capacitor_polarized",
    "ceramic": "capacitor",
    "mlcc": "capacitor",
    # Inductors
    "inductor": "inductor",
    "l": "inductor",
    "coil": "inductor",
    "ferrite_bead": "ferrite_bead",
    "bead": "ferrite_bead",
    # Diodes
    "diode": "diode",
    "d": "diode",
    "led": "led",
    "photodiode": "photo_diode",
    "schottky": "diode",
    "zener": "diode",
    "varactor": "varactor",
    "tunnel_diode": "tunnel_diode",
    # Transistors
    "bjt_npn": "bjt_npn",
    "npn": "bjt_npn",
    "bjt_pnp": "bjt_pnp",
    "pnp": "bjt_pnp",
    "nmos": "nmos",
    "n-channel": "nmos",
    "nfet": "nmos",
    "pmos": "pmos",
    "p-channel": "pmos",
    "pfet": "pmos",
    "photo_transistor": "photo_transistor",
    "phototransistor": "photo_transistor",
    # ICs
    "opamp": "opamp",
    "operational_amplifier": "opamp",
    "regulator": "regulator",
    "ldo": "regulator",
    # Others
    "connector": "connector",
    "header": "connector",
    "crystal": "crystal",
    "xtal": "crystal",
    "oscillator": "crystal",
    "fuse": "fuse",
    "f": "fuse",
    "transformer": "transformer",
    "xfmr": "transformer",
    "relay": "relay",
    "antenna": "antenna",
    "whip": "antenna",
    "microphone": "microphone",
    "mic": "microphone",
    "speaker": "speaker",
    "buzzer": "speaker",
    "triac": "triac",
    # Generic fallbacks
    "ic": "ic",
    "mcu": "ic",
    "microcontroller": "ic",
    "sensor": "ic",
    "module": "ic",
}


def generate_symbol(component: Component) -> SymbolDef:
    """Generate a schematic symbol for a component.

    Uses the component's ``type`` field to look up the best matching
    symbol generator in the registry.  For unrecognised types, an IC
    symbol is generated from the component's pin list, or a simple
    box placeholder is returned.

    Pins from the component's ``pins`` dict are mapped to symbol pins
    by matching ``(id, name)`` pairs.  Pin electrical type is inferred
    from :class:`~zaptrace.core.models.PinType`.

    If ``component.symbol`` is already set (non-None), it is returned
    as-is as a user override.
    """
    if component.symbol is not None:
        return component.symbol

    comp_type = component.type.lower().strip()

    # Direct symbol overrides in component properties
    override = component.properties.get("symbol_type", "")
    if override:
        lookup = override.lower().strip()
        gen_cls = SYMBOL_REGISTRY.get(lookup) or SYMBOL_REGISTRY.get(TYPE_ALIASES.get(lookup, ""))
        if gen_cls is not None:
            sym = gen_cls()
            _map_component_pins(component, sym)
            return sym

    # Type alias lookup
    canonical = TYPE_ALIASES.get(comp_type, "")
    if canonical:
        gen_cls = SYMBOL_REGISTRY.get(canonical)
        if gen_cls is not None:
            sym = gen_cls()
            _map_component_pins(component, sym)
            return sym

    # IC pin-based symbol
    if component.pins:
        pin_entries: list[tuple[str, str, str]] = []
        pin_names = list(component.pins.keys())
        mid = len(pin_names) // 2
        for i, pname in enumerate(pin_names):
            side = "L" if i < mid else "R"
            pin_entries.append((pname, pname, side))
        sym = _ic_sym(pin_entries)
        _map_component_pins(component, sym)
        return sym

    # Fallback: simple box
    return _placeholder_box()


def _placeholder_box() -> SymbolDef:
    body = [_rect(-15, -10, 30, 20, stroke="black", fill="white")]
    return SymbolDef(
        pins=[],
        body=body,
        height=24,
        width=34,
    )


def _map_component_pins(component: Component, sym: SymbolDef) -> None:
    """Map component pins to symbol pins by matching ``id`` / ``name``."""
    type_map = {
        "power": "power",
        "input": "input",
        "output": "output",
        "bidirectional": "bidirectional",
        "passive": "passive",
        "no_connect": "passive",
    }

    # Build index by pid and by name for flexible matching
    for sp in sym.pins:
        if sp.id in component.pins:
            cp = component.pins[sp.id]
            sp.electrical_type = type_map.get(cp.type.value, "passive")

    for cid, cp in component.pins.items():
        for sp in sym.pins:
            if sp.id == cid or sp.name == cp.name or sp.name == cp.name.upper():
                sp.electrical_type = type_map.get(cp.type.value, "passive")
