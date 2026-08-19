"""Thermal estimation helpers for circuit design.

Deterministic, textbook thermal calculators — junction temperature, regulator
and resistor dissipation, IPC-2221 trace width/temperature, and a thermal-via
estimate — so an agent can flag thermal problems before layout instead of after
a board comes back hot. These are *estimates*, not a CFD/thermal simulation.

Units: power in watts, temperatures in °C, currents in amps, resistances in
ohms, voltages in volts, trace widths in mm, copper weight in oz.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# IPC-2221 current-capacity constants (I = k * dT^0.44 * A^0.725, A in mils^2).
_K_EXTERNAL = 0.048
_K_INTERNAL = 0.024
_OZ_TO_MILS = 1.378  # 1 oz copper thickness in mils (~35 um)
_MM_TO_MILS = 39.3700787

# Rough thermal resistance of a single ~0.3 mm thermal via (order of magnitude).
_VIA_THERMAL_RESISTANCE_C_PER_W = 100.0


def junction_temperature(power_w: float, theta_ja_c_per_w: float, *, ambient_c: float = 25.0) -> float:
    """Junction temperature: ``Tj = Ta + P * theta_ja``."""
    if power_w < 0 or theta_ja_c_per_w < 0:
        raise ValueError("power and theta_ja must be non-negative")
    return round(ambient_c + power_w * theta_ja_c_per_w, 3)


def max_power_for_junction(tj_max_c: float, theta_ja_c_per_w: float, *, ambient_c: float = 25.0) -> float:
    """Maximum dissipation before reaching ``tj_max_c``: ``(Tj_max - Ta) / theta_ja``."""
    if theta_ja_c_per_w <= 0:
        raise ValueError("theta_ja must be positive")
    return round(max(0.0, (tj_max_c - ambient_c) / theta_ja_c_per_w), 4)


def linear_regulator_dissipation(vin_v: float, vout_v: float, iout_a: float) -> float:
    """Power burned in a linear regulator/LDO: ``(Vin - Vout) * Iout``."""
    if vin_v < vout_v:
        raise ValueError("vin must be >= vout for a linear regulator")
    if iout_a < 0:
        raise ValueError("iout must be non-negative")
    return round((vin_v - vout_v) * iout_a, 4)


def resistor_dissipation_v(voltage_v: float, resistance_ohms: float) -> float:
    """Resistor power from the voltage across it: ``V^2 / R``."""
    if resistance_ohms <= 0:
        raise ValueError("resistance must be positive")
    return round(voltage_v * voltage_v / resistance_ohms, 6)


def resistor_dissipation_i(current_a: float, resistance_ohms: float) -> float:
    """Resistor power from the current through it: ``I^2 * R``."""
    if resistance_ohms < 0:
        raise ValueError("resistance must be non-negative")
    return round(current_a * current_a * resistance_ohms, 6)


def ipc2221_trace_width_mm(
    current_a: float,
    temp_rise_c: float,
    *,
    copper_oz: float = 1.0,
    external: bool = True,
) -> float:
    """Minimum trace width (mm) for *current_a* at *temp_rise_c* (IPC-2221)."""
    if current_a <= 0 or temp_rise_c <= 0 or copper_oz <= 0:
        raise ValueError("current, temp_rise and copper_oz must be positive")
    k = _K_EXTERNAL if external else _K_INTERNAL
    area_mils2 = (current_a / (k * temp_rise_c**0.44)) ** (1.0 / 0.725)
    thickness_mils = copper_oz * _OZ_TO_MILS
    width_mils = area_mils2 / thickness_mils
    return round(width_mils / _MM_TO_MILS, 4)


def ipc2221_trace_temp_rise(
    current_a: float,
    width_mm: float,
    *,
    copper_oz: float = 1.0,
    external: bool = True,
) -> float:
    """Temperature rise (°C) of a *width_mm* trace carrying *current_a* (IPC-2221)."""
    if current_a <= 0 or width_mm <= 0 or copper_oz <= 0:
        raise ValueError("current, width and copper_oz must be positive")
    k = _K_EXTERNAL if external else _K_INTERNAL
    thickness_mils = copper_oz * _OZ_TO_MILS
    area_mils2 = width_mm * _MM_TO_MILS * thickness_mils
    return round((current_a / (k * area_mils2**0.725)) ** (1.0 / 0.44), 3)


def thermal_vias_for_power(
    power_w: float,
    *,
    target_rise_c: float = 40.0,
    per_via_c_per_w: float = _VIA_THERMAL_RESISTANCE_C_PER_W,
) -> int:
    """Rough number of parallel thermal vias to keep a power pad's rise under target.

    Vias in parallel divide thermal resistance, so ``n >= P * Rv / dT_target``.
    A heuristic aid, not a substitute for thermal simulation.
    """
    if power_w <= 0:
        return 0
    if target_rise_c <= 0 or per_via_c_per_w <= 0:
        raise ValueError("target_rise_c and per_via_c_per_w must be positive")
    return max(1, math.ceil(power_w * per_via_c_per_w / target_rise_c))


@dataclass(frozen=True)
class ThermalCheck:
    power_w: float
    junction_c: float
    margin_c: float
    within_limit: bool


def component_thermal_check(
    power_w: float,
    theta_ja_c_per_w: float,
    *,
    ambient_c: float = 25.0,
    tj_max_c: float = 125.0,
) -> ThermalCheck:
    """Estimate a component's junction temperature and whether it stays in spec."""
    tj = junction_temperature(power_w, theta_ja_c_per_w, ambient_c=ambient_c)
    return ThermalCheck(
        power_w=round(power_w, 4),
        junction_c=tj,
        margin_c=round(tj_max_c - tj, 3),
        within_limit=tj <= tj_max_c,
    )
