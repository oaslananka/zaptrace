"""Rail-level current budget evidence."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from zaptrace.core.models import Design, Net, PinType

_CURRENT_A_PATTERN = re.compile(r"(\d{1,12}(?:\.\d{1,12})?)\s{0,32}A", re.IGNORECASE)
_CURRENT_MA_PATTERN = re.compile(r"(\d{1,12}(?:\.\d{1,12})?)\s{0,32}ma", re.IGNORECASE)


class RailBudgetStatus(StrEnum):
    PASS = "pass"
    HUMAN_REVIEW_REQUIRED = "human-review-required"
    FAIL = "fail"


class RailLoadEntry(BaseModel):
    model_config = ConfigDict(strict=False)

    component_ref: str
    component_type: str
    current_a: float | None = None
    source: str = "missing"


class RailCurrentBudgetEntry(BaseModel):
    model_config = ConfigDict(strict=False)

    rail_id: str
    rail_name: str
    source_refs: list[str]
    source_current_a: float | None = None
    loads: list[RailLoadEntry]
    missing_current_refs: list[str]
    total_load_current_a: float
    margin_a: float | None = None
    margin_pct: float | None = None
    status: RailBudgetStatus
    message: str


class RailCurrentBudgetReport(BaseModel):
    schema_version: str = "1.0"
    rail_count: int
    failure_count: int
    missing_metadata_count: int
    blocked: bool
    human_review_required: bool
    rails: list[RailCurrentBudgetEntry]


def _parse_current(raw: str | None) -> float | None:
    if not raw:
        return None
    match = _CURRENT_A_PATTERN.search(raw)
    if match:
        return float(match.group(1))
    match = _CURRENT_MA_PATTERN.search(raw)
    if match:
        return float(match.group(1)) / 1000.0
    try:
        value = float(raw)
    except ValueError:
        return None
    return value / 1000.0 if value > 10 else value


def _property_current(properties: dict[str, Any]) -> tuple[float | None, str]:
    for key in ("operating_current_a", "current_a", "load_current_a", "max_current_a"):
        value = properties.get(key)
        if value is None:
            continue
        try:
            return float(value), f"properties.{key}"
        except (TypeError, ValueError):
            return None, f"invalid-properties.{key}"
    return None, "missing"


def _is_rail(net: Net) -> bool:
    name = net.name.upper()
    return net.type.value == "power" or name.startswith(("VDD", "VCC", "VBUS", "VBAT", "VIN", "+"))


def _regulator_output_rails(design: Design) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for comp in design.components.values():
        kind = comp.type.lower()
        if not any(token in kind for token in ("regulator", "ldo", "buck", "boost", "linear")):
            continue
        for pin in comp.pins.values():
            if pin.type == PinType.OUTPUT and pin.net:
                out.setdefault(pin.net, []).append(comp.ref)
    return out


def _component_load_current(component_ref: str, design: Design) -> RailLoadEntry:
    component = design.get_component(component_ref)
    if component is None:
        return RailLoadEntry(component_ref=component_ref, component_type="unknown")
    current, source = _property_current(component.properties)
    if current is None:
        current = _parse_current(component.value)
        source = "value" if current is not None else source
    return RailLoadEntry(
        component_ref=component.ref,
        component_type=component.type,
        current_a=current,
        source=source,
    )


def _source_current_a(refs: list[str], design: Design) -> float | None:
    ratings: list[float] = []
    for ref in refs:
        component = design.get_component(ref)
        if component is None:
            continue
        if component.current_rating is not None and component.current_rating > 0:
            ratings.append(component.current_rating)
            continue
        current, _source = _property_current(component.properties)
        if current is not None and current > 0:
            ratings.append(current)
    return max(ratings) if ratings else None


def _rail_loads(net: Net, source_refs: list[str], design: Design) -> list[RailLoadEntry]:
    loads: list[RailLoadEntry] = []
    seen_refs: set[str] = set()
    for node in net.nodes:
        ref = node.component_ref
        if ref in source_refs or ref in seen_refs:
            continue
        load = _component_load_current(ref, design)
        loads.append(load)
        seen_refs.add(load.component_ref)
    return loads


def _rail_budget_status(
    source_current: float | None,
    total_load: float,
    missing_refs: list[str],
) -> tuple[RailBudgetStatus, str]:
    if source_current is not None and total_load > source_current:
        return RailBudgetStatus.FAIL, "rail load current exceeds source current rating"
    if source_current is None or missing_refs:
        return (
            RailBudgetStatus.HUMAN_REVIEW_REQUIRED,
            "rail current budget has missing source/load current metadata",
        )
    return RailBudgetStatus.PASS, "rail current budget passes"


def _rail_budget_entry(
    rail_id: str,
    net: Net,
    source_refs: list[str],
    design: Design,
) -> RailCurrentBudgetEntry:
    source_current = _source_current_a(source_refs, design)
    loads = _rail_loads(net, source_refs, design)
    missing_refs = [load.component_ref for load in loads if load.current_a is None]
    total_load = round(sum(load.current_a or 0.0 for load in loads), 6)
    margin = round(source_current - total_load, 6) if source_current is not None else None
    margin_pct = round((margin / source_current) * 100, 3) if source_current and margin is not None else None
    status, message = _rail_budget_status(source_current, total_load, missing_refs)
    return RailCurrentBudgetEntry(
        rail_id=rail_id,
        rail_name=net.name,
        source_refs=source_refs,
        source_current_a=source_current,
        loads=loads,
        missing_current_refs=missing_refs,
        total_load_current_a=total_load,
        margin_a=margin,
        margin_pct=margin_pct,
        status=status,
        message=message,
    )


def build_rail_current_budget_report(design: Design) -> RailCurrentBudgetReport:
    sources_by_rail = _regulator_output_rails(design)
    entries = [
        _rail_budget_entry(rail_id, net, sources_by_rail.get(rail_id, []), design)
        for rail_id, net in sorted(design.nets.items())
        if _is_rail(net)
    ]
    failure_count = sum(entry.status == RailBudgetStatus.FAIL for entry in entries)
    missing_count = sum(len(entry.missing_current_refs) for entry in entries)
    review_required = any(entry.status == RailBudgetStatus.HUMAN_REVIEW_REQUIRED for entry in entries)
    return RailCurrentBudgetReport(
        rail_count=len(entries),
        failure_count=failure_count,
        missing_metadata_count=missing_count,
        blocked=failure_count > 0,
        human_review_required=review_required,
        rails=entries,
    )
