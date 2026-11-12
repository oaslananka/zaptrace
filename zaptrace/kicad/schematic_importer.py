"""KiCad schematic (.kicad_sch) import with verified net identity (issue #117).

Parses a flat KiCad schematic into the canonical ZapTrace Design model,
resolving wires, labels, junctions, symbols, and pins into deterministic
connectivity while preserving unsupported records as structured evidence.

Supported constructs
--------------------
* ``(symbol ...)``  — component instances with ref/value properties
* ``(wire ...)``    — single-segment wire (start/end coordinates)
* ``(junction ...)`` — explicit wire crossing junction
* ``(label ...)``, ``(global_label ...)``, ``(hierarchical_label ...)`` — net naming
* ``(no_connect ...)`` — unconnected pin marker (suppresses dangling-wire warning)
* one-pin library ``(power)`` + ``power_in`` symbols — global net names
* ``(net_tie ...)`` — noted as unsupported; does not fail import

Connectivity resolution
-----------------------
1. All wire endpoints are collected.
2. Wire segments are merged into connected groups via union-find, expanded by
   junction points that lie on any wire.
3. Each named group follows KiCad's verified global > power > local >
   hierarchical label priority, with root-sheet local name qualification.
   Unnamed groups use embedded symbol pin metadata when unambiguous, or a
   deterministic fallback when the original native name cannot be proven.
4. Symbol pins are assigned to the matching wire group using source pin
   geometry; library/explicit no-connect pins remain singleton native nets.
5. The result retains the original UTF-8 source byte sequence and readable
   page/presentation evidence for source-backed review. This is not a
   lossless conversion of schematic graphics into the editable Design model.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zaptrace.core.models import (
    Component,
    Design,
    DesignMeta,
    ImportLossRecord,
    Net,
    NetNode,
)
from zaptrace.io.sexp import SexpNode
from zaptrace.io.sexp import parse as _sexp_parse

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SchematicUnsupportedRecord:
    """A KiCad schematic construct that could not be fully imported."""

    kind: str
    message: str
    severity: str = "warning"
    source: str = ""  # "line:<n>" or xref

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "message": self.message,
            "severity": self.severity,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class KiCadSchematicSourceSnapshot:
    """Exact source bytes and independently accessible page/presentation evidence.

    Retention is *not* conversion into ZapTrace's editable Design fields.
    Unmapped constructs must remain visible in the unsupported ledger.
    The original byte sequence permits later lossless inspection even if
    a temporary project directory or the original source file disappears.
    """

    raw_bytes: bytes
    sha256: str
    paper: str | None
    title_block: dict[str, str]
    embedded_fonts: str | None
    top_level_counts: dict[str, int]

    def nodes(self, kind: str) -> list[list[SexpNode]]:
        """Recover original parsed top-level KiCad constructs on demand."""
        tree = _sexp_parse(self.raw_bytes.decode("utf-8"))
        if not isinstance(tree, list):
            raise ValueError("Invalid retained schematic source")
        return _find_all(tree, kind)

    def to_dict(self) -> dict[str, Any]:
        """Safe, small evidence summary: exclude full potentially private source."""
        return {
            "sha256": self.sha256,
            "byte_size": len(self.raw_bytes),
            "paper": self.paper,
            "title_block": dict(self.title_block),
            "embedded_fonts": self.embedded_fonts,
            "top_level_counts": dict(self.top_level_counts),
            "retention_scope": "original source bytes; canonical edit/export fidelity not verified",
        }


def _source_title_fields(title: list[SexpNode] | None) -> dict[str, str]:
    """Extract original title and indexed comments without dropping other nodes."""
    if title is None:
        return {}
    fields: dict[str, str] = {}
    for entry in title[1:]:
        if not isinstance(entry, list) or not entry:
            continue
        if _atom(entry, 0) == "comment" and len(entry) > 2:
            fields[f"comment_{_atom(entry, 1)}"] = _atom(entry, 2)
        elif len(entry) > 1:
            fields[_atom(entry, 0)] = _atom(entry, 1)
    return fields


def _source_snapshot(sexp: list[SexpNode], content: str) -> KiCadSchematicSourceSnapshot:
    """Capture exactly the input UTF-8 sequence plus readable native page data."""
    raw = content.encode("utf-8")
    paper = _find(sexp, "paper")
    fonts = _find(sexp, "embedded_fonts")
    fields = _source_title_fields(_find(sexp, "title_block"))
    counts: dict[str, int] = {}
    for entry in sexp[1:]:
        if isinstance(entry, list) and entry:
            kind = _atom(entry, 0)
            counts[kind] = counts.get(kind, 0) + 1
    return KiCadSchematicSourceSnapshot(
        raw_bytes=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        paper=_atom(paper) if paper is not None else None,
        title_block=fields,
        embedded_fonts=_atom(fonts) if fonts is not None else None,
        top_level_counts=dict(sorted(counts.items())),
    )


@dataclass
class KiCadSchematicImportResult:
    """Result of importing a .kicad_sch file.

    Attributes
    ----------
    design:
        The canonical ZapTrace Design derived from the schematic.
    unsupported:
        Schematic constructs that could not be fully mapped.
    source_path:
        The original .kicad_sch file path, if available.
    net_score:
        Fraction of design nets that have at least one component connection
        (1.0 means all nets are resolved). Ranges [0, 1].
    source_snapshot:
        Original bytes and page/presentation evidence retained independently
        of the editable Design. Does not waive unsupported construct findings.
    """

    design: Design
    unsupported: list[SchematicUnsupportedRecord] = field(default_factory=list)
    source_path: Path | None = None
    net_score: float = 1.0
    source_snapshot: KiCadSchematicSourceSnapshot | None = None

    @property
    def unsupported_count(self) -> int:
        return len(self.unsupported)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path) if self.source_path else None,
            "component_count": len(self.design.components),
            "net_count": len(self.design.nets),
            "unsupported_count": self.unsupported_count,
            "net_score": self.net_score,
            "source_sha256": self.source_snapshot.sha256 if self.source_snapshot else None,
            "source_byte_size": len(self.source_snapshot.raw_bytes) if self.source_snapshot else 0,
            "source_evidence": self.source_snapshot.to_dict() if self.source_snapshot else None,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Coordinate precision: treat coordinates within this distance as equal.
_COORD_EPSILON: float = 0.01  # 1 mil in mm


def _coord(node: list[SexpNode]) -> tuple[float, float]:
    """Extract (x, y) from ``(at x y ...)`` or ``(xy x y)``."""
    try:
        return float(str(node[1])), float(str(node[2]))
    except (IndexError, ValueError):
        return 0.0, 0.0


def _find(nodes: list[SexpNode], tag: str) -> list[SexpNode] | None:
    """Return the first child list whose head atom equals *tag*, or None."""
    for n in nodes:
        if isinstance(n, list) and n and n[0] == tag:
            return n  # type: ignore[return-value]
    return None


def _find_all(nodes: list[SexpNode], tag: str) -> list[list[SexpNode]]:
    """Return all child lists whose head atom equals *tag*."""
    return [n for n in nodes if isinstance(n, list) and n and n[0] == tag]  # type: ignore[return-value]


def _atom(node: list[SexpNode], index: int = 1) -> str:
    """Safely extract a string atom at *index* from a list node."""
    try:
        v = node[index]
        return str(v) if isinstance(v, str) else ""
    except IndexError:
        return ""


def _prop(nodes: list[SexpNode], key: str) -> str:
    """Return the value of the first ``(property "key" "value" ...)`` child."""
    for n in nodes:
        if isinstance(n, list) and len(n) >= 3 and n[0] == "property" and n[1] == key:
            return str(n[2])
    return ""


# ---------------------------------------------------------------------------
# Union-find for connectivity
# ---------------------------------------------------------------------------


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[int, int] = {}

    def _make(self, x: int) -> None:
        if x not in self._parent:
            self._parent[x] = x

    def find(self, x: int) -> int:
        self._make(x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        self._make(x)
        self._make(y)
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self._parent[ry] = rx

    def groups(self) -> dict[int, list[int]]:
        grps: dict[int, list[int]] = {}
        for k in self._parent:
            r = self.find(k)
            grps.setdefault(r, []).append(k)
        return grps


# ---------------------------------------------------------------------------
# Embedded library-symbol pin geometry
# ---------------------------------------------------------------------------


def _nested_pin_definitions(node: list[SexpNode]) -> list[list[SexpNode]]:
    """Return KiCad library pin definitions nested under one symbol definition."""
    pins: list[list[SexpNode]] = []
    for child in node:
        if not isinstance(child, list) or not child:
            continue
        if child[0] == "pin" and len(child) > 2 and _find(child, "number") is not None:
            pins.append(child)
        else:
            pins.extend(_nested_pin_definitions(child))
    return pins


def _embedded_library_pins(sexp: list[SexpNode]) -> dict[str, dict[str, tuple[float, float]]]:
    """Map embedded ``lib_symbols`` IDs to local pin connection coordinates."""
    lib_symbols = _find(sexp, "lib_symbols")
    if lib_symbols is None:
        return {}
    libraries: dict[str, dict[str, tuple[float, float]]] = {}
    for symbol in _find_all(lib_symbols, "symbol"):
        lib_id = _atom(symbol, 1)
        if not lib_id:
            continue
        pins: dict[str, tuple[float, float]] = {}
        for pin in _nested_pin_definitions(symbol):
            number_node = _find(pin, "number")
            at_node = _find(pin, "at")
            if number_node is None or at_node is None:
                continue
            number = _atom(number_node, 1)
            if number:
                pins[number] = _coord(at_node)
        libraries[lib_id] = pins
    return libraries


def _embedded_library_pin_names(sexp: list[SexpNode]) -> dict[str, dict[str, str]]:
    """Read pin names from the immutable embedded KiCad symbol definitions."""
    libraries = _find(sexp, "lib_symbols")
    if libraries is None:
        return {}
    output: dict[str, dict[str, str]] = {}
    for symbol in _find_all(libraries, "symbol"):
        lib_id = _atom(symbol)
        if not lib_id:
            continue
        pin_names: dict[str, str] = {}
        for pin in _nested_pin_definitions(symbol):
            number = _atom(_find(pin, "number") or [])
            if number:
                pin_names[number] = _atom(_find(pin, "name") or [])
        output[lib_id] = pin_names
    return output


def _embedded_library_pin_types(sexp: list[SexpNode]) -> dict[str, dict[str, str]]:
    """Read KiCad electrical pin types, including library-defined no-connect pins."""
    library = _find(sexp, "lib_symbols")
    if library is None:
        return {}
    output: dict[str, dict[str, str]] = {}
    for symbol in _find_all(library, "symbol"):
        lib_id = _atom(symbol)
        if lib_id:
            output[lib_id] = {
                number: _atom(pin, 1)
                for pin in _nested_pin_definitions(symbol)
                if (number := _atom(_find(pin, "number") or []))
            }
    return output


def _embedded_power_pin_labels(sexp: list[SexpNode]) -> dict[str, tuple[str, str, bool]]:
    """Resolve a KiCad power-input library pin and how it names its net.

    An embedded ``(power)`` marker and one ``power_in`` pin are
    mandatory. Legacy symbols with named pins use the library pin name.
    KiCad 10 power symbols with unnamed pins use the instance Value as
    their global net name; changing that value can change connectivity.
    Power-output flags are never converted to global labels.
    """
    libraries = _find(sexp, "lib_symbols")
    if libraries is None:
        return {}
    labels: dict[str, tuple[str, str, bool]] = {}
    for symbol in _find_all(libraries, "symbol"):
        if _find(symbol, "power") is None:
            continue
        pins = _nested_pin_definitions(symbol)
        if len(pins) != 1 or _atom(pins[0]) != "power_in":
            continue
        number = _atom(_find(pins[0], "number") or [])
        name = _atom(_find(pins[0], "name") or [])
        value_driven = not name or name == "~"
        if value_driven:
            # A modern library's Value supplies the default, but the
            # instance Value is authoritative for the actual named net.
            name = _prop(symbol, "Value")
        lib_id = _atom(symbol)
        if lib_id and number and name and name != "~":
            labels[lib_id] = number, name, value_driven
    return labels


def _rotate_local_pin(
    local: tuple[float, float],
    origin: tuple[float, float],
    angle_deg: float,
    mirror: str = "",
) -> tuple[float, float]:
    """Map KiCad library pin coordinates to sheet-space with rotation/mirroring.

    Library +Y points up; schematic sheet +Y points down. KiCad's symbol
    rotation angle is mathematical (counter-clockwise) before sheet inversion.
    The optional instance mirror is applied in sheet-space after rotation.
    """
    radians = math.radians(angle_deg)
    cos_angle = math.cos(radians)
    sin_angle = math.sin(radians)
    local_x, local_y = local
    dx = local_x * cos_angle - local_y * sin_angle
    dy = -local_x * sin_angle - local_y * cos_angle
    if mirror == "x":
        dy = -dy
    elif mirror == "y":
        dx = -dx
    origin_x, origin_y = origin
    return origin_x + dx, origin_y + dy


def _instance_pin_coordinates(
    node: list[SexpNode],
    lib_id: str,
    origin: tuple[float, float],
    angle: float,
    library_pins: dict[str, dict[str, tuple[float, float]]],
    mirror: str = "",
) -> list[tuple[str, float, float]]:
    """Resolve standard KiCad instance pin UUID records through embedded geometry."""
    definitions = library_pins.get(lib_id, {})
    coordinates: list[tuple[str, float, float]] = []
    for child in node:
        if not isinstance(child, list) or not child or child[0] != "pin":
            continue
        pin_name = _atom(child, 1)
        local = definitions.get(pin_name)
        if local is None:
            continue
        x, y = _rotate_local_pin(local, origin, angle, mirror)
        coordinates.append((pin_name, x, y))
    return coordinates


# ---------------------------------------------------------------------------
# Schematic parser
# ---------------------------------------------------------------------------


_LABEL_TAGS = ("label", "global_label", "hierarchical_label")

_NOTED_UNSUPPORTED_TAGS = (
    "version",
    "generator",
    "generator_version",
    "uuid",
    "title_block",
    "lib_symbols",
    "sheet",
    "sheet_instances",
    "symbol_instances",
    "net_tie_pad_groups",
    "bus",
    "bus_entry",
    "image",
    "polyline",
    "arc",
    "circle",
    "rectangle",
    "text",
    "text_box",
    "embedded_files",
    "rule_area",
)


def _handle_wire_tag(
    node: list[SexpNode],
    wires: list[tuple[tuple[float, float], tuple[float, float]]],
    unsupported: list[SchematicUnsupportedRecord],
) -> None:
    pts = _find(node, "pts")
    if not pts:
        return
    xy_nodes = _find_all(pts, "xy")
    if len(xy_nodes) == 2:
        wires.append((_coord(xy_nodes[0]), _coord(xy_nodes[1])))
    else:
        unsupported.append(
            SchematicUnsupportedRecord(
                kind="wire_malformed",
                message=f"wire with {len(xy_nodes)} points",
                severity="warning",
            )
        )


def _handle_junction_tag(node: list[SexpNode], junctions: list[tuple[float, float]]) -> None:
    at = _find(node, "at")
    if at:
        junctions.append(_coord(at))


def _handle_label_tag(node: list[SexpNode], tag: str, labels: list[tuple[str, str, tuple[float, float]]]) -> None:
    at = _find(node, "at")
    coord = _coord(at) if at else (0.0, 0.0)
    name = _atom(node, 1)
    labels.append((name, tag, coord))


def _parse_schematic(
    sexp: list[SexpNode],
) -> tuple[
    list[dict[str, Any]],  # symbols (component instances)
    list[tuple[tuple[float, float], tuple[float, float]]],  # wires
    list[tuple[float, float]],  # junctions
    list[tuple[str, str, tuple[float, float]]],  # labels: (name, kind, coord)
    list[SchematicUnsupportedRecord],
]:
    """Parse a top-level kicad_sch S-expression into raw schematic objects."""
    library_pins = _embedded_library_pins(sexp)
    library_pin_names = _embedded_library_pin_names(sexp)
    power_pin_labels = _embedded_power_pin_labels(sexp)
    symbols: list[dict[str, Any]] = []
    wires: list[tuple[tuple[float, float], tuple[float, float]]] = []
    junctions: list[tuple[float, float]] = []
    labels: list[tuple[str, str, tuple[float, float]]] = []
    unsupported: list[SchematicUnsupportedRecord] = []

    for node in sexp[1:]:  # skip "kicad_sch"
        if not isinstance(node, list) or not node:
            continue
        tag = str(node[0])

        if tag == "symbol":
            _parse_symbol(node, symbols, unsupported, library_pins, library_pin_names)
            instance = symbols[-1]
            power_label = power_pin_labels.get(instance["lib_id"])
            if power_label is not None:
                pin_number, library_name, value_driven = power_label
                power_name = (instance["value"] or library_name) if value_driven else library_name
                if power_name and power_name != "~":
                    for number, x, y in instance["pins"]:
                        if number == pin_number:
                            labels.append((power_name, "power_symbol", (x, y)))
                            break
        elif tag == "wire":
            _handle_wire_tag(node, wires, unsupported)
        elif tag == "junction":
            _handle_junction_tag(node, junctions)
        elif tag in _LABEL_TAGS:
            _handle_label_tag(node, tag, labels)
        elif tag == "no_connect":
            pass  # intentionally skipped
        elif tag in _NOTED_UNSUPPORTED_TAGS:
            unsupported.append(
                SchematicUnsupportedRecord(
                    kind=tag,
                    message=f"Schematic construct '{tag}' noted but not fully mapped",
                    severity="info",
                )
            )
        else:
            unsupported.append(
                SchematicUnsupportedRecord(
                    kind=f"unknown_{tag}",
                    message=f"Unknown schematic construct '{tag}'",
                    severity="warning",
                )
            )

    return symbols, wires, junctions, labels, unsupported


def _parse_pin_coordinate(child: list[SexpNode]) -> tuple[str, float, float] | None:
    pin_name = _atom(child, 1)
    pin_at = _find(child, "at")
    if pin_at:
        pin_x, pin_y = _coord(pin_at)
        return pin_name, pin_x, pin_y
    try:
        return pin_name, float(str(child[2])), float(str(child[3]))
    except (IndexError, ValueError):
        return None


def _symbol_pin_coordinates(node: list[SexpNode]) -> list[tuple[str, float, float]]:
    coordinates: list[tuple[str, float, float]] = []
    for child in node:
        if not isinstance(child, list) or not child or child[0] != "pin":
            continue
        coordinate = _parse_pin_coordinate(child)
        if coordinate is not None:
            coordinates.append(coordinate)
    return coordinates


def _parse_symbol(
    node: list[SexpNode],
    symbols: list[dict[str, Any]],
    unsupported: list[SchematicUnsupportedRecord],
    library_pins: dict[str, dict[str, tuple[float, float]]] | None = None,
    library_pin_names: dict[str, dict[str, str]] | None = None,
) -> None:
    """Extract component instance data from a ``(symbol ...)`` node."""
    lib_id_node = _find(node, "lib_id")
    lib_id = _atom(lib_id_node) if lib_id_node else ""
    at_node = _find(node, "at")
    at_coord = _coord(at_node) if at_node else (0.0, 0.0)
    at_angle = float(str(at_node[3])) if at_node and len(at_node) > 3 else 0.0

    ref = _prop(node, "Reference")
    value = _prop(node, "Value")
    footprint = _prop(node, "Footprint")
    unit_node = _find(node, "unit")
    unit = int(_atom(unit_node)) if unit_node else 1

    pin_coords = _symbol_pin_coordinates(node)
    if not pin_coords and library_pins:
        mirror_node = _find(node, "mirror")
        mirror_axis = _atom(mirror_node) if mirror_node else ""
        if mirror_axis not in {"", "x", "y"}:
            unsupported.append(
                SchematicUnsupportedRecord(
                    kind="unsupported_symbol_mirror",
                    message=f"Symbol '{ref}' has unsupported mirror axis",
                    severity="warning",
                )
            )
        else:
            pin_coords = _instance_pin_coordinates(node, lib_id, at_coord, at_angle, library_pins, mirror_axis)

    symbols.append(
        {
            "lib_id": lib_id,
            "ref": ref,
            "value": value,
            "footprint": footprint,
            "at": at_coord,
            "angle": at_angle,
            "unit": unit,
            "pins": pin_coords,
            "pin_library_names": library_pin_names.get(lib_id) if library_pin_names else None,
        }
    )

    # Only record meaningful unsupported attributes, not every missing optional
    if not ref:
        unsupported.append(
            SchematicUnsupportedRecord(
                kind="symbol_missing_ref",
                message=f"Symbol '{lib_id}' has no Reference property",
                severity="warning",
            )
        )


# ---------------------------------------------------------------------------
# Connectivity resolution
# ---------------------------------------------------------------------------


# KiCad 10 net-name precedence: global > power > local > hierarchical.
_KIND_PRIORITY = {"global_label": 0, "power_symbol": 1, "label": 2, "hierarchical_label": 3}


def _quantise(xy: tuple[float, float]) -> tuple[int, int]:
    """Stable millimetre-to-grid conversion across KiCad pin transforms.

    A transformed coordinate such as 169.54500000000002 and a literal wire
    endpoint 169.545 are electrically identical. Python's binary banker's
    rounding can put them on opposite sides of a half-grid boundary.
    """

    def snap(value: float) -> int:
        scaled = round(value / _COORD_EPSILON, 8)
        nearest = math.floor(abs(scaled) + 0.5)
        return -nearest if scaled < 0 else nearest

    return snap(xy[0]), snap(xy[1])


def _get_or_add_coord(
    xy: tuple[float, float],
    coords: list[tuple[float, float]],
    coord_idx: dict[tuple[int, int], int],
) -> int:
    q = _quantise(xy)
    if q not in coord_idx:
        coord_idx[q] = len(coords)
        coords.append(xy)
    return coord_idx[q]


def _union_wires(
    wires: list[tuple[tuple[float, float], tuple[float, float]]],
    coords: list[tuple[float, float]],
    coord_idx: dict[tuple[int, int], int],
    uf: _UnionFind,
) -> None:
    for start, end in wires:
        si = _get_or_add_coord(start, coords, coord_idx)
        ei = _get_or_add_coord(end, coords, coord_idx)
        uf.union(si, ei)


def _merge_junctions(
    junctions: list[tuple[float, float]],
    wires: list[tuple[tuple[float, float], tuple[float, float]]],
    coords: list[tuple[float, float]],
    coord_idx: dict[tuple[int, int], int],
    uf: _UnionFind,
) -> None:
    # Only an explicit junction joins intersecting wires. A wire crossing
    # without this marker must remain two separate electrical nets.
    # KiCad also places junctions where a wire endpoint touches the interior
    # of another wire, even when that long segment is not split.
    for junction in junctions:
        ji = _get_or_add_coord(junction, coords, coord_idx)
        for start, end in wires:
            if _point_on_wire(junction, start, end):
                uf.union(ji, coord_idx[_quantise(start)])


def _point_on_wire(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    """Check a label's *physical* position, not a fuzzy nearby-grid match."""
    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    scale = max(abs(dx), abs(dy))
    if scale == 0:
        return abs(px - ax) <= 1e-6 and abs(py - ay) <= 1e-6
    return (
        abs((px - ax) * dy - (py - ay) * dx) <= 1e-6 * scale
        and min(ax, bx) - 1e-6 <= px <= max(ax, bx) + 1e-6
        and min(ay, by) - 1e-6 <= py <= max(ay, by) + 1e-6
    )


def _group_labels(
    labels: list[tuple[str, str, tuple[float, float]]],
    coords: list[tuple[float, float]],
    coord_idx: dict[tuple[int, int], int],
    uf: _UnionFind,
    wires: list[tuple[tuple[float, float], tuple[float, float]]] | None = None,
    unsupported: list[SchematicUnsupportedRecord] | None = None,
) -> dict[int, list[tuple[str, str]]]:
    # KiCad allows a net label on a wire's interior, not just its endpoints.
    # A geometric crossing without an explicit junction is NOT a connection.
    # Do not merge two independent wire groups just because a label overlaps
    # their crossing; preserve an unsupported warning instead.
    if wires:
        endpoints = {_quantise(point) for start, end in wires for point in (start, end)}
        for name, _kind, point in labels:
            q = _quantise(point)
            if q in endpoints:
                continue
            candidates = {
                uf.find(coord_idx[_quantise(start)]) for start, end in wires if _point_on_wire(point, start, end)
            }
            if len(candidates) == 1:
                wire_root = next(iter(candidates))
                label_index = _get_or_add_coord(point, coords, coord_idx)
                uf.union(wire_root, label_index)
            elif len(candidates) > 1 and unsupported is not None:
                unsupported.append(
                    SchematicUnsupportedRecord(
                        kind="ambiguous_wire_label_crossing",
                        message=f"Net label '{name}' overlaps independent crossing wires",
                        severity="warning",
                    )
                )

    label_groups: dict[int, list[tuple[str, str]]] = {}
    for lname, lkind, lcoord in labels:
        li = _get_or_add_coord(lcoord, coords, coord_idx)
        r = uf.find(li)
        label_groups.setdefault(r, []).append((lname, lkind))
    return label_groups


def _best_name(group_labels: list[tuple[str, str]]) -> str:
    """Choose KiCad's highest-priority, alphabetically first explicit name.

    The schematic importer treats each file as one root sheet. KiCad's
    exported XML includes that sheet's '/' path on local labels, but keeps
    global/power names unqualified. The source format uses '{slash}' as an
    escape for a literal slash in a label's visible text.
    """
    if not group_labels:
        return ""
    label, kind = min(group_labels, key=lambda entry: (_KIND_PRIORITY.get(entry[1], 99), entry[0]))
    readable_name = label.replace("{slash}", "/")
    return "/" + readable_name if kind == "label" else readable_name


_NONPHYSICAL_KICAD_REFS = ("#PWR", "#FLG")


def _register_direct_pin_contacts(
    symbols: list[dict[str, Any]],
    coords: list[tuple[float, float]],
    coord_idx: dict[tuple[int, int], int],
    uf: _UnionFind,
) -> None:
    """KiCad joins directly touching physical pins, even without any wire.

    A single dangling pin is not evidence of an electrical net. Only create
    a contact point for coincident pins of *distinct* components; stacked
    pins on one instance alone do not establish a fabricated external net.
    Exclude power/flag annotations, which are handled by their own labels.
    """
    contacts: dict[tuple[int, int], set[str]] = {}
    positions: dict[tuple[int, int], tuple[float, float]] = {}
    for symbol in symbols:
        ref = symbol["ref"]
        if not ref or ref.startswith(_NONPHYSICAL_KICAD_REFS):
            continue
        for _number, x, y in symbol["pins"]:
            q = _quantise((x, y))
            contacts.setdefault(q, set()).add(ref)
            positions.setdefault(q, (x, y))
    for q, refs in contacts.items():
        if len(refs) >= 2:
            uf.find(_get_or_add_coord(positions[q], coords, coord_idx))


def _group_pins(
    symbols: list[dict[str, Any]],
    coord_idx: dict[tuple[int, int], int],
    uf: _UnionFind,
) -> dict[int, list[tuple[str, str]]]:
    group_pins: dict[int, list[tuple[str, str]]] = {}  # root → [(ref, pin_name)]
    for sym in symbols:
        ref = sym["ref"]
        # Power/flag symbols name or validate nets but are not physical pins
        # in KiCad's XML netlist. Keep the original symbol in design.components.
        if ref.startswith(_NONPHYSICAL_KICAD_REFS):
            continue
        for pin_name, px, py in sym["pins"]:
            q = _quantise((px, py))
            if q in coord_idx:
                gi = coord_idx[q]
                r = uf.find(gi)
                group_pins.setdefault(r, []).append((ref, pin_name))
    return group_pins


_AUTO_PIN_NET_TOKEN = re.compile(r"[A-Za-z0-9_.+-]+")


def _auto_generated_pin_net_name(
    pins: list[tuple[str, str]],
    ref_pin_names: dict[str, dict[str, str]],
) -> str:
    """Conservative KiCad 'Net-(ref-pin)' naming for fully identified pins.

    A user-visible library pin name takes priority over a generic pad number.
    If any physical pin lacks verified library metadata, has an unannotated
    reference, or has a duplicated/unsafe name, retain the legacy stable
    fallback rather than fabricating a KiCad-compatible name.
    """
    if not pins:
        return ""
    candidates: list[tuple[bool, str]] = []
    for ref, number in set(pins):
        names = ref_pin_names.get(ref)
        if not ref or ref.endswith("?") or ref.startswith("#") or names is None or number not in names:
            return ""
        pin_name = names[number]
        named = bool(pin_name and pin_name != "~" and pin_name != number)
        if named and (list(names.values()).count(pin_name) != 1 or _AUTO_PIN_NET_TOKEN.fullmatch(pin_name) is None):
            return ""
        suffix = pin_name if named else f"Pad{number}"
        if _AUTO_PIN_NET_TOKEN.fullmatch(ref) is None or _AUTO_PIN_NET_TOKEN.fullmatch(suffix) is None:
            return ""
        candidates.append((not named, f"Net-({ref}-{suffix})"))
    return min(candidates)[1]


def _name_nets(
    all_roots: set[int],
    label_groups: dict[int, list[tuple[str, str]]],
    group_pins: dict[int, list[tuple[str, str]]],
    ref_pin_names: dict[str, dict[str, str]],
) -> dict[str, list[tuple[str, str]]]:
    nets: dict[str, list[tuple[str, str]]] = {}
    for root in all_roots:
        pins = group_pins.get(root, [])
        net_name = _best_name(label_groups.get(root, []))
        if not net_name:
            net_name = _auto_generated_pin_net_name(pins, ref_pin_names)
        if not net_name:
            # Existing deterministic fallback for incomplete library pin data.
            net_name = "net_" + hashlib.sha256(str(root).encode()).hexdigest()[:8]
        if net_name in nets:
            nets[net_name].extend(pins)
        else:
            nets[net_name] = pins
    return nets


def _merge_flat_label_aliases(
    label_groups: dict[int, list[tuple[str, str]]],
    uf: _UnionFind,
) -> dict[int, list[tuple[str, str]]]:
    """Join matching label text on one flat sheet before name precedence."""
    roots_by_name: dict[str, int] = {}
    for root, entries in label_groups.items():
        for name, _kind in entries:
            key = name.replace("{slash}", "/")
            uf.union(root, roots_by_name.setdefault(key, root))
    merged: dict[int, list[tuple[str, str]]] = {}
    for root, entries in label_groups.items():
        merged.setdefault(uf.find(root), []).extend(entries)
    return merged


def _resolve_connectivity(
    symbols: list[dict[str, Any]],
    wires: list[tuple[tuple[float, float], tuple[float, float]]],
    junctions: list[tuple[float, float]],
    labels: list[tuple[str, str, tuple[float, float]]],
    unsupported: list[SchematicUnsupportedRecord] | None = None,
) -> dict[str, list[tuple[str, str]]]:
    """Resolve wire connectivity into named nets.

    Returns a dict mapping ``net_name → [(ref, pin_name), ...]``.
    """
    coords: list[tuple[float, float]] = []
    coord_idx: dict[tuple[int, int], int] = {}  # quantised coord → index
    uf = _UnionFind()

    _union_wires(wires, coords, coord_idx, uf)
    _merge_junctions(junctions, wires, coords, coord_idx, uf)
    _register_direct_pin_contacts(symbols, coords, coord_idx, uf)
    label_groups = _group_labels(labels, coords, coord_idx, uf, wires, unsupported)

    # Alias connectivity is scoped to this one sheet. The project importer
    # handles separate sheet namespaces; do not cross-connect local labels.
    label_groups = _merge_flat_label_aliases(label_groups, uf)

    group_pins = _group_pins(symbols, coord_idx, uf)

    all_roots = set(uf.groups())
    all_roots.update(label_groups)
    all_roots.update(group_pins)

    ref_pin_names = {
        symbol["ref"]: symbol["pin_library_names"]
        for symbol in symbols
        if symbol.get("ref") and symbol.get("pin_library_names") is not None
    }
    return _name_nets(all_roots, label_groups, group_pins, ref_pin_names)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def import_kicad_schematic(path: str | Path) -> KiCadSchematicImportResult:
    """Import a flat KiCad schematic (.kicad_sch) into a ZapTrace Design.

    This function:
    1. Parses the S-expression content.
    2. Extracts component instances, wires, junctions, and labels.
    3. Resolves connectivity via union-find.
    4. Builds the canonical Design model.
    5. Records unsupported constructs as ImportLossRecord entries.

    Parameters
    ----------
    path:
        Path to a ``.kicad_sch`` file.

    Returns
    -------
    KiCadSchematicImportResult
        The import result including the design, unsupported records, and
        net score.

    Raises
    ------
    ValueError
        If the file is not a valid kicad_sch S-expression.
    OSError
        If the file cannot be read.
    """
    p = Path(path)
    # read_bytes preserves LF/CRLF and all original UTF-8 bytes, not only
    # parser-normalized data. Required for byte-verifiable review evidence.
    content = p.read_bytes().decode("utf-8")
    return import_kicad_schematic_string(content, source_path=p)


def _add_imported_components(design: Design, symbols: list[dict[str, Any]]) -> None:
    seen_refs: set[str] = set()
    for symbol in symbols:
        ref = symbol["ref"]
        if not ref or ref in seen_refs:
            continue
        seen_refs.add(ref)
        component = Component(
            id=re.sub(r"(?a)\W", "_", ref).lower(),
            ref=ref,
            type=symbol["lib_id"].split(":")[-1] if ":" in symbol["lib_id"] else symbol["lib_id"],
            value=symbol["value"],
        )
        design.components[component.id] = component


def _add_imported_nets(design: Design, nets_raw: dict[str, list[tuple[str, str]]]) -> float:
    """Preserve distinct KiCad net names even when their normalized IDs collide.

    For example, USB_D+ and USB_D- both normalize to usb_d_.  Overwriting
    one silently discards connectivity and may make net_score exceed 1.
    """
    nets_with_pins = 0
    for net_name, pin_list in sorted(nets_raw.items()):
        base_id = re.sub(r"(?a)\W", "_", net_name).lower() or "net"
        net_id = base_id
        if net_id in design.nets:
            suffix = hashlib.sha256(net_name.encode("utf-8")).hexdigest()[:12]
            net_id = f"{base_id}_{suffix}"
            counter = 1
            while net_id in design.nets:
                net_id = f"{base_id}_{suffix}_{counter}"
                counter += 1
        nodes = [NetNode(component_ref=ref, pin_name=pin) for ref, pin in pin_list]
        design.nets[net_id] = Net(id=net_id, name=net_name, nodes=nodes)
        if nodes:
            nets_with_pins += 1
    return nets_with_pins / len(nets_raw) if nets_raw else 1.0


def _record_schematic_import_losses(
    design: Design,
    unsupported: list[SchematicUnsupportedRecord],
) -> None:
    for record in unsupported:
        if record.severity not in ("warning", "error"):
            continue
        design.import_losses.append(
            ImportLossRecord(
                source_format="kicad_sch",
                field_path=record.kind,
                behavior="noted",
                original_value=record.message,
                note=f"KiCad schematic import: {record.message} [{record.source}]",
            )
        )


def _source_nc_pin_inventory(
    symbols: list[dict[str, Any]],
    library_types: dict[str, dict[str, str]],
) -> tuple[dict[tuple[str, str], tuple[str, str]], dict[tuple[int, int], list[tuple[str, str]]]]:
    """Only library-identified original physical pins are eligible for NC."""
    pins: dict[tuple[str, str], tuple[str, str]] = {}
    locations: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for symbol in symbols:
        ref, lib_id = symbol["ref"], symbol["lib_id"]
        if not ref or ref.startswith(_NONPHYSICAL_KICAD_REFS):
            continue
        names = symbol.get("pin_library_names")
        definitions = library_types.get(lib_id, {})
        for number, x, y in symbol["pins"]:
            if not isinstance(names, dict) or number not in names or number not in definitions:
                continue
            pin = ref, number
            pins[pin] = names[number], definitions[number]
            locations.setdefault(_quantise((x, y)), []).append(pin)
    return pins, locations


def _source_no_connect_markers(
    sexp: list[SexpNode],
    locations: dict[tuple[int, int], list[tuple[str, str]]],
    unsupported: list[SchematicUnsupportedRecord],
) -> set[tuple[str, str]]:
    """Resolve exactly one physical library pin per explicit NC marker."""
    marked: set[tuple[str, str]] = set()
    for marker in _find_all(sexp, "no_connect"):
        at = _find(marker, "at")
        matches = locations.get(_quantise(_coord(at)), []) if at is not None else []
        if len(matches) != 1:
            unsupported.append(
                SchematicUnsupportedRecord(
                    kind="unresolved_no_connect_marker",
                    message="No-connect marker has no unique embedded-library pin",
                    severity="warning",
                )
            )
            continue
        marked.add(matches[0])
    return marked


def _append_source_no_connect_nets(
    sexp: list[SexpNode],
    symbols: list[dict[str, Any]],
    nets_raw: dict[str, list[tuple[str, str]]],
    unsupported: list[SchematicUnsupportedRecord],
) -> None:
    """Model only explicit KiCad NC markers or library no-connect pin types.

    Native netlist exports include these as singleton `unconnected-*` nets.
    Never synthesize a native name when a pin has no reliable embedded
    library definition, an NC marker is ambiguous, or a pin is connected.
    """
    occupied = {pin for nodes in nets_raw.values() for pin in nodes}
    pins, locations = _source_nc_pin_inventory(symbols, _embedded_library_pin_types(sexp))
    no_connect = {pin for pin, (_name, kind) in pins.items() if kind == "no_connect"}
    no_connect.update(_source_no_connect_markers(sexp, locations, unsupported))

    for ref, number in sorted(no_connect):
        pin = ref, number
        if pin in occupied:
            unsupported.append(
                SchematicUnsupportedRecord(
                    kind="no_connect_on_connected_pin",
                    message=f"Pin {ref}:{number} is both electrically connected and marked no-connect",
                    severity="warning",
                )
            )
            continue
        name, _kind = pins[pin]
        visible_name = name if name not in {"", "~", number} else ""
        suffix = f"{visible_name}-" if visible_name else ""
        native_name = f"unconnected-({ref}-{suffix}Pad{number})"
        if native_name in nets_raw:
            unsupported.append(
                SchematicUnsupportedRecord(
                    kind="duplicate_no_connect_net",
                    message=f"NC net {native_name} collides with another imported net",
                    severity="warning",
                )
            )
            continue
        nets_raw[native_name] = [pin]


def import_kicad_schematic_string(
    content: str,
    source_path: Path | None = None,
) -> KiCadSchematicImportResult:
    """Import a KiCad schematic from a string (for testing without file I/O).

    Parameters
    ----------
    content:
        The raw .kicad_sch S-expression text.
    source_path:
        Optional source file path for evidence records.

    Returns
    -------
    KiCadSchematicImportResult
    """
    sexp = _sexp_parse(content)
    if not isinstance(sexp, list) or not sexp or sexp[0] != "kicad_sch":
        raise ValueError("Not a valid kicad_sch file: root element must be (kicad_sch ...)")

    symbols, wires, junctions, labels, unsupported = _parse_schematic(sexp)

    # Resolve connectivity
    nets_raw = _resolve_connectivity(symbols, wires, junctions, labels, unsupported)
    _append_source_no_connect_nets(sexp, symbols, nets_raw, unsupported)

    # Build Design
    source_name = source_path.stem if source_path else "schematic"
    design = Design(meta=DesignMeta(name=source_name, author="kicad-schematic-import"))

    _add_imported_components(design, symbols)
    net_score = _add_imported_nets(design, nets_raw)
    _record_schematic_import_losses(design, unsupported)

    return KiCadSchematicImportResult(
        design=design,
        unsupported=unsupported,
        source_path=source_path,
        net_score=net_score,
        source_snapshot=_source_snapshot(sexp, content),
    )


def compute_schematic_net_score(
    exported_result: KiCadSchematicImportResult,
    imported_result: KiCadSchematicImportResult,
) -> float:
    """Compute self-round-trip net identity score.

    Measures what fraction of nets in *imported_result* are also present in
    *exported_result* (by name, normalised), and vice versa.  A score of 1.00
    means all nets are shared.

    Used to validate: export → import → same nets.
    """

    def _norm_names(result: KiCadSchematicImportResult) -> set[str]:
        return {re.sub(r"[^a-z0-9]", "_", n.lower()) for n in result.design.nets}

    a = _norm_names(exported_result)
    b = _norm_names(imported_result)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union
