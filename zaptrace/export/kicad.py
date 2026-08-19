"""KiCad file export — schematic (.kicad_sch) and PCB (.kicad_pcb).

All coordinates are in **millimeters**.  Output is review-grade; always run
the official KiCad DRC before fabrication.
"""

from __future__ import annotations

import json
import uuid as _uuid
from collections import Counter
from pathlib import Path

from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import (
    Component,
    CopperPourArea,
    Design,
    LayerSet,
    MountingHole,
    Pad,
    PadShape,
    TraceSegment,
)
from zaptrace.core.net_identity import canonical_routing_net_ids
from zaptrace.export.path_policy import resolve_output_artifact

_INDENTED_CLOSE = "    )"
_DOUBLE_INDENTED_CLOSE = "      )"
_SCHEMATIC_HIDDEN_EFFECTS = "        (effects (font (size 1.27 1.27)) (hide yes))"

# ======================================================================
# Public API
# ======================================================================


def _artifact_path(output_dir: Path, design: Design, suffix: str) -> Path:
    """Build a canonical KiCad artifact path inside a trusted output directory."""
    return resolve_output_artifact(
        output_dir,
        design.meta.name,
        suffix,
        fallback="zaptrace_design",
    )


def export_kicad(design: Design, output_dir: Path) -> dict[str, Path]:
    """Export both schematic and PCB to KiCad files.

    Returns dict of ``{kind: Path}``.
    """
    files = export_kicad_schematic(design, output_dir)
    files.update(export_kicad_pcb(design, output_dir))
    files.update(export_kicad_netlist_evidence(design, output_dir))
    return files


def export_kicad_schematic(design: Design, output_dir: Path) -> dict[str, Path]:
    """Export schematic (.kicad_sch + .kicad_pro).

    Returns dict of ``{kind: Path}``.
    """
    files: dict[str, Path] = {}

    sch_path = _artifact_path(output_dir, design, ".kicad_sch")
    sch_path.write_text(_build_schematic(design), encoding="utf-8", newline="\n")
    files["schematic"] = sch_path

    pro_path = _artifact_path(output_dir, design, ".kicad_pro")
    pro_path.write_text(_build_project(design), encoding="utf-8", newline="\n")
    files["project"] = pro_path

    return files


def export_kicad_pcb(design: Design, output_dir: Path) -> dict[str, Path]:
    """Export PCB layout (.kicad_pcb).

    Returns dict of ``{kind: Path}``.
    """
    files: dict[str, Path] = {}

    pcb_path = _artifact_path(output_dir, design, ".kicad_pcb")
    pcb_path.write_text(_build_pcb(design), encoding="utf-8", newline="\n")
    files["pcb"] = pcb_path

    return files


def export_kicad_netlist_evidence(design: Design, output_dir: Path) -> dict[str, Path]:
    """Export machine-readable netlist fidelity evidence for KiCad artifacts.

    The evidence is not a KiCad-native netlist. It is a ZapTrace contract that
    records which schematic nodes, footprint pads, PCB traces, and vias were
    represented by the generated KiCad artifact set.
    """
    evidence_path = _artifact_path(output_dir, design, ".kicad_netlist_evidence.json")
    evidence_path.write_text(
        json.dumps(_build_netlist_evidence(design), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {"netlist_evidence": evidence_path}


# ======================================================================
# Schematic (.kicad_sch)
# ======================================================================


_SCHEMATIC_UUID_NAMESPACE = _uuid.uuid5(_uuid.NAMESPACE_URL, "https://zaptrace.dev/kicad/schematic")


def _schematic_uuid(design: Design, *parts: str) -> str:
    """Return a deterministic UUID for one schematic artifact element."""
    key = "|".join((design.meta.name, design.meta.version, *parts))
    return str(_uuid.uuid5(_SCHEMATIC_UUID_NAMESPACE, key))


def _schematic_identifier(value: str) -> str:
    """Return a KiCad-library-safe identifier fragment."""
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)
    return cleaned or "component"


def _schematic_string(value: object) -> str:
    """Escape a value for a quoted KiCad S-expression string."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _schematic_number(value: float) -> str:
    """Format deterministic millimetre coordinates without binary-float noise."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _schematic_nodes_for_component(design: Design, component: Component) -> list[tuple[str, str]]:
    """Return unique logical pins and net names connected to *component*."""
    nodes: list[tuple[str, str]] = []
    seen_pins: set[str] = set()
    for net in design.nets.values():
        for node in net.nodes:
            if node.component_ref not in (component.id, component.ref) or node.pin_name in seen_pins:
                continue
            seen_pins.add(node.pin_name)
            nodes.append((node.pin_name, net.name))
    return nodes


def _schematic_component_position(index: int) -> tuple[float, float]:
    """Place components on KiCad's 2.54 mm connection grid."""
    return 50.8 + (index % 8) * 50.8, 50.8 + (index // 8) * 50.8


def _schematic_pin_geometry(index: int) -> tuple[float, float, int]:
    """Return local pin endpoint and orientation on KiCad's connection grid."""
    left_side = index % 2 == 0
    row = index // 2
    return (-5.08 if left_side else 5.08), row * 2.54, (0 if left_side else 180)


def _schematic_property(
    lines: list[str], name: str, value: object, x: float, y: float, *, hidden: bool = False
) -> None:
    """Append one KiCad property with the minimum valid effects block."""
    lines.append(
        f'    (property "{name}" "{_schematic_string(value)}" (at {_schematic_number(x)} {_schematic_number(y)} 0)'
    )
    lines.append("      (effects (font (size 1.27 1.27))" + (" (hide yes)" if hidden else "") + ")")
    lines.append(_INDENTED_CLOSE)


def _schematic_library_symbol(component: Component, nodes: list[tuple[str, str]]) -> list[str]:
    """Build a self-contained minimal KiCad library symbol for one component."""
    lib_id = f"ZapTrace_{_schematic_identifier(component.ref)}"
    lines = [
        f'    (symbol "{lib_id}"',
        "      (exclude_from_sim no)",
        "      (in_bom yes)",
        "      (on_board yes)",
        f'      (property "Reference" "{_schematic_string(component.ref[:1] or "U")}" (at 0 2.54 0)',
        "        (effects (font (size 1.27 1.27)))",
        _DOUBLE_INDENTED_CLOSE,
        (
            '      (property "Value" '
            f'"{_schematic_string(component.value or component.type or component.ref)}" (at 0 -2.54 0)'
        ),
        "        (effects (font (size 1.27 1.27)))",
        _DOUBLE_INDENTED_CLOSE,
        '      (property "Footprint" "" (at 0 0 0)',
        _SCHEMATIC_HIDDEN_EFFECTS,
        _DOUBLE_INDENTED_CLOSE,
        '      (property "Datasheet" "" (at 0 0 0)',
        _SCHEMATIC_HIDDEN_EFFECTS,
        _DOUBLE_INDENTED_CLOSE,
        '      (property "Description" "ZapTrace generated connectivity symbol" (at 0 0 0)',
        _SCHEMATIC_HIDDEN_EFFECTS,
        _DOUBLE_INDENTED_CLOSE,
        f'      (symbol "{lib_id}_1_1"',
        "        (rectangle (start -2.54 2.54) (end 2.54 -2.54)",
        "          (stroke (width 0) (type default))",
        "          (fill (type background))",
        "        )",
    ]
    for pin_index, (pin_name, _net_name) in enumerate(nodes):
        local_x, local_y, rotation = _schematic_pin_geometry(pin_index)
        safe_pin = _schematic_string(pin_name)
        lines.extend(
            [
                f"        (pin passive line (at {_schematic_number(local_x)} {_schematic_number(local_y)} {rotation})",
                "          (length 2.54)",
                f'          (name "{safe_pin}" (effects (font (size 1.27 1.27))))',
                f'          (number "{safe_pin}" (effects (font (size 1.27 1.27))))',
                "        )",
            ]
        )
    lines.extend([_DOUBLE_INDENTED_CLOSE, _INDENTED_CLOSE])
    return lines


def _schematic_symbol_instance(
    design: Design,
    component: Component,
    nodes: list[tuple[str, str]],
    index: int,
) -> tuple[list[str], list[str]]:
    """Build one symbol instance plus same-coordinate labels for connected pins."""
    x, y = _schematic_component_position(index)
    lib_id = f"ZapTrace_{_schematic_identifier(component.ref)}"
    symbol_uuid = _schematic_uuid(design, "symbol", component.ref)
    lines = [
        "  (symbol",
        f'    (lib_id "{lib_id}")',
        f"    (at {_schematic_number(x)} {_schematic_number(y)} 0)",
        "    (unit 1)",
        "    (exclude_from_sim no)",
        "    (in_bom yes)",
        "    (on_board yes)",
        "    (dnp no)",
        f'    (uuid "{symbol_uuid}")',
    ]
    _schematic_property(lines, "Reference", component.ref, x, y - 7.62)
    _schematic_property(lines, "Value", component.value or component.type or component.ref, x, y + 7.62)
    _schematic_property(lines, "Footprint", component.footprint or "", x, y, hidden=True)
    _schematic_property(lines, "Datasheet", "", x, y, hidden=True)
    _schematic_property(lines, "Description", "ZapTrace generated connectivity symbol", x, y, hidden=True)

    labels: list[str] = []
    for pin_index, (pin_name, net_name) in enumerate(nodes):
        local_x, local_y, _rotation = _schematic_pin_geometry(pin_index)
        pin_uuid = _schematic_uuid(design, "pin", component.ref, pin_name)
        lines.append(f'    (pin "{_schematic_string(pin_name)}" (uuid "{pin_uuid}"))')
        label_uuid = _schematic_uuid(design, "label", component.ref, pin_name, net_name)
        labels.append(
            f'  (label "{_schematic_string(net_name)}" '
            f"(at {_schematic_number(x + local_x)} {_schematic_number(y - local_y)} 0) "
            f'(effects (font (size 1.27 1.27))) (uuid "{label_uuid}"))'
        )
    lines.append("  )")
    return lines, labels


def _build_schematic(design: Design) -> str:
    """Build a self-contained, deterministic KiCad schematic.

    Each canonical net node is represented by an embedded-library pin, a
    standards-shaped symbol-instance pin UUID, and a same-coordinate local net
    label. The embedded symbols intentionally use passive electrical pin types:
    canonical electrical semantics remain enforced by ZapTrace ERC while this
    review-grade export preserves real KiCad connectivity without inventing pin
    directions that the canonical model cannot distinguish reliably.
    """
    root_uuid = _schematic_uuid(design, "root")
    lines = [
        "(kicad_sch",
        "  (version 20231120)",
        '  (generator "zaptrace")',
        f'  (uuid "{root_uuid}")',
        (
            "  (title_block "
            f'(title "{_schematic_string(design.meta.name)}") '
            f'(rev "{_schematic_string(design.meta.version)}")'
        ),
        f'    (company "{_schematic_string(design.meta.author)}")',
        "  )",
        "  (lib_symbols",
    ]
    component_nodes = [
        (component, _schematic_nodes_for_component(design, component)) for component in design.components.values()
    ]
    for component, nodes in component_nodes:
        lines.extend(_schematic_library_symbol(component, nodes))
    lines.append("  )")

    labels: list[str] = []
    for index, (component, nodes) in enumerate(component_nodes):
        instance_lines, instance_labels = _schematic_symbol_instance(design, component, nodes, index)
        lines.extend(instance_lines)
        labels.extend(instance_labels)
    lines.extend(labels)
    lines.extend(['  (sheet_instances (path "/" (page "1")))', ")"])
    return "\n".join(lines) + "\n"


def _build_project(design: Design) -> str:
    return json.dumps(
        {
            "meta": {"version": 1},
            "board": {"design_settings": {"defaults": {"copper_line_width": 0.25}}},
            "sheets": [["", design.meta.name]],
        },
        indent=2,
    )


# ======================================================================
# PCB (.kicad_pcb)
# ======================================================================


def _build_pcb(design: Design) -> str:
    """Build .kicad_pcb S-expression content from *design*."""
    lines: list[str] = []
    _w = lines.append

    _w("(kicad_pcb")
    _w("  (version 20241229)")
    _w('  (generator "zaptrace")')
    _w(f'  (generator_version "{design.meta.version}")')
    _w("  (general")
    _w("    (thickness 1.6)")
    _w("    (legacy_teardrops no)")
    _w("  )")
    _w('  (paper "A4")')

    # Page settings — title block
    _w("  (title_block")
    _w(f'    (title "{design.meta.name}")')
    _w(f'    (rev "{design.meta.version}")')
    if design.meta.author:
        _w(f'    (company "{design.meta.author}")')
    _w("  )")

    # Layer definitions
    board = canonical_board_definition(design)
    num_layers = board.layers
    _build_layers(lines, num_layers)

    # Setup (design rules)
    _w("  (setup")
    _w("    (via_size 0.6)")
    _w("    (via_drill 0.3)")
    _w("    (uvia_size 0.3)")
    _w("    (uvia_drill 0.1)")
    _w("  )")

    # Net definitions
    nets_list = _build_nets_list(design)
    for net_expr in nets_list:
        _w(net_expr)

    # Board outline
    _build_board_outline(lines, design)

    # Mounting holes
    mhs: list[MountingHole] = []
    if design.board_def is not None:
        mhs = canonical_board_definition(design).mounting_holes
    for mh in mhs:
        _build_mounting_hole(lines, mh)

    # Footprints (components)
    for comp in design.components.values():
        pos = _component_position(comp, design.placement)
        if pos is not None:
            _build_footprint(lines, comp, pos, design)

    # Traces (segments)
    net_ids = _net_index(design)
    routing = design.routing
    if routing is not None:
        canonical_routing_net_ids(design, routing)
        for seg in routing.traces:
            _build_segment(lines, seg, net_ids, num_layers)
        for via_data in routing.vias:
            _build_via(lines, via_data, net_ids, num_layers)

    # Copper pours
    for area in design.copper_pours.values():
        _build_zone(lines, area, net_ids)

    _w(")")

    return "\n".join(lines)


# ======================================================================
# Layer helpers
# ======================================================================


def _layer_name(index: int, num_layers: int) -> str:
    """Return the KiCad layer name for a logical layer *index*.

    2-layer boards: 0→F.Cu, 1→B.Cu
    4-layer boards: 0→F.Cu, 1→In1.Cu, 2→In2.Cu, 3→B.Cu
    """
    if index == 0:
        return "F.Cu"
    if num_layers <= 2:
        return "B.Cu"
    if index >= num_layers - 1:
        return "B.Cu"
    return f"In{index}.Cu"


def _copper_layers(num_layers: int) -> list[str]:
    """Return the list of copper layer names for *num_layers*."""
    return [_layer_name(i, num_layers) for i in range(num_layers)]


def _build_layers(lines: list[str], num_layers: int) -> None:
    """Emit KiCad 9/10 layer definitions to *lines*."""
    copper_layer_ids = [0] if num_layers <= 1 else [0, *range(4, 4 + max(num_layers - 2, 0) * 2, 2), 2]
    copper_names = _copper_layers(max(num_layers, 2))
    lines.append("  (layers")
    for layer_id, name in zip(copper_layer_ids, copper_names, strict=False):
        lines.append(f'    ({layer_id} "{name}" signal)')
    lines.extend(
        [
            '    (9 "F.Adhes" user "F.Adhesive")',
            '    (11 "B.Adhes" user "B.Adhesive")',
            '    (13 "F.Paste" user)',
            '    (15 "B.Paste" user)',
            '    (5 "F.SilkS" user "F.Silkscreen")',
            '    (7 "B.SilkS" user "B.Silkscreen")',
            '    (1 "F.Mask" user)',
            '    (3 "B.Mask" user)',
            '    (17 "Dwgs.User" user "User.Drawings")',
            '    (19 "Cmts.User" user "User.Comments")',
            '    (21 "Eco1.User" user "User.Eco1")',
            '    (23 "Eco2.User" user "User.Eco2")',
            '    (25 "Edge.Cuts" user)',
            '    (27 "Margin" user)',
            '    (31 "F.CrtYd" user "F.Courtyard")',
            '    (29 "B.CrtYd" user "B.Courtyard")',
            '    (35 "F.Fab" user)',
            '    (33 "B.Fab" user)',
        ]
    )
    lines.append("  )")


def _kicad_layer_name(layer: str, num_layers: int) -> str:
    """Map an internal layer identifier to a KiCad layer name.

    Handles ``layer_0``, ``top``, ``F.Cu`` → ``F.Cu``, and
    ``layer_1``, ``bottom`` → ``B.Cu`` or inner layers.
    """
    normalized = layer.replace("-", "_").replace(" ", "_").lower()
    if normalized in ("f.cu", "top", "layer_0"):
        return "F.Cu"
    if normalized in ("b.cu", "bottom", "layer_1"):
        return _layer_name(1, num_layers)
    for i in range(num_layers):
        if normalized in (f"layer_{i}", f"in{i}.cu"):
            return _layer_name(i, num_layers)
    # Passthrough — assume already a valid KiCad name
    return layer


def _layer_set_to_kicad(ls: LayerSet) -> str:
    """Map *LayerSet* to KiCad layer string."""
    mapping = {
        LayerSet.TOP: '"F.Cu"',
        LayerSet.BOTTOM: '"B.Cu"',
        LayerSet.ALL: '"*.Cu" "*.Mask"',
        LayerSet.INNER: '"In*.Cu"',
    }
    return mapping.get(ls, '"F.Cu"')


def _pad_shape_kicad(shape: PadShape) -> str:
    """Map *PadShape* to KiCad pad type."""
    mapping = {
        PadShape.RECT: "rect",
        PadShape.CIRCLE: "circle",
        PadShape.OVAL: "oval",
        PadShape.CUSTOM: "custom",
    }
    return mapping.get(shape, "rect")


def _component_by_ref_or_id(design: Design, ref: str) -> Component | None:
    for comp in design.components.values():
        if ref in (comp.id, comp.ref):
            return comp
    return None


def _component_pad_ids(comp: Component) -> set[str]:
    if comp.footprint_def is not None and comp.footprint_def.pads:
        return {pad.id for pad in comp.footprint_def.pads}
    return set(comp.pins)


def _physical_pad_ids_for_logical_pin(comp: Component, pin_name: str) -> set[str]:
    if not comp.package_pin_map:
        return {pin_name}
    return {pad_id for pad_id, logical_pin in comp.package_pin_map.items() if logical_pin == pin_name}


def _net_node_evidence(design: Design, component_ref: str, pin_name: str) -> tuple[dict[str, object], bool]:
    component = _component_by_ref_or_id(design, component_ref)
    component_present = component is not None
    pad_ids = _component_pad_ids(component) if component is not None else set()
    schematic_pin_present = component is not None and (pin_name in component.pins or not component.pins)
    expected_pad_ids = _physical_pad_ids_for_logical_pin(component, pin_name) if component is not None else set()
    if component is not None and component.package_pin_map:
        pcb_pad_present = bool(expected_pad_ids) and expected_pad_ids.issubset(pad_ids)
    else:
        pcb_pad_present = component is not None and (expected_pad_ids.issubset(pad_ids) if pad_ids else True)
    payload: dict[str, object] = {
        "component_ref": component_ref,
        "pin_name": pin_name,
        "component_present": component_present,
        "schematic_pin_present": schematic_pin_present,
        "pcb_pad_present": pcb_pad_present,
    }
    return payload, component_present and schematic_pin_present and pcb_pad_present


def _net_evidence(
    design: Design,
    net_id: str,
    trace_counts: Counter[str],
    via_counts: Counter[str],
) -> tuple[dict[str, object], int, int]:
    net = design.nets[net_id]
    nodes: list[dict[str, object]] = []
    missing_nodes: list[str] = []
    for node in net.nodes:
        payload, mapped = _net_node_evidence(design, node.component_ref, node.pin_name)
        nodes.append(payload)
        if not mapped:
            missing_nodes.append(f"{node.component_ref}.{node.pin_name}")
    payload = {
        "id": net_id,
        "name": net.name,
        "type": str(net.type),
        "nodes": nodes,
        "missing_or_unmapped_nodes": missing_nodes,
        "routed_segment_count": int(trace_counts.get(net_id, 0)),
        "routed_via_count": int(via_counts.get(net_id, 0)),
    }
    return payload, len(nodes), len(missing_nodes)


def _build_netlist_evidence(design: Design) -> dict[str, object]:
    """Build deterministic netlist evidence shared by schematic and PCB exports."""
    routing = design.routing
    canonical_routing_net_ids(design, routing)
    trace_counts = Counter(trace.net_id for trace in getattr(routing, "traces", []) if trace.net_id)
    via_counts = Counter(via[4] for via in getattr(routing, "vias", []) if len(via) >= 5 and via[4])

    nets: list[dict[str, object]] = []
    total_nodes = 0
    total_missing_pads = 0
    for net_id in design.nets:
        payload, node_count, missing_count = _net_evidence(design, net_id, trace_counts, via_counts)
        nets.append(payload)
        total_nodes += node_count
        total_missing_pads += missing_count

    return {
        "schema_version": "1.0",
        "generator": "zaptrace.kicad.netlist_evidence",
        "design": design.meta.name,
        "net_count": len(nets),
        "node_count": total_nodes,
        "missing_or_unmapped_node_count": total_missing_pads,
        "nets": nets,
        "fidelity": {
            "schematic_node_coverage": 1.0 if total_nodes == 0 else (total_nodes - total_missing_pads) / total_nodes,
            "pcb_pad_coverage": 1.0 if total_nodes == 0 else (total_nodes - total_missing_pads) / total_nodes,
            "has_routed_pcb_geometry": any(trace_counts.values()),
        },
    }


# ======================================================================
# Net helpers
# ======================================================================


def _net_index(design: Design) -> dict[str, int]:
    """Build ``net_id → net_number`` mapping (KiCad uses integer net IDs)."""
    idx: dict[str, int] = {}
    for i, net in enumerate(design.nets.values()):
        idx[net.id] = i + 1  # net 0 is reserved for unconnected
    return idx


def _build_nets_list(design: Design) -> list[str]:
    """Build ``(net N "Name")`` S-expressions."""
    exprs: list[str] = []
    for i, net in enumerate(design.nets.values()):
        exprs.append(f'  (net {i + 1} "{net.name}")')
    if not exprs:
        exprs.append('  (net 0 "")')
    return exprs


# ======================================================================
# Board outline
# ======================================================================


def _build_board_outline(lines: list[str], design: Design) -> None:
    """Emit board outline as ``(gr_rect ...)`` on Edge.Cuts."""
    board = canonical_board_definition(design)
    width = board.width
    height = board.height

    uid = _uuid4()
    lines.append("  (gr_rect")
    lines.append("    (start 0 0)")
    lines.append(f"    (end {width} {height})")
    lines.append("    (stroke (width 0.1) (type default))")
    lines.append("    (fill none)")
    lines.append('    (layer "Edge.Cuts")')
    lines.append(f'    (uuid "{uid}")')
    lines.append("  )")


# ======================================================================
# Mounting holes
# ======================================================================


def _build_mounting_hole(lines: list[str], mh: MountingHole) -> None:
    """Emit a mounting hole as a footprint with a single NPTH pad."""
    uid = _uuid4()
    x, y = mh.position
    lines.append('  (footprint "MountingHole"')
    lines.append('    (layer "F.Cu")')
    lines.append(f'    (uuid "{uid}")')
    lines.append(f"    (at {x} {y} 0)")
    lines.append(f'    (descr "Mounting hole ∅{mh.diameter} mm")')
    drill = mh.diameter * 0.9  # slightly smaller than hole
    lines.append('    (pad "" np_thru_hole circle')
    lines.append("      (at 0 0)")
    lines.append(f"      (size {mh.diameter} {mh.diameter})")
    lines.append(f"      (drill {drill})")
    lines.append('      (layers "*.Cu" "*.Mask")')
    lines.append(f'      (uuid "{_uuid4()}")')
    lines.append(_INDENTED_CLOSE)
    lines.append("  )")


# ======================================================================
# Footprints
# ======================================================================


def _component_position(
    comp: Component,
    placement: dict[str, tuple[float, float]] | None,
) -> tuple[float, float] | None:
    """Return the absolute board position of *comp*."""
    if comp.position is not None:
        return comp.position
    if placement is not None:
        pos = placement.get(comp.id) or placement.get(comp.ref)
        return pos
    return None


def _build_footprint(
    lines: list[str],
    comp: Component,
    at: tuple[float, float],
    design: Design,
) -> None:
    """Emit a KiCad footprint for *comp* placed at *at*."""
    uid = _uuid4()
    x, y = at
    fp = comp.footprint_def
    net_idx = _net_index(design)

    # Determine a reasonable KiCad library ID
    lib_id = f"zaptrace:{comp.type or 'unknown'}"
    has_pads = fp is not None and len(fp.pads) > 0

    lines.append(f'  (footprint "{lib_id}"')
    lines.append('    (layer "F.Cu")')
    lines.append(f'    (uuid "{uid}")')
    lines.append(f"    (at {x} {y} 0)")

    # Reference designator
    lines.append(f'    (property "Reference" "{comp.ref}"')
    lines.append("      (at 0 -2 0)")
    lines.append('      (layer "F.SilkS")')
    lines.append(f'      (uuid "{_uuid4()}")')
    lines.append("      (effects (font (size 1 1) (thickness 0.15)))")
    lines.append(_INDENTED_CLOSE)

    # Value
    if comp.value:
        lines.append(f'    (property "Value" "{comp.value}"')
        lines.append("      (at 0 3 0)")
        lines.append('      (layer "F.Fab")')
        lines.append(f'      (uuid "{_uuid4()}")')
        lines.append("      (effects (font (size 1 1) (thickness 0.15)))")
        lines.append(_INDENTED_CLOSE)

    # Footprint property
    lines.append(f'    (property "Footprint" "{fp.description if fp else ""}"')
    lines.append(f"      (at {x} {y} 0)")
    lines.append('      (layer "F.Fab")')
    lines.append("      (hide yes)")
    lines.append(_INDENTED_CLOSE)

    if has_pads and fp is not None:
        for pad in fp.pads:
            _build_pad(lines, pad, comp, net_idx, design)

    lines.append("  )")


def _build_pad(
    lines: list[str],
    pad: Pad,
    comp: Component,
    net_idx: dict[str, int],
    design: Design | None = None,
) -> None:
    """Emit a KiCad pad S-expression."""
    uid = _uuid4()
    pad_id = pad.id
    pad_type = "smd" if pad.drill is None else "thru_hole"
    pad_shape = _pad_shape_kicad(pad.shape)
    px, py = pad.position
    sw, sh = pad.size

    if pad.layer == LayerSet.TOP:
        layers_str = '"F.Cu" "F.Paste" "F.Mask"'
    elif pad.layer == LayerSet.BOTTOM:
        layers_str = '"B.Cu" "B.Paste" "B.Mask"'
    elif pad.layer == LayerSet.ALL:
        layers_str = '"*.Cu" "*.Mask"'
    else:
        layers_str = '"F.Cu" "F.Paste" "F.Mask"'

    lines.append(f'    (pad "{pad_id}" {pad_type} {pad_shape}')
    lines.append(f"      (at {px} {py} {pad.rotation})")
    lines.append(f"      (size {sw} {sh})")
    if pad.drill is not None:
        lines.append(f"      (drill {pad.drill})")
    lines.append(f"      (layers {layers_str})")

    net_num = _pin_net_number(comp, pad_id, net_idx, design)
    if net_num > 0:
        net_name = _net_name(design, net_num) if design else ""
        if net_name:
            lines.append(f'      (net {net_num} "{net_name}")')
        else:
            lines.append(f"      (net {net_num})")
    lines.append(f'      (uuid "{uid}")')
    lines.append(_INDENTED_CLOSE)


def _pin_net_number(comp: Component, pin_name: str, net_idx: dict[str, int], design: Design | None = None) -> int:
    """Look up the net number for *comp*'s pin *pin_name*.

    First checks the component's direct pin→net mapping (fast path).
    If not found and *design* is provided, searches all nets for a
    connection to this component+pin combination.
    """
    logical_pin_name = comp.package_pin_map.get(pin_name) if comp.package_pin_map else pin_name
    if logical_pin_name is None:
        return 0
    # Fast path: direct logical pin→net lookup.
    pin = comp.pins.get(logical_pin_name)
    if pin is not None and pin.net is not None:
        return net_idx.get(pin.net, 0)

    # Fallback: search all nets for this component+logical-pin combination.
    if design is not None:
        for net in design.nets.values():
            for node in net.nodes:
                if node.component_ref in (comp.id, comp.ref) and node.pin_name == logical_pin_name:
                    return net_idx.get(net.id, 0)

    return 0


def _net_name(design: Design, net_num: int) -> str:
    """Return the net name for *net_num* (1-based)."""
    for net in design.nets.values():
        n = next((i + 1 for i, n in enumerate(design.nets.values()) if n.id == net.id), 0)
        if n == net_num:
            return net.name
    return ""


# ======================================================================
# Traces (segments) & Vias
# ======================================================================


def _build_segment(
    lines: list[str],
    seg: TraceSegment,
    net_idx: dict[str, int],
    num_layers: int,
) -> None:
    """Emit a trace segment ``(segment ...)``."""
    uid = _uuid4()
    kicad_layer = _kicad_layer_name(seg.layer, num_layers)
    net_num = net_idx.get(seg.net_id, 0)
    if net_num == 0:
        return  # skip unconnected

    lines.append("  (segment")
    lines.append(f"    (start {seg.start[0]} {seg.start[1]})")
    lines.append(f"    (end {seg.end[0]} {seg.end[1]})")
    lines.append(f"    (width {seg.width})")
    lines.append(f'    (layer "{kicad_layer}")')
    lines.append(f"    (net {net_num})")
    lines.append(f'    (uuid "{uid}")')
    lines.append("  )")


def _build_via(
    lines: list[str],
    via: tuple[float, float, float, float] | tuple[float, float, float, float, str],
    net_idx: dict[str, int],
    num_layers: int,
) -> None:
    """Emit a via ``(via ...)``.

    *via* tuple can be:
    - ``(x, y, diameter, hole)`` — backward-compat, net=0
    - ``(x, y, diameter, hole, net_id)`` — preferred, carries net info for DRC
    """
    uid = _uuid4()
    x, y, diameter, hole, *rest = via
    via_net_id = rest[0] if rest else ""

    layers_str = '"F.Cu" "B.Cu"'
    if num_layers > 2:
        inner_list = " ".join(f'"In{n}.Cu"' for n in range(1, num_layers - 1))
        layers_str = f'"F.Cu" {inner_list} "B.Cu"'

    net_num = net_idx.get(via_net_id, 0) if via_net_id else 0

    lines.append("  (via")
    lines.append(f"    (at {x} {y})")
    lines.append(f"    (size {diameter})")
    lines.append(f"    (drill {hole})")
    lines.append(f"    (layers {layers_str})")
    lines.append(f"    (net {net_num})")
    lines.append(f'    (uuid "{uid}")')
    lines.append("  )")


# ======================================================================
# Copper pours (zones)
# ======================================================================


def _build_zone(
    lines: list[str],
    area: CopperPourArea,
    net_idx: dict[str, int],
) -> None:
    """Emit a copper pour zone ``(zone ...)``."""
    if len(area.polygon) < 3:
        return

    uid = _uuid4()
    net_num = net_idx.get(area.net_id, 0)
    kicad_layer = area.layer  # already a KiCad-layer name (F.Cu / B.Cu)

    lines.append("  (zone")
    lines.append(f"    (net {net_num})")
    lines.append(f'    (net_name "{area.net_id}")')
    lines.append(f'    (layer "{kicad_layer}")')
    lines.append(f'    (uuid "{uid}")')
    lines.append("    (hatch edge 0.5)")
    lines.append("    (connect_pads (clearance 0.25))")
    lines.append("    (min_thickness 0.25)")
    lines.append("    (filled_areas_thickness no)")
    lines.append("    (fill (thermal_gap 0.5) (thermal_bridge_width 0.5))")
    lines.append("    (polygon")
    lines.append("      (pts")
    for pt in area.polygon:
        lines.append(f"        (xy {pt[0]} {pt[1]})")
    lines.append("      )")
    lines.append(_INDENTED_CLOSE)
    lines.append("  )")


# ======================================================================
# Internal helpers
# ======================================================================


def _uuid4() -> str:
    """Return a fresh UUID4 string."""
    return str(_uuid.uuid4())
