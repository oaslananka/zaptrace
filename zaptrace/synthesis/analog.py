"""Analog & sensor front-end calculators.

Deterministic op-amp and ADC front-end maths so an agent can design a gain
stage and an ADC interface with *correct* values instead of guessing.

Units: resistances in ohms, voltages in volts, capacitances in farads,
frequencies in hertz.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from zaptrace.synthesis.calculators import _sig, nearest_e_series


def noninverting_gain(r_feedback: float, r_ground: float) -> float:
    """Non-inverting op-amp gain: ``Av = 1 + Rf/Rg``."""
    if r_feedback < 0 or r_ground <= 0:
        raise ValueError("r_feedback must be >= 0 and r_ground must be > 0")
    return round(1.0 + r_feedback / r_ground, 6)


def inverting_gain(r_feedback: float, r_input: float) -> float:
    """Inverting op-amp gain: ``Av = -Rf/Rin``."""
    if r_feedback < 0 or r_input <= 0:
        raise ValueError("r_feedback must be >= 0 and r_input must be > 0")
    return round(-r_feedback / r_input, 6)


def noninverting_feedback_for_gain(gain: float, r_ground: float, *, series: int = 24) -> float:
    """E-series feedback resistor for a target non-inverting gain (Rf = (Av-1)*Rg)."""
    if gain < 1.0:
        raise ValueError("non-inverting gain must be >= 1")
    if r_ground <= 0:
        raise ValueError("r_ground must be positive")
    ideal = (gain - 1.0) * r_ground
    if ideal == 0:
        return 0.0
    return nearest_e_series(ideal, series)


def inverting_feedback_for_gain(gain_magnitude: float, r_input: float, *, series: int = 24) -> float:
    """E-series feedback resistor for a target inverting gain magnitude (Rf = |Av|*Rin)."""
    if gain_magnitude <= 0:
        raise ValueError("gain_magnitude must be positive")
    if r_input <= 0:
        raise ValueError("r_input must be positive")
    return nearest_e_series(gain_magnitude * r_input, series)


def adc_lsb_voltage(vref_v: float, bits: int) -> float:
    """ADC least-significant-bit voltage: ``Vref / 2**bits``."""
    if vref_v <= 0:
        raise ValueError("vref must be positive")
    if bits <= 0:
        raise ValueError("bits must be positive")
    return vref_v / (2**bits)


def adc_code_for_voltage(voltage_v: float, vref_v: float, bits: int) -> int:
    """Ideal ADC code for an input voltage, clamped to the converter's range."""
    if vref_v <= 0 or bits <= 0:
        raise ValueError("vref and bits must be positive")
    max_code = 2**bits - 1
    code = round(voltage_v / vref_v * (2**bits))
    return max(0, min(max_code, code))


# ---------------------------------------------------------------------------
# Op-amp bandwidth / gain-bandwidth product
# ---------------------------------------------------------------------------


def opamp_closed_loop_bandwidth(gain_bandwidth_hz: float, closed_loop_gain: float) -> float:
    """Closed-loop -3 dB bandwidth of an op-amp stage.

    ``f_-3dB = GBW / |Av|`` (valid for single-pole roll-off approximation).

    Args:
        gain_bandwidth_hz: Op-amp gain-bandwidth product (GBW) in Hz.
        closed_loop_gain: Magnitude of the closed-loop gain (Av > 0).
    """
    if gain_bandwidth_hz <= 0:
        raise ValueError("gain_bandwidth_hz must be positive")
    if closed_loop_gain <= 0:
        raise ValueError("closed_loop_gain must be positive")
    return _sig(gain_bandwidth_hz / closed_loop_gain)


def opamp_min_gbw(target_bandwidth_hz: float, closed_loop_gain: float, *, margin: float = 3.0) -> float:
    """Minimum GBW an op-amp must have for a given closed-loop bandwidth.

    ``GBW_min = |Av| × f_bw × margin``

    A margin of 3× is typical to account for phase margin and process spread.

    Args:
        target_bandwidth_hz: Required signal bandwidth (Hz).
        closed_loop_gain: Closed-loop gain magnitude.
        margin: Safety margin (default 3×).
    """
    if target_bandwidth_hz <= 0 or closed_loop_gain <= 0 or margin <= 0:
        raise ValueError("all parameters must be positive")
    return _sig(closed_loop_gain * target_bandwidth_hz * margin)


# ---------------------------------------------------------------------------
# Anti-alias (Sallen-Key) filter calculator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AntiAliasFilterResult:
    filter_order: int
    cutoff_hz: float
    r_ohms: float
    c_farads: float
    attenuation_db_at_nyquist: float
    note: str


def anti_alias_filter(
    sample_rate_hz: float,
    *,
    signal_bandwidth_hz: float | None = None,
    attenuation_db_at_nyquist: float = 40.0,
    series: int = 24,
) -> AntiAliasFilterResult:
    """Size a passive RC anti-alias filter for a given sample rate.

    Uses a first-order RC filter positioned at ``signal_bandwidth_hz`` (defaults
    to half the Nyquist frequency = sample_rate/4). The actual attenuation at
    the Nyquist frequency (sample_rate/2) is computed from the chosen R/C values.

    For sharper roll-off, the caller should use a higher-order active filter
    (Sallen-Key). This function sizes the cut-off resistor for a 100 nF standard
    capacitor; use the result as a starting point.

    Args:
        sample_rate_hz: ADC sample rate (Hz).
        signal_bandwidth_hz: Desired signal pass-band; defaults to sample_rate/4.
        attenuation_db_at_nyquist: Target attenuation at Nyquist (dB). Used only
            to recommend filter order; not enforced by the RC.
        series: E-series for the resistor snap.
    """
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    nyquist_hz = sample_rate_hz / 2.0
    bw = signal_bandwidth_hz if signal_bandwidth_hz is not None else sample_rate_hz / 4.0
    if bw <= 0 or bw >= nyquist_hz:
        raise ValueError("signal_bandwidth_hz must be in (0, sample_rate/2)")
    # Size R for the cutoff using a standard 100 nF cap
    c = 100e-9
    r_ideal = 1.0 / (2.0 * math.pi * bw * c)
    r_chosen = nearest_e_series(r_ideal, series)
    fc = 1.0 / (2.0 * math.pi * r_chosen * c)
    # Attenuation of 1st-order RC at Nyquist
    ratio = nyquist_hz / fc
    atten_db = _sig(20.0 * math.log10(math.sqrt(1 + ratio**2)))
    # Recommend order based on target attenuation
    order = max(1, math.ceil(attenuation_db_at_nyquist / atten_db))
    return AntiAliasFilterResult(
        filter_order=order,
        cutoff_hz=_sig(fc),
        r_ohms=r_chosen,
        c_farads=c,
        attenuation_db_at_nyquist=atten_db,
        note=(
            f"RC anti-alias: R={r_chosen:g}Ω, C=100nF → fc={_sig(fc):g} Hz; "
            f"1st-order gives {atten_db:.1f} dB at Nyquist ({nyquist_hz / 1e3:.1f} kHz). "
            f"For {attenuation_db_at_nyquist:.0f} dB target, use {order}-order filter."
        ),
    )


# ---------------------------------------------------------------------------
# ADC source impedance check
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdcSourceImpedanceResult:
    ok: bool
    settling_time_ns: float
    required_settling_ns: float
    max_source_ohms: float
    note: str


def adc_source_impedance_check(
    source_resistance_ohms: float,
    adc_input_capacitance_pf: float,
    sample_rate_hz: float,
    bits: int,
    *,
    acquisition_cycles: float = 1.0,
) -> AdcSourceImpedanceResult:
    """Check that the source impedance allows the ADC to settle to full accuracy.

    The ADC's input capacitor (``Cin``) must charge through the source resistance
    (``Rs``) plus the ADC's internal switch resistance (approximated here as
    negligible) to within ``0.5 LSB`` in the acquisition time.

    Settling to 0.5 LSB requires: ``t_settle = N_bits * ln(2) * τ``
    where ``τ = Rs * Cin``.

    Equivalently, the maximum allowed source resistance is:
    ``Rs_max = t_acq / (N_bits * ln(2) * Cin)``

    Args:
        source_resistance_ohms: Driving source resistance (including op-amp
            output impedance and trace resistance).
        adc_input_capacitance_pf: ADC sample-and-hold input capacitance (pF).
        sample_rate_hz: ADC sample rate (Hz).
        bits: ADC resolution.
        acquisition_cycles: Number of clock cycles the ADC uses for acquisition
            (the sample window); default 1.0.
    """
    if source_resistance_ohms < 0:
        raise ValueError("source_resistance_ohms must be non-negative")
    if adc_input_capacitance_pf <= 0 or sample_rate_hz <= 0 or bits <= 0:
        raise ValueError("capacitance, sample rate, and bits must be positive")
    cin = adc_input_capacitance_pf * 1e-12
    t_acq_s = acquisition_cycles / sample_rate_hz
    # Required tau = t_acq / (bits * ln2); Rs_max = tau / Cin
    tau_required = t_acq_s / (bits * math.log(2))
    rs_max = tau_required / cin
    tau_actual = source_resistance_ohms * cin
    settling_time_ns = _sig(tau_actual * bits * math.log(2) * 1e9)
    required_ns = _sig(t_acq_s * 1e9)
    ok = source_resistance_ohms <= rs_max
    note = (
        f"ADC source impedance: Rs={source_resistance_ohms:g}Ω vs Rs_max={_sig(rs_max):g}Ω "
        f"for {bits}-bit settle in {required_ns:.1f} ns (t_settle={settling_time_ns:.1f} ns). "
        f"{'OK' if ok else 'FAIL — add op-amp buffer or reduce source impedance'}"
    )
    return AdcSourceImpedanceResult(
        ok=ok,
        settling_time_ns=settling_time_ns,
        required_settling_ns=required_ns,
        max_source_ohms=_sig(rs_max),
        note=note,
    )
