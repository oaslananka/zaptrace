"""Eagle .brd / .sch XML import adapter with round-trip support (issue #123).

Parses a subset of the Autodesk Eagle XML format (schema v7+) into a ZapTrace
:class:`~zaptrace.core.models.Design`. This is a *structural* import: nets,
components, placed parts, and footprint geometry are extracted. Eagle-specific
attributes (design rules, ULP scripts, ERC annotations) become unsupported
records rather than being silently ignored.

Eagle XML structure (simplified):
  <eagle><drawing><board>
    <components>  (BOM-level, with value)
    <nets>        (net table)
    <elements>    (placed parts with x/y/layer)
    <signals>     (same as nets with contactrefs and wires)
    <libraries>   (embedded package geometry)
  </board></drawing></eagle>

Security guards
---------------
* ``defusedxml`` blocks entity expansion, DTD processing, and XXE attacks.
* An explicit size cap (``MAX_INPUT_BYTES``) rejects oversized inputs before
  parsing begins.
* ``import_eagle_xml_bytes()`` and ``import_eagle_xml_string()`` accept
  in-memory payloads (testing and API use) without needing a file on disk.

Round-trip support
------------------
``export_eagle_xml()`` produces schema-valid, deterministic Eagle XML from an
:class:`EagleImportResult`, suitable for re-import. Unsupported constructs
(polygons, design rules, embedded library, etc.) are preserved as comments or
noted in the result; they are never silently dropped from the export.

``compute_eagle_roundtrip_score()`` computes a [0, 1] fidelity score over the
component, net, geometry, and layer dimensions.
"""

from __future__ import annotations

import hashlib
import io
import re
import xml.etree.ElementTree as _StdET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from xml.etree.ElementTree import Element as _Element
from xml.etree.ElementTree import ParseError as _XMLParseError

import defusedxml.ElementTree as ElementTree

# Maximum accepted input size: 10 MiB
MAX_INPUT_BYTES: int = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EagleUnsupportedRecord:
    """An Eagle construct that could not be fully imported."""

    kind: str
    message: str
    severity: str = "warning"
    xpath: str = ""  # source location as XPath-like string

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "message": self.message,
            "severity": self.severity,
            "xpath": self.xpath,
        }


@dataclass
class EaglePad:
    """One pad from a placed element's package geometry."""

    name: str
    x_mm: float = 0.0
    y_mm: float = 0.0
    dx_mm: float = 0.5
    dy_mm: float = 0.5
    layer: int = 1
    kind: str = "smd"  # "smd" or "thru-hole"
    drill_mm: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "dx_mm": self.dx_mm,
            "dy_mm": self.dy_mm,
            "layer": self.layer,
            "kind": self.kind,
            "drill_mm": self.drill_mm,
        }


@dataclass
class EagleTrack:
    """One routed wire segment."""

    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    width: float = 0.2032
    layer: int = 1
    net_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "width": self.width,
            "layer": self.layer,
            "net_name": self.net_name,
        }


@dataclass
class EagleVia:
    """One via."""

    x: float = 0.0
    y: float = 0.0
    drill: float = 0.4
    extent: str = "1-16"

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "drill": self.drill,
            "extent": self.extent,
        }


@dataclass
class EagleLayer:
    """One Eagle layer definition."""

    number: int = 0
    name: str = ""
    color: int = 4
    visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "name": self.name,
            "color": self.color,
            "visible": self.visible,
        }


@dataclass
class EagleImportResult:
    """Result of importing an Eagle .brd or .sch XML file."""

    source_path: Path | None = None
    schema_version: str = ""
    # Core data
    nets: dict[str, list[str]] = field(default_factory=dict)  # net_name → [refs]
    components: dict[str, dict[str, str]] = field(default_factory=dict)  # ref → attrs
    unsupported: list[EagleUnsupportedRecord] = field(default_factory=list)
    # Geometry
    pads: dict[str, list[EaglePad]] = field(default_factory=dict)  # ref → pads
    tracks: list[EagleTrack] = field(default_factory=list)
    vias: list[EagleVia] = field(default_factory=list)
    layers: list[EagleLayer] = field(default_factory=list)
    # Board outline (dimension wires, layer 20)
    board_outline: list[EagleTrack] = field(default_factory=list)
    # Package geometry map: package_name → list of pads (library-level)
    packages: dict[str, list[EaglePad]] = field(default_factory=dict)

    @property
    def unsupported_count(self) -> int:
        return len(self.unsupported)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path) if self.source_path else None,
            "schema_version": self.schema_version,
            "component_count": len(self.components),
            "net_count": len(self.nets),
            "track_count": len(self.tracks),
            "via_count": len(self.vias),
            "layer_count": len(self.layers),
            "pad_count": sum(len(p) for p in self.pads.values()),
            "unsupported_count": self.unsupported_count,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _float(val: str | None, default: float = 0.0) -> float:
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


def _int(val: str | None, default: int = 0) -> int:
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


def _bool_attr(val: str | None) -> bool:
    return str(val).lower() in ("yes", "true", "1") if val else False


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------


def _parse_root(root: _Element) -> EagleImportResult:
    """Parse an already-loaded Eagle XML root element."""
    if root.tag != "eagle":
        raise ValueError(f"Not an Eagle file: root tag is '{root.tag}', expected 'eagle'")

    version = root.get("version", "")
    result = EagleImportResult(schema_version=version)

    # --- Layers ---
    for layer_el in root.iter("layer"):
        result.layers.append(
            EagleLayer(
                number=_int(layer_el.get("number")),
                name=layer_el.get("name", ""),
                color=_int(layer_el.get("color"), 4),
                visible=layer_el.get("visible", "yes") != "no",
            )
        )

    # --- Library packages (geometry) ---
    for lib_el in root.iter("library"):
        for pkg_el in lib_el.findall(".//package"):
            pkg_name = pkg_el.get("name", "")
            if not pkg_name:
                continue
            pads: list[EaglePad] = []
            for smd in pkg_el.findall("smd"):
                pads.append(
                    EaglePad(
                        name=smd.get("name", ""),
                        x_mm=_float(smd.get("x")),
                        y_mm=_float(smd.get("y")),
                        dx_mm=_float(smd.get("dx"), 0.5),
                        dy_mm=_float(smd.get("dy"), 0.5),
                        layer=_int(smd.get("layer"), 1),
                        kind="smd",
                    )
                )
            for pad in pkg_el.findall("pad"):
                pads.append(
                    EaglePad(
                        name=pad.get("name", ""),
                        x_mm=_float(pad.get("x")),
                        y_mm=_float(pad.get("y")),
                        dx_mm=_float(pad.get("diameter"), 1.8),
                        dy_mm=_float(pad.get("diameter"), 1.8),
                        layer=17,
                        kind="thru-hole",
                        drill_mm=_float(pad.get("drill"), 0.9),
                    )
                )
            result.packages[pkg_name] = pads
        result.unsupported.append(
            EagleUnsupportedRecord(
                "library",
                "Embedded library definitions partially imported (packages only)",
                "info",
                xpath="/eagle/drawing/board/libraries/library",
            )
        )
        break  # flag once

    # --- BOM components ---
    for comp in root.iter("component"):
        ref = comp.get("name", "")
        if not ref:
            continue
        result.components[ref] = {
            "type": comp.get("deviceset", ""),
            "value": comp.get("value", ""),
        }

    # --- Placed elements ---
    for elem in root.iter("element"):
        ref = elem.get("name", "")
        if not ref:
            continue
        existing = result.components.setdefault(ref, {})
        existing["x_mm"] = elem.get("x", "0")
        existing["y_mm"] = elem.get("y", "0")
        existing["layer"] = elem.get("layer", "")
        existing["package"] = elem.get("package", "")
        if not existing.get("type"):
            existing["type"] = existing["package"]
        if not existing.get("value"):
            existing["value"] = elem.get("value", "")
        # Resolve pads from package geometry
        pkg_name = existing.get("package", "")
        if pkg_name and pkg_name in result.packages:
            ex = _float(elem.get("x"))
            ey = _float(elem.get("y"))
            result.pads[ref] = [
                EaglePad(
                    name=p.name,
                    x_mm=ex + p.x_mm,
                    y_mm=ey + p.y_mm,
                    dx_mm=p.dx_mm,
                    dy_mm=p.dy_mm,
                    layer=p.layer,
                    kind=p.kind,
                    drill_mm=p.drill_mm,
                )
                for p in result.packages[pkg_name]
            ]

    # --- Nets / signals ---
    for signal in root.iter("signal"):
        net_name = signal.get("name", "")
        if not net_name:
            continue
        refs: list[str] = []
        for cr in signal.findall("contactref"):
            element = cr.get("element", "")
            if element:
                refs.append(element)
        result.nets[net_name] = refs
        # Tracks within signal
        for wire in signal.findall("wire"):
            result.tracks.append(
                EagleTrack(
                    x1=_float(wire.get("x1")),
                    y1=_float(wire.get("y1")),
                    x2=_float(wire.get("x2")),
                    y2=_float(wire.get("y2")),
                    width=_float(wire.get("width"), 0.2032),
                    layer=_int(wire.get("layer"), 1),
                    net_name=net_name,
                )
            )

    # Schematic-style <net> elements
    for net in root.iter("net"):
        net_name = net.get("name", "")
        if not net_name or net_name in result.nets:
            continue
        refs = [pin.get("part", "") for pin in net.findall("pinref") if pin.get("part")]
        result.nets[net_name] = refs

    # --- Vias ---
    for via in root.iter("via"):
        result.vias.append(
            EagleVia(
                x=_float(via.get("x")),
                y=_float(via.get("y")),
                drill=_float(via.get("drill"), 0.4),
                extent=via.get("extent", "1-16"),
            )
        )

    # --- Board outline (dimension layer = 20) ---
    for wire in root.iter("wire"):
        if wire.get("layer") == "20":
            result.board_outline.append(
                EagleTrack(
                    x1=_float(wire.get("x1")),
                    y1=_float(wire.get("y1")),
                    x2=_float(wire.get("x2")),
                    y2=_float(wire.get("y2")),
                    width=_float(wire.get("width"), 0.127),
                    layer=20,
                )
            )

    # --- Unsupported constructs ---
    for _polygon in root.iter("polygon"):
        result.unsupported.append(
            EagleUnsupportedRecord(
                "polygon",
                "Polygon fill not imported",
                "info",
                xpath="/eagle/drawing/board//polygon",
            )
        )
        break

    for _dr in root.iter("designrules"):
        result.unsupported.append(
            EagleUnsupportedRecord(
                "designrules",
                "Eagle design rules not imported",
                "info",
                xpath="/eagle/drawing/board/designrules",
            )
        )
        break

    for _attr_el in root.iter("attribute"):
        result.unsupported.append(
            EagleUnsupportedRecord(
                "attribute",
                "Component-level attributes not imported",
                "info",
                xpath="/eagle/drawing/board/elements/element/attribute",
            )
        )
        break

    return result


# ---------------------------------------------------------------------------
# Public import API
# ---------------------------------------------------------------------------


def import_eagle_xml(path: str | Path) -> EagleImportResult:
    """Parse an Eagle .brd or .sch XML file into a structured import result.

    Args:
        path: Path to the Eagle XML file (.brd or .sch).

    Returns:
        An :class:`EagleImportResult` with the extracted data.

    Raises:
        ValueError: If the file is not valid Eagle XML or exceeds the size cap.
        FileNotFoundError: If the file does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Eagle file not found: {path}")

    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"Eagle file too large: {len(raw)} bytes > {MAX_INPUT_BYTES} limit")

    result = import_eagle_xml_bytes(raw)
    result.source_path = path
    return result


def import_eagle_xml_bytes(data: bytes) -> EagleImportResult:
    """Parse Eagle XML from bytes (safe for untrusted input).

    Args:
        data: Raw UTF-8 encoded Eagle XML bytes.

    Returns:
        An :class:`EagleImportResult`.

    Raises:
        ValueError: If the bytes are not valid Eagle XML or are too large.
    """
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError(f"Eagle input too large: {len(data)} bytes > {MAX_INPUT_BYTES} limit")

    try:
        tree = ElementTree.parse(io.BytesIO(data))  # type: ignore[attr-defined]
    except _XMLParseError as exc:
        raise ValueError(f"Invalid Eagle XML: {exc}") from exc

    root: _Element = cast(_Element, tree.getroot())
    return _parse_root(root)


def import_eagle_xml_string(content: str) -> EagleImportResult:
    """Parse Eagle XML from a string.

    Args:
        content: Raw Eagle XML text.

    Returns:
        An :class:`EagleImportResult`.
    """
    return import_eagle_xml_bytes(content.encode("utf-8"))


def import_eagle_to_design(path: str | Path) -> tuple[Any, EagleImportResult]:
    """Import an Eagle file and convert to a ZapTrace Design (best-effort).

    Returns ``(design, import_result)`` where ``design`` is a ZapTrace
    :class:`~zaptrace.core.models.Design` built from the extracted data.
    Import losses are recorded in the design's ``import_losses`` field.
    """
    from zaptrace.core.models import (
        Component,
        Design,
        DesignMeta,
        ImportLossRecord,
        Net,
        NetNode,
    )

    eagle_result = import_eagle_xml(path)
    design = Design(meta=DesignMeta(name=Path(path).stem, author="eagle-import"))

    # Add components
    for ref, attrs in eagle_result.components.items():
        design.components[ref.lower()] = Component(
            id=ref.lower(),
            ref=ref,
            type=attrs.get("type", "unknown"),
            value=attrs.get("value", ""),
        )

    # Add nets
    for net_name, refs in eagle_result.nets.items():
        net_id = re.sub(r"(?a)\W", "_", net_name).lower()
        nodes = [NetNode(component_ref=r, pin_name="?") for r in refs]
        design.nets[net_id] = Net(id=net_id, name=net_name, nodes=nodes)

    # Record import losses for unsupported Eagle constructs
    for ur in eagle_result.unsupported:
        design.import_losses.append(
            ImportLossRecord(
                source_format="eagle",
                field_path=ur.kind,
                behavior="dropped",
                original_value=ur.message,
                note=f"Eagle import: {ur.message}",
            )
        )

    return design, eagle_result


# ---------------------------------------------------------------------------
# Eagle XML exporter
# ---------------------------------------------------------------------------


def _append_eagle_layers(drawing: _Element, result: EagleImportResult) -> None:
    layers_el = _StdET.SubElement(drawing, "layers")
    for layer in sorted(result.layers, key=lambda item: item.number):
        _StdET.SubElement(
            layers_el,
            "layer",
            attrib={
                "number": str(layer.number),
                "name": layer.name,
                "color": str(layer.color),
                "fill": "1",
                "visible": "yes" if layer.visible else "no",
                "active": "yes",
            },
        )


def _append_eagle_outline(board: _Element, result: EagleImportResult) -> None:
    plain = _StdET.SubElement(board, "plain")
    for wire in result.board_outline:
        _StdET.SubElement(
            plain,
            "wire",
            attrib={
                "x1": str(wire.x1),
                "y1": str(wire.y1),
                "x2": str(wire.x2),
                "y2": str(wire.y2),
                "width": str(wire.width),
                "layer": "20",
            },
        )


def _append_eagle_components(board: _Element, result: EagleImportResult) -> None:
    components_el = _StdET.SubElement(board, "components")
    elements_el = _StdET.SubElement(board, "elements")
    for ref in sorted(result.components):
        attrs = result.components[ref]
        _StdET.SubElement(
            components_el,
            "component",
            attrib={
                "name": ref,
                "library": "zaptrace-export",
                "deviceset": attrs.get("type", ""),
                "value": attrs.get("value", ""),
            },
        )
        _StdET.SubElement(
            elements_el,
            "element",
            attrib={
                "name": ref,
                "library": "zaptrace-export",
                "package": attrs.get("package", attrs.get("type", "")),
                "value": attrs.get("value", ""),
                "x": attrs.get("x_mm", "0"),
                "y": attrs.get("y_mm", "0"),
            },
        )


def _append_eagle_signals(board: _Element, result: EagleImportResult) -> None:
    signals_el = _StdET.SubElement(board, "signals")
    tracks_by_net: dict[str, list[EagleTrack]] = {}
    for track in result.tracks:
        tracks_by_net.setdefault(track.net_name, []).append(track)

    for net_name in sorted(result.nets):
        signal_el = _StdET.SubElement(signals_el, "signal", attrib={"name": net_name})
        for ref in sorted(result.nets[net_name]):
            _StdET.SubElement(signal_el, "contactref", attrib={"element": ref, "pad": "?"})
        for track in tracks_by_net.get(net_name, []):
            _StdET.SubElement(
                signal_el,
                "wire",
                attrib={
                    "x1": str(track.x1),
                    "y1": str(track.y1),
                    "x2": str(track.x2),
                    "y2": str(track.y2),
                    "width": str(track.width),
                    "layer": str(track.layer),
                },
            )


def _append_eagle_vias(board: _Element, result: EagleImportResult) -> None:
    for via in result.vias:
        _StdET.SubElement(
            board,
            "via",
            attrib={
                "x": str(via.x),
                "y": str(via.y),
                "extent": via.extent,
                "drill": str(via.drill),
            },
        )


def _append_eagle_unsupported_notes(board: _Element, result: EagleImportResult) -> None:
    if not result.unsupported:
        return
    comments = "; ".join(f"{record.kind}: {record.message}" for record in result.unsupported)
    board.append(_StdET.Comment(f" ZapTrace export notes: {comments} "))


def export_eagle_xml(result: EagleImportResult) -> str:
    """Export an :class:`EagleImportResult` as schema-valid Eagle XML.

    The output is deterministic: elements are ordered alphabetically by
    reference / net name. Only the supported subset is emitted; unsupported
    constructs are annotated as XML comments so they are not silently lost.
    """
    root = _StdET.Element("eagle", attrib={"version": result.schema_version or "7.7.0"})
    drawing = _StdET.SubElement(root, "drawing")
    _append_eagle_layers(drawing, result)
    board = _StdET.SubElement(drawing, "board")
    _append_eagle_outline(board, result)
    _append_eagle_components(board, result)
    _append_eagle_signals(board, result)
    _append_eagle_vias(board, result)
    _append_eagle_unsupported_notes(board, result)

    tree = _StdET.ElementTree(root)
    _StdET.indent(tree)
    buf = io.StringIO()
    tree.write(buf, encoding="unicode", xml_declaration=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Round-trip scorer
# ---------------------------------------------------------------------------


def compute_eagle_roundtrip_score(
    original: EagleImportResult,
    reimported: EagleImportResult,
) -> float:
    """Compute a round-trip fidelity score in [0, 1].

    Measures component, net, track, via, and layer preservation from
    *original* to *reimported* using Jaccard similarity on each dimension,
    then averages the five dimensions.

    Args:
        original: The import result from the original Eagle file.
        reimported: The import result after exporting and re-importing.

    Returns:
        A float in [0, 1]. 1.0 means perfect fidelity.
    """

    def _jaccard(a: set[object], b: set[object]) -> float:
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    # Component identity (by ref)
    comp_score = _jaccard(
        set(original.components),
        set(reimported.components),
    )

    # Net identity (by name)
    net_score = _jaccard(
        set(original.nets),
        set(reimported.nets),
    )

    # Track fidelity: use (x1,y1,x2,y2,layer) tuples
    def _track_key(t: EagleTrack) -> tuple:
        return (round(t.x1, 3), round(t.y1, 3), round(t.x2, 3), round(t.y2, 3), t.layer)

    track_score = _jaccard(
        {_track_key(t) for t in original.tracks},
        {_track_key(t) for t in reimported.tracks},
    )

    # Via fidelity: use (x, y, drill) tuples
    def _via_key(v: EagleVia) -> tuple:
        return (round(v.x, 3), round(v.y, 3), v.drill)

    via_score = _jaccard(
        {_via_key(v) for v in original.vias},
        {_via_key(v) for v in reimported.vias},
    )

    # Layer fidelity: by layer number
    layer_score = _jaccard(
        {la.number for la in original.layers},
        {la.number for la in reimported.layers},
    )

    return (comp_score + net_score + track_score + via_score + layer_score) / 5.0


def eagle_result_hash(result: EagleImportResult) -> str:
    """Compute a deterministic SHA-256 digest of the import result.

    Useful for verifying that two imports produce identical results.
    """
    parts = [
        "|".join(sorted(result.components)),
        "|".join(sorted(result.nets)),
        str(len(result.tracks)),
        str(len(result.vias)),
        str(len(result.layers)),
    ]
    return hashlib.sha256("::".join(parts).encode()).hexdigest()
