"""Regulator dropout and thermal margin evidence."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from zaptrace.analysis.rail_current import build_rail_current_budget_report
from zaptrace.core.models import Component, Design, PinType

_VOLTAGE_PATTERN = re.compile(r"(\d{1,12}(?:\.\d{1,12})?)\s{0,32}V", re.IGNORECASE)
_RAIL_PATTERN = re.compile(r"(?:VDD_|VCC_|VOUT_)?(\d+)(?:V)?(\d+)?", re.IGNORECASE)


class RegulatorMarginStatus(StrEnum):
    PASS = "pass"
    HUMAN_REVIEW_REQUIRED = "human-review-required"
    FAIL = "fail"


class RegulatorMarginEntry(BaseModel):
    model_config = ConfigDict(strict=False)

    component_ref: str
    regulator_type: str
    input_nets: list[str]
    output_nets: list[str]
    vin_v: float | None = None
    vout_v: float | None = None
    iout_a: float | None = None
    dropout_v: float | None = None
    dropout_margin_v: float | None = None
    power_dissipation_w: float | None = None
    theta_ja_c_per_w: float | None = None
    ambient_c: float | None = None
    junction_c: float | None = None
    junction_max_c: float | None = None
    thermal_margin_c: float | None = None
    missing_fields: list[str]
    status: RegulatorMarginStatus
    message: str


class RegulatorMarginReport(BaseModel):
    schema_version: str = "1.0"
    regulator_count: int
    failure_count: int
    missing_metadata_count: int
    blocked: bool
    human_review_required: bool
    regulators: list[RegulatorMarginEntry]


def _float_prop(component: Component, *keys: str) -> float | None:
    for key in keys:
        value = component.properties.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _parse_voltage(raw: str | None) -> float | None:
    if not raw:
        return None
    match = _VOLTAGE_PATTERN.search(raw)
    if match:
        return float(match.group(1))
    try:
        return float(raw.strip().replace("V", "").replace("v", ""))
    except ValueError:
        return None


def _voltage_from_net_name(name: str) -> float | None:
    upper = name.upper()
    if upper in {"VBUS", "USB_VBUS"}:
        return 5.0
    match = _RAIL_PATTERN.search(upper)
    if not match:
        return None
    whole = match.group(1)
    frac = match.group(2) or ""
    if frac:
        return float(f"{whole}.{frac}")
    return float(whole)


def _is_regulator(component: Component) -> bool:
    text = f"{component.type} {component.value or ''}".lower()
    return any(token in text for token in ("regulator", "ldo", "buck", "boost", "linear"))


def _regulator_kind(component: Component) -> str:
    text = f"{component.type} {component.value or ''}".lower()
    if "ldo" in text or "linear" in text:
        return "linear"
    if "buck" in text:
        return "buck"
    if "boost" in text:
        return "boost"
    return "regulator"


def _pin_nets(component: Component, pin_type: PinType) -> list[str]:
    return sorted({pin.net for pin in component.pins.values() if pin.type == pin_type and pin.net})


def _rail_current_by_id(design: Design) -> dict[str, float | None]:
    report = build_rail_current_budget_report(design)
    return {rail.rail_id: rail.total_load_current_a for rail in report.rails}


def _net_voltage(design: Design, net_id: str) -> float | None:
    net = design.nets.get(net_id)
    if net is None:
        return None
    return _voltage_from_net_name(net.name) or _voltage_from_net_name(net.id)


def _entry_for_regulator(component: Component, design: Design) -> RegulatorMarginEntry:
    input_nets = _pin_nets(component, PinType.POWER)
    output_nets = _pin_nets(component, PinType.OUTPUT)
    rail_current = _rail_current_by_id(design)
    kind = _regulator_kind(component)
    vin = _float_prop(component, "input_voltage_v", "vin_v")
    if vin is None:
        vin = _parse_voltage(component.voltage_supply)
    if vin is None and input_nets:
        vin = _net_voltage(design, input_nets[0])
    vout = _float_prop(component, "output_voltage_v", "vout_v")
    if vout is None and output_nets:
        vout = _net_voltage(design, output_nets[0])
    iout = _float_prop(component, "output_current_a", "iout_a", "load_current_a")
    if iout is None and output_nets:
        iout = rail_current.get(output_nets[0])
    dropout = _float_prop(component, "dropout_voltage_v", "ldo_dropout_v")
    theta = _float_prop(component, "theta_ja_c_per_w", "thermal_resistance_c_per_w")
    ambient = _float_prop(component, "ambient_c", "ambient_temperature_c", "max_ambient_c")
    tj_max = _float_prop(component, "junction_max_c", "t_junction_max_c", "tj_max_c")
    missing: list[str] = []
    for name, value in (
        ("vin_v", vin),
        ("vout_v", vout),
        ("iout_a", iout),
        ("theta_ja_c_per_w", theta),
        ("ambient_c", ambient),
        ("junction_max_c", tj_max),
    ):
        if value is None:
            missing.append(name)
    if kind == "linear" and dropout is None:
        missing.append("dropout_v")
    dropout_margin = None
    if kind == "linear" and vin is not None and vout is not None and dropout is not None:
        dropout_margin = round(vin - vout - dropout, 6)
    pd = None
    if vin is not None and vout is not None and iout is not None:
        if kind == "linear":
            pd = round(max(0.0, vin - vout) * iout, 6)
        else:
            efficiency = _float_prop(component, "efficiency", "efficiency_pct")
            if efficiency is not None:
                eff = efficiency / 100.0 if efficiency > 1 else efficiency
                if eff > 0:
                    pd = round((vout * iout) * (1.0 - eff) / eff, 6)
            else:
                missing.append("efficiency")
    junction = None
    thermal_margin = None
    if pd is not None and theta is not None and ambient is not None and tj_max is not None:
        junction = round(ambient + pd * theta, 6)
        thermal_margin = round(tj_max - junction, 6)
    status = RegulatorMarginStatus.PASS
    message = "regulator dropout and thermal margins pass"
    if missing:
        status = RegulatorMarginStatus.HUMAN_REVIEW_REQUIRED
        message = "regulator margin has missing metadata"
    if (dropout_margin is not None and dropout_margin < 0) or (thermal_margin is not None and thermal_margin < 0):
        status = RegulatorMarginStatus.FAIL
        message = "regulator dropout or thermal margin failed"
    return RegulatorMarginEntry(
        component_ref=component.ref,
        regulator_type=kind,
        input_nets=input_nets,
        output_nets=output_nets,
        vin_v=vin,
        vout_v=vout,
        iout_a=iout,
        dropout_v=dropout,
        dropout_margin_v=dropout_margin,
        power_dissipation_w=pd,
        theta_ja_c_per_w=theta,
        ambient_c=ambient,
        junction_c=junction,
        junction_max_c=tj_max,
        thermal_margin_c=thermal_margin,
        missing_fields=sorted(set(missing)),
        status=status,
        message=message,
    )


def build_regulator_margin_report(design: Design) -> RegulatorMarginReport:
    """Build regulator dropout and thermal margin report."""
    entries = [
        _entry_for_regulator(component, design) for component in design.components.values() if _is_regulator(component)
    ]
    failures = sum(1 for entry in entries if entry.status == RegulatorMarginStatus.FAIL)
    missing_count = sum(len(entry.missing_fields) for entry in entries)
    review = any(entry.status == RegulatorMarginStatus.HUMAN_REVIEW_REQUIRED for entry in entries)
    return RegulatorMarginReport(
        regulator_count=len(entries),
        failure_count=failures,
        missing_metadata_count=missing_count,
        blocked=failures > 0,
        human_review_required=review,
        regulators=entries,
    )
