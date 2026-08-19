"""Signal-integrity timing helpers.

Transmission-line timing maths that complements the geometry-based impedance
code (:mod:`zaptrace.ee.routing.impedance`) and the length-match analysis:
propagation delay, the critical length above which a trace must be treated as a
transmission line, and the length-match tolerance for an allowed skew.

These are deterministic textbook estimates, not a field solver. Times are in
picoseconds, lengths in millimetres, dielectric constants are relative.
"""

from __future__ import annotations

import math

# Speed of light in mm per picosecond (299792458 m/s).
_C_MM_PER_PS = 0.299792458


def microstrip_eff_dielectric(er: float, w_over_h: float) -> float:
    """Effective dielectric constant of a microstrip (Hammerstad approximation).

    ``eeff = (er+1)/2 + (er-1)/2 * (1 + 12 h/w) ** -0.5``.
    """
    if er < 1.0:
        raise ValueError("er must be >= 1")
    if w_over_h <= 0:
        raise ValueError("w_over_h must be positive")
    return round((er + 1) / 2 + (er - 1) / 2 * (1 + 12 / w_over_h) ** -0.5, 4)


def propagation_delay_ps_per_mm(eff_dielectric: float) -> float:
    """Propagation delay per unit length: ``sqrt(eeff) / c``."""
    if eff_dielectric < 1.0:
        raise ValueError("eff_dielectric must be >= 1")
    return round(math.sqrt(eff_dielectric) / _C_MM_PER_PS, 4)


def critical_length_mm(rise_time_ps: float, eff_dielectric: float, *, divisor: float = 6.0) -> float:
    """Length above which a trace behaves as a transmission line.

    Uses the delay rule ``l_crit = t_rise / (divisor * t_pd)``; ``divisor`` is 6
    for the common 1/6-rule (use 2 for a looser 1/2-rule).
    """
    if rise_time_ps <= 0:
        raise ValueError("rise_time_ps must be positive")
    if divisor <= 0:
        raise ValueError("divisor must be positive")
    t_pd = propagation_delay_ps_per_mm(eff_dielectric)
    return round(rise_time_ps / (divisor * t_pd), 4)


def length_match_tolerance_mm(skew_ps: float, eff_dielectric: float) -> float:
    """Maximum length mismatch (mm) that stays within an allowed *skew_ps*."""
    if skew_ps < 0:
        raise ValueError("skew_ps must be non-negative")
    t_pd = propagation_delay_ps_per_mm(eff_dielectric)
    return round(skew_ps / t_pd, 4)


def delay_for_length_ps(length_mm: float, eff_dielectric: float) -> float:
    """Total propagation delay (ps) of a *length_mm* trace."""
    if length_mm < 0:
        raise ValueError("length_mm must be non-negative")
    return round(length_mm * propagation_delay_ps_per_mm(eff_dielectric), 4)


# ---------------------------------------------------------------------------
# Crosstalk heuristic (signal classification + crosstalk risk)
# ---------------------------------------------------------------------------


def crosstalk_coupling_fraction(
    aggressor_width_mm: float,
    victim_width_mm: float,
    trace_separation_mm: float,
    substrate_height_mm: float,
) -> float:
    """Estimate the near-end crosstalk coupling fraction between two microstrip traces.

    Uses the IPC-2141 approximation:
    ``k ≈ 0.25 * exp(-2 * pi * s / h)``
    where *s* is the edge-to-edge separation and *h* is the substrate height.

    The fraction is the fraction of the aggressor's switching voltage that
    appears on the victim. Values above 0.05 (5 %) are typically flagged.

    Args:
        aggressor_width_mm: Width of the aggressor trace (mm).
        victim_width_mm: Width of the victim trace (mm).
        trace_separation_mm: Edge-to-edge spacing between the two traces (mm).
        substrate_height_mm: PCB substrate thickness (mm) below the trace layer.
    """
    if trace_separation_mm < 0:
        raise ValueError("trace_separation_mm must be non-negative")
    if substrate_height_mm <= 0:
        raise ValueError("substrate_height_mm must be positive")
    _ = aggressor_width_mm, victim_width_mm  # not used in this approximation
    s = trace_separation_mm
    h = substrate_height_mm
    return round(0.25 * math.exp(-2 * math.pi * s / h), 6)


CROSSTALK_RISK_THRESHOLD = 0.05  # 5 % coupling → flag as at-risk


def crosstalk_risk_label(coupling_fraction: float) -> str:
    """Return a human-readable risk label for a coupling fraction.

    ``"low"`` (< 1 %), ``"medium"`` (1–5 %), ``"high"`` (> 5 %).
    """
    if coupling_fraction < 0.01:
        return "low"
    if coupling_fraction <= CROSSTALK_RISK_THRESHOLD:
        return "medium"
    return "high"


# ---------------------------------------------------------------------------
# Return-path continuity checker
# ---------------------------------------------------------------------------

from dataclasses import dataclass  # noqa: E402


@dataclass(frozen=True)
class ReturnPathCheck:
    """Result of a return-path continuity analysis for a single net."""

    net_id: str
    net_name: str
    has_return_path_hint: bool
    return_path_net: str | None
    risk: str
    note: str


def check_return_path_hints(nets: dict) -> list[ReturnPathCheck]:
    """Flag high-speed or high-current nets that lack a return-path net assignment.

    A high-speed or high-current net without a designated return-path net hint
    may have its return current routed over a split-plane gap or through a
    sub-optimal path, causing EMI and SI failures.

    Args:
        nets: Mapping of net_id → Net (from ``Design.nets``).

    Returns:
        A list of :class:`ReturnPathCheck` results — one per net that has
        constraints. Only nets with ``NetConstraints`` are evaluated.
    """
    results: list[ReturnPathCheck] = []
    for net_id, net in nets.items():
        if net.constraints is None:
            continue
        needs_hint = net.constraints.is_high_current or net.constraints.impedance_target is not None
        if not needs_hint:
            continue
        rp = net.constraints.return_path_net
        has_hint = rp is not None
        if has_hint:
            risk = "low"
            note = f"Return-path net assigned: '{rp}'"
        else:
            risk = "high"
            note = "No return-path net assigned; routing may cross a plane gap"
        results.append(
            ReturnPathCheck(
                net_id=net_id,
                net_name=net.name,
                has_return_path_hint=has_hint,
                return_path_net=rp,
                risk=risk,
                note=note,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Impedance / return-path risk report
# ---------------------------------------------------------------------------

from enum import StrEnum  # noqa: E402

from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

from zaptrace.core.models import Design  # noqa: E402


class SiRiskStatus(StrEnum):
    PASS = "pass"
    HUMAN_REVIEW_REQUIRED = "human-review-required"
    BLOCKED = "blocked"


class ImpedanceAssumption(BaseModel):
    model_config = ConfigDict(strict=False)

    net_id: str
    net_name: str
    target_ohms: float
    assumed_er: float = 4.2
    assumed_copper_thickness_mm: float = 0.035
    assumed_dielectric_height_mm: float = 0.18
    method: str = "heuristic microstrip estimate, not field-solver signoff"


class ReturnPathDiagnostic(BaseModel):
    model_config = ConfigDict(strict=False)

    net_id: str
    net_name: str
    risk: str
    return_path_net: str | None = None
    status: SiRiskStatus
    message: str


class ImpedanceReturnPathReport(BaseModel):
    schema_version: str = "1.0"
    assumption_count: int
    diagnostic_count: int
    blocked: bool
    human_review_required: bool
    assumptions: list[ImpedanceAssumption]
    diagnostics: list[ReturnPathDiagnostic]
    limitations: list[str] = Field(default_factory=list)


def build_impedance_return_path_report(design: Design) -> ImpedanceReturnPathReport:
    """Build explicit impedance-assumption and return-path continuity evidence."""
    assumptions: list[ImpedanceAssumption] = []
    for net_id, net in design.nets.items():
        if net.constraints and net.constraints.impedance_target is not None:
            assumptions.append(
                ImpedanceAssumption(
                    net_id=net_id,
                    net_name=net.name,
                    target_ohms=float(net.constraints.impedance_target),
                )
            )
    diagnostics: list[ReturnPathDiagnostic] = []
    for check in check_return_path_hints(design.nets):
        status = SiRiskStatus.PASS
        if check.risk == "high":
            status = SiRiskStatus.HUMAN_REVIEW_REQUIRED
        diagnostics.append(
            ReturnPathDiagnostic(
                net_id=check.net_id,
                net_name=check.net_name,
                risk=check.risk,
                return_path_net=check.return_path_net,
                status=status,
                message=check.note,
            )
        )
    human_review = any(item.status == SiRiskStatus.HUMAN_REVIEW_REQUIRED for item in diagnostics)
    blocked = any(item.status == SiRiskStatus.BLOCKED for item in diagnostics)
    return ImpedanceReturnPathReport(
        assumption_count=len(assumptions),
        diagnostic_count=len(diagnostics),
        blocked=blocked,
        human_review_required=human_review,
        assumptions=assumptions,
        diagnostics=diagnostics,
        limitations=[
            "Impedance assumptions are heuristic and require field-solver/fabricator stackup confirmation.",
            "Return-path continuity uses constraints.return_path_net hints and cannot infer full plane geometry.",
        ],
    )
