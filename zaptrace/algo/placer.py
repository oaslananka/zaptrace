from __future__ import annotations

import math

from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Design


def place_components(design: Design) -> dict[str, tuple[float, float]]:
    """Assign deterministic component positions and avoid known courtyard overlap.

    The legacy force-directed placement remains the primary result. When resolved
    footprint courtyards reveal physical overlap, the deterministic board grid is
    used only if it reduces that overlap count. Designs without resolved footprint
    geometry keep the established placement behavior.
    """
    try:
        from zaptrace._core import place_components as _rust_place

        n = len(design.components)
        connections = _build_connections(design)
        board = canonical_board_definition(design)
        positions_raw = _rust_place(n, board.width, board.height, connections, 5.0)
        ids = list(design.components.keys())
        positions = {ids[i]: pos for i, pos in enumerate(positions_raw)}
    except ImportError:
        positions = _place_python(design)
    return _prefer_less_overlapping_grid(design, positions)


_POWER_NET_PREFIXES = ("GND", "VSS", "VDD", "VCC", "VBUS", "VBAT", "VIN", "AGND", "DGND")


def _is_power_net(name: str) -> bool:
    """Power/ground nets fan out to nearly every part; they steer placement
    nowhere useful and go to copper pour, so they are excluded from the springs."""
    upper = name.upper()
    return any(upper.startswith(p) for p in _POWER_NET_PREFIXES)


def _component_reference_indices(design: Design) -> dict[str, int]:
    reference_indices: dict[str, int] = {}
    for component in design.components.values():
        if component.ref not in reference_indices:
            reference_indices[component.ref] = len(reference_indices)
    return reference_indices


def _star_connections(refs: list[str], reference_indices: dict[str, int]) -> list[tuple[int, int]]:
    root_index = reference_indices.get(refs[0])
    if root_index is None:
        return []
    return [(root_index, reference_indices[ref]) for ref in refs[1:] if ref in reference_indices]


def _pair_connections(refs: list[str], reference_indices: dict[str, int]) -> list[tuple[int, int]]:
    connections: list[tuple[int, int]] = []
    for index, left_ref in enumerate(refs):
        left_index = reference_indices.get(left_ref)
        if left_index is None:
            continue
        for right_ref in refs[index + 1 :]:
            right_index = reference_indices.get(right_ref)
            if right_index is not None:
                connections.append((left_index, right_index))
    return connections


def _build_connections(design: Design) -> list[tuple[int, int]]:
    reference_indices = _component_reference_indices(design)
    connections: list[tuple[int, int]] = []
    for net in design.nets.values():
        if _is_power_net(net.name):
            continue
        refs = [node.component_ref for node in net.nodes]
        if len(refs) > 4:
            connections.extend(_star_connections(refs, reference_indices))
        else:
            connections.extend(_pair_connections(refs, reference_indices))
    return connections


def _courtyard_size(design: Design, component_id: str) -> tuple[float, float] | None:
    component = design.components.get(component_id)
    footprint = component.footprint_def if component is not None else None
    if footprint is None or not footprint.courtyard:
        return None
    width, height = footprint.courtyard
    if width <= 0 or height <= 0:
        return None
    return float(width), float(height)


def _placement_overlap_count(
    design: Design,
    positions: dict[str, tuple[float, float]],
    *,
    clearance_mm: float = 0.5,
) -> int:
    """Count pairwise resolved-footprint courtyard overlaps."""
    component_ids = [component_id for component_id in design.components if component_id in positions]
    count = 0
    for index, left_id in enumerate(component_ids):
        left_size = _courtyard_size(design, left_id)
        if left_size is None:
            continue
        left_x, left_y = positions[left_id]
        for right_id in component_ids[index + 1 :]:
            right_size = _courtyard_size(design, right_id)
            if right_size is None:
                continue
            right_x, right_y = positions[right_id]
            required_x = (left_size[0] + right_size[0]) / 2.0 + clearance_mm
            required_y = (left_size[1] + right_size[1]) / 2.0 + clearance_mm
            if abs(left_x - right_x) < required_x and abs(left_y - right_y) < required_y:
                count += 1
    return count


def _placement_within_board(
    design: Design,
    positions: dict[str, tuple[float, float]],
) -> bool:
    """Return whether resolved footprint courtyards remain inside board bounds."""
    board = canonical_board_definition(design)
    for component_id, (x, y) in positions.items():
        size = _courtyard_size(design, component_id)
        if size is None:
            continue
        half_width = size[0] / 2.0
        half_height = size[1] / 2.0
        if x - half_width < 0.0 or x + half_width > board.width:
            return False
        if y - half_height < 0.0 or y + half_height > board.height:
            return False
    return True


def _prefer_less_overlapping_grid(
    design: Design,
    positions: dict[str, tuple[float, float]],
    *,
    margin: float = 5.0,
) -> dict[str, tuple[float, float]]:
    """Prefer the deterministic board grid only when it reduces courtyard overlap."""
    overlap_count = _placement_overlap_count(design, positions)
    if overlap_count == 0 or len(positions) < 2:
        return positions
    board = canonical_board_definition(design)
    grid_positions = _grid_positions(list(design.components), board.width, board.height, margin)
    grid_is_better = _placement_overlap_count(design, grid_positions) < overlap_count
    if _placement_within_board(design, grid_positions) and grid_is_better:
        return grid_positions
    return positions


def _grid_positions(
    component_ids: list[str],
    width: float,
    height: float,
    margin: float,
) -> dict[str, tuple[float, float]]:
    count = len(component_ids)
    columns = max(1, math.ceil(math.sqrt(count * width / height)))
    rows = max(1, math.ceil(count / columns))
    cell_width = (width - 2 * margin) / columns
    cell_height = (height - 2 * margin) / rows
    return {
        component_id: (
            margin + (index % columns) * cell_width + cell_width / 2,
            margin + (index // columns) * cell_height + cell_height / 2,
        )
        for index, component_id in enumerate(component_ids)
    }


def _apply_spring_forces(
    component_ids: list[str],
    connections: list[tuple[int, int]],
    positions: dict[str, tuple[float, float]],
    forces: dict[str, list[float]],
) -> None:
    rest_length = 8.0
    spring_constant = 0.05
    for left_index, right_index in connections:
        left_id, right_id = component_ids[left_index], component_ids[right_index]
        left_x, left_y = positions[left_id]
        right_x, right_y = positions[right_id]
        dx, dy = right_x - left_x, right_y - left_y
        distance = max(math.sqrt(dx**2 + dy**2), 0.1)
        stretch = distance - rest_length
        unit_x, unit_y = dx / distance, dy / distance
        force_x = spring_constant * stretch * unit_x
        force_y = spring_constant * stretch * unit_y
        forces[left_id][0] += force_x
        forces[left_id][1] += force_y
        forces[right_id][0] -= force_x
        forces[right_id][1] -= force_y


def _apply_repulsion_forces(
    component_ids: list[str],
    positions: dict[str, tuple[float, float]],
    forces: dict[str, list[float]],
) -> None:
    for left_index, left_id in enumerate(component_ids):
        for right_id in component_ids[left_index + 1 :]:
            left_x, left_y = positions[left_id]
            right_x, right_y = positions[right_id]
            dx, dy = right_x - left_x, right_y - left_y
            distance = max(math.sqrt(dx**2 + dy**2), 0.1)
            if distance >= 10.0:
                continue
            repulsion = 2.0 / (distance**2)
            force_x, force_y = -repulsion * dx / distance, -repulsion * dy / distance
            forces[left_id][0] += force_x
            forces[left_id][1] += force_y
            forces[right_id][0] -= force_x
            forces[right_id][1] -= force_y


def _update_positions(
    component_ids: list[str],
    positions: dict[str, tuple[float, float]],
    forces: dict[str, list[float]],
    *,
    width: float,
    height: float,
    margin: float,
) -> None:
    for component_id in component_ids:
        x, y = positions[component_id]
        positions[component_id] = (
            max(margin, min(width - margin, x + forces[component_id][0])),
            max(margin, min(height - margin, y + forces[component_id][1])),
        )


def _place_python(design: Design) -> dict[str, tuple[float, float]]:
    """Pure Python grid placement plus force-directed refinement."""
    component_ids = list(design.components)
    if not component_ids:
        return {}
    board = canonical_board_definition(design)
    margin = 5.0
    positions = _grid_positions(component_ids, board.width, board.height, margin)
    connections = _build_connections(design)
    for _ in range(20):
        forces = {component_id: [0.0, 0.0] for component_id in component_ids}
        _apply_spring_forces(component_ids, connections, positions, forces)
        _apply_repulsion_forces(component_ids, positions, forces)
        _update_positions(
            component_ids,
            positions,
            forces,
            width=board.width,
            height=board.height,
            margin=margin,
        )
    return positions
