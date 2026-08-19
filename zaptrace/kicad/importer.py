"""KiCad PCB import and round-trip fidelity scoring.

This importer intentionally starts with the subset ZapTrace can export today:
board dimensions, copper layers, net table, placed footprints/pads, segments,
and vias. Unsupported or unknown KiCad constructs are reported instead of being
silently treated as fully understood.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from zaptrace.core.models import (
    BoardConfig,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    LayerSet,
    Net,
    NetNode,
    Pad,
    PadShape,
    Pin,
    PinType,
    RouteResult,
    TraceSegment,
    Via,
)
from zaptrace.io.sexp import SexpNode
from zaptrace.io.sexp import parse as _sexp_parse

# Backward-compatible alias so the rest of the module continues to use SExpr.
SExpr = SexpNode


@dataclass(frozen=True)
class KiCadUnsupportedRecord:
    """A KiCad construct that could not be fully represented in ZapTrace."""

    kind: str
    message: str
    severity: str = "warning"
    source: str = ""


@dataclass(frozen=True)
class KiCadImportResult:
    """Result returned by :func:`import_kicad_pcb`."""

    design: Design
    unsupported: list[KiCadUnsupportedRecord] = field(default_factory=list)
    source_path: Path | None = None

    @property
    def unsupported_count(self) -> int:
        return len(self.unsupported)


@dataclass(frozen=True)
class KiCadFidelityReport:
    """Semantic score for an original ZapTrace design and imported KiCad design."""

    score: float
    component_refs_matched: int
    component_refs_total: int
    net_names_matched: int
    net_names_total: int
    placed_components_matched: int
    placed_components_total: int
    board_dimensions_match: bool
    trace_count_delta: int
    via_count_delta: int
    unsupported_count: int
    sections: dict[str, float]


def import_kicad_pcb(path: str | Path) -> KiCadImportResult:
    """Import a KiCad ``.kicad_pcb`` file into a ZapTrace :class:`Design`.

    The parser is an S-expression reader rather than a regex-only importer so it
    can tolerate KiCad formatting changes while preserving unsupported-data
    accounting for constructs outside the current ZapTrace model.
    """
    pcb_path = Path(path)
    text = pcb_path.read_text(encoding="utf-8")
    root = _parse_one(text)
    if not isinstance(root, list) or _head(root) != "kicad_pcb":
        raise ValueError(f"Not a KiCad PCB file: {pcb_path}")

    unsupported = _collect_unsupported(root)
    title, revision = _parse_title_block(root, fallback=pcb_path.stem)
    layer_names = _parse_copper_layers(root)
    board_width, board_height = _parse_board_size(root)
    net_number_to_id, nets = _parse_nets(root)
    components = _parse_footprints(root, net_number_to_id, nets)
    routing = _parse_routing(root, net_number_to_id)

    design = Design(
        meta=DesignMeta(name=title, version=revision or "0.1.0"),
        board=BoardConfig(width_mm=board_width, height_mm=board_height, layers=max(len(layer_names), 2)),
        components=components,
        nets=nets,
        routing=routing,
    )
    return KiCadImportResult(design=design, unsupported=unsupported, source_path=pcb_path)


def load_kicad_footprint(path: str | Path) -> FootprintDef | None:
    """Load a KiCad ``.kicad_mod`` land pattern into a :class:`FootprintDef`.

    Reads pad geometry (id, shape, position, size, drill, layer) and the F.CrtYd
    courtyard extent. Returns ``None`` when the file is not a footprint or has no
    pads — an empty land pattern is not usable geometry. Tolerant of KiCad format
    versions (single- or multi-line forms) since it parses S-expressions, not text.
    """
    fp_path = Path(path)
    root = _parse_one(fp_path.read_text(encoding="utf-8"))
    if not isinstance(root, list) or _head(root) != "footprint":
        return None
    pads = [_pad_from_form(pad) for pad in _children(root, "pad") if _atom(pad, 1)]
    if not pads:
        return None
    return FootprintDef(
        pads=pads,
        courtyard=_courtyard_extent(root),
        description=_atom(_first(root, "descr"), 1),
        source=f"KiCad:{fp_path.stem}",
    )


def _courtyard_extent(root: SExpr) -> tuple[float, float]:
    """Bounding-box (width, height) of the F.CrtYd graphics, in mm.

    The router blocks a component by its courtyard; a zero extent makes it skip
    the part, so fall back to the pad bounding box when no courtyard is drawn.
    """
    points = _linear_courtyard_points(root) + _polygon_courtyard_points(root)
    if not points:
        return _pad_bbox_extent(root)
    return _point_extent(points)


def _linear_courtyard_points(root: SExpr) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for name in ("fp_line", "fp_rect"):
        for form in _children(root, name):
            if _atom(_first(form, "layer"), 1) == "F.CrtYd":
                points.extend(_graphic_endpoints(form))
    return points


def _graphic_endpoints(form: SExpr) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for endpoint in ("start", "end"):
        point = _first(form, endpoint)
        if point is not None:
            points.append((_float_atom(point, 1), _float_atom(point, 2)))
    return points


def _polygon_courtyard_points(root: SExpr) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for form in _children(root, "fp_poly"):
        if _atom(_first(form, "layer"), 1) != "F.CrtYd":
            continue
        vertices = _first(form, "pts")
        if vertices is not None:
            points.extend((_float_atom(xy, 1), _float_atom(xy, 2)) for xy in _children(vertices, "xy"))
    return points


def _point_extent(points: list[tuple[float, float]]) -> tuple[float, float]:
    xs, ys = zip(*points, strict=True)
    return (round(max(xs) - min(xs), 4), round(max(ys) - min(ys), 4))


def _pad_bbox_extent(root: SExpr) -> tuple[float, float]:
    """Fallback courtyard: pad bounding box plus a small margin."""
    xs: list[float] = []
    ys: list[float] = []
    for pad in _children(root, "pad"):
        at = _first(pad, "at")
        size = _first(pad, "size")
        cx, cy = _float_atom(at, 1), _float_atom(at, 2)
        half_w = _float_atom(size, 1, 1.0) / 2.0
        half_h = _float_atom(size, 2, 1.0) / 2.0
        xs.extend((cx - half_w, cx + half_w))
        ys.extend((cy - half_h, cy + half_h))
    if not xs or not ys:
        return (0.0, 0.0)
    return (round(max(xs) - min(xs) + 0.5, 4), round(max(ys) - min(ys) + 0.5, 4))


def score_kicad_roundtrip(
    original: Design,
    imported: Design,
    unsupported_count: int = 0,
) -> KiCadFidelityReport:
    """Score semantic fidelity after ``Design -> KiCad -> Design`` round-trip."""
    original_refs = {component.ref for component in original.components.values()}
    imported_refs = {component.ref for component in imported.components.values()}
    component_matches = len(original_refs & imported_refs)

    original_nets = {net.name for net in original.nets.values()}
    imported_nets = {net.name for net in imported.nets.values()}
    net_matches = len(original_nets & imported_nets)

    original_positions = {
        component.ref: component.position for component in original.components.values() if component.position
    }
    imported_positions = {
        component.ref: component.position for component in imported.components.values() if component.position
    }
    placed_matches = sum(
        1
        for ref, pos in original_positions.items()
        if ref in imported_positions and _points_close(pos, imported_positions[ref])
    )

    original_trace_count = len(original.routing.traces) if original.routing else 0
    imported_trace_count = len(imported.routing.traces) if imported.routing else 0
    trace_delta = abs(original_trace_count - imported_trace_count)

    original_via_count = len(original.routing.vias) if original.routing else 0
    imported_via_count = len(imported.routing.vias) if imported.routing else 0
    via_delta = abs(original_via_count - imported_via_count)

    board_match = _float_close(original.board.width_mm, imported.board.width_mm) and _float_close(
        original.board.height_mm, imported.board.height_mm
    )

    sections = {
        "components": _ratio(component_matches, len(original_refs)),
        "nets": _ratio(net_matches, len(original_nets)),
        "placements": _ratio(placed_matches, len(original_positions)),
        "board": 1.0 if board_match else 0.0,
        "traces": _count_score(original_trace_count, imported_trace_count),
        "vias": _count_score(original_via_count, imported_via_count),
        "unsupported": 1.0 if unsupported_count == 0 else 0.0,
    }
    score = round(sum(sections.values()) / len(sections), 4)
    return KiCadFidelityReport(
        score=score,
        component_refs_matched=component_matches,
        component_refs_total=len(original_refs),
        net_names_matched=net_matches,
        net_names_total=len(original_nets),
        placed_components_matched=placed_matches,
        placed_components_total=len(original_positions),
        board_dimensions_match=board_match,
        trace_count_delta=trace_delta,
        via_count_delta=via_delta,
        unsupported_count=unsupported_count,
        sections=sections,
    )


def _parse_one(text: str) -> SExpr:
    """Parse a single KiCad S-expression string into an SExpr tree.

    Delegates to the shared :func:`~zaptrace.io.sexp.parse` codec which
    handles quoted strings, escape sequences, and semicolon comments.
    Raises :class:`ValueError` if the input is malformed.
    """
    try:
        result = _sexp_parse(text)
    except Exception as exc:
        raise ValueError(f"Malformed KiCad S-expression: {exc}") from exc
    if not isinstance(result, list):
        raise ValueError(f"Expected a list S-expression, got atom: {result!r}")
    return result


def _head(form: SExpr) -> str:
    if isinstance(form, list) and form and isinstance(form[0], str):
        return form[0]
    return ""


def _children(form: SExpr, name: str) -> list[list[SExpr]]:
    if not isinstance(form, list):
        return []
    return [child for child in form[1:] if isinstance(child, list) and _head(child) == name]


def _first(form: SExpr, name: str) -> list[SExpr] | None:
    children = _children(form, name)
    return children[0] if children else None


def _find_forms(form: SExpr, name: str) -> list[list[SExpr]]:
    matches: list[list[SExpr]] = []
    if isinstance(form, list):
        if _head(form) == name:
            matches.append(form)
        for child in form[1:]:
            matches.extend(_find_forms(child, name))
    return matches


def _atom(form: list[SExpr] | None, index: int, default: str = "") -> str:
    if form is None or index >= len(form) or isinstance(form[index], list):
        return default
    return str(form[index])


def _float_atom(form: list[SExpr] | None, index: int, default: float = 0.0) -> float:
    try:
        return float(_atom(form, index, str(default)))
    except ValueError:
        return default


def _parse_title_block(root: SExpr, fallback: str) -> tuple[str, str]:
    title_block = _first(root, "title_block")
    title = _atom(_first(title_block, "title"), 1, fallback) if title_block else fallback
    revision = _atom(_first(title_block, "rev"), 1, "0.1.0") if title_block else "0.1.0"
    return title or fallback, revision or "0.1.0"


def _parse_copper_layers(root: SExpr) -> list[str]:
    layers = _first(root, "layers")
    if layers is None:
        return ["F.Cu", "B.Cu"]
    names = []
    for child in layers[1:]:
        if not isinstance(child, list) or len(child) < 3:
            continue
        if _atom(child, 2) == "signal":
            names.append(_atom(child, 1))
    return names or ["F.Cu", "B.Cu"]


def _parse_board_size(root: SExpr) -> tuple[float, float]:
    for rect in _find_forms(root, "gr_rect"):
        start = _first(rect, "start")
        end = _first(rect, "end")
        if start and end:
            width = abs(_float_atom(end, 1) - _float_atom(start, 1))
            height = abs(_float_atom(end, 2) - _float_atom(start, 2))
            if width > 0 and height > 0:
                return width, height
    return 100.0, 80.0


def _parse_nets(root: SExpr) -> tuple[dict[int, str], dict[str, Net]]:
    used: set[str] = set()
    number_to_id: dict[int, str] = {}
    nets: dict[str, Net] = {}
    for net_form in _children(root, "net"):
        try:
            number = int(_atom(net_form, 1, "0"))
        except ValueError:
            continue
        if number == 0:
            continue
        name = _atom(net_form, 2, f"Net-{number}")
        net_id = _stable_id(name, used, fallback=f"net_{number}")
        number_to_id[number] = net_id
        nets[net_id] = Net(id=net_id, name=name)
    return number_to_id, nets


def _footprint_pins_and_pads(
    footprint: list[SExpr],
    ref: str,
    net_number_to_id: dict[int, str],
    nets: dict[str, Net],
) -> tuple[dict[str, Pin], list[Pad]]:
    pins: dict[str, Pin] = {}
    pads: list[Pad] = []
    for pad_form in _children(footprint, "pad"):
        pad_id = _atom(pad_form, 1)
        if not pad_id:
            continue
        net_id = _pad_net_id(pad_form, net_number_to_id)
        pins[pad_id] = Pin(name=pad_id, type=PinType.PASSIVE, net=net_id)
        pads.append(_pad_from_form(pad_form))
        if net_id and net_id in nets:
            nets[net_id].nodes.append(NetNode(component_ref=ref, pin_name=pad_id))
    return pins, pads


def _component_from_footprint(
    footprint: list[SExpr],
    index: int,
    used_ids: set[str],
    net_number_to_id: dict[int, str],
    nets: dict[str, Net],
) -> tuple[str, Component]:
    ref = _property_value(footprint, "Reference") or f"FP{index}"
    value = _property_value(footprint, "Value")
    comp_id = _stable_id(ref, used_ids, fallback=f"component_{index}")
    at = _first(footprint, "at")
    position = (_float_atom(at, 1), _float_atom(at, 2)) if at else None
    lib_id = _atom(footprint, 1, "")
    type_name = lib_id.split(":", 1)[1] if ":" in lib_id else lib_id or "unknown"
    pins, pads = _footprint_pins_and_pads(footprint, ref, net_number_to_id, nets)
    component = Component(
        id=comp_id,
        ref=ref,
        type=type_name,
        value=value,
        footprint=lib_id,
        footprint_def=FootprintDef(pads=pads, description=lib_id) if pads else None,
        pins=pins,
        position=position,
    )
    return comp_id, component


def _parse_footprints(root: SExpr, net_number_to_id: dict[int, str], nets: dict[str, Net]) -> dict[str, Component]:
    components: dict[str, Component] = {}
    used_ids: set[str] = set()
    for index, footprint in enumerate(_children(root, "footprint"), start=1):
        comp_id, component = _component_from_footprint(
            footprint,
            index,
            used_ids,
            net_number_to_id,
            nets,
        )
        components[comp_id] = component
    return components


def _parse_routing(root: SExpr, net_number_to_id: dict[int, str]) -> RouteResult | None:
    traces: list[TraceSegment] = []
    vias: list[Via] = []

    for segment in _children(root, "segment"):
        net_id = _net_ref_id(_first(segment, "net"), net_number_to_id)
        if not net_id:
            continue
        start = _first(segment, "start")
        end = _first(segment, "end")
        layer = _atom(_first(segment, "layer"), 1, "F.Cu")
        width = _float_atom(_first(segment, "width"), 1, 0.2)
        traces.append(
            TraceSegment(
                layer=layer,
                start=(_float_atom(start, 1), _float_atom(start, 2)),
                end=(_float_atom(end, 1), _float_atom(end, 2)),
                width=width,
                net_id=net_id,
            )
        )

    for via in _children(root, "via"):
        net_id = _net_ref_id(_first(via, "net"), net_number_to_id)
        at = _first(via, "at")
        vias.append(
            (
                _float_atom(at, 1),
                _float_atom(at, 2),
                _float_atom(_first(via, "size"), 1, 0.45),
                _float_atom(_first(via, "drill"), 1, 0.2),
                net_id,
            )
        )

    if not traces and not vias:
        return None
    return RouteResult(
        traces=traces,
        vias=vias,
        net_count=len(net_number_to_id),
        routed_net_count=len({trace.net_id for trace in traces}),
    )


def _property_value(form: SExpr, property_name: str) -> str | None:
    for prop in _children(form, "property"):
        if _atom(prop, 1) == property_name:
            return _atom(prop, 2)
    return None


def _pad_net_id(pad_form: SExpr, net_number_to_id: dict[int, str]) -> str | None:
    return _net_ref_id(_first(pad_form, "net"), net_number_to_id) or None


def _net_ref_id(net_form: list[SExpr] | None, net_number_to_id: dict[int, str]) -> str:
    if net_form is None:
        return ""
    try:
        number = int(_atom(net_form, 1, "0"))
    except ValueError:
        return ""
    return net_number_to_id.get(number, "")


def _pad_from_form(pad_form: list[SExpr]) -> Pad:
    pad_id = _atom(pad_form, 1)
    shape = _pad_shape(_atom(pad_form, 3, "rect"))
    at = _first(pad_form, "at")
    size = _first(pad_form, "size")
    drill = _first(pad_form, "drill")
    layers = _first(pad_form, "layers")
    return Pad(
        id=pad_id,
        layer=_pad_layer(layers),
        shape=shape,
        position=(_float_atom(at, 1), _float_atom(at, 2)),
        size=(_float_atom(size, 1, 1.0), _float_atom(size, 2, 1.0)),
        drill=_float_atom(drill, 1) if drill else None,
        plated=_atom(pad_form, 2) != "np_thru_hole",
        rotation=_float_atom(at, 3),
    )


def _pad_shape(raw: str) -> PadShape:
    try:
        return PadShape(raw)
    except ValueError:
        return PadShape.CUSTOM


def _pad_layer(layers: list[SExpr] | None) -> LayerSet:
    layer_names = {_atom(layers, index) for index in range(1, len(layers or []))}
    if "*.Cu" in layer_names:
        return LayerSet.ALL
    if "B.Cu" in layer_names and "F.Cu" not in layer_names:
        return LayerSet.BOTTOM
    return LayerSet.TOP


def _collect_unsupported(root: SExpr) -> list[KiCadUnsupportedRecord]:
    unsupported: list[KiCadUnsupportedRecord] = []
    for form_name in ("arc", "image", "group", "teardrops"):
        for _ in _find_forms(root, form_name):
            unsupported.append(
                KiCadUnsupportedRecord(
                    kind=form_name,
                    message=f"KiCad '{form_name}' is preserved as unsupported",
                )
            )
    return unsupported


def _stable_id(value: str, used: set[str], fallback: str) -> str:
    base = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_") or fallback
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _points_close(a: tuple[float, float], b: tuple[float, float], tolerance: float = 1e-6) -> bool:
    return _float_close(a[0], b[0], tolerance) and _float_close(a[1], b[1], tolerance)


def _float_close(a: float, b: float, tolerance: float = 1e-6) -> bool:
    return abs(a - b) <= tolerance


def _ratio(matched: int, total: int) -> float:
    if total == 0:
        return 1.0
    return matched / total


def _count_score(original_count: int, imported_count: int) -> float:
    denominator = max(original_count, imported_count, 1)
    return 1.0 - (abs(original_count - imported_count) / denominator)
