"""Current density and copper-width evidence."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from zaptrace.analysis.rail_current import build_rail_current_budget_report
from zaptrace.analysis.thermal import ipc2221_trace_width_mm
from zaptrace.core.models import Design, NetType


class CurrentDensityStatus(StrEnum):
    PASS = "pass"
    HUMAN_REVIEW_REQUIRED = "human-review-required"
    FAIL = "fail"


class CurrentDensityTraceEntry(BaseModel):
    model_config = ConfigDict(strict=False)

    net_id: str
    net_name: str
    layer: str
    width_mm: float
    current_a: float
    required_width_mm: float
    margin_mm: float
    status: CurrentDensityStatus
    message: str


class CurrentDensityReport(BaseModel):
    schema_version: str = "1.0"
    high_current_net_count: int
    trace_count: int
    violation_count: int
    missing_route_count: int
    blocked: bool
    human_review_required: bool
    traces: list[CurrentDensityTraceEntry]
    missing_route_nets: list[str]
    assumptions: list[str]


def _high_current_net_ids(design: Design) -> list[str]:
    ids: list[str] = []
    for net_id, net in design.nets.items():
        if net.type == NetType.POWER or (net.constraints and net.constraints.is_high_current):
            ids.append(net_id)
    return sorted(set(ids))


def _rail_current_map(design: Design) -> dict[str, float]:
    report = build_rail_current_budget_report(design)
    return {rail.rail_id: rail.total_load_current_a for rail in report.rails}


def _current_for_net(design: Design, net_id: str, rail_currents: dict[str, float]) -> float:
    net = design.nets[net_id]
    if net_id in rail_currents and rail_currents[net_id] > 0:
        return rail_currents[net_id]
    if net.constraints and net.constraints.is_high_current:
        return 1.0
    return 0.5


def _required_width_mm(design: Design, net_id: str, current_a: float) -> float:
    net = design.nets[net_id]
    if net.constraints and net.constraints.min_trace_width_mm is not None:
        return net.constraints.min_trace_width_mm
    return ipc2221_trace_width_mm(max(current_a, 0.001), 10.0, copper_oz=1.0, external=True)


def build_current_density_report(design: Design) -> CurrentDensityReport:
    """Build current density and copper width evidence for routed high-current nets."""
    rail_currents = _rail_current_map(design)
    high_current = _high_current_net_ids(design)
    traces_by_net: dict[str, list] = {}
    if design.routing is not None:
        for segment in design.routing.traces:
            traces_by_net.setdefault(segment.net_id, []).append(segment)
    entries: list[CurrentDensityTraceEntry] = []
    missing_routes: list[str] = []
    for net_id in high_current:
        segments = traces_by_net.get(net_id, [])
        if not segments:
            missing_routes.append(net_id)
            continue
        current = _current_for_net(design, net_id, rail_currents)
        required = _required_width_mm(design, net_id, current)
        net = design.nets[net_id]
        for segment in segments:
            margin = round(segment.width - required, 6)
            status = CurrentDensityStatus.PASS if margin >= 0 else CurrentDensityStatus.FAIL
            entries.append(
                CurrentDensityTraceEntry(
                    net_id=net_id,
                    net_name=net.name,
                    layer=segment.layer,
                    width_mm=segment.width,
                    current_a=current,
                    required_width_mm=round(required, 6),
                    margin_mm=margin,
                    status=status,
                    message="trace width passes current-density rule"
                    if status == CurrentDensityStatus.PASS
                    else "trace width below required current-carrying width",
                )
            )
    violations = sum(1 for entry in entries if entry.status == CurrentDensityStatus.FAIL)
    return CurrentDensityReport(
        high_current_net_count=len(high_current),
        trace_count=len(entries),
        violation_count=violations,
        missing_route_count=len(missing_routes),
        blocked=violations > 0,
        human_review_required=bool(missing_routes),
        traces=entries,
        missing_route_nets=missing_routes,
        assumptions=[
            "IPC-2221 external trace width estimate, 10C temperature rise, 1 oz copper",
            "High-current non-rail nets without rail budget use a conservative 1A default",
        ],
    )
