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


def parse_easyeda_footprint(data: dict) -> FootprintDef:
    """Parse EasyEDA footprint JSON into a FootprintDef."""
    data_str = data.get("dataStr", {})
    head = data_str.get("head", {})
    shapes = data_str.get("shape", [])

    pads: list[Pad] = []
    outline: list[DrawCommand] = []

    # Base offset (EasyEDA coordinates)
    base_x = float(head.get("x", 0))
    base_y = float(head.get("y", 0))

    # 1 unit = 10 mils = 0.254 mm
    unit_to_mm = 0.254

    for shape_str in shapes:
        parts = shape_str.split("~")
        if not parts:
            continue

        stype = parts[0]

        if stype == "PAD":
            # format e.g. PAD~RECT~x~y~w~h~layer~id~...
            if len(parts) >= 8:
                shape_val = parts[1]
                try:
                    px = (float(parts[2]) - base_x) * unit_to_mm
                    # EasyEDA Y is inverted (down is positive)
                    py = (float(parts[3]) - base_y) * unit_to_mm * -1.0
                    w = float(parts[4]) * unit_to_mm
                    h = float(parts[5]) * unit_to_mm

                    # Pad shapes mapping
                    pshape = PadShape.RECT
                    if shape_val in ("ELLIPSE", "CIRCLE", "OVAL"):
                        pshape = PadShape.OVAL if w != h else PadShape.CIRCLE

                    pad_id = parts[7]
                    if not pad_id and len(parts) > 13:
                        pad_id = parts[13]  # sometime it's empty in id but present later

                    layer = LayerSet.TOP
                    if parts[6] == "2":
                        layer = LayerSet.BOTTOM
                    elif parts[6] == "11":
                        layer = LayerSet.ALL

                    drill = None
                    if layer == LayerSet.ALL and len(parts) >= 10:
                        drill = float(parts[8]) * unit_to_mm

                    pads.append(
                        Pad(
                            id=pad_id or "0",
                            layer=layer,
                            shape=pshape,
                            position=(px, py),
                            size=(w, h),
                            drill=drill,
                            plated=(drill is not None),
                        )
                    )
                except ValueError:
                    continue

        elif stype == "TRACK":
            # format TRACK~width~layer~net~path...
            if len(parts) >= 5:
                try:
                    width = float(parts[1]) * unit_to_mm
                    path_str = parts[4].split()
                    if len(path_str) >= 4:
                        pts = []
                        for i in range(0, len(path_str), 2):
                            x = (float(path_str[i]) - base_x) * unit_to_mm
                            y = (float(path_str[i + 1]) - base_y) * unit_to_mm * -1.0
                            pts.append((x, y))

                        for i in range(len(pts) - 1):
                            outline.append(
                                DrawCommand(
                                    type="line",
                                    params={
                                        "x1": pts[i][0],
                                        "y1": pts[i][1],
                                        "x2": pts[i + 1][0],
                                        "y2": pts[i + 1][1],
                                        "width": width,
                                    },
                                )
                            )
                except ValueError:
                    continue

        elif stype == "CIRCLE" and len(parts) >= 5:
            # format CIRCLE~cx~cy~r~layer~id...
            try:
                cx = (float(parts[1]) - base_x) * unit_to_mm
                cy = (float(parts[2]) - base_y) * unit_to_mm * -1.0
                r = float(parts[3]) * unit_to_mm
                outline.append(DrawCommand(type="circle", params={"x": cx, "y": cy, "r": r}))
            except ValueError:
                continue

    courtyard_w = 0.0
    courtyard_h = 0.0
    if pads:
        max_x = max(abs(p.position[0]) + p.size[0] / 2 for p in pads)
        max_y = max(abs(p.position[1]) + p.size[1] / 2 for p in pads)
        courtyard_w = (max_x + 0.5) * 2
        courtyard_h = (max_y + 0.5) * 2

    return FootprintDef(
        pads=pads,
        outline=outline,
        courtyard=(courtyard_w, courtyard_h),
        source="easyeda",
        description=head.get("c_para", {}).get("package", ""),
    )


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
            # format P~type~x~y...  type is usually something like show~0~1~x~y~rot
            # P~show~0~1~-20~0~180~...
            if len(parts) >= 7:
                try:
                    # In schematic, units are roughly pixels or 10mils
                    # Just need relative coords. Usually 1 unit = 0.1 inch = 2.54mm visually
                    # We'll scale by 10 for drawing
                    scale = 1.0

                    px = float(parts[4]) * scale
                    py = float(parts[5]) * scale * -1.0  # Invert Y

                    pin_id = parts[3]

                    sym_pins.append(
                        SymbolPin(
                            id=pin_id,
                            name=pin_id,
                            position=(px, py),
                            length=5.0,
                            orientation="left",  # Simplified
                            electrical_type="passive",
                        )
                    )
                except ValueError:
                    continue

        elif stype == "PL":  # Polyline
            # PL~path~color...
            # path is e.g. -5 8 -5 -8
            if len(parts) >= 2:
                path_str = parts[1].split()
                try:
                    if len(path_str) >= 4:
                        for i in range(0, len(path_str) - 2, 2):
                            x1 = float(path_str[i])
                            y1 = float(path_str[i + 1]) * -1.0
                            x2 = float(path_str[i + 2])
                            y2 = float(path_str[i + 3]) * -1.0
                            body.append(DrawCommand(type="line", params={"x1": x1, "y1": y1, "x2": x2, "y2": y2}))
                except ValueError:
                    continue

        elif stype == "PT":  # Polygon/Path
            # PT~svg path~...
            pass

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
