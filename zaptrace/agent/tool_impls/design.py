"""Design agent tool implementations."""

from __future__ import annotations

from .deps import Any, Component, DiffType, diff_designs, parse_file, parse_str
from .runtime import _get_session, _persist_design, _set_design, _validate_path


def tool_design_parse_file(path: str, session_id: str = "default") -> dict[str, Any]:
    """Parse a design YAML file into a Design object."""
    p = _validate_path(path, must_exist=True)
    design = parse_file(p)
    session = _get_session(session_id)
    _set_design(session, design.meta.name, design, operation="parse-file")
    return {
        "design_name": design.meta.name,
        "component_count": len(design.components),
        "net_count": len(design.nets),
        "board": f"{design.board.width_mm}x{design.board.height_mm}mm",
    }


def tool_design_parse_str(yaml_content: str, session_id: str = "default") -> dict[str, Any]:
    """Parse a YAML string into a Design object."""
    design = parse_str(yaml_content)
    session = _get_session(session_id)
    _set_design(session, design.meta.name, design, operation="parse-string")
    return {
        "design_name": design.meta.name,
        "component_count": len(design.components),
        "net_count": len(design.nets),
        "board": f"{design.board.width_mm}x{design.board.height_mm}mm",
    }


def tool_design_inspect(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Inspect a parsed design and return its details."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        available = list(session.get("designs", {}).keys())
        raise ValueError(f"Design '{design_name}' not found. Available: {available}")
    return design.model_dump(mode="json")


def tool_design_list_nets(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """List all nets in a design with their connections."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    nets_info: dict[str, dict[str, Any]] = {}
    for net_id, net in design.nets.items():
        nets_info[net_id] = {
            "name": net.name,
            "type": net.type.value,
            "nodes": [{"component": n.component_ref, "pin": n.pin_name} for n in net.nodes],
        }
    return {"design": design_name, "nets": nets_info}


def tool_design_diff(design_a_name: str, design_b_name: str, session_id: str = "default") -> dict[str, Any]:
    """Diff two designs and report changes."""

    session = _get_session(session_id)
    designs = session.get("designs", {})
    design_a = designs.get(design_a_name)
    design_b = designs.get(design_b_name)
    if design_a is None:
        raise ValueError(f"Design '{design_a_name}' not found")
    if design_b is None:
        raise ValueError(f"Design '{design_b_name}' not found")
    entries = diff_designs(design_a, design_b)
    added = [e for e in entries if e.type in (DiffType.COMPONENT_ADDED, DiffType.NET_ADDED)]
    removed = [e for e in entries if e.type in (DiffType.COMPONENT_REMOVED, DiffType.NET_REMOVED)]
    changed = [
        e for e in entries if e.type in (DiffType.VALUE_CHANGED, DiffType.FOOTPRINT_CHANGED, DiffType.BOARD_CHANGED)
    ]  # noqa: E501
    return {
        "design_a": design_a_name,
        "design_b": design_b_name,
        "diff_entries": [e.__dict__ for e in entries],
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
        "summary": f"{len(added)} added, {len(removed)} removed, {len(changed)} changed",
    }


def tool_board_update(
    design_name: str,
    width_mm: float | None = None,
    height_mm: float | None = None,
    layers: int | None = None,
    session_id: str = "default",
) -> dict[str, Any]:  # noqa: E501
    """Update board configuration parameters."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    if width_mm is not None:
        design.board.width_mm = width_mm
    if height_mm is not None:
        design.board.height_mm = height_mm
    if layers is not None:
        design.board.layers = layers
    _persist_design(session, design_name, operation="board-update")
    return {
        "design": design_name,
        "width_mm": design.board.width_mm,
        "height_mm": design.board.height_mm,
        "layers": design.board.layers,
    }


def tool_component_add(
    design_name: str,
    component_id: str,
    ref: str,
    type_name: str,
    value: str | None = None,
    footprint: str = "",
    session_id: str = "default",
) -> dict[str, Any]:  # noqa: E501
    """Add a new component to a design."""
    import uuid

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    comp = Component(
        id=component_id or str(uuid.uuid4())[:8],
        ref=ref,
        type=type_name,
        value=value,
        footprint=footprint,
    )
    design.components[comp.id] = comp
    _persist_design(session, design_name, operation="component-add")
    return {
        "design": design_name,
        "component_id": comp.id,
        "ref": ref,
        "type": type_name,
    }


def tool_component_remove(design_name: str, component_id: str, session_id: str = "default") -> dict[str, Any]:
    """Remove a component from a design."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    if component_id not in design.components:
        raise ValueError(f"Component '{component_id}' not in design")
    ref = design.components[component_id].ref
    del design.components[component_id]
    # Remove orphaned net nodes
    nets_to_remove: list[str] = []
    for net_id, net in design.nets.items():
        net.nodes = [n for n in net.nodes if n.component_ref != ref]
        if not net.nodes:
            nets_to_remove.append(net_id)
    for net_id in nets_to_remove:
        del design.nets[net_id]
    _persist_design(session, design_name, operation="component-remove")
    return {
        "design": design_name,
        "removed_component": component_id,
        "ref": ref,
        "removed_orphan_nets": nets_to_remove,
    }


__all__ = [
    "tool_design_parse_file",
    "tool_design_parse_str",
    "tool_design_inspect",
    "tool_design_list_nets",
    "tool_design_diff",
    "tool_board_update",
    "tool_component_add",
    "tool_component_remove",
]
