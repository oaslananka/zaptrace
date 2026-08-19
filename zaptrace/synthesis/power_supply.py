"""Switching power-supply design calculators.

Deterministic, textbook buck-converter design maths so an agent can pick a
*correct* inductor and output capacitor for a target ripple instead of copying
a reference design blindly. Pure functions, fully testable.

Units: voltages in volts, currents in amps, inductance in henries, capacitance
in farads, frequency in hertz.
"""

from __future__ import annotations

from dataclasses import dataclass


def buck_duty_cycle(vin_v: float, vout_v: float) -> float:
    """Ideal buck duty cycle: ``D = Vout / Vin``."""
    if vin_v <= 0:
        raise ValueError("vin must be positive")
    if not 0 < vout_v <= vin_v:
        raise ValueError("vout must satisfy 0 < vout <= vin")
    return round(vout_v / vin_v, 4)


def buck_inductor_henries(
    vin_v: float,
    vout_v: float,
    iout_a: float,
    fsw_hz: float,
    *,
    ripple_ratio: float = 0.3,
) -> float:
    """Inductor for a target peak-to-peak ripple fraction of the output current.

    ``L = Vout * (Vin - Vout) / (Vin * fsw * dIL)`` where ``dIL = ripple_ratio * Iout``.
    """
    if iout_a <= 0 or fsw_hz <= 0:
        raise ValueError("iout and fsw must be positive")
    if not 0 < ripple_ratio <= 1:
        raise ValueError("ripple_ratio must be in (0, 1]")
    buck_duty_cycle(vin_v, vout_v)  # validates vin/vout relationship
    delta_il = ripple_ratio * iout_a
    return vout_v * (vin_v - vout_v) / (vin_v * fsw_hz * delta_il)


def inductor_ripple_current_a(vin_v: float, vout_v: float, inductor_h: float, fsw_hz: float) -> float:
    """Peak-to-peak inductor ripple current: ``Vout*(Vin-Vout) / (Vin*fsw*L)``."""
    if inductor_h <= 0 or fsw_hz <= 0:
        raise ValueError("inductor and fsw must be positive")
    buck_duty_cycle(vin_v, vout_v)
    return vout_v * (vin_v - vout_v) / (vin_v * fsw_hz * inductor_h)


def buck_output_cap_farads(ripple_current_a: float, fsw_hz: float, vripple_v: float) -> float:
    """Output capacitance to hold ripple voltage: ``dIL / (8 * fsw * Vripple)``."""
    if ripple_current_a <= 0 or fsw_hz <= 0 or vripple_v <= 0:
        raise ValueError("ripple_current, fsw and vripple must be positive")
    return ripple_current_a / (8.0 * fsw_hz * vripple_v)


@dataclass(frozen=True)
class BuckDesign:
    duty_cycle: float
    inductor_h: float
    ripple_current_a: float
    output_cap_f: float


def design_buck(
    vin_v: float,
    vout_v: float,
    iout_a: float,
    fsw_hz: float,
    *,
    ripple_ratio: float = 0.3,
    output_ripple_v: float = 0.01,
) -> BuckDesign:
    """Compute the inductor, ripple current and output cap for a buck converter."""
    inductor = buck_inductor_henries(vin_v, vout_v, iout_a, fsw_hz, ripple_ratio=ripple_ratio)
    ripple = inductor_ripple_current_a(vin_v, vout_v, inductor, fsw_hz)
    return BuckDesign(
        duty_cycle=buck_duty_cycle(vin_v, vout_v),
        inductor_h=inductor,
        ripple_current_a=round(ripple, 6),
        output_cap_f=buck_output_cap_farads(ripple, fsw_hz, output_ripple_v),
    )
