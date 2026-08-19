"""Differential-pair and length/skew sign-off evidence."""

from __future__ import annotations

import math
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from zaptrace.core.models import Design, Net, NetType, TraceSegment


class DiffPairCheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    MISSING_ROUTE = "missing-route"


class DiffPairLengthEntry(BaseModel):
    """One differential/length-match group measurement."""

    model_config = ConfigDict(strict=False)

    group_name: str
    net_ids: list[str]
    net_names: list[str]
    lengths_mm: dict[str, float]
    delta_mm: float
    tolerance_mm: float
    supported_profile: bool
    status: DiffPairCheckStatus
    blocking: bool
    message: str


class DiffPairLengthReport(BaseModel):
    """Machine-readable differential-pair length/skew report."""

    schema_version: str = "1.0"
    pair_count: int
    violation_count: int
    missing_route_count: int
    blocked: bool
    entries: list[DiffPairLengthEntry]


def _glob_match(pattern: str, value: str) -> bool:
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return value.startswith(pattern.rstrip("*"))
    return pattern == value


def _segment_length(segment: TraceSegment) -> float:
    return math.dist(segment.start, segment.end)


def _net_length(design: Design, net_id: str) -> float:
    if design.routing is None:
        return 0.0
    return round(sum(_segment_length(segment) for segment in design.routing.traces if segment.net_id == net_id), 3)


def _routed_net_ids(design: Design) -> set[str]:
    if design.routing is None:
        return set()
    return {segment.net_id for segment in design.routing.traces}


def _routing_tolerance(design: Design, nets: list[Net], default_tolerance_mm: float) -> tuple[float, bool]:
    supported = False
    tolerance = default_tolerance_mm
    for intent in design.constraints.routing:
        matched = [net for net in nets if _glob_match(intent.net, net.id) or _glob_match(intent.net, net.name)]
        if matched and intent.differential_pair:
            supported = True
            if intent.length_match_mm is not None:
                tolerance = min(tolerance, intent.length_match_mm)
    for net in nets:
        if net.type == NetType.DIFFERENTIAL or (net.constraints and net.constraints.diff_pair_partner):
            supported = True
    return tolerance, supported


def _length_groups(design: Design) -> dict[str, list[Net]]:
    groups: dict[str, list[Net]] = {}
    for net in design.nets.values():
        if net.constraints and net.constraints.length_match_group:
            groups.setdefault(net.constraints.length_match_group, []).append(net)
    for net in design.nets.values():
        partner_id = net.constraints.diff_pair_partner if net.constraints else None
        if partner_id and partner_id in design.nets:
            pair_ids = {net.id, partner_id}
            if any(pair_ids <= {member.id for member in existing} for existing in groups.values()):
                continue
            group = f"diffpair:{min(net.id, partner_id)}:{max(net.id, partner_id)}"
            members = {item.id: item for item in groups.get(group, [])}
            members[net.id] = net
            members[partner_id] = design.nets[partner_id]
            groups[group] = list(members.values())
    return groups


def build_diffpair_length_report(design: Design, *, default_tolerance_mm: float = 1.0) -> DiffPairLengthReport:
    """Build differential-pair/length-match report from routed traces."""
    entries: list[DiffPairLengthEntry] = []
    routed = _routed_net_ids(design)
    for group_name, nets in sorted(_length_groups(design).items()):
        if len(nets) < 2:
            continue
        tolerance, supported = _routing_tolerance(design, nets, default_tolerance_mm)
        lengths = {net.id: _net_length(design, net.id) for net in nets}
        missing = [net.id for net in nets if net.id not in routed]
        delta = round(max(lengths.values()) - min(lengths.values()), 3) if lengths else 0.0
        status = DiffPairCheckStatus.PASS
        if missing:
            status = DiffPairCheckStatus.MISSING_ROUTE
        elif delta > tolerance:
            status = DiffPairCheckStatus.FAIL
        blocking = supported and status != DiffPairCheckStatus.PASS
        entries.append(
            DiffPairLengthEntry(
                group_name=group_name,
                net_ids=[net.id for net in nets],
                net_names=[net.name for net in nets],
                lengths_mm=lengths,
                delta_mm=delta,
                tolerance_mm=tolerance,
                supported_profile=supported,
                status=status,
                blocking=blocking,
                message="missing routed length evidence for " + ", ".join(missing)
                if missing
                else f"length delta {delta:.3f} mm vs tolerance {tolerance:.3f} mm",
            )
        )
    violations = sum(1 for entry in entries if entry.status == DiffPairCheckStatus.FAIL)
    missing_routes = sum(1 for entry in entries if entry.status == DiffPairCheckStatus.MISSING_ROUTE)
    return DiffPairLengthReport(
        pair_count=len(entries),
        violation_count=violations,
        missing_route_count=missing_routes,
        blocked=any(entry.blocking for entry in entries),
        entries=entries,
    )


def write_diffpair_length_report(report: DiffPairLengthReport, output_path: str | Path) -> Path:
    out = Path(output_path)
    if out.suffix.lower() != ".json":
        raise ValueError(f"unexpected diff-pair report suffix: {out.suffix}")
    resolved = out.resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    # nosemgrep: python.lang.security.audit.path-traversal.path-traversal-write
    resolved.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return resolved
