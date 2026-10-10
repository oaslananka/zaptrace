"""Instance a digest-verified KiCad footprint without redrawing vendor artwork.

The original .kicad_mod remains byte-identical in the portable library. Its
S-expression children (pads, F.CrtYd/antenna keepouts, silk/fab lines, models)
are copied semantically into the board; only instance identity, location, and
nets change. This avoids falsely presenting a pads-only replica as a library
footprint and keeps the unmodified source as the audit authority.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable

from zaptrace.core.models import Component
from zaptrace.io.sexp import SexpNode, parse, write
from zaptrace.kicad.verified_vendor import verified_footprint_bytes

_QUOTE_ATOM_POSITIONS: dict[str, set[int]] = {
    "footprint": {1},
    "property": {1, 2},
    "pad": {1},
    "fp_text": {2},
    "layer": {1},
    "layers": {1, 2, 3, 4, 5},
    "net": {2},
    "model": {1},
    "uuid": {1},
    "descr": {1},
    "tags": {1},
}


def _kicad_format(node: SexpNode, indent: int = 0) -> str:
    """Keep S-expression identifiers on the same line as opening brackets.

    Quote KiCad's identifier/string fields even when the value is a bare word.
    Nested records retain complete supplier geometry, drills, models and zones.
    """
    if isinstance(node, str):
        return write(node)
    if not node or not isinstance(node[0], str):
        raise ValueError("Malformed vendor S-expression")
    kind = node[0]
    atoms: list[str] = []
    parts: list[str] = []
    nested = False
    for pos, value in enumerate(node):
        if isinstance(value, str) and not nested:
            atoms.append(json.dumps(value) if pos in _QUOTE_ATOM_POSITIONS.get(kind, set()) else write(value))
        else:
            nested = True
            if not isinstance(value, list):
                raise ValueError("Unsupported nested S-expression")
            parts.append("  " * (indent + 1) + _kicad_format(value, indent + 1))
    out = "(" + " ".join(atoms)
    if parts:
        out += "\n" + "\n".join(parts) + "\n" + "  " * indent
    return out + ")"


def _form(node: SexpNode, kind: str) -> bool:
    return isinstance(node, list) and len(node) > 0 and node[0] == kind


def _board_zone_coordinates(zone: list[SexpNode], at: tuple[float, float], copper_layers: list[str]) -> None:
    """Convert vendor-local footprint rule-area points to board coordinates.

    KiCad stores a footprint's antenna/keepout zone points in *board* space,
    unlike its local pad and artwork coordinates. The layer set is constrained
    to real layers of the board, just as KiCad native footprint placement does.
    """
    if not copper_layers:
        raise ValueError("No installed copper layers for verified footprint rule area")

    seen_polygon = False
    seen_layers = False
    updated: list[SexpNode] = [zone[0]]
    for item in zone[1:]:
        if not isinstance(item, list) or not item:
            raise ValueError("Invalid supplier footprint zone")
        kind = item[0]
        if kind in {"net", "net_name", "filled_areas_thickness"}:
            continue
        if kind == "layers":
            active = [layer for layer in item[1:] if isinstance(layer, str) and layer in copper_layers]
            if not active:
                raise ValueError("Vendor keepout applies to no installed copper layer")
            updated.append(["layers", *active])
            seen_layers = True
        elif kind == "polygon":
            for pts in item[1:]:
                if not isinstance(pts, list) or not pts or pts[0] != "pts":
                    raise ValueError("Unsupported footprint zone polygon geometry")
                for point in pts[1:]:
                    if not isinstance(point, list) or len(point) != 3 or point[0] != "xy":
                        raise ValueError("Malformed vendor footprint zone coordinate")
                    x, y = float(str(point[1])), float(str(point[2]))
                    if not math.isfinite(x) or not math.isfinite(y):
                        raise ValueError("Nonfinite vendor footprint zone point")
                    x_text = f"{x + at[0]:.5f}".rstrip("0").rstrip(".")
                    y_text = f"{y + at[1]:.5f}".rstrip("0").rstrip(".")
                    point[1] = "0" if x_text in {"", "-0"} else x_text
                    point[2] = "0" if y_text in {"", "-0"} else y_text
            updated.append(item)
            seen_polygon = True
        else:
            updated.append(item)

    if not (seen_polygon and seen_layers):
        raise ValueError("Verified rule-area footprint missing layer/shape")
    zone[:] = updated


def _instance_identity(node: SexpNode, ref: str, path: str, uuid_for: Callable[[str], str]) -> None:
    if not isinstance(node, list):
        return
    if node and node[0] in {"tstamp", "uuid"} and len(node) == 2:
        node[:] = ["uuid", uuid_for(f"vendor-{ref}-{path}")]
        return
    for index, child in enumerate(node):
        _instance_identity(child, ref, f"{path}.{index}", uuid_for)


def render_verified_footprint(
    component: Component,
    at: tuple[float, float],
    net_index: dict[str, int],
    net_name: Callable[[int], str],
    uuid_for: Callable[[str], str],
    copper_layers: list[str],
) -> str:
    """Build a KiCad board footprint from a digest-pinned, unmodified source.

    Pin IDs and net mappings must have been validated by the caller's
    _physical_footprint_library_id check before using this function.
    """
    asset = component.footprint_asset
    if not asset:
        raise ValueError("Verified footprint embedding requires a pinned asset")
    filename, content = verified_footprint_bytes(asset)
    root = parse(content.decode("utf-8"))
    if not _form(root, "footprint") or not isinstance(root, list) or root[1] != filename.removesuffix(".kicad_mod"):
        raise ValueError(f"Malformed verified footprint {asset!r}")

    footprint: list[SexpNode] = [
        "footprint",
        f"ZapTrace:{root[1]}",
        ["layer", "F.Cu"],
        ["uuid", uuid_for(f"footprint-{component.ref}")],
        ["at", str(at[0]), str(at[1]), "0"],
    ]
    mapped_pads: set[str] = set()
    for idx, child in enumerate(root[2:]):
        if not isinstance(child, list) or not child:
            raise ValueError("Unexpected source footprint expression")
        kind = str(child[0])
        if kind in {"version", "generator", "generator_version", "layer", "embedded_fonts"}:
            continue
        if kind in {"uuid", "tstamp", "at"}:
            # These fields belong to the library root, not its board instance.
            continue
        if kind == "zone":
            _board_zone_coordinates(child, at, copper_layers)
        if kind == "property" and len(child) >= 3:
            if child[1] == "Reference":
                child[2] = component.ref
            elif child[1] == "Value" and component.value:
                child[2] = component.value
        if kind == "fp_text" and len(child) >= 3:
            # KiCad <8 legacy library fields become named footprint
            # properties on the board; text geometry stays from vendor.
            if child[1] == "reference":
                child[:3] = ["property", "Reference", component.ref]
            elif child[1] == "value":
                child[:3] = ["property", "Value", component.value or str(child[2])]
        if kind == "pad" and len(child) >= 3:
            pad_id = str(child[1])
            logical_pin = component.package_pin_map.get(pad_id) if component.package_pin_map else pad_id
            if logical_pin is not None and logical_pin in component.pins:
                pin_net = component.pins[logical_pin].net
                if pin_net in net_index:
                    num = net_index[pin_net]
                    child.append(["net", str(num), net_name(num)])
                    mapped_pads.add(pad_id)
        _instance_identity(child, component.ref, str(idx), uuid_for)
        if kind == "pad":
            # Match KiCad's usual field order for exact net/UUID evidence.
            ids = [field for field in child[3:] if _form(field, "uuid")]
            child[:] = child[:3] + [field for field in child[3:] if not _form(field, "uuid")] + ids
        footprint.append(child)

    expected = set(component.package_pin_map) if component.package_pin_map else set(component.pins)
    if not expected.issubset(mapped_pads):
        raise ValueError(f"Verified footprint failed to bind all mapped nets: {component.ref!r}")

    return _kicad_format(footprint)
