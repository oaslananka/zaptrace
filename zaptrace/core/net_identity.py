"""Canonical net-identity helpers.

ZapTrace uses ``Net.id`` as the machine identity everywhere routing, export,
DRC/DFM, proof checks, and manufacturing evidence exchange references to a
net. ``Net.name`` is a human label only and may be duplicated or changed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from zaptrace.core.models import Design, RouteResult, TraceSegment, Via

_DECIMAL_RAIL_RE = re.compile(r"(?<!\d)(\d{1,12}\.\d{1,12})\s{0,32}V", re.IGNORECASE)
_EUROPEAN_RAIL_RE = re.compile(r"\b(\d{1,12})V(\d{1,12})\b", re.IGNORECASE)
_WHOLE_RAIL_RE = re.compile(r"(?<![\d.])(\d{1,12})\s{0,32}V\b", re.IGNORECASE)


def voltage_from_net_name(name: str) -> float | None:
    """Return a bounded voltage inferred from a human net label."""
    match = _DECIMAL_RAIL_RE.search(name)
    if match:
        return float(match.group(1))
    match = _EUROPEAN_RAIL_RE.search(name)
    if match:
        return float(f"{match.group(1)}.{match.group(2)}")
    match = _WHOLE_RAIL_RE.search(name)
    if match:
        return float(match.group(1))
    return None


@dataclass(frozen=True)
class NetIdentityReport:
    """Result of routing-net identity normalization."""

    changed_trace_count: int = 0
    changed_via_count: int = 0
    unknown_refs: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.unknown_refs


def canonical_net_id(design: Design, ref: str | None) -> str | None:
    """Return the canonical ``Net.id`` for *ref*.

    ``ref`` may already be a net id. A unique human ``Net.name`` is accepted as
    a compatibility alias so legacy artifacts can be normalized at boundaries.
    Ambiguous or unknown aliases return ``None`` instead of guessing.
    """
    if not ref:
        return None
    if ref in design.nets:
        return ref
    matches = [net.id for net in design.nets.values() if net.name == ref]
    if len(matches) == 1:
        return matches[0]
    return None


def _normalize_trace_net_ids(
    design: Design,
    traces: list[TraceSegment],
) -> tuple[list[TraceSegment], int, list[str]]:
    """Normalize trace aliases and return traces, change count, and unknown refs."""
    normalized: list[TraceSegment] = []
    changed = 0
    unknown: list[str] = []
    for trace in traces:
        canonical = canonical_net_id(design, trace.net_id)
        if canonical is None:
            if trace.net_id:
                unknown.append(trace.net_id)
            normalized.append(trace)
            continue
        if canonical != trace.net_id:
            changed += 1
            if hasattr(trace, "model_copy"):
                trace = trace.model_copy(update={"net_id": canonical})
            else:
                trace.net_id = canonical
        normalized.append(trace)
    return normalized, changed, unknown


def _normalize_via_net_ids(
    design: Design,
    vias: list[Via],
) -> tuple[list[Via], int, list[str]]:
    """Normalize via aliases and return vias, change count, and unknown refs."""
    normalized: list[Via] = []
    changed = 0
    unknown: list[str] = []
    for via in vias:
        if len(via) < 5:
            normalized.append(via)
            continue
        x, y, diameter, hole, ref = via
        canonical = canonical_net_id(design, ref)
        if canonical is None:
            if ref:
                unknown.append(str(ref))
            normalized.append(via)
            continue
        if canonical != ref:
            changed += 1
            normalized.append((x, y, diameter, hole, canonical))
        else:
            normalized.append(via)
    return normalized, changed, unknown


def canonical_routing_net_ids(design: Design, routing: RouteResult | None) -> NetIdentityReport:
    """Normalize a ``RouteResult`` in-place so traces/vias reference ``Net.id``.

    Unknown refs are reported and left unchanged; callers can fail release gates
    on ``report.ok is False``.
    """
    if routing is None:
        return NetIdentityReport()

    traces, changed_traces, trace_unknown = _normalize_trace_net_ids(
        design,
        list(getattr(routing, "traces", [])),
    )
    routing.traces = traces

    vias, changed_vias, via_unknown = _normalize_via_net_ids(
        design,
        list(getattr(routing, "vias", [])),
    )
    if hasattr(routing, "vias"):
        routing.vias = vias

    return NetIdentityReport(
        changed_trace_count=changed_traces,
        changed_via_count=changed_vias,
        unknown_refs=tuple(sorted(set(trace_unknown + via_unknown))),
    )
