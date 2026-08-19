"""Component derating policy engine.

Deterministic pre-signoff checks for simple voltage/current/power derating. The
engine uses explicit component ratings plus operating values stored in component
properties and produces machine-readable evidence for proof packs.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.core.models import Component, Design


class DeratingStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    SKIPPED = "skipped"


class DeratingPolicy(BaseModel):
    """Configurable component derating thresholds."""

    model_config = ConfigDict(strict=False)

    voltage_utilization_max: float = Field(default=0.8, gt=0, le=1)
    current_utilization_max: float = Field(default=0.8, gt=0, le=1)
    power_utilization_max: float = Field(default=0.5, gt=0, le=1)
    require_operating_values: bool = False


class DeratingFinding(BaseModel):
    """One derating finding for one component and one metric."""

    component_ref: str
    metric: str
    status: DeratingStatus
    used: float | None = None
    rating: float | None = None
    utilization: float | None = None
    limit: float | None = None
    message: str


class DeratingReport(BaseModel):
    """Machine-readable derating policy report."""

    schema_version: str = "1.0"
    policy: DeratingPolicy
    component_count: int
    finding_count: int
    blocked: bool
    findings: list[DeratingFinding]
    message: str


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _component_property_float(component: Component, *names: str) -> float | None:
    for name in names:
        value = _float(component.properties.get(name))
        if value is not None:
            return value
    return None


def _voltage_supply_float(component: Component) -> float | None:
    raw = component.voltage_supply.strip().lower().replace("v", "")
    return _float(raw)


def _check_metric(
    component: Component,
    *,
    metric: str,
    used: float | None,
    rating: float | None,
    limit: float,
    require_operating_values: bool,
) -> DeratingFinding | None:
    if rating is None or rating <= 0:
        return None
    if used is None:
        if not require_operating_values:
            return None
        return DeratingFinding(
            component_ref=component.ref,
            metric=metric,
            status=DeratingStatus.WARNING,
            rating=rating,
            limit=limit,
            message=f"{component.ref} missing operating {metric} for derating check",
        )
    utilization = round(used / rating, 4)
    status = DeratingStatus.FAIL if utilization > limit else DeratingStatus.PASS
    return DeratingFinding(
        component_ref=component.ref,
        metric=metric,
        status=status,
        used=used,
        rating=rating,
        utilization=utilization,
        limit=limit,
        message=(
            f"{component.ref} {metric} utilization {utilization:.3f} exceeds derating limit {limit:.3f}"
            if status == DeratingStatus.FAIL
            else f"{component.ref} {metric} utilization {utilization:.3f} is within derating limit {limit:.3f}"
        ),
    )


def evaluate_component_derating(design: Design, policy: DeratingPolicy | None = None) -> DeratingReport:
    """Evaluate all components in a design against a derating policy."""
    policy = policy or DeratingPolicy()
    findings: list[DeratingFinding] = []
    for component in sorted(design.components.values(), key=lambda item: item.ref):
        checks = [
            _check_metric(
                component,
                metric="voltage",
                used=_component_property_float(component, "operating_voltage_v", "voltage_v")
                or _voltage_supply_float(component),
                rating=component.voltage_rating
                or _component_property_float(component, "voltage_rating_v", "max_voltage_v"),
                limit=policy.voltage_utilization_max,
                require_operating_values=policy.require_operating_values,
            ),
            _check_metric(
                component,
                metric="current",
                used=_component_property_float(component, "operating_current_a", "current_a", "load_current_a"),
                rating=component.current_rating
                or _component_property_float(component, "current_rating_a", "max_current_a"),
                limit=policy.current_utilization_max,
                require_operating_values=policy.require_operating_values,
            ),
            _check_metric(
                component,
                metric="power",
                used=_component_property_float(component, "operating_power_w", "power_w"),
                rating=_component_property_float(component, "rated_power_w", "power_rating_w", "max_power_w"),
                limit=policy.power_utilization_max,
                require_operating_values=policy.require_operating_values,
            ),
        ]
        findings.extend(check for check in checks if check is not None)
    blocked = any(finding.status == DeratingStatus.FAIL for finding in findings)
    return DeratingReport(
        policy=policy,
        component_count=len(design.components),
        finding_count=len(findings),
        blocked=blocked,
        findings=findings,
        message="derating policy passed" if not blocked else "derating policy failed",
    )
