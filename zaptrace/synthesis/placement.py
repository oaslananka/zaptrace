"""Constraint-aware placement intelligence.

Analyses placement constraints from the :class:`ConstraintSet`, groups
components functionally by net connectivity, scores placement candidates
against constraints, and detects potential issues (decoupling caps far from
ICs, mixed-signal separation, keepout violations, edge-proximity rules).

This is *intelligence*, not a placer: it does not move components. It reads a
design's existing or proposed placement and tells an agent or downstream tool
*what* to fix and *why*, using the same deterministic, evidence-bearing style
as the rest of the synthesis module.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.core.models import ConstraintSet, Design, PlacementIntent

# ---------------------------------------------------------------------------
# Public result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FunctionalGroup:
    """A cluster of components that share a common function via net connectivity."""

    name: str
    component_ids: tuple[str, ...]
    net_ids: tuple[str, ...]


@dataclass(frozen=True)
class PlacementObservation:
    """A single structured observation about a placement.

    Each observation carries an explicit *severity*, a human-readable *message*,
    a list of *component_ids* involved, and the *constraint* that produced it
    (or ``None`` for advisory observations like decoupling-cap proximity).
    """

    severity: str  # "info" | "warning" | "error"
    category: str  # "grouping" | "proximity" | "keepout" | "edge" | "separation" | "intent"
    message: str
    component_ids: list[str] = field(default_factory=list)
    constraint: PlacementIntent | None = None
    suggestion: str = ""


@dataclass(frozen=True)
class PlacementCandidate:
    """A scored placement option for a component or group.

    ``score`` ranges from 0.0 (worst) to 1.0 (perfect). Two candidates with
    the same component can be compared to choose the better placement.
    """

    component_id: str
    x_mm: float
    y_mm: float
    score: float
    reasons: list[str] = field(default_factory=list)


class PlacementScoreSection(BaseModel):
    """One machine-readable placement scorecard section."""

    model_config = ConfigDict(strict=False)

    name: str
    score: float = Field(ge=0, le=1)
    status: str
    observation_count: int = Field(default=0, ge=0)
    blocking_count: int = Field(default=0, ge=0)
    summary: str = ""


class PlacementScorecard(BaseModel):
    """Machine-readable placement scorecard for proof-pack/release evidence."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    overall_score: float = Field(ge=0, le=1)
    status: str
    min_autonomous_score: float = Field(default=0.75, ge=0, le=1)
    min_review_score: float = Field(default=0.9, ge=0, le=1)
    group_count: int = Field(default=0, ge=0)
    component_count: int = Field(default=0, ge=0)
    placed_component_count: int = Field(default=0, ge=0)
    section_scores: list[PlacementScoreSection]
    observations: list[dict[str, Any]] = Field(default_factory=list)
    blocking_observation_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    human_review_required: bool = False
    blocked: bool = False


@dataclass(frozen=True)
class PlacementAnalysis:
    """Full constraint-aware placement analysis result."""

    groups: list[FunctionalGroup] = field(default_factory=list)
    observations: list[PlacementObservation] = field(default_factory=list)
    candidates: list[PlacementCandidate] = field(default_factory=list)
    score: float = 1.0  # overall placement score (1.0 = all constraints met)


def _observation_dict(observation: PlacementObservation) -> dict[str, Any]:
    data = asdict(observation)
    if observation.constraint is not None:
        data["constraint"] = observation.constraint.model_dump(mode="json")
    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _glob_match(pattern: str, value: str) -> bool:
    """Simple glob match: supports trailing ``*`` wildcard."""
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return value.startswith(pattern.rstrip("*"))
    return value == pattern


def _comp_ids_for_glob(design: Design, pattern: str) -> list[str]:
    """Return component IDs whose ref or id matches *pattern*."""
    return [
        cid for cid, comp in design.components.items() if _glob_match(pattern, comp.ref) or _glob_match(pattern, cid)
    ]


def _comp_id_by_ref(design: Design, ref: str) -> str | None:
    """Return the component ID for a given reference designator."""
    for cid, comp in design.components.items():
        if comp.ref == ref:
            return cid
    return None


def _distance_mm(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


# ---------------------------------------------------------------------------
# Functional grouping
# ---------------------------------------------------------------------------


def _component_ref_lookup(design: Design) -> dict[str, str]:
    return {comp.ref: cid for cid, comp in design.components.items()}


def _net_component_ids(design: Design, ref_to_id: dict[str, str]) -> dict[str, set[str]]:
    net_to_comps: dict[str, set[str]] = {}
    for net_id, net in design.nets.items():
        comps: set[str] = set()
        for node in net.nodes:
            cid = node.component_ref
            if cid in design.components:
                comps.add(cid)
            elif cid in ref_to_id:
                comps.add(ref_to_id[cid])
        if comps:
            net_to_comps[net_id] = comps
    return net_to_comps


class _ComponentUnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, component_id: str) -> None:
        if component_id not in self.parent:
            self.parent[component_id] = component_id

    def find(self, component_id: str) -> str:
        while self.parent.get(component_id, component_id) != component_id:
            self.parent[component_id] = self.parent[self.parent[component_id]]
            component_id = self.parent[component_id]
        return component_id

    def union(self, first: str, second: str) -> None:
        first_root, second_root = self.find(first), self.find(second)
        if first_root != second_root:
            self.parent[first_root] = second_root


def _component_groups(net_to_comps: dict[str, set[str]]) -> dict[str, set[str]]:
    union_find = _ComponentUnionFind()
    all_component_ids: set[str] = set()
    for comps in net_to_comps.values():
        comp_list = list(comps)
        for component_id in comp_list:
            all_component_ids.add(component_id)
            union_find.add(component_id)
        for index in range(1, len(comp_list)):
            union_find.union(comp_list[0], comp_list[index])
    root_to_comps: dict[str, set[str]] = {}
    for component_id in all_component_ids:
        root = union_find.find(component_id)
        root_to_comps.setdefault(root, set()).add(component_id)
    return root_to_comps


def _functional_group(
    design: Design,
    root: str,
    comps: set[str],
    net_to_comps: dict[str, set[str]],
) -> FunctionalGroup:
    net_ids = {net_id for net_id, comps_on_net in net_to_comps.items() if comps_on_net & comps}
    net_names = [design.nets[net_id].name for net_id in net_ids if net_id in design.nets]
    name = ", ".join(sorted(net_names)) if net_names else f"group_{root}"
    return FunctionalGroup(
        name=name,
        component_ids=tuple(sorted(comps)),
        net_ids=tuple(sorted(net_ids)),
    )


def group_components(design: Design) -> list[FunctionalGroup]:
    """Group components by shared-net connectivity."""
    net_to_comps = _net_component_ids(design, _component_ref_lookup(design))
    if not net_to_comps:
        return []
    return [
        _functional_group(design, root, comps, net_to_comps) for root, comps in _component_groups(net_to_comps).items()
    ]


# ---------------------------------------------------------------------------
# Decoupling-cap heuristics
# ---------------------------------------------------------------------------


def _is_capacitor_like(component: Any) -> bool:
    ctype = getattr(component, "type", "").lower()
    ref = getattr(component, "ref", "").upper()
    return ctype == "capacitor" or ref.startswith("C")


def _is_bulk_cap_value(value: str) -> bool:
    for unit in ("uf", "µf", "mf"):
        if unit not in value:
            continue
        try:
            number = float(value.replace("uf", "").replace("µf", "").replace("mf", "").strip())
        except ValueError:
            return False
        return number >= 10.0
    return False


def _is_decoupling_cap(component: Any) -> bool:
    """Heuristic check: is this component likely a decoupling capacitor?"""
    if not _is_capacitor_like(component):
        return False
    value = (getattr(component, "value", "") or "").lower().strip()
    return not _is_bulk_cap_value(value)


# ---------------------------------------------------------------------------
# Keepout / clearance checks
# ---------------------------------------------------------------------------


def _near_constraint_observations(
    design: Design,
    placement: dict[str, tuple[float, float]],
    intent: PlacementIntent,
) -> list[PlacementObservation]:
    if not intent.near or not intent.max_distance_mm:
        return []
    target_ids = _comp_ids_for_glob(design, intent.near)
    if not target_ids:
        return []
    observations: list[PlacementObservation] = []
    for cid in _comp_ids_for_glob(design, intent.component):
        if cid not in placement:
            continue
        distances = [_distance_mm(placement[cid], placement[target]) for target in target_ids if target in placement]
        if not distances or min(distances) <= intent.max_distance_mm:
            continue
        min_dist = min(distances)
        comp = design.components[cid]
        observations.append(
            PlacementObservation(
                severity="warning",
                category="keepout",
                message=(
                    f"{comp.ref} ({cid}) is {min_dist:.1f} mm from {intent.near}, "
                    f"exceeds max_distance_mm={intent.max_distance_mm:.1f} mm"
                ),
                component_ids=[cid] + target_ids,
                constraint=intent,
                suggestion=f"Move {comp.ref} within {intent.max_distance_mm:.1f} mm of {intent.near}",
            )
        )
    return observations


def _is_on_requested_edge(
    edge: str, x: float, y: float, board_width: float, board_height: float, margin: float
) -> bool:
    if edge == "left":
        return x < margin
    if edge == "right":
        return x > board_width - margin
    if edge == "top":
        return y > board_height - margin
    if edge == "bottom":
        return y < margin
    return False


def _edge_constraint_observations(
    design: Design,
    placement: dict[str, tuple[float, float]],
    intent: PlacementIntent,
) -> list[PlacementObservation]:
    if not intent.edge:
        return []
    board = design.board
    board_width = board.width_mm if hasattr(board, "width_mm") else 100.0
    board_height = board.height_mm if hasattr(board, "height_mm") else 80.0
    margin = 10.0
    observations: list[PlacementObservation] = []
    for cid in _comp_ids_for_glob(design, intent.component):
        if cid not in placement:
            continue
        x, y = placement[cid]
        if _is_on_requested_edge(intent.edge, x, y, board_width, board_height, margin):
            continue
        comp = design.components[cid]
        observations.append(
            PlacementObservation(
                severity="warning",
                category="edge",
                message=(
                    f"{comp.ref} ({cid}) should be near the {intent.edge} board edge (current: x={x:.1f}, y={y:.1f})"
                ),
                component_ids=[cid],
                constraint=intent,
                suggestion=f"Move {comp.ref} to the {intent.edge} edge of the board",
            )
        )
    return observations


def _check_keepouts(
    design: Design,
    constraints: ConstraintSet,
) -> list[PlacementObservation]:
    """Check that placement constraints are satisfied."""
    placement = design.placement
    if not placement:
        return []
    observations: list[PlacementObservation] = []
    for intent in constraints.placement:
        observations.extend(_near_constraint_observations(design, placement, intent))
        observations.extend(_edge_constraint_observations(design, placement, intent))
    return observations


# ---------------------------------------------------------------------------
# Decoupling cap proximity check
# ---------------------------------------------------------------------------


def _check_decoupling_proximity(design: Design) -> list[PlacementObservation]:
    """Check that decoupling capacitors are close to the ICs they serve.

    For each decoupling cap, finds the *nearest* IC and warns if it's too far.
    A cap that is within 5 mm of at least one IC is considered well-placed.
    """
    observations: list[PlacementObservation] = []
    placement = design.placement
    if not placement:
        return observations

    ic_ids = [
        cid
        for cid, comp in design.components.items()
        if comp.type.lower() in ("ic", "mcu", "microcontroller", "regulator", "sensor", "op-amp", "amplifier")
    ]
    if not ic_ids:
        return observations

    # Pre-compute IC positions
    ic_positions = {ic_id: placement[ic_id] for ic_id in ic_ids if ic_id in placement}
    if not ic_positions:
        return observations

    for cid, comp in design.components.items():
        if not _is_decoupling_cap(comp) or cid not in placement:
            continue
        cap_pos = placement[cid]

        # Find the closest IC
        min_dist = min(
            (_distance_mm(cap_pos, ic_pos) for ic_pos in ic_positions.values()),
            default=float("inf"),
        )
        if min_dist == float("inf"):
            continue

        if min_dist > 10.0:
            nearest_ic_id = min(
                ic_positions,
                key=lambda ic_id, cap_pos=cap_pos: _distance_mm(cap_pos, ic_positions[ic_id]),
            )
            nearest_ic = design.components[nearest_ic_id]
            observations.append(
                PlacementObservation(
                    severity="warning",
                    category="proximity",
                    message=(
                        f"Decoupling cap {comp.ref} ({cid}) is {min_dist:.1f} mm from "
                        f"nearest IC {nearest_ic.ref} ({nearest_ic_id}); "
                        "recommend < 5 mm for effective decoupling"
                    ),
                    component_ids=[cid, nearest_ic_id],
                    suggestion=f"Move {comp.ref} within 5 mm of an IC",
                )
            )
        elif min_dist > 5.0:
            nearest_ic_id = min(
                ic_positions,
                key=lambda ic_id, cap_pos=cap_pos: _distance_mm(cap_pos, ic_positions[ic_id]),
            )
            nearest_ic = design.components[nearest_ic_id]
            observations.append(
                PlacementObservation(
                    severity="info",
                    category="proximity",
                    message=(
                        f"Decoupling cap {comp.ref} ({cid}) is {min_dist:.1f} mm from "
                        f"nearest IC {nearest_ic.ref} ({nearest_ic_id}); "
                        "optimal is < 5 mm"
                    ),
                    component_ids=[cid, nearest_ic_id],
                    suggestion=f"Move {comp.ref} within 5 mm of {nearest_ic.ref} for best decoupling",
                )
            )

    return observations


# ---------------------------------------------------------------------------
# Analog / digital separation check
# ---------------------------------------------------------------------------


def _check_analog_digital_separation(design: Design) -> list[PlacementObservation]:
    """Flag analog components placed near noisy digital components."""
    observations: list[PlacementObservation] = []
    placement = design.placement
    if not placement:
        return observations

    analog_ids = [
        cid
        for cid, comp in design.components.items()
        if comp.type.lower() in ("sensor", "op-amp", "amplifier", "adc", "dac", "analog", "filter")
    ]
    digital_ids = [
        cid
        for cid, comp in design.components.items()
        if comp.type.lower()
        in ("ic", "mcu", "microcontroller", "regulator", "switcher", "dc-dc", "digital", "cpld", "fpga")
    ]

    for a_id in analog_ids:
        if a_id not in placement:
            continue
        a_pos = placement[a_id]
        for d_id in digital_ids:
            if d_id not in placement:
                continue
            d_pos = placement[d_id]
            dist = _distance_mm(a_pos, d_pos)
            if dist < 5.0:
                a_comp = design.components[a_id]
                d_comp = design.components[d_id]
                observations.append(
                    PlacementObservation(
                        severity="warning",
                        category="separation",
                        message=(
                            f"Analog component {a_comp.ref} ({a_id}) is {dist:.1f} mm from "
                            f"digital/noisy component {d_comp.ref} ({d_id}); "
                            "recommend >= 5 mm separation to reduce noise coupling"
                        ),
                        component_ids=[a_id, d_id],
                        suggestion=f"Increase separation between {a_comp.ref} and {d_comp.ref}",
                    )
                )

    return observations


# ---------------------------------------------------------------------------
# Candidate scoring
# ---------------------------------------------------------------------------


def _board_size(design: Design) -> tuple[float, float]:
    board = design.board
    width = board.width_mm if hasattr(board, "width_mm") else 100.0
    height = board.height_mm if hasattr(board, "height_mm") else 80.0
    return width, height


def _edge_score_adjustment(
    x_mm: float, y_mm: float, board_width: float, board_height: float, margin: float
) -> tuple[float, list[str]]:
    edge_dist = min(x_mm, board_width - x_mm, y_mm, board_height - y_mm)
    if edge_dist >= margin:
        return 0.0, []
    return -0.15, [f"too close to board edge ({edge_dist:.1f} mm < {margin:.1f} mm margin)"]


def _edge_intent_score_adjustment(
    intent: PlacementIntent,
    x_mm: float,
    y_mm: float,
    board_width: float,
    board_height: float,
    margin: float,
) -> tuple[float, list[str]]:
    if not intent.edge:
        return 0.0, []
    if _is_on_requested_edge(intent.edge, x_mm, y_mm, board_width, board_height, margin):
        return 0.05, [f"on correct board edge ({intent.edge})"]
    return -0.03, []


def _near_intent_score_adjustment(
    design: Design,
    intent: PlacementIntent,
    position: tuple[float, float],
    placement: dict[str, tuple[float, float]],
) -> tuple[float, list[str]]:
    if not intent.near or not intent.max_distance_mm:
        return 0.0, []
    targets = [placement[cid] for cid in _comp_ids_for_glob(design, intent.near) if cid in placement]
    if not targets:
        return 0.0, []
    min_distance = min(_distance_mm(position, target) for target in targets)
    if min_distance <= intent.max_distance_mm:
        return 0.05, [f"within {intent.max_distance_mm:.1f} mm of {intent.near} ({min_distance:.1f} mm)"]
    return -0.03, []


def _constraint_score_adjustment(
    design: Design,
    component_id: str,
    component: Any,
    position: tuple[float, float],
    placement: dict[str, tuple[float, float]],
    constraints: ConstraintSet,
    board_width: float,
    board_height: float,
    margin: float,
) -> tuple[float, list[str]]:
    constraint_score = 0.3
    reasons: list[str] = []
    x_mm, y_mm = position
    for intent in constraints.placement:
        if not _glob_match(intent.component, component.ref) and not _glob_match(intent.component, component_id):
            continue
        for delta, delta_reasons in (
            _edge_intent_score_adjustment(intent, x_mm, y_mm, board_width, board_height, margin),
            _near_intent_score_adjustment(design, intent, position, placement),
        ):
            constraint_score += delta
            reasons.extend(delta_reasons)
    return constraint_score - 0.3, reasons


def _connected_component_refs(design: Design, component_id: str, component_ref: str) -> set[str]:
    connected: set[str] = set()
    for net in design.nets.values():
        if not any(node.component_ref in (component_id, component_ref) for node in net.nodes):
            continue
        for node in net.nodes:
            if node.component_ref not in (component_id, component_ref):
                connected.add(node.component_ref)
    return connected


def _connected_score_adjustment(
    design: Design,
    component_id: str,
    component_ref: str,
    position: tuple[float, float],
    placement: dict[str, tuple[float, float]],
) -> tuple[float, list[str]]:
    connected = _connected_component_refs(design, component_id, component_ref)
    if not connected:
        return 0.0, []
    total_distance = 0.0
    count = 0
    for connected_ref in connected:
        connected_id = next((cid for cid, comp in design.components.items() if comp.ref == connected_ref), None)
        if connected_id and connected_id in placement:
            total_distance += _distance_mm(position, placement[connected_id])
            count += 1
    if count == 0:
        return 0.0, []
    average = total_distance / count
    if average < 10.0:
        return 0.05, [f"close to {count} connected component(s) (avg {average:.1f} mm)"]
    if average > 30.0:
        return -0.1, [f"far from {count} connected component(s) (avg {average:.1f} mm)"]
    return 0.0, []


def _analog_digital_score_adjustment(
    design: Design,
    component_id: str,
    component: Any,
    position: tuple[float, float],
    placement: dict[str, tuple[float, float]],
) -> tuple[float, list[str]]:
    analog_types = ("sensor", "op-amp", "amplifier", "adc", "dac", "analog", "filter")
    digital_types = ("mcu", "microcontroller", "digital", "cpld", "fpga", "switcher", "dc-dc")
    component_type = component.type.lower()
    is_analog = component_type in analog_types
    is_digital = component_type in digital_types
    if not is_analog and not is_digital:
        return 0.0, []
    adjustment = 0.0
    reasons: list[str] = []
    for other_id, other_component in design.components.items():
        if other_id == component_id or other_id not in placement:
            continue
        other_type = other_component.type.lower()
        distance = _distance_mm(position, placement[other_id])
        if is_analog and other_type in ("mcu", "microcontroller", "switcher", "dc-dc", "digital") and distance < 5.0:
            adjustment -= 0.1
            reasons.append(f"analog {component.ref} too close to digital {other_component.ref} ({distance:.1f} mm)")
        if is_digital and other_type in ("sensor", "analog", "adc", "dac") and distance < 5.0:
            adjustment -= 0.05
    return adjustment, reasons


def _score_placement_for_component(
    design: Design,
    component_id: str,
    x_mm: float,
    y_mm: float,
    constraints: ConstraintSet,
) -> PlacementCandidate:
    """Score a single (component_id, x, y) placement candidate."""
    placement = design.placement
    assert placement is not None, "design.placement must be set before scoring"
    component = design.components.get(component_id)
    if component is None:
        return PlacementCandidate(component_id, x_mm, y_mm, 0.0, ["unknown component"])
    board_width, board_height = _board_size(design)
    margin = 5.0
    position = (x_mm, y_mm)
    score = 1.0
    reasons: list[str] = []
    for adjustment, adjustment_reasons in (
        _edge_score_adjustment(x_mm, y_mm, board_width, board_height, margin),
        _constraint_score_adjustment(
            design, component_id, component, position, placement, constraints, board_width, board_height, margin
        ),
        _connected_score_adjustment(design, component_id, component.ref, position, placement),
        _analog_digital_score_adjustment(design, component_id, component, position, placement),
    ):
        score += adjustment
        reasons.extend(adjustment_reasons)
    return PlacementCandidate(
        component_id=component_id,
        x_mm=x_mm,
        y_mm=y_mm,
        score=max(0.0, min(1.0, score)),
        reasons=reasons,
    )


def _hot_component_ids(design: Design) -> list[str]:
    ids: list[str] = []
    for cid, comp in design.components.items():
        props = comp.properties or {}
        value = props.get("thermal_power_w") or props.get("power_w") or props.get("operating_power_w")
        try:
            if value is not None and float(value) >= 0.5:
                ids.append(cid)
                continue
        except (TypeError, ValueError):
            pass
        if comp.type.lower() in ("regulator", "switcher", "dc-dc", "power"):
            ids.append(cid)
    return ids


def _check_thermal_spacing(design: Design) -> list[PlacementObservation]:
    placement = design.placement or {}
    hot = [cid for cid in _hot_component_ids(design) if cid in placement]
    out: list[PlacementObservation] = []
    for i, a_id in enumerate(hot):
        for b_id in hot[i + 1 :]:
            dist = _distance_mm(placement[a_id], placement[b_id])
            if dist < 8.0:
                a = design.components[a_id]
                b = design.components[b_id]
                out.append(
                    PlacementObservation(
                        severity="warning",
                        category="thermal_spacing",
                        message=f"{a.ref} and {b.ref} thermal spacing is {dist:.1f} mm",
                        component_ids=[a_id, b_id],
                        suggestion="Increase spacing or add thermal evidence",
                    )
                )
    return out


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze_placement(design: Design) -> PlacementAnalysis:
    """Run a full constraint-aware placement analysis on *design*.

    Produces:
    - Functional groups (clusters of connected components)
    - Observations (warnings, infos, errors about the current placement)
    - Scored placement candidates for each component
    - An overall placement score (1.0 = all constraints met, no issues)
    """
    groups = group_components(design)
    observations: list[PlacementObservation] = []
    candidates: list[PlacementCandidate] = []
    constraints = design.constraints

    observations.extend(_check_keepouts(design, constraints))
    observations.extend(_check_decoupling_proximity(design))
    observations.extend(_check_analog_digital_separation(design))
    observations.extend(_check_thermal_spacing(design))

    if not constraints.placement and design.placement:
        observations.append(
            PlacementObservation(
                severity="info",
                category="intent",
                message="Design has placement data but no placement constraints; consider adding PlacementIntent items",
                suggestion="Add placement constraints via design.constraints.placement",
            )
        )

    if design.placement:
        for cid in design.components:
            if cid in design.placement:
                pos = design.placement[cid]
                candidate = _score_placement_for_component(design, cid, pos[0], pos[1], constraints)
                candidates.append(candidate)

    # Overall score: average of candidate scores, penalized by warnings/errors
    warning_count = sum(1 for o in observations if o.severity == "warning")
    error_count = sum(1 for o in observations if o.severity == "error")
    base_score = sum(c.score for c in candidates) / max(len(candidates), 1) if candidates else 1.0
    overall = base_score - (warning_count * 0.02) - (error_count * 0.05)
    overall = max(0.0, min(1.0, overall))

    return PlacementAnalysis(
        groups=groups,
        observations=observations,
        candidates=candidates,
        score=overall,
    )


# ---------------------------------------------------------------------------
# Machine-readable scorecard
# ---------------------------------------------------------------------------


def _section_status(score: float, blocking_count: int) -> str:
    if blocking_count:
        return "fail"
    if score < 0.9:
        return "warning"
    return "pass"


def _score_section(
    name: str, observations: list[PlacementObservation], *, base_score: float = 1.0
) -> PlacementScoreSection:
    warnings = sum(1 for item in observations if item.severity == "warning")
    errors = sum(1 for item in observations if item.severity == "error")
    score = max(0.0, min(1.0, base_score - warnings * 0.15 - errors * 0.35))
    return PlacementScoreSection(
        name=name,
        score=round(score, 3),
        status=_section_status(score, errors),
        observation_count=len(observations),
        blocking_count=errors,
        summary=f"{len(observations)} observation(s), {errors} blocking error(s)",
    )


def build_placement_scorecard(
    design: Design,
    *,
    min_autonomous_score: float = 0.75,
    min_review_score: float = 0.9,
) -> PlacementScorecard:
    """Build a machine-readable scorecard from placement analysis evidence."""
    analysis = analyze_placement(design)
    observations = analysis.observations
    categories = {
        "connector_constraints": [item for item in observations if item.category == "edge"],
        "decoupling_proximity": [item for item in observations if item.category == "proximity"],
        "keepouts": [item for item in observations if item.category == "keepout"],
        "thermal_spacing": [item for item in observations if item.category == "thermal_spacing"],
    }
    component_count = len(design.components)
    placed_count = len(design.placement or {})
    grouped = {cid for group in analysis.groups for cid in group.component_ids}
    group_score = 1.0 if not component_count else max(0.0, min(1.0, len(grouped) / component_count))
    sections = [
        PlacementScoreSection(
            name="block_grouping",
            score=round(group_score, 3),
            status=_section_status(group_score, 0),
            observation_count=0,
            blocking_count=0,
            summary=f"{len(analysis.groups)} functional group(s) across {component_count} component(s)",
        ),
        _score_section("connector_constraints", categories["connector_constraints"]),
        _score_section("decoupling_proximity", categories["decoupling_proximity"]),
        _score_section("keepouts", categories["keepouts"]),
        _score_section("thermal_spacing", categories["thermal_spacing"]),
    ]
    warning_count = sum(1 for item in observations if item.severity == "warning")
    blocking_count = sum(1 for item in observations if item.severity == "error")
    if placed_count < component_count:
        missing = component_count - placed_count
        warning_count += missing
        coverage = round(placed_count / component_count, 3) if component_count else 1.0
        sections.append(
            PlacementScoreSection(
                name="placement_coverage",
                score=coverage,
                status="warning" if component_count else "pass",
                observation_count=missing,
                blocking_count=0,
                summary=f"{placed_count}/{component_count} component(s) have placement coordinates",
            )
        )
    section_mean = sum(section.score for section in sections) / len(sections) if sections else 1.0
    overall = max(0.0, min(1.0, analysis.score * 0.6 + section_mean * 0.4))
    blocked = blocking_count > 0 or overall < min_autonomous_score
    human_review = not blocked and (warning_count > 0 or overall < min_review_score)
    if blocked:
        status = "fail"
    elif human_review:
        status = "warning"
    else:
        status = "pass"
    return PlacementScorecard(
        overall_score=round(overall, 3),
        status=status,
        min_autonomous_score=min_autonomous_score,
        min_review_score=min_review_score,
        group_count=len(analysis.groups),
        component_count=component_count,
        placed_component_count=placed_count,
        section_scores=sections,
        observations=[_observation_dict(item) for item in observations],
        blocking_observation_count=blocking_count,
        warning_count=warning_count,
        human_review_required=human_review,
        blocked=blocked,
    )
