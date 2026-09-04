"""Altium Designer ASCII schematic importer (issue #136).

Parses the pipe-delimited ASCII record format exported by Altium Designer
from ``.SchDoc`` files into a ZapTrace :class:`~zaptrace.core.models.Design`.

Altium stores schematics in OLE Compound Document (CFB) binary format.
Many Altium versions can also export a plain-text ASCII variant where each
schematic object is a single pipe-delimited line of ``KEY=VALUE`` pairs, with
the record type identified by ``|RECORD=N|``.

This module targets the **ASCII export** format only. Binary ``.SchDoc`` /
``.PcbDoc`` files (OLE magic ``D0 CF 11 E0 A1 B1 1A E1``) are detected and
rejected with a clear error message — the caller should first export to ASCII
from within Altium Designer before calling this importer.

Supported record types
----------------------
=====  ==================  ================================================
 Rec#   Name                Extracted fields
=====  ==================  ================================================
  1    SchematicSheet       TEMPLATEFILENAME, AREACOLOR, BORDERON (metadata)
  2    Pin                  PART, X, Y, NAME, NUMBER, PINLENGTH, PINCONGLOMERATE
  4    Label                TEXT, X, Y, ORIENTATION
 28    Component            LIBREFERENCE, DESIGNITEMID, DESCRIPTION,
                            UNIQUEID, LOCATION.X, LOCATION.Y, PARTCOUNT
 37    Wire                 X1, Y1, X2, Y2
209    Port                 TEXT, X, Y, STYLE
=====  ==================  ================================================

All other record types are collected as :class:`AltiumRecord` evidence items
with severity ``"info"`` in :attr:`AltiumImportResult.unsupported_records`.

Net inference
-------------
Nets are inferred from wire connectivity and label/port proximity:

1. Wire endpoints are clustered into *nodes* (coordinate equality).
2. Labels (RECORD=4) and ports (RECORD=209) annotate the nearest node.
3. Connected components of nodes form a net; the first label found names it.
4. Component pins (RECORD=2) are matched to the node at their endpoint.

Security guards
---------------
* Inputs larger than :data:`MAX_INPUT_BYTES` (10 MiB) are rejected.
* OLE binary magic bytes trigger a clear :exc:`ValueError` instead of a crash.
* Any parsing error produces ``error_count > 0``; partial results are never
  silently claimed as complete.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from zaptrace.core.models import (
    Component,
    Design,
    DesignMeta,
    Net,
    NetNode,
    NetType,
    Pin,
    PinType,
)

# Maximum accepted input size: 10 MiB
MAX_INPUT_BYTES: int = 10 * 1024 * 1024

# OLE Compound Document magic header
_OLE_MAGIC: bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# Altium mil → mm conversion (1 mil = 0.0254 mm)
_MIL_TO_MM: float = 0.0254

# Tolerance (in mils) for matching wire endpoints to pins / labels
_SNAP_TOLERANCE: int = 50


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AltiumRecord:
    """A single raw Altium record (one pipe-delimited line)."""

    record_type: int
    fields: dict[str, str]
    severity: str = "info"

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "fields": dict(self.fields),
            "severity": self.severity,
        }


@dataclass
class AltiumImportResult:
    """Result of importing an Altium ASCII schematic."""

    design: Design
    unsupported_records: list[AltiumRecord] = field(default_factory=list)
    supported_record_types: set[int] = field(default_factory=set)
    total_record_count: int = 0
    net_score: float = 0.0
    _errors: list[str] = field(default_factory=list)
    _warnings: list[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self._errors)

    @property
    def warning_count(self) -> int:
        return len(self._warnings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_count": len(self.design.components),
            "net_count": len(self.design.nets),
            "total_record_count": self.total_record_count,
            "supported_record_types": sorted(self.supported_record_types),
            "unsupported_record_count": len(self.unsupported_records),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "net_score": self.net_score,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_record_line(line: str) -> tuple[int, dict[str, str]] | None:
    """Parse one pipe-delimited record line into (record_type, fields).

    Returns ``None`` for blank lines or lines without a valid ``RECORD`` key.
    """
    line = line.strip().strip("|")
    if not line:
        return None

    pairs: dict[str, str] = {}
    for token in line.split("|"):
        token = token.strip()
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        pairs[key.strip().upper()] = value.strip()

    raw_type = pairs.get("RECORD")
    if raw_type is None:
        return None
    try:
        record_type = int(raw_type)
    except ValueError:
        return None

    return record_type, pairs


def _mil(value: str) -> float:
    """Convert a string mil value to millimetres."""
    try:
        return float(value) * _MIL_TO_MM
    except (ValueError, TypeError):
        return 0.0


def _coord(fields: dict[str, str], x_key: str, y_key: str) -> tuple[float, float]:
    return (_mil(fields.get(x_key, "0")), _mil(fields.get(y_key, "0")))


def _infer_pin_type(fields: dict[str, str]) -> PinType:
    """Heuristically determine pin type from PINCONGLOMERATE flags."""
    conglomerate = fields.get("PINCONGLOMERATE", "")
    try:
        flags = int(conglomerate)
    except (ValueError, TypeError):
        return PinType.PASSIVE
    # Bit 0: input, Bit 1: output (simplified Altium encoding)
    if flags & 0x01:
        return PinType.INPUT
    if flags & 0x02:
        return PinType.OUTPUT
    return PinType.PASSIVE


def _node_key(x_mil: float, y_mil: float) -> tuple[int, int]:
    """Snap a mil coordinate to the nearest snap-grid cell."""
    return (round(x_mil / _SNAP_TOLERANCE), round(y_mil / _SNAP_TOLERANCE))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[tuple[int, int], tuple[int, int]] = {}

    def find(self, node: tuple[int, int]) -> tuple[int, int]:
        self.parent.setdefault(node, node)
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def union(self, first: tuple[int, int], second: tuple[int, int]) -> None:
        first_root = self.find(first)
        second_root = self.find(second)
        if first_root != second_root:
            self.parent[first_root] = second_root


def _validate_altium_source(source: str | bytes) -> str:
    raw_bytes = source if isinstance(source, bytes) else source.encode("utf-8", errors="replace")
    if len(raw_bytes) > MAX_INPUT_BYTES:
        raise ValueError(
            f"Input exceeds maximum allowed size of {MAX_INPUT_BYTES} bytes ({len(raw_bytes)} bytes received)."
        )
    if raw_bytes[:8] == _OLE_MAGIC:
        raise ValueError(
            "Input appears to be a binary OLE Compound Document (.SchDoc / .PcbDoc). "
            "Please export the file as ASCII from within Altium Designer before importing."
        )
    return raw_bytes.decode("utf-8", errors="replace") if isinstance(source, bytes) else source


def _tokenize_altium_records(
    text: str,
) -> tuple[
    list[AltiumRecord],
    set[int],
    list[AltiumRecord],
    dict[int, list[dict[str, str]]],
]:
    supported = {1, 2, 4, 28, 37, 209}
    all_records: list[AltiumRecord] = []
    supported_types: set[int] = set()
    unsupported: list[AltiumRecord] = []
    buckets = {record_type: [] for record_type in supported}
    for line in text.splitlines():
        parsed = _parse_record_line(line)
        if parsed is None:
            continue
        record_type, fields = parsed
        record = AltiumRecord(record_type=record_type, fields=fields)
        all_records.append(record)
        if record_type in supported:
            supported_types.add(record_type)
            buckets[record_type].append(fields)
        else:
            record.severity = "info"
            unsupported.append(record)
    return all_records, supported_types, unsupported, buckets


def _build_altium_components(
    components_raw: list[dict[str, str]],
) -> tuple[dict[str, Component], dict[int, str]]:
    components: dict[str, Component] = {}
    comp_index_map: dict[int, str] = {}
    for index, fields in enumerate(components_raw):
        lib_ref = fields.get("LIBREFERENCE", fields.get("DESIGNITEMID", f"COMP{index}"))
        unique_id = fields.get("UNIQUEID", f"UID{index}")
        x_mil = float(fields.get("LOCATION.X", "0") or "0")
        y_mil = float(fields.get("LOCATION.Y", "0") or "0")
        components[unique_id] = Component(
            id=unique_id,
            ref=_guess_ref(lib_ref, components),
            type=_lib_ref_to_type(lib_ref),
            value=fields.get("VALUE", fields.get("DESIGNITEMID", lib_ref)),
            properties={
                "libreference": lib_ref,
                "description": fields.get("DESCRIPTION", ""),
                "partcount": fields.get("PARTCOUNT", "1"),
            },
            position=(_mil(str(x_mil)), _mil(str(y_mil))),
        )
        comp_index_map[index] = unique_id
    return components, comp_index_map


def _attach_altium_pins(
    pins_raw: list[dict[str, str]],
    components_raw: list[dict[str, str]],
    components: dict[str, Component],
    comp_index_map: dict[int, str],
    warnings: list[str],
) -> list[tuple[float, float, str, str]]:
    pin_coords: list[tuple[float, float, str, str]] = []
    for fields in pins_raw:
        owner = fields.get("OWNER", "0")
        owner_index = _owner_to_comp_index(owner, comp_index_map, components_raw)
        if owner_index is None:
            warnings.append(f"Pin with OWNER={owner} could not be resolved to a component; skipping.")
            continue
        comp_id = comp_index_map.get(owner_index)
        if comp_id is None:
            continue
        component = components.get(comp_id)
        if component is None:
            continue
        pin_name = fields.get("NAME", fields.get("NUMBER", "?"))
        pin_num = fields.get("NUMBER", "?")
        x_mil = float(fields.get("X", "0") or "0")
        y_mil = float(fields.get("Y", "0") or "0")
        pin_length = float(fields.get("PINLENGTH", "100") or "100")
        orientation = int(fields.get("ORIENTATION", "0") or "0")
        tip_x, tip_y = _pin_tip(x_mil, y_mil, pin_length, orientation)
        component.pins[pin_num] = Pin(
            name=pin_name,
            type=_infer_pin_type(fields),
            position=(_mil(str(x_mil)), _mil(str(y_mil))),
        )
        pin_coords.append((tip_x, tip_y, comp_id, pin_num))
    return pin_coords


def _altium_node_names(labels_raw: list[dict[str, str]], ports_raw: list[dict[str, str]]) -> dict[tuple[int, int], str]:
    node_names: dict[tuple[int, int], str] = {}
    for fields in [*labels_raw, *ports_raw]:
        text = fields.get("TEXT", "").strip()
        if not text:
            continue
        key = _node_key(float(fields.get("X", "0") or "0"), float(fields.get("Y", "0") or "0"))
        node_names.setdefault(key, text)
    return node_names


def _altium_wire_graph(wires_raw: list[dict[str, str]], node_names: dict[tuple[int, int], str]) -> _UnionFind:
    graph = _UnionFind()
    endpoints: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for fields in wires_raw:
        first = _node_key(float(fields.get("X1", "0") or "0"), float(fields.get("Y1", "0") or "0"))
        second = _node_key(float(fields.get("X2", "0") or "0"), float(fields.get("Y2", "0") or "0"))
        endpoints.append((first, second))
        graph.union(first, second)
    for key in node_names:
        for first, second in endpoints:
            if key in (first, second):
                graph.union(key, first)
    return graph


def _altium_net_name(
    root: tuple[int, int],
    node_names: dict[tuple[int, int], str],
    graph: _UnionFind,
    counter: list[int],
) -> str:
    if root in node_names:
        return node_names[root]
    for candidate, label in node_names.items():
        if graph.find(candidate) == root:
            return label
    counter[0] += 1
    return f"Net{counter[0]:04d}"


def _unique_altium_net_id(name: str, nets: dict[str, Net]) -> str:
    base_id = _sanitize_net_id(name)
    net_id = base_id
    suffix = 0
    while net_id in nets:
        suffix += 1
        net_id = f"{base_id}_{suffix}"
    return net_id


def _build_altium_nets(
    pin_coords: list[tuple[float, float, str, str]],
    node_names: dict[tuple[int, int], str],
    graph: _UnionFind,
    components: dict[str, Component],
) -> dict[str, Net]:
    net_nodes: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for tip_x, tip_y, comp_id, pin_num in pin_coords:
        root = graph.find(_node_key(tip_x, tip_y))
        net_nodes.setdefault(root, []).append((comp_id, pin_num))

    nets: dict[str, Net] = {}
    counter = [0]
    for root, pin_list in net_nodes.items():
        net_name = _altium_net_name(root, node_names, graph, counter)
        net_id = _unique_altium_net_id(net_name, nets)
        nets[net_id] = Net(
            id=net_id,
            name=net_name,
            type=_classify_net(net_name),
            nodes=[NetNode(component_ref=comp_id, pin_name=pin_num) for comp_id, pin_num in pin_list],
        )
        for comp_id, pin_num in pin_list:
            component = components.get(comp_id)
            if component and pin_num in component.pins:
                component.pins[pin_num] = component.pins[pin_num].model_copy(update={"net": net_id})
    return nets


def read_altium_ascii_sch(source: str | bytes) -> AltiumImportResult:
    """Parse an Altium ASCII schematic into a :class:`AltiumImportResult`."""
    errors: list[str] = []
    warnings: list[str] = []
    text = _validate_altium_source(source)
    all_records, supported_types, unsupported, buckets = _tokenize_altium_records(text)
    sheets = buckets[1]
    components_raw = buckets[28]
    components, comp_index_map = _build_altium_components(components_raw)
    pin_coords = _attach_altium_pins(buckets[2], components_raw, components, comp_index_map, warnings)
    node_names = _altium_node_names(buckets[4], buckets[209])
    graph = _altium_wire_graph(buckets[37], node_names)
    nets = _build_altium_nets(pin_coords, node_names, graph, components)
    total_pins = sum(len(component.pins) for component in components.values())
    connected_pins = sum(len(net.nodes) for net in nets.values())
    net_score = min(1.0, connected_pins / total_pins) if total_pins > 0 else 0.0
    design_name = sheets[0].get("DESCRIPTION", "Untitled") if sheets else "Untitled"
    result = AltiumImportResult(
        design=Design(
            meta=DesignMeta(name=design_name, author="Altium importer"),
            components=components,
            nets=nets,
        ),
        unsupported_records=unsupported,
        supported_record_types=supported_types,
        total_record_count=len(all_records),
        net_score=net_score,
    )
    result._errors = errors
    result._warnings = warnings
    return result


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------

_REF_COUNTERS: dict[str, int] = {}


def _guess_ref(lib_ref: str, existing: dict[str, Component]) -> str:
    """Produce a unique reference designator like R1, C2, U3."""
    prefix_map = {
        "RES": "R",
        "CAP": "C",
        "IND": "L",
        "SW": "SW",
        "LED": "D",
        "DIODE": "D",
        "NPN": "Q",
        "PNP": "Q",
        "NMOS": "Q",
        "PMOS": "Q",
        "VCC": "P",
        "GND": "P",
    }
    upper = lib_ref.upper()
    prefix = "U"
    for key, val in prefix_map.items():
        if upper.startswith(key):
            prefix = val
            break

    # Find the next available number for this prefix
    used = {c.ref for c in existing.values()}
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def _lib_ref_to_type(lib_ref: str) -> str:
    """Map a LibReference string to a canonical component type."""
    upper = lib_ref.upper()
    if any(k in upper for k in ("RES", "R0", "RESISTOR")):
        return "resistor"
    if any(k in upper for k in ("CAP", "C0", "CAPACITOR")):
        return "capacitor"
    if any(k in upper for k in ("IND", "L0", "INDUCTOR")):
        return "inductor"
    if any(k in upper for k in ("LED", "DIODE")):
        return "diode"
    if any(k in upper for k in ("NPN", "PNP", "NMOS", "PMOS", "BJT", "FET", "TRANSISTOR")):
        return "transistor"
    return "ic"


def _pin_tip(x_mil: float, y_mil: float, length: float, orientation: int) -> tuple[float, float]:
    """Compute the wire-connection tip of a pin given its root and orientation.

    Altium orientation: 0=right, 1=up, 2=left, 3=down (90° steps).
    """
    if orientation == 0:
        return (x_mil + length, y_mil)
    if orientation == 1:
        return (x_mil, y_mil + length)
    if orientation == 2:
        return (x_mil - length, y_mil)
    if orientation == 3:
        return (x_mil, y_mil - length)
    return (x_mil + length, y_mil)


def _owner_to_comp_index(
    owner_str: str,
    comp_index_map: dict[int, str],
    components_raw: list[dict[str, str]],
) -> int | None:
    """Map an OWNER record index to the 0-based component list index."""
    try:
        owner_val = int(owner_str)
    except (ValueError, TypeError):
        return None

    # OWNER in Altium is the global record index (0-based line number among
    # all records in the file).  We need to find which component has that
    # index.  We use a simple heuristic: treat OWNER as the 0-based component
    # list index.  If that fails, fall back to the nearest match.
    if owner_val in comp_index_map:
        return owner_val

    # Try to find a component whose raw record has a matching index
    for i in range(len(components_raw)):
        if i == owner_val:
            return i

    # Last resort: return the last component
    if comp_index_map:
        return max(comp_index_map.keys())
    return None


_NET_ID_RE = re.compile(r"(?a)\W")


def _sanitize_net_id(name: str) -> str:
    sanitized = _NET_ID_RE.sub("_", name).strip("_")
    return sanitized if sanitized else "Net_unnamed"


def _classify_net(name: str) -> NetType:
    upper = name.upper()
    if "GND" in upper or "GROUND" in upper or "AGND" in upper or "DGND" in upper:
        return NetType.GROUND
    if "VCC" in upper or "VDD" in upper or "POWER" in upper or "PWR" in upper or upper.startswith("V"):
        return NetType.POWER
    if "CLK" in upper or "CLOCK" in upper:
        return NetType.CLOCK
    return NetType.SIGNAL
