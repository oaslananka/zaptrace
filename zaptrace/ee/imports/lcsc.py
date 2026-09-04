"""LCSC / EasyEDA component geometry importer."""

from __future__ import annotations

import json
import logging
from pathlib import Path
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

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "zaptrace" / "lcsc"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _read_cached_component(cache_file: Path) -> tuple[dict, dict] | None:
    if not cache_file.exists():
        return None
    try:
        with cache_file.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError:
        return None
    return data.get("symbol"), data.get("footprint")


def _fetch_search_items(httpx_module: Any, lcsc_id: str, headers: dict[str, str]) -> list[dict]:
    try:
        with httpx_module.Client(verify=True) as client:
            response = client.post("https://lceda.cn/api/components/search", json={"wd": lcsc_id}, headers=headers)
            response.raise_for_status()
            result = response.json()
    except Exception:
        logger.exception("Failed to fetch LCSC search data")
        return []
    return result.get("result", {}).get("lists", {}).get("lcsc", [])


def _fetch_component_record(httpx_module: Any, uuid: str, headers: dict[str, str], *, label: str) -> dict | None:
    try:
        with httpx_module.Client(verify=True) as client:
            response = client.get(f"https://lceda.cn/api/components/{uuid}", headers=headers)
            response.raise_for_status()
            result = response.json()
    except Exception:
        logger.exception("Failed to fetch %s data", label)
        return None
    return result.get("result") if result.get("success") else None


def _cache_component(cache_file: Path, symbol_data: dict | None, footprint_data: dict | None) -> None:
    with cache_file.open("w", encoding="utf-8") as handle:
        json.dump({"symbol": symbol_data, "footprint": footprint_data}, handle)


def fetch_lcsc_component(lcsc_id: str) -> tuple[dict, dict] | None:
    """Fetch symbol and footprint data for an LCSC component from EasyEDA."""
    cache_file = CACHE_DIR / f"{lcsc_id}.json"
    cached = _read_cached_component(cache_file)
    if cached is not None:
        return cached

    try:
        import httpx
    except ImportError:
        logger.error("httpx is required to fetch LCSC components")
        return None

    headers = {"User-Agent": "Mozilla/5.0"}
    items = _fetch_search_items(httpx, lcsc_id, headers)
    if not items:
        return None

    item = items[0]
    symbol_uuid = item.get("uuid")
    if not symbol_uuid:
        return None

    puuid = item.get("dataStr", {}).get("head", {}).get("puuid")
    symbol_data = _fetch_component_record(httpx, symbol_uuid, headers, label="symbol")
    footprint_data = _fetch_component_record(httpx, puuid, headers, label="footprint") if puuid else None
    if not symbol_data and not footprint_data:
        return None

    _cache_component(cache_file, symbol_data, footprint_data)
    return symbol_data or {}, footprint_data or {}


def _easyeda_pad(parts: list[str], base_x: float, base_y: float, unit_to_mm: float) -> Pad | None:
    if len(parts) < 8:
        return None
    try:
        px = (float(parts[2]) - base_x) * unit_to_mm
        py = (float(parts[3]) - base_y) * unit_to_mm * -1.0
        width = float(parts[4]) * unit_to_mm
        height = float(parts[5]) * unit_to_mm
        shape_val = parts[1]
        shape = PadShape.RECT
        if shape_val in ("ELLIPSE", "CIRCLE", "OVAL"):
            shape = PadShape.OVAL if width != height else PadShape.CIRCLE
        pad_id = parts[7] or (parts[13] if len(parts) > 13 else "")
        layer = {"2": LayerSet.BOTTOM, "11": LayerSet.ALL}.get(parts[6], LayerSet.TOP)
        drill = float(parts[8]) * unit_to_mm if layer == LayerSet.ALL and len(parts) >= 10 else None
        return Pad(
            id=pad_id or "0",
            layer=layer,
            shape=shape,
            position=(px, py),
            size=(width, height),
            drill=drill,
            plated=drill is not None,
        )
    except ValueError:
        return None


def _easyeda_track(parts: list[str], base_x: float, base_y: float, unit_to_mm: float) -> list[DrawCommand]:
    if len(parts) < 5:
        return []
    try:
        width = float(parts[1]) * unit_to_mm
        path_str = parts[4].split()
        if len(path_str) < 4:
            return []
        points = [
            (
                (float(path_str[index]) - base_x) * unit_to_mm,
                (float(path_str[index + 1]) - base_y) * unit_to_mm * -1.0,
            )
            for index in range(0, len(path_str), 2)
        ]
    except (ValueError, IndexError):
        return []
    return [
        DrawCommand(
            type="line",
            params={
                "x1": first[0],
                "y1": first[1],
                "x2": second[0],
                "y2": second[1],
                "width": width,
            },
        )
        for first, second in zip(points, points[1:], strict=False)
    ]


def _easyeda_circle(parts: list[str], base_x: float, base_y: float, unit_to_mm: float) -> DrawCommand | None:
    if len(parts) < 5:
        return None
    try:
        cx = (float(parts[1]) - base_x) * unit_to_mm
        cy = (float(parts[2]) - base_y) * unit_to_mm * -1.0
        radius = float(parts[3]) * unit_to_mm
    except ValueError:
        return None
    return DrawCommand(type="circle", params={"x": cx, "y": cy, "r": radius})


def _easyeda_courtyard(pads: list[Pad]) -> tuple[float, float]:
    if not pads:
        return 0.0, 0.0
    max_x = max(abs(pad.position[0]) + pad.size[0] / 2 for pad in pads)
    max_y = max(abs(pad.position[1]) + pad.size[1] / 2 for pad in pads)
    return (max_x + 0.5) * 2, (max_y + 0.5) * 2


def parse_easyeda_footprint(data: dict) -> FootprintDef:
    """Parse EasyEDA footprint JSON into a FootprintDef."""
    data_str = data.get("dataStr", {})
    head = data_str.get("head", {})
    base_x = float(head.get("x", 0))
    base_y = float(head.get("y", 0))
    unit_to_mm = 0.254
    pads: list[Pad] = []
    outline: list[DrawCommand] = []

    for shape_str in data_str.get("shape", []):
        parts = shape_str.split("~")
        if not parts:
            continue
        if parts[0] == "PAD":
            pad = _easyeda_pad(parts, base_x, base_y, unit_to_mm)
            if pad is not None:
                pads.append(pad)
        elif parts[0] == "TRACK":
            outline.extend(_easyeda_track(parts, base_x, base_y, unit_to_mm))
        elif parts[0] == "CIRCLE":
            circle = _easyeda_circle(parts, base_x, base_y, unit_to_mm)
            if circle is not None:
                outline.append(circle)

    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=_easyeda_courtyard(pads),
        source="easyeda",
        description=head.get("c_para", {}).get("package", ""),
    )


def _parse_easyeda_pin_shape(parts: list[str]) -> SymbolPin | None:
    if len(parts) < 7:
        return None
    try:
        scale = 1.0
        px = float(parts[4]) * scale
        py = float(parts[5]) * scale * -1.0
        pin_id = parts[3]
    except ValueError:
        return None
    return SymbolPin(
        id=pin_id,
        name=pin_id,
        position=(px, py),
        length=5.0,
        orientation="left",
        electrical_type="passive",
    )


def _parse_easyeda_polyline_shape(parts: list[str]) -> list[DrawCommand]:
    if len(parts) < 2:
        return []
    path_str = parts[1].split()
    if len(path_str) < 4:
        return []
    commands: list[DrawCommand] = []
    try:
        for i in range(0, len(path_str) - 2, 2):
            x1 = float(path_str[i])
            y1 = float(path_str[i + 1]) * -1.0
            x2 = float(path_str[i + 2])
            y2 = float(path_str[i + 3]) * -1.0
            commands.append(DrawCommand(type="line", params={"x1": x1, "y1": y1, "x2": x2, "y2": y2}))
    except ValueError:
        pass
    return commands


def parse_easyeda_symbol(data: dict) -> SymbolDef:
    """Parse EasyEDA symbol JSON into a SymbolDef."""
    data_str = data.get("dataStr", {})
    shapes = data_str.get("shape", [])

    sym_pins: list[SymbolPin] = []
    body: list[DrawCommand] = []

    for shape_str in shapes:
        parts = shape_str.split("~")
        if not parts:
            continue

        stype = parts[0]
        if stype == "P":  # Pin
            pin = _parse_easyeda_pin_shape(parts)
            if pin is not None:
                sym_pins.append(pin)
        elif stype == "PL":  # Polyline
            body.extend(_parse_easyeda_polyline_shape(parts))
        elif stype == "PT":  # Polygon/Path
            pass  # PT~svg path~... not yet mapped

    return SymbolDef(pins=sym_pins, body=body, origin=(0.0, 0.0), height=20.0, width=20.0)


def import_lcsc_component(lcsc_id: str) -> tuple[FootprintDef | None, SymbolDef | None]:
    """Fetch and parse an LCSC component."""
    res = fetch_lcsc_component(lcsc_id)
    if not res:
        return None, None

    symbol_data, footprint_data = res

    fp_def = None
    if footprint_data:
        fp_def = parse_easyeda_footprint(footprint_data)
        fp_def.description = f"LCSC:{lcsc_id} " + fp_def.description

    sym_def = None
    if symbol_data:
        sym_def = parse_easyeda_symbol(symbol_data)

    return fp_def, sym_def
