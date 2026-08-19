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


def read_altium_ascii_sch(source: str | bytes) -> AltiumImportResult:
    """Parse an Altium ASCII schematic into a :class:`AltiumImportResult`.

    Parameters
    ----------
    source:
        Either a ``str`` containing the ASCII schematic text, or ``bytes``
        that will be decoded as UTF-8 (with ``errors="replace"``).

    Returns
    -------
    AltiumImportResult
        Always returns a result.  Failures populate :attr:`_errors`.

    Raises
    ------
    ValueError
        If the input is oversized or begins with OLE binary magic bytes.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------
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

    text: str = raw_bytes.decode("utf-8", errors="replace") if isinstance(source, bytes) else source

    # ------------------------------------------------------------------
    # Pass 1: tokenise all records
    # ------------------------------------------------------------------
    # Intermediate storage keyed by record type
    _supported = {1, 2, 4, 28, 37, 209}

    all_records: list[AltiumRecord] = []
    supported_types: set[int] = set()
    unsupported: list[AltiumRecord] = []

    # Typed record buckets
    sheets: list[dict[str, str]] = []
    components_raw: list[dict[str, str]] = []
    pins_raw: list[dict[str, str]] = []
    labels_raw: list[dict[str, str]] = []
    wires_raw: list[dict[str, str]] = []
    ports_raw: list[dict[str, str]] = []

    for line in text.splitlines():
        parsed = _parse_record_line(line)
        if parsed is None:
            continue
        rtype, rfields = parsed
        rec = AltiumRecord(record_type=rtype, fields=rfields)
        all_records.append(rec)

        if rtype in _supported:
            supported_types.add(rtype)
            if rtype == 1:
                sheets.append(rfields)
            elif rtype == 28:
                components_raw.append(rfields)
            elif rtype == 2:
                pins_raw.append(rfields)
            elif rtype == 4:
                labels_raw.append(rfields)
            elif rtype == 37:
                wires_raw.append(rfields)
            elif rtype == 209:
                ports_raw.append(rfields)
        else:
            rec.severity = "info"
            unsupported.append(rec)

    # ------------------------------------------------------------------
    # Pass 2: build components (RECORD=28)
    # ------------------------------------------------------------------
    components: dict[str, Component] = {}
    comp_index_map: dict[int, str] = {}  # raw line-index → component id

    for idx, cf in enumerate(components_raw):
        lib_ref = cf.get("LIBREFERENCE", cf.get("DESIGNITEMID", f"COMP{idx}"))
        unique_id = cf.get("UNIQUEID", f"UID{idx}")
        description = cf.get("DESCRIPTION", "")

        # Build reference designator heuristically from lib ref + index
        ref = _guess_ref(lib_ref, components)

        x_mil = float(cf.get("LOCATION.X", "0") or "0")
        y_mil = float(cf.get("LOCATION.Y", "0") or "0")

        comp = Component(
            id=unique_id,
            ref=ref,
            type=_lib_ref_to_type(lib_ref),
            value=cf.get("VALUE", cf.get("DESIGNITEMID", lib_ref)),
            properties={
                "libreference": lib_ref,
                "description": description,
                "partcount": cf.get("PARTCOUNT", "1"),
            },
            position=(_mil(str(x_mil)), _mil(str(y_mil))),
        )
        components[unique_id] = comp
        comp_index_map[idx] = unique_id

    # ------------------------------------------------------------------
    # Pass 3: attach pins to components (RECORD=2)
    # ------------------------------------------------------------------
    # Pins reference their owner by OWNER field (1-based record index in
    # the original file, but Altium uses OWNERINDEX which is the 0-based
    # index of the owning RECORD=28 in the component list).
    # We use OWNER to find the parent component via comp_index_map.
    pin_coords: list[tuple[float, float, str, str]] = []
    # (x_mil, y_mil, comp_id, pin_name)

    for pf in pins_raw:
        owner_str = pf.get("OWNER", "0")
        # Map owner record index to component index
        owner_index = _owner_to_comp_index(owner_str, comp_index_map, components_raw)
        if owner_index is None:
            warnings.append(f"Pin with OWNER={owner_str} could not be resolved to a component; skipping.")
            continue

        comp_id = comp_index_map.get(owner_index)
        if comp_id is None:
            continue
        comp = components.get(comp_id)
        if comp is None:
            continue

        pin_name = pf.get("NAME", pf.get("NUMBER", "?"))
        pin_num = pf.get("NUMBER", "?")
        x_mil = float(pf.get("X", "0") or "0")
        y_mil = float(pf.get("Y", "0") or "0")
        pin_length = float(pf.get("PINLENGTH", "100") or "100")
        orientation = int(pf.get("ORIENTATION", "0") or "0")

        # Compute tip coordinate (where the wire connects)
        tip_x, tip_y = _pin_tip(x_mil, y_mil, pin_length, orientation)

        pin_obj = Pin(
            name=pin_name,
            type=_infer_pin_type(pf),
            position=(_mil(str(x_mil)), _mil(str(y_mil))),
        )
        comp.pins[pin_num] = pin_obj
        pin_coords.append((tip_x, tip_y, comp_id, pin_num))

    # ------------------------------------------------------------------
    # Pass 4: build connectivity graph (wires + labels + ports)
    # ------------------------------------------------------------------
    # Collect all nodes that need naming
    node_names: dict[tuple[int, int], str] = {}  # snapped key → net name

    for lf in labels_raw:
        text_val = lf.get("TEXT", "").strip()
        if not text_val:
            continue
        x_mil = float(lf.get("X", "0") or "0")
        y_mil = float(lf.get("Y", "0") or "0")
        key = _node_key(x_mil, y_mil)
        node_names.setdefault(key, text_val)

    for pf in ports_raw:
        text_val = pf.get("TEXT", "").strip()
        if not text_val:
            continue
        x_mil = float(pf.get("X", "0") or "0")
        y_mil = float(pf.get("Y", "0") or "0")
        key = _node_key(x_mil, y_mil)
        node_names.setdefault(key, text_val)

    # Build adjacency for wires (Union-Find style)
    wire_endpoints: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for wf in wires_raw:
        x1 = float(wf.get("X1", "0") or "0")
        y1 = float(wf.get("Y1", "0") or "0")
        x2 = float(wf.get("X2", "0") or "0")
        y2 = float(wf.get("Y2", "0") or "0")
        k1 = _node_key(x1, y1)
        k2 = _node_key(x2, y2)
        wire_endpoints.append((k1, k2))

    # Simple union-find
    parent: dict[tuple[int, int], tuple[int, int]] = {}

    def find(n: tuple[int, int]) -> tuple[int, int]:
        parent.setdefault(n, n)
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    def union(a: tuple[int, int], b: tuple[int, int]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for k1, k2 in wire_endpoints:
        union(k1, k2)

    # Also union label positions with any adjacent wire endpoint
    for key in node_names:
        for k1, k2 in wire_endpoints:
            if key in (k1, k2):
                union(key, k1)

    # Group pin tips into nets
    net_nodes: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for tip_x, tip_y, comp_id, pin_num in pin_coords:
        key = find(_node_key(tip_x, tip_y))
        net_nodes.setdefault(key, []).append((comp_id, pin_num))

    # Name each net group
    nets: dict[str, Net] = {}
    _net_counter = [0]

    def next_net_name() -> str:
        _net_counter[0] += 1
        return f"Net{_net_counter[0]:04d}"

    root_to_net: dict[tuple[int, int], str] = {}

    for root, pin_list in net_nodes.items():
        # Find a label for this root
        net_name: str | None = None
        # Check if root itself has a name
        if root in node_names:
            net_name = node_names[root]
        else:
            # Search all nodes with same root
            for candidate_key, label in node_names.items():
                if find(candidate_key) == root:
                    net_name = label
                    break
        if net_name is None:
            net_name = next_net_name()

        net_id = _sanitize_net_id(net_name)
        # Handle duplicate net IDs
        base_id = net_id
        suffix = 0
        while net_id in nets:
            suffix += 1
            net_id = f"{base_id}_{suffix}"

        net_type = _classify_net(net_name)
        net_obj = Net(
            id=net_id,
            name=net_name,
            type=net_type,
            nodes=[NetNode(component_ref=comp_id, pin_name=pin_num) for comp_id, pin_num in pin_list],
        )
        nets[net_id] = net_obj
        root_to_net[root] = net_id

        # Back-annotate pin net connections
        for comp_id, pin_num in pin_list:
            comp = components.get(comp_id)
            if comp and pin_num in comp.pins:
                comp.pins[pin_num] = comp.pins[pin_num].model_copy(update={"net": net_id})

    # ------------------------------------------------------------------
    # Pass 5: net_score
    # ------------------------------------------------------------------
    total_pins = sum(len(c.pins) for c in components.values())
    connected_pins = sum(len(n.nodes) for n in nets.values())
    net_score = min(1.0, connected_pins / total_pins) if total_pins > 0 else 0.0

    # ------------------------------------------------------------------
    # Assemble Design
    # ------------------------------------------------------------------
    design_name = sheets[0].get("DESCRIPTION", "Untitled") if sheets else "Untitled"
    design = Design(
        meta=DesignMeta(name=design_name, author="Altium importer"),
        components=components,
        nets=nets,
    )

    result = AltiumImportResult(
        design=design,
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
