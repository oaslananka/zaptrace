"""Specctra DSN export — universal interchange for external autorouters."""

from __future__ import annotations

from typing import Protocol

from zaptrace.core.models import Design, LayerSet, Net, Pad
from zaptrace.ee.knowledge import KnowledgeBase
from zaptrace.ee.routing.impedance import ImpedanceResult

_INDENTED_CLOSE = "    )"


class _GeometryResolver(Protocol):
    def resolve_net_geometry(self, net: Net) -> ImpedanceResult | dict[str, float] | None: ...


def _parser_lines() -> list[str]:
    """Render parser metadata and coordinate units."""
    return [
        "  (parser",
        '    (string_quote ")',
        "    (space_in_quoted_tokens on)",
        '    (host_cad "ZapTrace")',
        '    (host_version "1.0")',
        "  )",
        "  (resolution mm 10000)",
        "  (unit mm)",
    ]


def _outline_path_points(design: Design) -> list[str]:
    board = design.board_def
    if board is None or not board.outline:
        return []
    points = [f"{point[0]:.4f} {point[1]:.4f}" for point in board.outline]
    if board.outline[0] != board.outline[-1]:
        first = board.outline[0]
        points.append(f"{first[0]:.4f} {first[1]:.4f}")
    return points


def _structure_lines(design: Design) -> tuple[list[str], list[str]]:
    """Render layer stack and board boundary records."""
    lines = ["  (structure"]
    layer_names: list[str] = []
    board = design.board_def
    if board is not None:
        for layer in board.layer_stack:
            layer_type = "signal" if layer.type.lower() == "signal" else "power"
            lines.append(f"    (layer {layer.name} (type {layer_type}))")
            layer_names.append(layer.name)

    outline_points = _outline_path_points(design)
    if outline_points:
        lines.extend(
            [
                "    (boundary",
                f"      (path pcb 0 {' '.join(outline_points)})",
                _INDENTED_CLOSE,
            ]
        )
    lines.append("  )")
    return lines, layer_names


def _component_placement(design: Design, component_id: str) -> tuple[float, float, float]:
    component = design.components[component_id]
    if design.placement and component_id in design.placement:
        placement = design.placement[component_id]
        if len(placement) >= 3:
            return placement[0], placement[1], placement[2]
        return placement[0], placement[1], 0.0
    if component.position:
        return component.position[0], component.position[1], 0.0
    return 0.0, 0.0, 0.0


def _placement_lines(design: Design) -> list[str]:
    """Render placed components that have physical pads."""
    lines = ["  (placement"]
    for component_id, component in design.components.items():
        if not component.footprint_def or not component.footprint_def.pads:
            continue
        pos_x, pos_y, rotation = _component_placement(design, component_id)
        lines.extend(
            [
                f"    (component {component_id}",
                f"      (place {component_id} {pos_x:.4f} {pos_y:.4f} front {rotation:.1f})",
                _INDENTED_CLOSE,
            ]
        )
    lines.append("  )")
    return lines


def _pad_layer_name(pad: Pad, layer_names: list[str]) -> str:
    layer_name = layer_names[0] if layer_names else "F.Cu"
    if pad.layer == LayerSet.BOTTOM and len(layer_names) > 1:
        return layer_names[-1]
    return layer_name


def _padstack_name(pad: Pad, layer_name: str) -> str:
    return f"Pad_{pad.shape.value}_{pad.size[0]:.2f}x{pad.size[1]:.2f}_{layer_name}".replace(".", "_")


def _padstack_shape(pad: Pad, layer_name: str) -> str:
    if pad.shape.value == "circle":
        return f"(circle {layer_name} {pad.size[0] / 2:.4f})"
    x1, y1 = -pad.size[0] / 2, -pad.size[1] / 2
    x2, y2 = pad.size[0] / 2, pad.size[1] / 2
    return f"(rect {layer_name} {x1:.4f} {y1:.4f} {x2:.4f} {y2:.4f})"


def _library_lines(design: Design, layer_names: list[str]) -> list[str]:
    """Render component images and deduplicated padstack definitions."""
    lines = ["  (library"]
    padstacks: dict[str, tuple[Pad, str]] = {}
    for component_id, component in design.components.items():
        if not component.footprint_def or not component.footprint_def.pads:
            continue
        lines.append(f"    (image {component_id}")
        for pad in component.footprint_def.pads:
            layer_name = _pad_layer_name(pad, layer_names)
            padstack_name = _padstack_name(pad, layer_name)
            padstacks.setdefault(padstack_name, (pad, layer_name))
            lines.append(f"      (pin {padstack_name} {pad.id} {pad.position[0]:.4f} {pad.position[1]:.4f})")
        lines.append(_INDENTED_CLOSE)

    for padstack_name, (pad, layer_name) in padstacks.items():
        lines.extend(
            [
                f"    (padstack {padstack_name}",
                f"      (shape {_padstack_shape(pad, layer_name)})",
                _INDENTED_CLOSE,
            ]
        )
    lines.append("  )")
    return lines


def _network_lines(design: Design) -> list[str]:
    """Render logical net connectivity."""
    lines = ["  (network"]
    for net in design.nets.values():
        lines.extend([f"    (net {net.name}", "      (pins"])
        lines.extend(f"        {node.component_ref}-{node.pin_name}" for node in net.nodes)
        lines.extend(["      )", _INDENTED_CLOSE])
    lines.append("  )")
    return lines


def _trace_width(net: Net, knowledge_base: _GeometryResolver) -> float:
    geometry = knowledge_base.resolve_net_geometry(net)
    if isinstance(geometry, ImpedanceResult):
        return geometry.trace_width
    if isinstance(geometry, dict):
        return geometry.get("trace_width", 0.2)
    return 0.2


def _wiring_lines(design: Design, knowledge_base: _GeometryResolver) -> list[str]:
    """Render per-net width and clearance classes."""
    lines = ["  (wiring"]
    for net in design.nets.values():
        width = _trace_width(net, knowledge_base)
        lines.extend(
            [
                f"    (class {net.name}_Class {net.name}",
                "      (rule",
                f"        (width {width:.4f})",
                "        (clearance 0.1500)",
                "      )",
                _INDENTED_CLOSE,
            ]
        )
    lines.append("  )")
    return lines


def export_dsn(design: Design) -> str:
    """Serialize a placed design to a complete Specctra DSN string."""
    knowledge_base = KnowledgeBase()
    lines = [f"(pcb {design.meta.name}"]
    lines.extend(_parser_lines())
    structure, layer_names = _structure_lines(design)
    lines.extend(structure)
    lines.extend(_placement_lines(design))
    lines.extend(_library_lines(design, layer_names))
    lines.extend(_network_lines(design))
    lines.extend(_wiring_lines(design, knowledge_base))
    lines.append(")")
    return "\n".join(lines)
