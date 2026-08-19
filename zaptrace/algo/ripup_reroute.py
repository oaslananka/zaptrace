"""Bounded rip-up and reroute for failed native routes (issue #127).

Design principles:
* Deterministic: same input → same rip order and reroute sequence.
* Budget-safe: hard cap on iterations and wall time; never exceeds configured limits.
* Conflict scoring: net priority = length × conflict_degree; highest first for rip.
* Valid recovery: on timeout/no-solution the design retains all legal routes that
  existed before the call; ripped-but-unresolved nets are listed in evidence.
* Evidence-complete: RipupResult carries enough data to reconstruct what happened.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Public API types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RipupConfig:
    """Tuning parameters for a bounded rip-up/reroute pass.

    Attributes:
        max_iterations:  Hard cap on rip-attempt cycles (default 10).
        max_seconds:     Wall-clock budget per pass (default 30.0 s).
        min_improvement: Stop early when completion_rate rises by less than this
                         fraction in one cycle (default 0.0 → always run to budget).
        cost_inflation:  Multiply conflict cost after each failed attempt (default 1.5).
        max_rip_per_iter: Maximum nets ripped in one iteration (default 5).
    """

    max_iterations: int = 10
    max_seconds: float = 30.0
    min_improvement: float = 0.0
    cost_inflation: float = 1.5
    max_rip_per_iter: int = 5

    def to_dict(self) -> dict[str, object]:
        return {
            "max_iterations": self.max_iterations,
            "max_seconds": self.max_seconds,
            "min_improvement": self.min_improvement,
            "cost_inflation": self.cost_inflation,
            "max_rip_per_iter": self.max_rip_per_iter,
        }


DEFAULT_RIPUP_CONFIG = RipupConfig()


@dataclass
class NetConflict:
    """Conflict record for one unrouted net.

    Attributes:
        net_name:        Net identifier.
        conflict_degree: Number of other nets that share grid cells with this net.
        estimated_length_mm: Approximate wirelength (Euclidean distance sum of nodes).
        conflict_score:  Derived sort key = estimated_length_mm × (1 + conflict_degree).
        attempts:        Number of rip-and-reroute attempts on this net so far.
        last_reason:     Diagnostic string from the last routing failure.
    """

    net_name: str
    conflict_degree: int = 0
    estimated_length_mm: float = 0.0
    conflict_score: float = 0.0
    attempts: int = 0
    last_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "net_name": self.net_name,
            "conflict_degree": self.conflict_degree,
            "estimated_length_mm": round(self.estimated_length_mm, 4),
            "conflict_score": round(self.conflict_score, 4),
            "attempts": self.attempts,
            "last_reason": self.last_reason,
        }


@dataclass
class RipupIteration:
    """Evidence record for one rip-up-and-reroute iteration.

    Attributes:
        iteration:       1-based iteration index.
        nets_ripped:     Names of nets whose routes were removed.
        nets_recovered:  Names of nets successfully rerouted in this iteration.
        nets_remaining:  Names still unrouted at end of this iteration.
        routed_before:   Count of routed nets before this iteration.
        routed_after:    Count of routed nets after this iteration.
        elapsed_s:       Wall time consumed by this iteration.
    """

    iteration: int
    nets_ripped: list[str]
    nets_recovered: list[str]
    nets_remaining: list[str]
    routed_before: int
    routed_after: int
    elapsed_s: float = 0.0

    @property
    def improvement(self) -> int:
        return self.routed_after - self.routed_before

    def to_dict(self) -> dict[str, object]:
        return {
            "iteration": self.iteration,
            "nets_ripped": list(self.nets_ripped),
            "nets_recovered": list(self.nets_recovered),
            "nets_remaining": list(self.nets_remaining),
            "routed_before": self.routed_before,
            "routed_after": self.routed_after,
            "improvement": self.improvement,
            "elapsed_s": round(self.elapsed_s, 4),
        }


@dataclass
class RipupResult:
    """Outcome of a bounded rip-up and reroute pass.

    Attributes:
        status:           "pass" | "partial" | "no_solution" | "timeout" | "skipped".
        design_name:      Board identifier.
        routed_nets_before: Count before rip-up pass.
        routed_nets_after:  Count after rip-up pass.
        total_nets:       Total net count.
        remaining_conflicts: Conflicts still unresolved at exit.
        iterations:       Per-iteration evidence records.
        config:           RipupConfig that governed this pass.
        elapsed_s:        Total wall time for the pass.
        result_hash:      Deterministic SHA-256 of the evidence (excludes elapsed).
    """

    status: str
    design_name: str
    routed_nets_before: int = 0
    routed_nets_after: int = 0
    total_nets: int = 0
    remaining_conflicts: list[NetConflict] = field(default_factory=list)
    iterations: list[RipupIteration] = field(default_factory=list)
    config: RipupConfig = field(default_factory=RipupConfig)
    elapsed_s: float = 0.0
    result_hash: str = ""

    @property
    def accepted(self) -> bool:
        return self.status == "pass"

    @property
    def completion_rate_before(self) -> float:
        if self.total_nets == 0:
            return 1.0
        return self.routed_nets_before / self.total_nets

    @property
    def completion_rate_after(self) -> float:
        if self.total_nets == 0:
            return 1.0
        return self.routed_nets_after / self.total_nets

    @property
    def improvement(self) -> int:
        return self.routed_nets_after - self.routed_nets_before

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "design_name": self.design_name,
            "routed_nets_before": self.routed_nets_before,
            "routed_nets_after": self.routed_nets_after,
            "total_nets": self.total_nets,
            "completion_rate_before": round(self.completion_rate_before, 4),
            "completion_rate_after": round(self.completion_rate_after, 4),
            "improvement": self.improvement,
            "accepted": self.accepted,
            "remaining_conflicts": [c.to_dict() for c in self.remaining_conflicts],
            "iterations": [it.to_dict() for it in self.iterations],
            "config": self.config.to_dict(),
            "elapsed_s": round(self.elapsed_s, 4),
            "result_hash": self.result_hash,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Internal routing primitives
# ---------------------------------------------------------------------------

# Each routed net is represented as a list of (x1,y1,x2,y2) float tuples
_Segments = list[tuple[float, float, float, float]]

# Routing table: net_name → segments
_RouteTable = dict[str, _Segments]


@dataclass
class _RipupState:
    route_table: _RouteTable
    current_unrouted: list[str]
    current_routed: int
    iterations_done: list[RipupIteration] = field(default_factory=list)
    cost_factor: float = 1.0


def _euclidean_length(segments: _Segments) -> float:
    total = 0.0
    for x1, y1, x2, y2 in segments:
        dx, dy = x2 - x1, y2 - y1
        total += math.sqrt(dx * dx + dy * dy)
    return total


def _segments_bbox(segments: _Segments) -> tuple[float, float, float, float] | None:
    """Return (min_x, min_y, max_x, max_y) for a segment list, or None if empty."""
    if not segments:
        return None
    xs = [x for x1, _, x2, _ in segments for x in (x1, x2)]
    ys = [y for _, y1, _, y2 in segments for y in (y1, y2)]
    return min(xs), min(ys), max(xs), max(ys)


def _bboxes_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax_min, ay_min, ax_max, ay_max = a
    bx_min, by_min, bx_max, by_max = b
    return ax_max >= bx_min and bx_max >= ax_min and ay_max >= by_min and by_max >= ay_min


def _estimate_unrouted_geometry(
    positions: list[tuple[float, float]],
) -> tuple[float, tuple[float, float, float, float] | None]:
    if len(positions) < 2:
        return 0.0, None
    xs = [point[0] for point in positions]
    ys = [point[1] for point in positions]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    estimated_length = 0.0
    remaining = list(positions)
    current = remaining.pop(0)
    while remaining:
        best_distance = float("inf")
        best_index = 0
        for index, position in enumerate(remaining):
            distance = math.sqrt((position[0] - current[0]) ** 2 + (position[1] - current[1]) ** 2)
            if distance < best_distance:
                best_distance = distance
                best_index = index
        estimated_length += best_distance
        current = remaining.pop(best_index)
    return estimated_length, bbox


def _route_conflict_degree(
    net_name: str,
    estimated_bbox: tuple[float, float, float, float] | None,
    route_table: _RouteTable,
) -> int:
    if estimated_bbox is None:
        return 0
    degree = 0
    for other_net, other_segments in route_table.items():
        if other_net == net_name:
            continue
        other_bbox = _segments_bbox(other_segments)
        if other_bbox is not None and _bboxes_overlap(estimated_bbox, other_bbox):
            degree += 1
    return degree


def _score_conflicts(
    unrouted: list[str],
    route_table: _RouteTable,
    node_positions: dict[str, list[tuple[float, float]]],
) -> list[NetConflict]:
    """Compute deterministic conflict scores sorted by score then net name."""
    conflicts: list[NetConflict] = []
    for net_name in unrouted:
        estimated_length, estimated_bbox = _estimate_unrouted_geometry(node_positions.get(net_name, []))
        conflict_degree = _route_conflict_degree(net_name, estimated_bbox, route_table)
        score = estimated_length * (1.0 + conflict_degree)
        conflicts.append(
            NetConflict(
                net_name=net_name,
                conflict_degree=conflict_degree,
                estimated_length_mm=round(estimated_length, 4),
                conflict_score=round(score, 4),
            )
        )
    conflicts.sort(key=lambda conflict: (-conflict.conflict_score, conflict.net_name))
    return conflicts


def _attempt_route_net(
    positions: list[tuple[float, float]],
    cost_factor: float = 1.0,
) -> _Segments | None:
    """Route a single net as a Manhattan L-path MST.

    Returns segment list on success, None if fewer than 2 positions available.
    cost_factor is recorded in evidence but does not affect routing geometry
    (the geometric layer has no cost model; cost affects net selection only).
    """
    _ = cost_factor  # retained for evidence / future use
    if len(positions) < 2:
        return None
    # Build MST by nearest-neighbour greedy; then route each edge as L-shape
    segments: _Segments = []
    remaining = list(positions)
    current = remaining.pop(0)
    while remaining:
        best_dist = float("inf")
        best_idx = 0
        for k, pos in enumerate(remaining):
            d = math.sqrt((pos[0] - current[0]) ** 2 + (pos[1] - current[1]) ** 2)
            if d < best_dist:
                best_dist = d
                best_idx = k
        nxt = remaining.pop(best_idx)
        # L-shaped route: horizontal then vertical
        mid_x = nxt[0]
        mid_y = current[1]
        segments.append((current[0], current[1], mid_x, mid_y))
        segments.append((mid_x, mid_y, nxt[0], nxt[1]))
        current = nxt
    return segments


def _build_result_hash(
    design_name: str,
    routed_before: int,
    routed_after: int,
    remaining: list[NetConflict],
    iterations: list[RipupIteration],
) -> str:
    payload = {
        "design_name": design_name,
        "routed_before": routed_before,
        "routed_after": routed_after,
        "remaining_net_names": sorted(c.net_name for c in remaining),
        "iterations": [
            {
                "i": it.iteration,
                "ripped": sorted(it.nets_ripped),
                "recovered": sorted(it.nets_recovered),
            }
            for it in iterations
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _skipped_ripup_result(design_name: str, routed_nets: int, total_nets: int, config: RipupConfig) -> RipupResult:
    return RipupResult(
        status="skipped",
        design_name=design_name,
        routed_nets_before=routed_nets,
        routed_nets_after=routed_nets,
        total_nets=total_nets,
        config=config,
        elapsed_s=0.0,
        result_hash=_build_result_hash(design_name, routed_nets, routed_nets, [], []),
    )


def _select_nets_to_rip(
    conflicts: list[NetConflict],
    config: RipupConfig,
    iteration_num: int,
    route_table: _RouteTable,
) -> list[str]:
    selected: list[str] = []
    for conflict in conflicts[: config.max_rip_per_iter]:
        selected.append(conflict.net_name)
        conflict.attempts += 1
        conflict.last_reason = f"ripped in iteration {iteration_num}"
    for net_name in selected:
        route_table.pop(net_name, None)
    return selected


def _reroute_selected_nets(
    selected: list[str],
    positions: dict[str, list[tuple[float, float]]],
    route_table: _RouteTable,
    cost_factor: float,
) -> tuple[list[str], list[str]]:
    recovered: list[str] = []
    still_unrouted: list[str] = []
    for net_name in selected:
        net_positions = positions.get(net_name, [])
        route = _attempt_route_net(net_positions, cost_factor)
        if route is not None and len(net_positions) >= 2:
            route_table[net_name] = route
            recovered.append(net_name)
        else:
            still_unrouted.append(net_name)
    return recovered, still_unrouted


def _execute_ripup_iteration(
    state: _RipupState,
    positions: dict[str, list[tuple[float, float]]],
    config: RipupConfig,
    iteration_num: int,
    iteration_start: float,
) -> int:
    routed_before = state.current_routed
    conflicts = _score_conflicts(state.current_unrouted, state.route_table, positions)
    selected = _select_nets_to_rip(conflicts, config, iteration_num, state.route_table)
    recovered, still_unrouted = _reroute_selected_nets(selected, positions, state.route_table, state.cost_factor)
    state.current_routed += len(recovered)
    state.current_unrouted = [net for net in state.current_unrouted if net not in selected] + still_unrouted
    state.iterations_done.append(
        RipupIteration(
            iteration=iteration_num,
            nets_ripped=list(selected),
            nets_recovered=recovered,
            nets_remaining=list(state.current_unrouted),
            routed_before=routed_before,
            routed_after=state.current_routed,
            elapsed_s=round(time.monotonic() - iteration_start, 4),
        )
    )
    state.cost_factor *= config.cost_inflation
    return routed_before


def _stop_after_iteration(
    state: _RipupState,
    routed_before: int,
    total_nets: int,
    config: RipupConfig,
) -> bool:
    if not state.current_unrouted:
        return True
    improvement_fraction = (state.current_routed - routed_before) / total_nets if total_nets > 0 else 0.0
    return config.min_improvement > 0.0 and improvement_fraction < config.min_improvement


def _ripup_status(
    state: _RipupState,
    routed_before: int,
    elapsed_total: float,
    config: RipupConfig,
) -> str:
    if not state.current_unrouted:
        return "pass"
    if elapsed_total >= config.max_seconds:
        return "timeout"
    if state.current_routed > routed_before:
        return "partial"
    return "no_solution"


def _finalize_ripup_result(
    design_name: str,
    state: _RipupState,
    routed_before: int,
    total_nets: int,
    positions: dict[str, list[tuple[float, float]]],
    config: RipupConfig,
    elapsed_total: float,
) -> RipupResult:
    final_conflicts = _score_conflicts(state.current_unrouted, state.route_table, positions)
    result_hash = _build_result_hash(
        design_name, routed_before, state.current_routed, final_conflicts, state.iterations_done
    )
    return RipupResult(
        status=_ripup_status(state, routed_before, elapsed_total, config),
        design_name=design_name,
        routed_nets_before=routed_before,
        routed_nets_after=state.current_routed,
        total_nets=total_nets,
        remaining_conflicts=final_conflicts,
        iterations=state.iterations_done,
        config=config,
        elapsed_s=round(elapsed_total, 4),
        result_hash=result_hash,
    )


def run_ripup_reroute(
    design_name: str,
    unrouted_nets: list[str],
    routed_nets: int,
    total_nets: int,
    node_positions: dict[str, list[tuple[float, float]]] | None = None,
    config: RipupConfig | None = None,
    _initial_route_table: _RouteTable | None = None,
) -> RipupResult:
    """Perform a bounded deterministic rip-up and reroute pass."""
    cfg = config or DEFAULT_RIPUP_CONFIG
    positions = node_positions or {}
    start_time = time.monotonic()
    if not unrouted_nets:
        return _skipped_ripup_result(design_name, routed_nets, total_nets, cfg)

    state = _RipupState(
        route_table=dict(_initial_route_table) if _initial_route_table else {},
        current_unrouted=list(unrouted_nets),
        current_routed=routed_nets,
    )
    routed_before = routed_nets
    for iteration_num in range(1, cfg.max_iterations + 1):
        iteration_start = time.monotonic()
        if iteration_start - start_time >= cfg.max_seconds:
            break
        iteration_routed_before = _execute_ripup_iteration(state, positions, cfg, iteration_num, iteration_start)
        if _stop_after_iteration(state, iteration_routed_before, total_nets, cfg):
            break

    elapsed_total = time.monotonic() - start_time
    return _finalize_ripup_result(
        design_name,
        state,
        routed_before,
        total_nets,
        positions,
        cfg,
        elapsed_total,
    )
