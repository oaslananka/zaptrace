from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from zaptrace.core.exceptions import ParseError
from zaptrace.core.models import (
    Block,
    BoardConfig,
    BoardConstraints,
    BoardDefinition,
    Component,
    ConstraintSet,
    CopperPourArea,
    Design,
    DesignMeta,
    DRCResult,
    LayerSpec,
    MountingHole,
    Net,
    NetClass,
    NetNode,
    Pin,
    RouteResult,
    TraceSegment,
    Via,
)


def parse_file(path: Path, *, strict: bool = False) -> Design:
    """Parse a trusted filesystem path into a validated Design object.

    Agent and network callers must resolve the path through their workspace
    containment policy before calling this low-level SDK function.
    """
    try:
        # Sonar S2083 and CodeQL py/path-injection: this low-level SDK
        # function intentionally accepts an already trusted path. Network
        # and agent callers enforce workspace containment before invocation.
        # codeql[py/path-injection]
        content = path.read_text(encoding="utf-8")  # NOSONAR
    except OSError as e:
        raise ParseError(f"Cannot read {path}: {e}") from e
    return parse_str(content, source=str(path), strict=strict)


def parse_str(content: str, source: str = "<string>", *, strict: bool = False) -> Design:
    """Parse YAML content string and return a validated Design object.

    By default the parser remains lenient for legacy examples. Strict mode is
    intended for release gates and rejects YAML files that do not carry the
    ZapTrace design signature.
    """
    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ParseError(f"YAML syntax error in {source}: {e}") from e

    if not isinstance(raw, dict):
        raise ParseError(f"Design file must be a YAML mapping, got {type(raw).__name__}")

    _validate_design_signature(raw, source=source, strict=strict)

    try:
        return _build_design(raw)
    except PydanticValidationError as e:
        raise ParseError(f"Schema validation error in {source}:\n{e}") from e
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise ParseError(f"Structural error in {source}: {e}") from e


_ALLOWED_TOP_LEVEL_KEYS = {
    "kind",
    "schema_version",
    "meta",
    "board",
    "board_def",
    "components",
    "nets",
    "blocks",
    "placement",
    "routing",
    "net_classes",
    "drc_result",
    "copper_pours",
    "constraints",
}


def _validate_design_signature(raw: dict[str, Any], *, source: str, strict: bool) -> None:
    """Validate the release-mode ZapTrace design signature."""
    if not strict:
        return

    if raw.get("kind") != "zaptrace.design":
        raise ParseError(f"Strict design signature missing kind: zaptrace.design in {source}")

    schema_version = raw.get("schema_version")
    if schema_version not in (1, "1", "1.0"):
        raise ParseError(f"Strict design signature missing supported schema_version in {source}")

    meta = raw.get("meta")
    if not isinstance(meta, dict) or not str(meta.get("name", "")).strip():
        raise ParseError(f"Strict design signature requires meta.name in {source}")

    for key in ("components", "nets"):
        value = raw.get(key)
        if not isinstance(value, dict) or not value:
            raise ParseError(f"Strict design signature requires non-empty {key} mapping in {source}")

    unknown = sorted(set(raw) - _ALLOWED_TOP_LEVEL_KEYS)
    if unknown:
        raise ParseError(f"Strict design signature rejects unknown top-level keys in {source}: {', '.join(unknown)}")


def _build_design(raw: dict[str, Any]) -> Design:
    """Convert raw dict to Design, resolving pin-net references and all schema v1 fields."""
    meta = DesignMeta(**raw.get("meta", {"name": "Untitled"}))
    board = BoardConfig(**raw.get("board", {}))

    # --- Components ---
    components: dict[str, Component] = {}
    for comp_id, comp_data in raw.get("components", {}).items():
        pins: dict[str, Pin] = {}
        for pin_name, pin_data in (comp_data.get("pins") or {}).items():
            if isinstance(pin_data, str):
                pin_data = {"type": pin_data}
            pins[pin_name] = Pin.model_validate({**pin_data, "name": pin_name})
        filtered_comp = {k: v for k, v in comp_data.items() if k not in ("pins", "id")}
        components[comp_id] = Component(id=comp_id, pins=pins, **filtered_comp)

    # --- Nets ---
    nets: dict[str, Net] = {}
    for net_id, net_data in raw.get("nets", {}).items():
        nodes: list[NetNode] = []
        for node in net_data.get("nodes", []):
            if isinstance(node, str) and "." in node:
                ref, pin = node.split(".", 1)
                nodes.append(NetNode(component_ref=ref, pin_name=pin))
            elif isinstance(node, dict):
                nodes.append(NetNode(**node))
        filtered_net = {k: v for k, v in net_data.items() if k not in ("nodes", "id")}
        nets[net_id] = Net(id=net_id, nodes=nodes, **filtered_net)

    # --- Blocks ---
    blocks = [Block(**b) for b in raw.get("blocks", [])]

    # --- BoardDefinition (schema v1 extended board spec) ---
    board_def: BoardDefinition | None = None
    if "board_def" in raw:
        bd = raw["board_def"]
        if bd:
            board_def = _parse_board_definition(bd)

    # --- Placement ---
    placement: dict[str, tuple[float, float]] | None = None
    if "placement" in raw:
        placement = {}
        for cid, pos in raw["placement"].items():
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                placement[cid] = (float(pos[0]), float(pos[1]))
            elif isinstance(pos, dict) and "x" in pos and "y" in pos:
                placement[cid] = (float(pos["x"]), float(pos["y"]))

    # --- Routing (RouteResult) ---
    routing: RouteResult | None = None
    if "routing" in raw:
        routing = _parse_routing(raw["routing"])

    # --- Net Classes (net_id -> NetClass enum) ---
    net_classes: dict[str, NetClass] | None = None
    if "net_classes" in raw:
        net_classes = {}
        for net_id, nc_str in raw["net_classes"].items():
            if isinstance(nc_str, str):
                net_classes[net_id] = NetClass(nc_str)

    # --- DRC Result ---
    drc_result: DRCResult | None = None
    if "drc_result" in raw:
        drc_result = DRCResult.model_validate(raw["drc_result"])

    # --- Copper Pours ---
    copper_pours: dict[str, CopperPourArea] = {}
    if "copper_pours" in raw:
        for pour_id, pour_data in raw["copper_pours"].items():
            copper_pours[pour_id] = CopperPourArea.model_validate(pour_data)

    constraints = ConstraintSet.model_validate(raw.get("constraints") or {})

    return Design(
        meta=meta,
        components=components,
        nets=nets,
        blocks=blocks,
        board=board,
        board_def=board_def,
        placement=placement,
        routing=routing,
        net_classes=net_classes,
        drc_result=drc_result,
        copper_pours=copper_pours,
        constraints=constraints,
    )


def _parse_board_definition(bd: dict[str, Any]) -> BoardDefinition:
    """Parse BoardDefinition from raw dict, handling nested sub-models."""
    # Layer stack
    layer_stack: list[LayerSpec] = []
    for ls in bd.get("layer_stack", []):
        layer_stack.append(LayerSpec(**ls))

    # Outline (list of (x,y) tuples)
    outline: list[tuple[float, float]] = []
    for pt in bd.get("outline", []):
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            outline.append((float(pt[0]), float(pt[1])))

    # Cutouts (list of polygon outlines)
    cutouts: list[list[tuple[float, float]]] = []
    for polygon in bd.get("cutouts", []):
        poly: list[tuple[float, float]] = []
        for pt in polygon:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                poly.append((float(pt[0]), float(pt[1])))
        cutouts.append(poly)

    # Mounting holes
    mounting_holes: list[MountingHole] = []
    for mh in bd.get("mounting_holes", []):
        mounting_holes.append(MountingHole(**mh))

    return BoardDefinition(
        width=float(bd.get("width", 100.0)),
        height=float(bd.get("height", 80.0)),
        layers=int(bd.get("layers", 2)),
        layer_stack=layer_stack,
        outline=outline,
        cutouts=cutouts,
        mounting_holes=mounting_holes,
        constraints=BoardConstraints.model_validate(bd.get("constraints") or {}),
        copper_pour_gnd=bool(bd.get("copper_pour_gnd", True)),
    )


def _parse_routing(r: dict[str, Any]) -> RouteResult:
    """Parse RouteResult from raw dict."""
    traces: list[TraceSegment] = []
    for t in r.get("traces", []):
        traces.append(TraceSegment(**t))

    vias: list[Via] = []
    for v in r.get("vias", []):
        if isinstance(v, (list, tuple)) and len(v) >= 4:
            via_base = (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
            if len(v) >= 5 and v[4] is not None:
                vias.append((*via_base, str(v[4])))
            else:
                vias.append(via_base)

    return RouteResult(
        traces=traces,
        vias=vias,
        layers_used=list(r.get("layers_used", [])),
        total_trace_length_mm=float(r.get("total_trace_length_mm", 0.0)),
        net_count=int(r.get("net_count", 0)),
        routed_net_count=int(r.get("routed_net_count", 0)),
    )


# ---------------------------------------------------------------------------
# Serialization (Design -> dict -> YAML/JSON)
# ---------------------------------------------------------------------------


def design_to_dict(design: Design) -> dict[str, Any]:
    """Serialize a Design object to a plain dict suitable for YAML/JSON output.

    This is the inverse of parse_str() — together they provide lossless
    round-trip serialization for all schema v1 fields.
    """
    out: dict[str, Any] = {
        "kind": "zaptrace.design",
        "schema_version": 1,
        "meta": design.meta.model_dump(mode="json", exclude_none=True),
    }

    # Board config
    out["board"] = design.board.model_dump(mode="json", exclude_none=True)

    # Board definition (schema v1)
    if design.board_def is not None:
        out["board_def"] = _dump_board_definition(design.board_def)

    # Components
    components: dict[str, Any] = {}
    for cid, comp in design.components.items():
        cd = comp.model_dump(mode="json", exclude_none=True)
        cd.pop("id", None)
        components[cid] = cd
    out["components"] = components

    # Nets
    nets: dict[str, Any] = {}
    for nid, net in design.nets.items():
        nd = net.model_dump(mode="json", exclude_none=True)
        nd.pop("id", None)
        nets[nid] = nd
    out["nets"] = nets

    constraints = design.constraints.model_dump(mode="json", exclude_none=True)
    if any(constraints.get(key) for key in ("voltage_domains", "placement", "routing")) or constraints.get(
        "manufacturing", {}
    ).get("profile"):
        out["constraints"] = constraints

    # Blocks
    if design.blocks:
        out["blocks"] = [b.model_dump(mode="json", exclude_none=True) for b in design.blocks]

    # Placement
    if design.placement is not None:
        out["placement"] = {cid: [x, y] for cid, (x, y) in design.placement.items()}

    # Routing
    if design.routing is not None:
        out["routing"] = _dump_routing(design.routing)

    # Net classes
    if design.net_classes is not None:
        out["net_classes"] = {nid: nc.value for nid, nc in design.net_classes.items()}

    # DRC result
    if design.drc_result is not None:
        out["drc_result"] = design.drc_result.model_dump(mode="json", exclude_none=True)

    # Copper pours
    if design.copper_pours:
        out["copper_pours"] = {
            pid: pour.model_dump(mode="json", exclude_none=True) for pid, pour in design.copper_pours.items()
        }

    return out


def _dump_board_definition(bd: BoardDefinition) -> dict[str, Any]:
    """Serialize BoardDefinition to a plain dict."""
    out = {
        "width": bd.width,
        "height": bd.height,
        "layers": bd.layers,
    }
    if bd.layer_stack:
        out["layer_stack"] = [ls.model_dump(mode="json") for ls in bd.layer_stack]
    if bd.outline:
        out["outline"] = [[x, y] for x, y in bd.outline]
    if bd.cutouts:
        out["cutouts"] = [[[x, y] for x, y in poly] for poly in bd.cutouts]
    if bd.mounting_holes:
        out["mounting_holes"] = [mh.model_dump(mode="json") for mh in bd.mounting_holes]
    constraints = bd.constraints.model_dump(mode="json", exclude_none=True)
    if constraints:
        out["constraints"] = constraints
    if not bd.copper_pour_gnd:
        out["copper_pour_gnd"] = False
    return out


def _dump_routing(r: RouteResult) -> dict[str, Any]:
    """Serialize RouteResult to a plain dict."""
    out: dict[str, Any] = {}
    if r.traces:
        out["traces"] = [t.model_dump(mode="json") for t in r.traces]
    if r.vias:
        out["vias"] = [[*via[:4], via[4]] if len(via) == 5 else [*via] for via in r.vias]
    if r.layers_used:
        out["layers_used"] = r.layers_used
    if r.total_trace_length_mm:
        out["total_trace_length_mm"] = r.total_trace_length_mm
    if r.net_count:
        out["net_count"] = r.net_count
    if r.routed_net_count:
        out["routed_net_count"] = r.routed_net_count
    return out


def dump_str(design: Design, sort_keys: bool = False) -> str:
    """Serialize a Design object to a YAML string.

    This is the inverse of parse_str() and supports lossless round-trip
    for the full schema v1.
    """
    data = design_to_dict(design)
    return yaml.dump(data, default_flow_style=None, sort_keys=sort_keys, allow_unicode=True)


def dump_file(design: Design, path: Path | str, sort_keys: bool = False) -> None:
    """Serialize a Design object to a YAML file."""
    text = dump_str(design, sort_keys=sort_keys)
    Path(path).write_text(text, encoding="utf-8")


def dump_json(design: Design, indent: int = 2) -> str:
    """Serialize a Design object to a JSON string (no Pydantic model_dump_json)."""
    import json

    data = design_to_dict(design)
    return json.dumps(data, indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# JSON Schema export
# ---------------------------------------------------------------------------


def generate_json_schema() -> dict[str, Any]:
    """Generate a JSON Schema (draft 2020-12) for the ZapTrace Design model.

    The schema is computed from the Pydantic model definitions and can be
    used by editors, IDEs, and agent tooling for validation and autocompletion.
    """
    from pydantic import TypeAdapter

    ta = TypeAdapter(Design)
    schema = ta.json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://zaptrace.dev/schemas/design-v1.json"
    schema["title"] = "ZapTrace Design"
    schema["description"] = "Schema for ZapTrace PCB design files (v1)"
    return schema


def write_json_schema(path: Path | str, indent: int = 2) -> None:
    """Write the generated JSON Schema to a file."""
    import json

    schema = generate_json_schema()
    Path(path).write_text(json.dumps(schema, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
