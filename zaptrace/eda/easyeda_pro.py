"""EasyEDA Pro project reader/writer with shared shape codec (issues #120, #121).

Reads an EasyEDA Pro ZIP/JSONL project into the canonical ZapTrace model,
preserving unknown constructs as structured degradation records.

EasyEDA Pro project structure
-------------------------------
A ``.epro`` or ``.zip`` file contains:
* ``project.json``    — project metadata (name, version, source provenance)
* ``schematic.jsonl`` — one JSON object per line, schematic elements
* ``pcb.jsonl``       — one JSON object per line, PCB elements

Known record types (``"type"`` field)
--------------------------------------
Schematic:
  * ``HEADER``    — file format metadata (version, generator, docType)
  * ``CANVAS``    — canvas settings
  * ``COMPONENT`` — placed component with ref, value, package, mpn, x/y
  * ``NET``       — net with name and list of ``{component, pin}`` refs
  * ``WIRE``      — wire segment with net reference and coordinate list
  * ``LABEL``     — net label annotation

PCB:
  * ``HEADER``     — file format metadata
  * ``LAYER``      — layer definition (id, name, color)
  * ``FOOTPRINT``  — placed footprint (ref, package, x/y/rotation)
  * ``TRACK``      — routed copper track (net, x1/y1/x2/y2, width, layer)
  * ``VIA``        — via (x/y, outer/inner diameter)

Unknown records
---------------
Any record whose ``"type"`` is not in the supported set is preserved as an
:class:`EasyEdaDegradationRecord` with the document (file name) and 0-based
line index. Records are never silently dropped.

Security guards
---------------
* ZIP path traversal: rejects any entry whose resolved path escapes the
  extraction root.
* Oversized ZIP: rejects ZIPs with an uncompressed total exceeding
  ``MAX_UNCOMPRESSED_BYTES``.
* Oversized JSONL: rejects individual lines exceeding
  ``MAX_JSONL_LINE_BYTES``.
* Malformed JSONL: records a degradation entry instead of crashing.
* Unsupported version: warns but continues (version mismatch is non-fatal).
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

# Safety limits
MAX_UNCOMPRESSED_BYTES: int = 50 * 1024 * 1024  # 50 MiB
MAX_JSONL_LINE_BYTES: int = 1 * 1024 * 1024  # 1 MiB per line

# Supported EasyEDA Pro version prefix
_SUPPORTED_VERSIONS = ("2.",)
_PROJECT_JSON_NAME = "project.json"
_JSONL_SUFFIX = ".jsonl"
_SCHEMATIC_JSONL_NAME = "schematic.jsonl"
_PCB_JSONL_NAME = "pcb.jsonl"

# ---------------------------------------------------------------------------
# Shared codec: record type vocabularies
# ---------------------------------------------------------------------------

_SCH_KNOWN = frozenset({"HEADER", "CANVAS", "COMPONENT", "NET", "WIRE", "LABEL"})
_PCB_KNOWN = frozenset({"HEADER", "LAYER", "FOOTPRINT", "TRACK", "VIA", "DIMENSION_LINE", "CANVAS"})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EasyEdaDegradationRecord:
    """An unknown or unsupported EasyEDA Pro record.

    Attributes
    ----------
    record_type:
        The ``"type"`` field from the JSON record, or ``"PARSE_ERROR"`` if the
        line could not be decoded as JSON.
    document:
        The file inside the ZIP where the record was encountered.
    line_index:
        0-based line index within the JSONL file.
    severity:
        ``"info"`` for known-unknown constructs; ``"error"`` for parse errors.
    raw:
        The raw line text (truncated to 200 chars for safety).
    """

    record_type: str
    document: str
    line_index: int
    severity: str = "info"
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "document": self.document,
            "line_index": self.line_index,
            "severity": self.severity,
            "raw": self.raw[:200],
        }


@dataclass
class EasyEdaComponent:
    """A placed component from the EasyEDA Pro schematic."""

    id: str
    ref: str
    value: str = ""
    package: str = ""
    mpn: str = ""
    x: float = 0.0
    y: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ref": self.ref,
            "value": self.value,
            "package": self.package,
            "mpn": self.mpn,
            "x": self.x,
            "y": self.y,
        }


@dataclass
class EasyEdaNet:
    """A net from the EasyEDA Pro schematic."""

    id: str
    name: str
    pins: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "pins": self.pins}


@dataclass
class EasyEdaLayer:
    """A PCB layer from the EasyEDA Pro document."""

    id: int
    name: str
    color: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "color": self.color}


@dataclass
class EasyEdaTrack:
    """A routed track from the EasyEDA Pro PCB."""

    layer: int
    net: str
    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 0.2

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "net": self.net,
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "width": self.width,
        }


@dataclass
class EasyEdaVia:
    """A via from the EasyEDA Pro PCB."""

    x: float
    y: float
    outer_diameter: float = 0.8
    inner_diameter: float = 0.4

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "outer_diameter": self.outer_diameter,
            "inner_diameter": self.inner_diameter,
        }


@dataclass
class EasyEdaFootprint:
    """A placed footprint from the EasyEDA Pro PCB."""

    ref: str
    package: str
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "package": self.package,
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
        }


@dataclass
class EasyEdaProSchematic:
    """Extracted schematic data from an EasyEDA Pro project."""

    format_version: str = ""
    components: list[EasyEdaComponent] = field(default_factory=list)
    nets: list[EasyEdaNet] = field(default_factory=list)
    degradation: list[EasyEdaDegradationRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "component_count": len(self.components),
            "net_count": len(self.nets),
            "degradation_count": len(self.degradation),
        }


@dataclass
class EasyEdaProPcb:
    """Extracted PCB data from an EasyEDA Pro project."""

    format_version: str = ""
    layers: list[EasyEdaLayer] = field(default_factory=list)
    footprints: list[EasyEdaFootprint] = field(default_factory=list)
    tracks: list[EasyEdaTrack] = field(default_factory=list)
    vias: list[EasyEdaVia] = field(default_factory=list)
    degradation: list[EasyEdaDegradationRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "layer_count": len(self.layers),
            "footprint_count": len(self.footprints),
            "track_count": len(self.tracks),
            "via_count": len(self.vias),
            "degradation_count": len(self.degradation),
        }


@dataclass
class EasyEdaProProject:
    """The result of reading an EasyEDA Pro ZIP project.

    Attributes
    ----------
    project_name:
        The project name from ``project.json``.
    format_version:
        The EasyEDA Pro format version.
    source_provenance:
        The source provenance field from ``project.json``, if present.
    schematic:
        Extracted schematic data (may be empty if no schematic file found).
    pcb:
        Extracted PCB data (may be empty if no PCB file found).
    degradation:
        Top-level degradation records (project-level unknowns).
    """

    project_name: str = ""
    format_version: str = ""
    source_provenance: str = ""
    schematic: EasyEdaProSchematic = field(default_factory=EasyEdaProSchematic)
    pcb: EasyEdaProPcb = field(default_factory=EasyEdaProPcb)
    degradation: list[EasyEdaDegradationRecord] = field(default_factory=list)

    @property
    def total_degradation_count(self) -> int:
        return len(self.degradation) + len(self.schematic.degradation) + len(self.pcb.degradation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "format_version": self.format_version,
            "source_provenance": self.source_provenance,
            "schematic": self.schematic.to_dict(),
            "pcb": self.pcb.to_dict(),
            "total_degradation_count": self.total_degradation_count,
        }


# ---------------------------------------------------------------------------
# ZIP security helpers
# ---------------------------------------------------------------------------


def _is_safe_path(arcname: str) -> bool:
    """Return True if *arcname* does not attempt path traversal."""
    p = PurePosixPath(arcname)
    # Reject absolute paths or any path with ".." components
    if p.is_absolute():
        return False
    return all(part != ".." for part in p.parts)


def _check_zip_size(zf: zipfile.ZipFile) -> None:
    """Raise ValueError if uncompressed total exceeds MAX_UNCOMPRESSED_BYTES."""
    total = sum(info.file_size for info in zf.infolist())
    if total > MAX_UNCOMPRESSED_BYTES:
        raise ValueError(f"EasyEDA Pro ZIP uncompressed size {total} > {MAX_UNCOMPRESSED_BYTES} limit")


# ---------------------------------------------------------------------------
# Shared JSONL codec
# ---------------------------------------------------------------------------


def _parse_jsonl(
    text: str,
    document: str,
    known_types: frozenset[str],
) -> tuple[list[dict[str, Any]], list[EasyEdaDegradationRecord]]:
    """Parse JSONL text into (records, degradation_records).

    Each line is decoded as a JSON object. Unknown ``"type"`` values and lines
    that cannot be decoded are recorded as degradation records.
    """
    records: list[dict[str, Any]] = []
    degradation: list[EasyEdaDegradationRecord] = []

    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue

        if len(line.encode("utf-8")) > MAX_JSONL_LINE_BYTES:
            degradation.append(
                EasyEdaDegradationRecord(
                    record_type="OVERSIZED_LINE",
                    document=document,
                    line_index=i,
                    severity="error",
                    raw=line[:200],
                )
            )
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            degradation.append(
                EasyEdaDegradationRecord(
                    record_type="PARSE_ERROR",
                    document=document,
                    line_index=i,
                    severity="error",
                    raw=f"{exc}: {line[:200]}",
                )
            )
            continue

        if not isinstance(obj, dict):
            degradation.append(
                EasyEdaDegradationRecord(
                    record_type="NON_OBJECT_LINE",
                    document=document,
                    line_index=i,
                    severity="error",
                    raw=line[:200],
                )
            )
            continue

        record_type = obj.get("type", "UNKNOWN")
        if record_type not in known_types:
            degradation.append(
                EasyEdaDegradationRecord(
                    record_type=record_type,
                    document=document,
                    line_index=i,
                    severity="info",
                    raw=line[:200],
                )
            )
        else:
            records.append(obj)

    return records, degradation


# ---------------------------------------------------------------------------
# Schematic extractor
# ---------------------------------------------------------------------------


def _extract_schematic(text: str, document: str) -> EasyEdaProSchematic:
    """Extract schematic data from JSONL content."""
    records, degradation = _parse_jsonl(text, document, _SCH_KNOWN)
    sch = EasyEdaProSchematic(degradation=degradation)

    for rec in records:
        rtype = rec.get("type")
        if rtype == "HEADER":
            sch.format_version = str(rec.get("version", ""))
        elif rtype == "COMPONENT":
            sch.components.append(
                EasyEdaComponent(
                    id=str(rec.get("id", "")),
                    ref=str(rec.get("ref", "")),
                    value=str(rec.get("value", "")),
                    package=str(rec.get("package", "")),
                    mpn=str(rec.get("mpn", "")),
                    x=float(rec.get("x", 0.0)),
                    y=float(rec.get("y", 0.0)),
                )
            )
        elif rtype == "NET":
            pins_raw = rec.get("pins", [])
            pins = [
                {"component": str(p.get("component", "")), "pin": str(p.get("pin", ""))}
                for p in pins_raw
                if isinstance(p, dict)
            ]
            sch.nets.append(
                EasyEdaNet(
                    id=str(rec.get("id", "")),
                    name=str(rec.get("name", "")),
                    pins=pins,
                )
            )

    return sch


# ---------------------------------------------------------------------------
# PCB extractor
# ---------------------------------------------------------------------------


def _extract_pcb(text: str, document: str) -> EasyEdaProPcb:
    """Extract PCB data from JSONL content."""
    records, degradation = _parse_jsonl(text, document, _PCB_KNOWN)
    pcb = EasyEdaProPcb(degradation=degradation)

    for rec in records:
        rtype = rec.get("type")
        if rtype == "HEADER":
            pcb.format_version = str(rec.get("version", ""))
        elif rtype == "LAYER":
            pcb.layers.append(
                EasyEdaLayer(
                    id=int(rec.get("id", 0)),
                    name=str(rec.get("name", "")),
                    color=str(rec.get("color", "")),
                )
            )
        elif rtype == "FOOTPRINT":
            pcb.footprints.append(
                EasyEdaFootprint(
                    ref=str(rec.get("ref", "")),
                    package=str(rec.get("package", "")),
                    x=float(rec.get("x", 0.0)),
                    y=float(rec.get("y", 0.0)),
                    rotation=float(rec.get("rotation", 0.0)),
                )
            )
        elif rtype == "TRACK":
            pcb.tracks.append(
                EasyEdaTrack(
                    layer=int(rec.get("layer", 1)),
                    net=str(rec.get("net", "")),
                    x1=float(rec.get("x1", 0.0)),
                    y1=float(rec.get("y1", 0.0)),
                    x2=float(rec.get("x2", 0.0)),
                    y2=float(rec.get("y2", 0.0)),
                    width=float(rec.get("width", 0.2)),
                )
            )
        elif rtype == "VIA":
            pcb.vias.append(
                EasyEdaVia(
                    x=float(rec.get("x", 0.0)),
                    y=float(rec.get("y", 0.0)),
                    outer_diameter=float(rec.get("outerDiameter", 0.8)),
                    inner_diameter=float(rec.get("innerDiameter", 0.4)),
                )
            )

    return pcb


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_easyeda_pro_zip(raw: bytes | bytearray) -> EasyEdaProProject:
    """Read an EasyEDA Pro ZIP project from raw archive bytes.

    Filesystem callers must resolve and authorize paths at their trust boundary,
    then pass the resulting bytes to this parser.

    Raises
    ------
    TypeError:
        If *raw* is not a bytes-like archive payload.
    ValueError:
        If the ZIP is malformed, unsafe (path traversal), or too large.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError("EasyEDA Pro reader requires raw ZIP bytes")
    payload = bytes(raw)

    try:
        zf = zipfile.ZipFile(io.BytesIO(payload), "r")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid ZIP file: {exc}") from exc

    with zf:
        _check_zip_size(zf)

        # Security: reject unsafe entry names
        for info in zf.infolist():
            if not _is_safe_path(info.filename):
                raise ValueError(f"Unsafe ZIP entry path (path traversal): {info.filename!r}")

        return _parse_zip_contents(zf)


def _read_zip_member(zf: zipfile.ZipFile, name: str) -> bytes:
    """Read one validated member while normalizing corrupt local headers."""
    try:
        return zf.read(name)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Malformed ZIP member data: {exc}") from exc


def _append_zip_degradation(
    project: EasyEdaProProject,
    *,
    record_type: str,
    document: str,
    severity: str,
    raw: str,
) -> None:
    project.degradation.append(
        EasyEdaDegradationRecord(
            record_type=record_type,
            document=document,
            line_index=0,
            severity=severity,
            raw=raw,
        )
    )


def _load_project_metadata(
    zf: zipfile.ZipFile,
    names: list[str],
    project: EasyEdaProProject,
) -> None:
    if _PROJECT_JSON_NAME not in names:
        _append_zip_degradation(
            project,
            record_type="MISSING_PROJECT_JSON",
            document="",
            severity="error",
            raw="project.json not found in ZIP",
        )
        return

    try:
        meta = json.loads(_read_zip_member(zf, _PROJECT_JSON_NAME).decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        _append_zip_degradation(
            project,
            record_type="PARSE_ERROR",
            document=_PROJECT_JSON_NAME,
            severity="error",
            raw="project.json could not be decoded",
        )
        return

    project.project_name = str(meta.get("name", ""))
    project.format_version = str(meta.get("formatVersion", meta.get("version", "")))
    project.source_provenance = str(meta.get("sourceProvenance", ""))
    if project.format_version and not any(
        project.format_version.startswith(version) for version in _SUPPORTED_VERSIONS
    ):
        _append_zip_degradation(
            project,
            record_type="UNSUPPORTED_VERSION",
            document=_PROJECT_JSON_NAME,
            severity="info",
            raw=f"version={project.format_version}",
        )


def _schematic_document_name(names: list[str]) -> str | None:
    preferred = [name for name in names if "schematic" in name.lower() and name.endswith(_JSONL_SUFFIX)]
    if preferred:
        return preferred[0]
    fallback = [name for name in names if name.endswith(_JSONL_SUFFIX) and "pcb" not in name.lower()]
    return fallback[0] if fallback else None


def _load_schematic_document(
    zf: zipfile.ZipFile,
    names: list[str],
    project: EasyEdaProProject,
) -> None:
    document = _schematic_document_name(names)
    if document is None:
        return
    try:
        content = _read_zip_member(zf, document).decode("utf-8", errors="replace")
        project.schematic = _extract_schematic(content, document)
    except Exception as exc:  # pragma: no cover
        _append_zip_degradation(
            project,
            record_type="SCHEMATIC_READ_ERROR",
            document=document,
            severity="error",
            raw=str(exc)[:200],
        )


def _load_pcb_document(
    zf: zipfile.ZipFile,
    names: list[str],
    project: EasyEdaProProject,
) -> None:
    pcb_names = [name for name in names if "pcb" in name.lower() and name.endswith(_JSONL_SUFFIX)]
    if not pcb_names:
        return
    document = pcb_names[0]
    try:
        content = _read_zip_member(zf, document).decode("utf-8", errors="replace")
        project.pcb = _extract_pcb(content, document)
    except Exception as exc:  # pragma: no cover
        _append_zip_degradation(
            project,
            record_type="PCB_READ_ERROR",
            document=document,
            severity="error",
            raw=str(exc)[:200],
        )


def _parse_zip_contents(zf: zipfile.ZipFile) -> EasyEdaProProject:
    """Internal: extract project from an already-opened, validated ZipFile."""
    project = EasyEdaProProject()
    names = zf.namelist()
    _load_project_metadata(zf, names, project)
    _load_schematic_document(zf, names, project)
    _load_pcb_document(zf, names, project)
    return project


# ---------------------------------------------------------------------------
# Write-side data classes
# ---------------------------------------------------------------------------

_EASYEDA_FORMAT_VERSION = "2.0.0"


@dataclass
class EasyEdaWriteFinding:
    """A single finding recorded during EasyEDA Pro export.

    Attributes
    ----------
    category:
        ``"represented"`` — mapped without loss;
        ``"transformed"`` — mapped with noted fidelity reduction;
        ``"unsupported"`` — could not be expressed in EasyEDA Pro format.
    element:
        Human-readable description of the element (e.g. ``"component R1"``).
    detail:
        Optional extra detail or reason.
    """

    category: str  # "represented" | "transformed" | "unsupported"
    element: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category, "element": self.element, "detail": self.detail}


@dataclass
class EasyEdaWriteDegradationReport:
    """Machine-readable write degradation report for a single export operation.

    Attributes
    ----------
    represented_count:
        Number of design elements fully represented in the output.
    transformed_count:
        Number of elements that required a lossy or approximate mapping.
    unsupported_count:
        Number of elements that could not be represented and were omitted.
    findings:
        Ordered list of individual :class:`EasyEdaWriteFinding` records.
    accepted:
        ``True`` when ``unsupported_count == 0`` (no silent data loss).
    """

    represented_count: int = 0
    transformed_count: int = 0
    unsupported_count: int = 0
    findings: list[EasyEdaWriteFinding] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.unsupported_count == 0

    def _add(self, category: str, element: str, detail: str = "") -> None:
        self.findings.append(EasyEdaWriteFinding(category=category, element=element, detail=detail))
        if category == "represented":
            self.represented_count += 1
        elif category == "transformed":
            self.transformed_count += 1
        else:
            self.unsupported_count += 1

    def represented(self, element: str, detail: str = "") -> None:
        self._add("represented", element, detail)

    def transformed(self, element: str, detail: str = "") -> None:
        self._add("transformed", element, detail)

    def unsupported(self, element: str, detail: str = "") -> None:
        self._add("unsupported", element, detail)

    def to_dict(self) -> dict[str, Any]:
        return {
            "represented_count": self.represented_count,
            "transformed_count": self.transformed_count,
            "unsupported_count": self.unsupported_count,
            "accepted": self.accepted,
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# JSONL serialisers (write side)
# ---------------------------------------------------------------------------


def _build_schematic_jsonl(design: Any, report: EasyEdaWriteDegradationReport) -> str:
    """Serialise canonical design schematic to EasyEDA Pro JSONL text."""
    lines: list[str] = []

    lines.append(json.dumps({"type": "HEADER", "version": _EASYEDA_FORMAT_VERSION, "generator": "zaptrace"}))
    lines.append(json.dumps({"type": "CANVAS", "width": 1000, "height": 800}))

    components = getattr(design, "components", {}) or {}
    nets = getattr(design, "nets", {}) or {}

    for comp_id in sorted(components):
        comp = components[comp_id]
        position = getattr(comp, "position", None) or (0.0, 0.0)
        x, y = float(position[0]), float(position[1])
        mpn = getattr(comp, "mpn", None) or ""
        value = getattr(comp, "value", None) or ""
        footprint = getattr(comp, "footprint", "") or ""
        ref = getattr(comp, "ref", comp_id)
        record: dict[str, Any] = {
            "type": "COMPONENT",
            "id": str(comp_id),
            "ref": str(ref),
            "value": str(value),
            "package": str(footprint),
            "mpn": str(mpn),
            "x": x,
            "y": y,
        }
        lines.append(json.dumps(record, sort_keys=True))
        report.represented(f"component {ref}")

    for net_id in sorted(nets):
        net = nets[net_id]
        net_name = getattr(net, "name", net_id) or net_id
        nodes = getattr(net, "nodes", []) or []
        pins = [{"component": str(getattr(n, "component_id", "")), "pin": str(getattr(n, "pin", ""))} for n in nodes]
        record = {"type": "NET", "id": str(net_id), "name": str(net_name), "pins": pins}
        lines.append(json.dumps(record, sort_keys=True))
        report.represented(f"net {net_name}")

    # Blocks and other design elements not expressible in EasyEDA Pro schematic JSONL
    blocks = getattr(design, "blocks", []) or []
    for blk in blocks:
        blk_id = getattr(blk, "id", "block")
        report.unsupported(f"block {blk_id}", "EasyEDA Pro JSONL does not support block groupings")

    return "\n".join(lines) + "\n"


def _build_pcb_jsonl(design: Any, report: EasyEdaWriteDegradationReport) -> str:
    """Serialise canonical design PCB to EasyEDA Pro JSONL text."""
    lines: list[str] = []

    lines.append(json.dumps({"type": "HEADER", "version": _EASYEDA_FORMAT_VERSION, "generator": "zaptrace"}))

    # Standard layer mapping
    layer_map: list[dict[str, Any]] = [
        {"type": "LAYER", "id": 1, "name": "TopCopper", "color": "#FF0000"},
        {"type": "LAYER", "id": 2, "name": "BottomCopper", "color": "#0000FF"},
        {"type": "LAYER", "id": 3, "name": "TopSilkscreen", "color": "#FFFF00"},
        {"type": "LAYER", "id": 4, "name": "BottomSilkscreen", "color": "#00FFFF"},
        {"type": "LAYER", "id": 11, "name": "BoardOutline", "color": "#FFAA00"},
    ]
    for lyr in layer_map:
        lines.append(json.dumps(lyr, sort_keys=True))
        report.represented(f"layer {lyr['name']}")

    components = getattr(design, "components", {}) or {}
    for comp_id in sorted(components):
        comp = components[comp_id]
        position = getattr(comp, "position", None) or (0.0, 0.0)
        x, y = float(position[0]), float(position[1])
        footprint = getattr(comp, "footprint", "") or ""
        ref = getattr(comp, "ref", comp_id)
        record = {
            "type": "FOOTPRINT",
            "ref": str(ref),
            "package": str(footprint),
            "x": x,
            "y": y,
            "rotation": 0.0,
        }
        lines.append(json.dumps(record, sort_keys=True))
        report.represented(f"footprint {ref}")

    # Routed tracks
    routing = getattr(design, "routing", None)
    if routing is not None:
        traces = getattr(routing, "traces", []) or []
        for tr in traces:
            net = getattr(tr, "net", "") or ""
            x1 = float(getattr(tr, "x1", 0.0))
            y1 = float(getattr(tr, "y1", 0.0))
            x2 = float(getattr(tr, "x2", 0.0))
            y2 = float(getattr(tr, "y2", 0.0))
            width = float(getattr(tr, "width", 0.2))
            record = {
                "type": "TRACK",
                "layer": 1,
                "net": str(net),
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "width": width,
            }
            lines.append(json.dumps(record, sort_keys=True))
            report.represented(f"track net={net}")

        vias = getattr(routing, "vias", []) or []
        for via in vias:
            x = float(getattr(via, "x", 0.0))
            y = float(getattr(via, "y", 0.0))
            record = {
                "type": "VIA",
                "x": x,
                "y": y,
                "outerDiameter": 0.8,
                "innerDiameter": 0.4,
            }
            lines.append(json.dumps(record, sort_keys=True))
            report.represented(f"via at ({x},{y})")

    # Copper pours not representable in EasyEDA Pro basic JSONL
    copper_pours = getattr(design, "copper_pours", {}) or {}
    for pour_id in sorted(copper_pours):
        report.unsupported(f"copper_pour {pour_id}", "EasyEDA Pro JSONL does not support copper pours")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Public writer API
# ---------------------------------------------------------------------------


def write_easyeda_pro_zip(
    design: Any,
    *,
    project_name: str = "",
    source_provenance: str = "zaptrace",
) -> tuple[bytes, EasyEdaWriteDegradationReport]:
    """Export a canonical ZapTrace design to an EasyEDA Pro ZIP archive.

    The output is a deterministic, reproducible ``.epro`` compatible ZIP
    containing:
    * ``project.json``   — project metadata
    * ``schematic.jsonl`` — schematic components and nets
    * ``pcb.jsonl``       — PCB footprints and (if present) routed tracks

    Parameters
    ----------
    design:
        A ZapTrace :class:`~zaptrace.core.models.Design` or any object with
        ``meta``, ``components``, ``nets``, ``routing``, and ``blocks``
        attributes.
    project_name:
        Override the project name; defaults to ``design.meta.name``.
    source_provenance:
        Provenance label written to ``project.json``; defaults to ``"zaptrace"``.

    Returns
    -------
    tuple[bytes, EasyEdaWriteDegradationReport]
        * The raw ZIP bytes (suitable for writing to a ``.epro`` file).
        * A machine-readable degradation report describing what was
          represented, transformed, or unsupported.

    Notes
    -----
    The report's ``accepted`` property is ``True`` when no unsupported
    elements were encountered (zero data loss). The report is always emitted
    even for zero-loss exports.
    """
    report = EasyEdaWriteDegradationReport()

    meta = getattr(design, "meta", None)
    name = project_name or (str(getattr(meta, "name", "")) if meta else "") or "untitled"

    project_meta: dict[str, Any] = {
        "name": name,
        "formatVersion": _EASYEDA_FORMAT_VERSION,
        "sourceProvenance": source_provenance,
        "generator": "zaptrace",
    }
    if meta:
        if getattr(meta, "version", None):
            project_meta["version"] = str(meta.version)
        if getattr(meta, "author", None):
            project_meta["author"] = str(meta.author)
        report.represented("project metadata")
    else:
        report.transformed("project metadata", "no DesignMeta; minimal project.json generated")

    sch_jsonl = _build_schematic_jsonl(design, report)
    pcb_jsonl = _build_pcb_jsonl(design, report)

    buf = io.BytesIO()
    # Use ZIP_DEFLATED with deterministic timestamps (1980-01-01 00:00:00)
    epoch = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as zf:
        info = zipfile.ZipInfo(_PROJECT_JSON_NAME, date_time=epoch)
        zf.writestr(info, json.dumps(project_meta, indent=2, sort_keys=True))
        info = zipfile.ZipInfo(_SCHEMATIC_JSONL_NAME, date_time=epoch)
        zf.writestr(info, sch_jsonl.encode("utf-8"))
        info = zipfile.ZipInfo(_PCB_JSONL_NAME, date_time=epoch)
        zf.writestr(info, pcb_jsonl.encode("utf-8"))

    return buf.getvalue(), report


def compute_easyeda_write_fidelity(
    design: Any,
    *,
    project_name: str = "",
) -> dict[str, Any]:
    """Write a design to EasyEDA Pro, read it back, and compute fidelity metrics.

    Returns a dict with keys:
    * ``component_jaccard`` — Jaccard similarity of component refs
    * ``net_jaccard``       — Jaccard similarity of net names
    * ``overall_score``     — mean of the above Jaccard scores
    * ``degradation_report`` — the write-side :meth:`EasyEdaWriteDegradationReport.to_dict`
    * ``roundtrip_degradation_count`` — total degradation records on re-read
    """
    raw_bytes, write_report = write_easyeda_pro_zip(design, project_name=project_name)
    readback = read_easyeda_pro_zip(raw_bytes)

    # Component ref Jaccard
    orig_refs = {str(getattr(c, "ref", cid)) for cid, c in (getattr(design, "components", {}) or {}).items()}
    read_refs = {c.ref for c in readback.schematic.components}
    comp_j = _jaccard(orig_refs, read_refs)

    # Net name Jaccard
    orig_nets = {str(getattr(n, "name", nid)) for nid, n in (getattr(design, "nets", {}) or {}).items()}
    read_nets = {n.name for n in readback.schematic.nets}
    net_j = _jaccard(orig_nets, read_nets)

    scores = [comp_j, net_j]
    overall = sum(scores) / len(scores) if scores else 0.0

    return {
        "component_jaccard": round(comp_j, 4),
        "net_jaccard": round(net_j, 4),
        "overall_score": round(overall, 4),
        "degradation_report": write_report.to_dict(),
        "roundtrip_degradation_count": readback.total_degradation_count,
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity coefficient for two string sets."""
    if not a and not b:
        return 1.0
    union = a | b
    intersection = a & b
    return len(intersection) / len(union) if union else 1.0
