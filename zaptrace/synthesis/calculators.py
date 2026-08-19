"""Component-value calculators for circuit synthesis.

Deterministic, datasheet-grounded helper functions that compute the passive
values a real schematic needs — LED series resistors, voltage dividers, RC
filters, I2C pull-ups — and snap them onto standard E-series preferred values.

These are the building blocks an agent (or the synthesis engine) uses to choose
*correct* component values instead of guessing. Every function is a pure
function with no side effects, so the results are reproducible and testable.

All resistances are in ohms, capacitances in farads, voltages in volts,
currents in amperes, frequencies in hertz, unless a parameter name says
otherwise (e.g. ``*_ma``, ``*_pf``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# E-series preferred values (IEC 60063)
# ---------------------------------------------------------------------------

# Mantissas in the [1.0, 10.0) decade.
_E12 = (1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2)
_E24 = (
    1.0,
    1.1,
    1.2,
    1.3,
    1.5,
    1.6,
    1.8,
    2.0,
    2.2,
    2.4,
    2.7,
    3.0,
    3.3,
    3.6,
    3.9,
    4.3,
    4.7,
    5.1,
    5.6,
    6.2,
    6.8,
    7.5,
    8.2,
    9.1,
)

_E_SERIES: dict[int, tuple[float, ...]] = {12: _E12, 24: _E24}

# Decades spanning sub-ohm passives through gigaohm/gigafarad-scale values.
_DECADES = tuple(range(-13, 10))

_POSITIVE_VALUE_ERROR = "value must be positive"


def _sig(value: float, digits: int = 6) -> float:
    """Round *value* to *digits* significant figures (kills float-mul noise)."""
    if value == 0:
        return 0.0
    exponent = digits - 1 - math.floor(math.log10(abs(value)))
    return round(value, exponent)


def _candidates(series: int) -> list[float]:
    if series not in _E_SERIES:
        raise ValueError(f"Unsupported E-series: E{series}. Choose from {sorted(_E_SERIES)}.")
    base = _E_SERIES[series]
    values = {_sig(mantissa * (10.0**decade)) for decade in _DECADES for mantissa in base}
    return sorted(values)


def nearest_e_series(value: float, series: int = 24) -> float:
    """Snap *value* to the closest E*series* preferred value."""
    if value <= 0:
        raise ValueError(_POSITIVE_VALUE_ERROR)
    return min(_candidates(series), key=lambda candidate: abs(candidate - value))


def e_series_ceil(value: float, series: int = 24) -> float:
    """Smallest E*series* preferred value greater than or equal to *value*."""
    if value <= 0:
        raise ValueError(_POSITIVE_VALUE_ERROR)
    higher = [c for c in _candidates(series) if c >= _sig(value)]
    if not higher:
        raise ValueError(f"{value} exceeds the supported E-series range")
    return higher[0]


def e_series_floor(value: float, series: int = 24) -> float:
    """Largest E*series* preferred value less than or equal to *value*."""
    if value <= 0:
        raise ValueError(_POSITIVE_VALUE_ERROR)
    lower = [c for c in _candidates(series) if c <= _sig(value)]
    if not lower:
        raise ValueError(f"{value} is below the supported E-series range")
    return lower[-1]


# ---------------------------------------------------------------------------
# LED series resistor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedResistor:
    ideal_ohms: float
    chosen_ohms: float
    actual_current_a: float
    resistor_power_w: float
    series: int


def led_series_resistor(
    supply_v: float,
    forward_v: float,
    current_ma: float,
    *,
    series: int = 24,
) -> LedResistor:
    """Size a current-limiting resistor for an LED.

    Picks the next E-series value *at or above* the ideal resistance so the
    actual current never exceeds the target (safer for the LED).

    Args:
        supply_v: Rail driving the LED + resistor.
        forward_v: LED forward voltage (Vf) at the target current.
        current_ma: Desired forward current in milliamps.
        series: E-series to snap onto (12 or 24).
    """
    if supply_v <= forward_v:
        raise ValueError("supply_v must exceed the LED forward voltage")
    if current_ma <= 0:
        raise ValueError("current_ma must be positive")
    current_a = current_ma / 1000.0
    ideal = (supply_v - forward_v) / current_a
    chosen = e_series_ceil(ideal, series)
    actual_current = (supply_v - forward_v) / chosen
    power = (supply_v - forward_v) * actual_current
    return LedResistor(
        ideal_ohms=_sig(ideal),
        chosen_ohms=chosen,
        actual_current_a=_sig(actual_current),
        resistor_power_w=_sig(power),
        series=series,
    )


# ---------------------------------------------------------------------------
# Resistive voltage divider
# ---------------------------------------------------------------------------


def divider_output_v(input_v: float, r_top: float, r_bottom: float) -> float:
    """Output of an unloaded resistive divider: Vin * Rb / (Rt + Rb)."""
    if r_top < 0 or r_bottom <= 0:
        raise ValueError("r_top must be >= 0 and r_bottom must be > 0")
    return _sig(input_v * r_bottom / (r_top + r_bottom))


@dataclass(frozen=True)
class Divider:
    r_top_ohms: float
    r_bottom_ohms: float
    actual_output_v: float
    series: int


def divider_for_output(
    input_v: float,
    output_v: float,
    r_bottom: float,
    *,
    series: int = 24,
) -> Divider:
    """Choose ``r_top`` (snapped to E-series) for a target divider output.

    ``r_bottom`` is treated as fixed; ``r_top = r_bottom * (Vin/Vout - 1)``.
    """
    if not 0 < output_v < input_v:
        raise ValueError("output_v must satisfy 0 < output_v < input_v")
    if r_bottom <= 0:
        raise ValueError("r_bottom must be positive")
    ideal_top = r_bottom * (input_v / output_v - 1.0)
    chosen_top = nearest_e_series(ideal_top, series)
    return Divider(
        r_top_ohms=chosen_top,
        r_bottom_ohms=r_bottom,
        actual_output_v=divider_output_v(input_v, chosen_top, r_bottom),
        series=series,
    )


# ---------------------------------------------------------------------------
# RC first-order filter
# ---------------------------------------------------------------------------


def rc_cutoff_hz(r_ohms: float, c_farads: float) -> float:
    """-3 dB cutoff of a first-order RC filter: 1 / (2*pi*R*C)."""
    if r_ohms <= 0 or c_farads <= 0:
        raise ValueError("r_ohms and c_farads must be positive")
    return _sig(1.0 / (2.0 * math.pi * r_ohms * c_farads))


def rc_resistor_for_cutoff(cutoff_hz: float, c_farads: float, *, series: int = 24) -> float:
    """E-series resistor giving the closest cutoff for a fixed capacitor."""
    if cutoff_hz <= 0 or c_farads <= 0:
        raise ValueError("cutoff_hz and c_farads must be positive")
    ideal = 1.0 / (2.0 * math.pi * cutoff_hz * c_farads)
    return nearest_e_series(ideal, series)


# ---------------------------------------------------------------------------
# I2C pull-up sizing (NXP UM10204)
# ---------------------------------------------------------------------------

# Maximum bus rise time per I2C mode (seconds).
_I2C_RISE_TIME_S = {100_000: 1000e-9, 400_000: 300e-9, 1_000_000: 120e-9}
_I2C_VOL_MAX_V = 0.4  # output-low voltage at the sink current
_I2C_IOL_A = 3e-3  # standard 3 mA sink current


@dataclass(frozen=True)
class I2cPullup:
    min_ohms: float
    max_ohms: float
    recommended_ohms: float
    bus_speed_hz: int


def i2c_pullup(
    supply_v: float,
    bus_capacitance_pf: float,
    *,
    bus_speed_hz: int = 100_000,
    series: int = 24,
) -> I2cPullup:
    """Compute the valid I2C pull-up range and a recommended E-series value.

    - ``Rp_min = (Vdd - Vol_max) / Iol`` (the bus must still pull low).
    - ``Rp_max = t_r / (0.8473 * Cb)`` (the bus must rise within ``t_r``).

    The recommendation is the largest E-series value at or below ``Rp_max``
    that is also at least ``Rp_min`` — larger pull-ups save power while still
    meeting the rise-time budget.
    """
    if bus_speed_hz not in _I2C_RISE_TIME_S:
        raise ValueError(f"Unsupported I2C speed {bus_speed_hz} Hz; choose {sorted(_I2C_RISE_TIME_S)}")
    if supply_v <= _I2C_VOL_MAX_V:
        raise ValueError("supply_v must exceed the I2C Vol_max (0.4 V)")
    if bus_capacitance_pf <= 0:
        raise ValueError("bus_capacitance_pf must be positive")
    rise_time = _I2C_RISE_TIME_S[bus_speed_hz]
    cb_farads = bus_capacitance_pf * 1e-12
    r_min = (supply_v - _I2C_VOL_MAX_V) / _I2C_IOL_A
    r_max = rise_time / (0.8473 * cb_farads)
    if r_max < r_min:
        raise ValueError(f"No valid pull-up: bus capacitance ({bus_capacitance_pf} pF) too high for {bus_speed_hz} Hz")
    recommended = e_series_floor(r_max, series)
    if recommended < r_min:
        recommended = e_series_ceil(r_min, series)
    return I2cPullup(
        min_ohms=_sig(r_min),
        max_ohms=_sig(r_max),
        recommended_ohms=recommended,
        bus_speed_hz=bus_speed_hz,
    )


# ---------------------------------------------------------------------------
# USB-C CC (Configuration Channel) termination (USB Type-C spec R2.x §4.5.1)
# ---------------------------------------------------------------------------

# Sink (UFP) presents Rd = 5.1 kΩ ±20% from each CC pin to GND.
_USB_C_RD_OHMS = 5_100.0
# Source (DFP) presents Rp from each CC pin to a pull-up rail; the value
# advertises the current the source offers at 5 V (Type-C spec Table 4-25,
# Rp to VBUS column).
_USB_C_RP_OHMS: dict[str, float] = {
    "default": 56_000.0,  # USB default power (500 mA USB2 / 900 mA USB3)
    "1.5A": 22_000.0,  # 1.5 A @ 5 V
    "3.0A": 10_000.0,  # 3.0 A @ 5 V
}


@dataclass(frozen=True)
class UsbCCcTermination:
    role: str  # "sink" (UFP) or "source" (DFP)
    resistor: str  # "Rd" or "Rp"
    ohms: float
    connection: str  # where the resistor ties (e.g. "CC1/CC2 to GND")
    advertised_current_a: float | None  # source-advertised current, else None
    note: str


def usb_c_cc_termination(role: str, advertised_current_a: float | None = None) -> UsbCCcTermination:
    """Resolve the USB-C CC-pin termination resistor for a port role.

    A sink (UFP) presents ``Rd = 5.1 kΩ`` from each CC pin to GND. A source
    (DFP) presents ``Rp`` advertising the current it offers at 5 V — 56 kΩ for
    USB-default power, 22 kΩ for 1.5 A, 10 kΩ for 3.0 A. The same value goes on
    both CC1 and CC2 (one is CC, the other becomes VCONN when a cable is
    plugged). Values above 3.0 A require USB-PD negotiation, not a fixed Rp.

    Args:
        role: ``"sink"``/``"ufp"`` or ``"source"``/``"dfp"``.
        advertised_current_a: For a source, the current to advertise (defaults
            to USB-default power). Ignored for a sink.
    """
    normalized = role.strip().lower()
    if normalized in {"sink", "ufp"}:
        return UsbCCcTermination(
            role="sink",
            resistor="Rd",
            ohms=_USB_C_RD_OHMS,
            connection="CC1/CC2 to GND",
            advertised_current_a=None,
            note="UFP sink: Rd = 5.1 kΩ ±20% on each CC pin (USB-C spec §4.5.1)",
        )
    if normalized in {"source", "dfp"}:
        if advertised_current_a is None or advertised_current_a <= 0.9:
            tier, current = "default", advertised_current_a if advertised_current_a else None
        elif advertised_current_a <= 1.5:
            tier, current = "1.5A", 1.5
        elif advertised_current_a <= 3.0:
            tier, current = "3.0A", 3.0
        else:
            raise ValueError("currents above 3.0 A require USB-PD, not a fixed Rp")
        return UsbCCcTermination(
            role="source",
            resistor="Rp",
            ohms=_USB_C_RP_OHMS[tier],
            connection="CC1/CC2 to pull-up rail",
            advertised_current_a=current,
            note=f"DFP source: Rp = {_USB_C_RP_OHMS[tier] / 1000:g} kΩ advertises {tier} (USB-C Table 4-25)",
        )
    raise ValueError(f"role must be sink/ufp or source/dfp, got {role!r}")


# ---------------------------------------------------------------------------
# Decoupling / bypass capacitor planner
# ---------------------------------------------------------------------------

# Standard ceramic capacitor DC voltage ratings (volts).
_CAP_VOLTAGE_RATINGS = (6.3, 10.0, 16.0, 25.0, 50.0, 100.0)
# High-frequency decoupling cap placed at each power pin (farads -> 100 nF).
_DECOUPLE_PER_PIN_F = 100e-9
# Minimum bulk capacitance per rail (farads -> 10 uF) — standard practice.
_BULK_MIN_F = 10e-6


@dataclass(frozen=True)
class DecouplingPlan:
    per_pin_nf: float
    per_pin_count: int
    bulk_uf: float
    rail_v: float
    cap_voltage_rating_v: float
    note: str


def decoupling_plan(power_pins: int, rail_v: float, *, bulk_uf: float | None = None) -> DecouplingPlan:
    """Plan decoupling/bypass capacitors for an IC's power rail.

    Standard practice: one 100 nF high-frequency ceramic at each power pin
    (placed close to the pin) plus bulk capacitance on the rail. Ceramic X7R/X5R
    lose capacitance under DC bias, so the recommended voltage rating is derated
    to at least twice the rail voltage.

    Args:
        power_pins: Number of power pins to bypass (one 100 nF each).
        rail_v: The rail voltage feeding the pins.
        bulk_uf: Bulk capacitance to specify; defaults to 10 uF (the practical
            minimum). Values below 10 uF are raised to it.
    """
    if power_pins < 1:
        raise ValueError("power_pins must be >= 1")
    if rail_v <= 0:
        raise ValueError("rail_v must be positive")
    bulk_f = _BULK_MIN_F if bulk_uf is None else max(bulk_uf * 1e-6, _BULK_MIN_F)
    derated = 2.0 * rail_v
    rating = next((r for r in _CAP_VOLTAGE_RATINGS if r >= derated), None)
    if rating is None:
        raise ValueError(f"rail {rail_v} V exceeds the supported decoupling cap voltage range")
    return DecouplingPlan(
        per_pin_nf=_DECOUPLE_PER_PIN_F * 1e9,
        per_pin_count=power_pins,
        bulk_uf=_sig(bulk_f * 1e6),
        rail_v=rail_v,
        cap_voltage_rating_v=rating,
        note=(
            f"{power_pins}x 100 nF at the power pins + {_sig(bulk_f * 1e6):g} uF bulk on the "
            f"{rail_v:g} V rail; caps rated >= {rating:g} V (2x derate for ceramic DC bias)"
        ),
    )


# ---------------------------------------------------------------------------
# Li-ion / Li-Po linear charger programming (Microchip MCP73831/2)
# ---------------------------------------------------------------------------

# MCP73831 sets charge current via I_chg[mA] = 1000 / R_prog[kΩ], valid for
# R_prog 2 kΩ–10 kΩ (i.e. 500 mA down to 100 mA).
_MCP73831_K = 1000.0
_MCP73831_MIN_MA = 100.0
_MCP73831_MAX_MA = 500.0


@dataclass(frozen=True)
class LipoChargeResistor:
    ideal_kohms: float
    chosen_ohms: float
    target_current_ma: float
    actual_current_ma: float
    series: int
    note: str


def lipo_charge_resistor(charge_current_ma: float, *, series: int = 24) -> LipoChargeResistor:
    """Size the PROG resistor for an MCP73831/2 Li-ion/Li-Po linear charger.

    The charger regulates charge current to ``I_chg = 1000 / R_prog`` (mA, kΩ).
    A safe charge current is typically ≤ 0.5–1C of the cell capacity, so for a
    1000 mAh cell pick ~500 mA. The resistance is rounded *up* to the next
    E-series value so the actual current never exceeds the target.

    Args:
        charge_current_ma: Target charge current (100–500 mA for the MCP73831).
        series: E-series to snap the resistor onto (12 or 24).
    """
    if not _MCP73831_MIN_MA <= charge_current_ma <= _MCP73831_MAX_MA:
        raise ValueError(f"charge_current_ma must be within {_MCP73831_MIN_MA}-{_MCP73831_MAX_MA} mA for the MCP73831")
    ideal_kohm = _MCP73831_K / charge_current_ma
    chosen = e_series_ceil(ideal_kohm * 1000.0, series)  # round R up -> current at/under target
    actual = _MCP73831_K / (chosen / 1000.0)
    return LipoChargeResistor(
        ideal_kohms=_sig(ideal_kohm),
        chosen_ohms=chosen,
        target_current_ma=charge_current_ma,
        actual_current_ma=_sig(actual),
        series=series,
        note=(
            f"MCP73831 PROG = {chosen:g} Ω -> {_sig(actual):g} mA charge "
            f"(I_chg = 1000 / R_prog[kΩ]); keep <= ~1C of the cell capacity"
        ),
    )


# ---------------------------------------------------------------------------
# Buck (step-down) converter inductor + output capacitor
# ---------------------------------------------------------------------------

# Default peak-to-peak inductor ripple as a fraction of output current (30% is
# the usual starting point) and default output ripple as a fraction of Vout.
_BUCK_RIPPLE_RATIO = 0.3
_BUCK_OUTPUT_RIPPLE_FRACTION = 0.01


@dataclass(frozen=True)
class BuckLcResult:
    duty_cycle: float
    ripple_current_a: float
    peak_inductor_current_a: float
    inductor_uh: float
    inductor_chosen_uh: float
    output_cap_uf: float
    output_cap_chosen_uf: float
    note: str


def buck_inductor_capacitor(
    vin: float,
    vout: float,
    iout: float,
    f_sw_hz: float,
    *,
    ripple_ratio: float = _BUCK_RIPPLE_RATIO,
    output_ripple_v: float | None = None,
    series: int = 12,
) -> BuckLcResult:
    """Size the inductor and output capacitor for a synchronous buck converter.

    Continuous-conduction-mode equations:
    - ``L = Vout * (Vin - Vout) / (Vin * f_sw * ΔIL)`` with ``ΔIL = ripple_ratio * Iout``
    - ``Cout = ΔIL / (8 * f_sw * ΔVout)``

    The inductor snaps to the nearest E-series value (ripple is a soft target);
    the output capacitor rounds *up* so the output ripple stays at or under
    ``ΔVout`` (default 1 % of Vout).

    Args:
        vin: Input voltage (must exceed ``vout``).
        vout: Output voltage.
        iout: Maximum load current.
        f_sw_hz: Switching frequency.
        ripple_ratio: Inductor ripple current as a fraction of ``iout``.
        output_ripple_v: Allowed output ripple; defaults to 1 % of ``vout``.
        series: E-series for the snapped component values.
    """
    if not 0 < vout < vin:
        raise ValueError("require 0 < vout < vin")
    if iout <= 0 or f_sw_hz <= 0:
        raise ValueError("iout and f_sw_hz must be positive")
    if not 0 < ripple_ratio <= 1:
        raise ValueError("ripple_ratio must be in (0, 1]")
    delta_il = ripple_ratio * iout
    delta_vout = output_ripple_v if output_ripple_v is not None else _BUCK_OUTPUT_RIPPLE_FRACTION * vout
    if delta_vout <= 0:
        raise ValueError("output_ripple_v must be positive")
    inductance_h = vout * (vin - vout) / (vin * f_sw_hz * delta_il)
    capacitance_f = delta_il / (8.0 * f_sw_hz * delta_vout)
    inductor_uh = inductance_h * 1e6
    cap_uf = capacitance_f * 1e6
    chosen_l = nearest_e_series(inductor_uh, series)
    chosen_c = e_series_ceil(cap_uf, series)
    return BuckLcResult(
        duty_cycle=_sig(vout / vin),
        ripple_current_a=_sig(delta_il),
        peak_inductor_current_a=_sig(iout + delta_il / 2.0),
        inductor_uh=_sig(inductor_uh),
        inductor_chosen_uh=chosen_l,
        output_cap_uf=_sig(cap_uf),
        output_cap_chosen_uf=chosen_c,
        note=(
            f"buck {vin:g}->{vout:g} V @ {iout:g} A, {f_sw_hz / 1000:g} kHz: "
            f"L ~ {chosen_l:g} uH, Cout >= {chosen_c:g} uF ({ripple_ratio * 100:g}% ripple)"
        ),
    )


# ---------------------------------------------------------------------------
# Pull-up / pull-down resistor sizing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PullResistorResult:
    direction: str
    rail_v: float
    logic_v_high: float
    logic_v_low: float
    max_sink_current_ma: float
    resistor_ohms: float
    resistor_chosen_ohms: float
    note: str


def pull_resistor(
    rail_v: float,
    *,
    direction: str = "up",
    logic_threshold_v: float | None = None,
    max_sink_current_ma: float = 0.5,
    series: int = 24,
) -> PullResistorResult:
    """Size a pull-up or pull-down resistor for a digital logic signal.

    The resistor is sized so that:
    - The quiescent current through the resistor stays at or under
      ``max_sink_current_ma`` when the signal is actively driven to the
      opposite rail (worst-case DC load).
    - For a pull-up, ``logic_threshold_v`` is the minimum high level the
      receiver requires; default is 70 % of ``rail_v``.
    - For a pull-down, ``logic_threshold_v`` is the maximum low level; default
      is 30 % of ``rail_v``.

    Args:
        rail_v: The pull rail voltage (VCC for pull-up, GND = 0 for pull-down).
        direction: ``"up"`` or ``"down"``.
        logic_threshold_v: Desired logic level threshold. Defaults to 70 % of
            ``rail_v`` for pull-up and 30 % for pull-down.
        max_sink_current_ma: Maximum acceptable quiescent current in mA when
            the signal is actively driven against the pull resistor.
        series: E-series for snapping to a standard value (default E24).
    """
    if direction not in ("up", "down"):
        raise ValueError("direction must be 'up' or 'down'")
    if rail_v <= 0:
        raise ValueError("rail_v must be positive")
    if max_sink_current_ma <= 0:
        raise ValueError("max_sink_current_ma must be positive")

    if direction == "up":
        v_driven_low = 0.0
        threshold = logic_threshold_v if logic_threshold_v is not None else 0.7 * rail_v
        voltage_across_r = rail_v - v_driven_low
    else:
        v_driven_high = rail_v
        threshold = logic_threshold_v if logic_threshold_v is not None else 0.3 * rail_v
        voltage_across_r = v_driven_high

    r_min = voltage_across_r / (max_sink_current_ma / 1000.0)
    chosen = e_series_ceil(r_min / 1000.0, series) * 1000.0  # work in kΩ then back

    direction_label = "pull-up" if direction == "up" else "pull-down"
    note = (
        f"{direction_label} {rail_v:g} V rail: R = {chosen / 1000:g} kΩ "
        f"(quiescent ≤ {max_sink_current_ma:g} mA, "
        f"threshold {'≥' if direction == 'up' else '≤'} {threshold:g} V)"
    )
    return PullResistorResult(
        direction=direction,
        rail_v=rail_v,
        logic_v_high=rail_v if direction == "up" else rail_v - chosen * max_sink_current_ma / 1000.0,
        logic_v_low=chosen * max_sink_current_ma / 1000.0 if direction == "up" else 0.0,
        max_sink_current_ma=max_sink_current_ma,
        resistor_ohms=_sig(r_min),
        resistor_chosen_ohms=chosen,
        note=note,
    )


# ---------------------------------------------------------------------------
# Boot / reset strap planner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrapPin:
    signal_name: str
    default_state: str
    resistor_kohms: float
    rail: str
    rationale: str


@dataclass(frozen=True)
class BootResetStrapPlan:
    mcu_family: str
    strap_pins: list[StrapPin]
    note: str


_MCU_STRAP_TABLE: dict[str, list[dict[str, object]]] = {
    "stm32": [
        {
            "signal_name": "BOOT0",
            "default_state": "low",
            "resistor_kohms": 10.0,
            "rail": "GND",
            "rationale": "BOOT0=0 selects flash boot; pull low to avoid accidental DFU mode at power-up",
        },
        {
            "signal_name": "NRST",
            "default_state": "high",
            "resistor_kohms": 10.0,
            "rail": "VDD",
            "rationale": "NRST is open-drain with internal weak pull-up; external 10k ensures fast release",
        },
    ],
    "esp32": [
        {
            "signal_name": "EN",
            "default_state": "high",
            "resistor_kohms": 10.0,
            "rail": "VDD",
            "rationale": "EN must be pulled high for normal operation; 10k limits reset button current",
        },
        {
            "signal_name": "IO0",
            "default_state": "high",
            "resistor_kohms": 10.0,
            "rail": "VDD",
            "rationale": "IO0=1 at power-up selects SPI flash boot; pull low via button for programming mode",
        },
    ],
    "rp2040": [
        {
            "signal_name": "RUN",
            "default_state": "high",
            "resistor_kohms": 10.0,
            "rail": "IOVDD",
            "rationale": "RUN pulled high for normal operation; connect reset button to GND through this resistor",
        },
    ],
    "nrf52": [
        {
            "signal_name": "RESET",
            "default_state": "high",
            "resistor_kohms": 10.0,
            "rail": "VDD",
            "rationale": "RESET is active-low; pull high so the device does not stay in reset",
        },
    ],
    "generic": [
        {
            "signal_name": "RESET",
            "default_state": "high",
            "resistor_kohms": 10.0,
            "rail": "VDD",
            "rationale": "Generic active-low reset; pull high so the device starts normally at power-up",
        },
    ],
}


# ---------------------------------------------------------------------------
# Boost (step-up) converter inductor + output capacitor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoostLcResult:
    duty_cycle: float
    ripple_current_a: float
    peak_inductor_current_a: float
    inductor_uh: float
    inductor_chosen_uh: float
    output_cap_uf: float
    output_cap_chosen_uf: float
    note: str


def boost_inductor_capacitor(
    vin: float,
    vout: float,
    iout: float,
    f_sw_hz: float,
    *,
    ripple_ratio: float = 0.3,
    output_ripple_v: float | None = None,
    series: int = 12,
) -> BoostLcResult:
    """Size the inductor and output capacitor for a non-synchronous boost converter.

    CCM equations (non-synchronous, ideal):
    - ``D = 1 - Vin/Vout``
    - ``L = Vin * D / (f_sw * ΔIL)``   where ``ΔIL = ripple_ratio * Iin_avg``
    - ``Cout = Iout * D / (f_sw * ΔVout)``

    Args:
        vin: Input voltage (must be less than ``vout``).
        vout: Output voltage.
        iout: Maximum load current (A).
        f_sw_hz: Switching frequency (Hz).
        ripple_ratio: Inductor ripple current as a fraction of average input current.
        output_ripple_v: Allowed output voltage ripple; defaults to 1 % of vout.
        series: E-series for the snapped values.
    """
    if not 0 < vin < vout:
        raise ValueError("require 0 < vin < vout for a boost converter")
    if iout <= 0 or f_sw_hz <= 0:
        raise ValueError("iout and f_sw_hz must be positive")
    if not 0 < ripple_ratio <= 1:
        raise ValueError("ripple_ratio must be in (0, 1]")
    duty = 1.0 - vin / vout
    # Average input current = Iout / (1-D) = Iout * Vout / Vin
    iin_avg = iout * vout / vin
    delta_il = ripple_ratio * iin_avg
    delta_vout = output_ripple_v if output_ripple_v is not None else 0.01 * vout
    if delta_vout <= 0:
        raise ValueError("output_ripple_v must be positive")
    inductance_h = vin * duty / (f_sw_hz * delta_il)
    capacitance_f = iout * duty / (f_sw_hz * delta_vout)
    inductor_uh = inductance_h * 1e6
    cap_uf = capacitance_f * 1e6
    chosen_l = nearest_e_series(inductor_uh, series)
    chosen_c = e_series_ceil(cap_uf, series)
    peak_il = iin_avg + delta_il / 2.0
    return BoostLcResult(
        duty_cycle=_sig(duty),
        ripple_current_a=_sig(delta_il),
        peak_inductor_current_a=_sig(peak_il),
        inductor_uh=_sig(inductor_uh),
        inductor_chosen_uh=chosen_l,
        output_cap_uf=_sig(cap_uf),
        output_cap_chosen_uf=chosen_c,
        note=(
            f"boost {vin:g}->{vout:g} V @ {iout:g} A load, {f_sw_hz / 1000:g} kHz: "
            f"D={_sig(duty):.2f}, L ~ {chosen_l:g} uH (IL_peak={_sig(peak_il):.2f} A), "
            f"Cout >= {chosen_c:g} uF"
        ),
    )


# ---------------------------------------------------------------------------
# LDO selection guide
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LdoSelectionResult:
    dropout_v: float
    min_vin_v: float
    power_dissipation_w: float
    max_ambient_c: float
    note: str


def ldo_selection(
    vin: float,
    vout: float,
    iout: float,
    *,
    ldo_dropout_v: float = 0.3,
    theta_ja_c_per_w: float = 50.0,
    t_ambient_max_c: float = 85.0,
    t_junction_max_c: float = 125.0,
) -> LdoSelectionResult:
    """Guide LDO regulator selection for a given operating point.

    Checks that:
    1. Vin is high enough to keep the LDO out of dropout (Vin ≥ Vout + Vdrop).
    2. The power dissipation Pd = (Vin − Vout) × Iout fits within the thermal budget.
    3. The junction temperature Tj = Ta + Pd × θja stays below T_junction_max.

    Args:
        vin: Input voltage to the LDO (V).
        vout: Regulated output voltage (V).
        iout: Maximum load current (A).
        ldo_dropout_v: LDO dropout voltage at full load (V); default 0.3 V.
        theta_ja_c_per_w: Thermal resistance junction-to-ambient (°C/W).
        t_ambient_max_c: Maximum ambient temperature (°C).
        t_junction_max_c: Maximum junction temperature rating (°C).
    """
    if vin <= vout:
        raise ValueError("vin must exceed vout")
    if iout <= 0:
        raise ValueError("iout must be positive")
    min_vin = vout + ldo_dropout_v
    if vin < min_vin:
        raise ValueError(f"vin ({vin}V) is below the minimum ({min_vin}V = vout + dropout); LDO would be in dropout")
    pd = (vin - vout) * iout
    tj = t_ambient_max_c + pd * theta_ja_c_per_w
    # Maximum ambient temperature at which Tj stays below t_junction_max
    t_ambient_for_tj_max = t_junction_max_c - pd * theta_ja_c_per_w
    ok = tj <= t_junction_max_c
    note = (
        f"LDO {vin:g}→{vout:g} V @ {iout:g} A: "
        f"Pd={_sig(pd):.2f} W, Tj={_sig(tj):.1f}°C "
        f"({'OK' if ok else 'OVER — reduce Vin or add heatsink'}) "
        f"[θja={theta_ja_c_per_w:g}°C/W, Ta_max={t_ambient_max_c:g}°C]"
    )
    return LdoSelectionResult(
        dropout_v=ldo_dropout_v,
        min_vin_v=_sig(min_vin),
        power_dissipation_w=_sig(pd),
        max_ambient_c=_sig(t_ambient_for_tj_max),
        note=note,
    )


# ---------------------------------------------------------------------------
# MOSFET safe-operating-area (SOA) check
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MosfetSoaResult:
    vds_ok: bool
    id_ok: bool
    pd_ok: bool
    soa_ok: bool
    margin_vds: float
    margin_id: float
    margin_pd: float
    note: str


def mosfet_soa_check(
    vds_applied: float,
    id_applied: float,
    *,
    vds_max: float,
    id_max: float,
    pd_max_w: float,
    theta_ja_c_per_w: float = 50.0,
    t_ambient_c: float = 25.0,
    t_junction_max_c: float = 150.0,
    derating: float = 0.8,
) -> MosfetSoaResult:
    """Check that an N-channel MOSFET operating point stays within its SOA.

    Applies a *derating* factor (default 0.8 = 80 %) to all three limits
    (Vds, Id, Pd) so the device operates with margin — standard practice for
    reliable designs.

    Args:
        vds_applied: Drain-to-source voltage in the circuit (V).
        id_applied: Drain current at the operating point (A).
        vds_max: Datasheet Vds(max) (V).
        id_max: Datasheet Id(max) (A).
        pd_max_w: Datasheet Pd(max) at Tc=25°C (W).
        theta_ja_c_per_w: Thermal resistance junction-to-ambient (°C/W).
        t_ambient_c: Ambient temperature (°C).
        t_junction_max_c: Datasheet Tj(max) (°C).
        derating: Derating factor (0–1).
    """
    if not 0 < derating <= 1:
        raise ValueError("derating must be in (0, 1]")
    if theta_ja_c_per_w <= 0:
        raise ValueError("theta_ja_c_per_w must be positive")
    derated_vds = vds_max * derating
    derated_id = id_max * derating
    thermal_pd_max_w = max(0.0, (t_junction_max_c - t_ambient_c) / theta_ja_c_per_w)
    effective_pd_max_w = min(pd_max_w, thermal_pd_max_w)
    derated_pd = effective_pd_max_w * derating
    pd_applied = vds_applied * id_applied
    estimated_junction_c = t_ambient_c + pd_applied * theta_ja_c_per_w
    vds_ok = vds_applied <= derated_vds
    id_ok = id_applied <= derated_id
    pd_ok = pd_applied <= derated_pd
    soa_ok = vds_ok and id_ok and pd_ok
    margin_vds = _sig(derated_vds / vds_applied) if vds_applied > 0 else float("inf")
    margin_id = _sig(derated_id / id_applied) if id_applied > 0 else float("inf")
    margin_pd = _sig(derated_pd / pd_applied) if pd_applied > 0 else float("inf")
    status = "PASS" if soa_ok else "FAIL"
    note = (
        f"MOSFET SOA [{status}] Vds={vds_applied}V/{derated_vds}V derated, "
        f"Id={id_applied}A/{derated_id}A derated, "
        f"Pd={_sig(pd_applied):.2f}W/{_sig(derated_pd)}W derated "
        f"(datasheet={pd_max_w:g}W, thermal={_sig(thermal_pd_max_w)}W, "
        f"Tj_est={_sig(estimated_junction_c)}°C/{t_junction_max_c:g}°C; "
        f"margins: Vds×{margin_vds}, Id×{margin_id}, Pd×{margin_pd})"
    )
    return MosfetSoaResult(
        vds_ok=vds_ok,
        id_ok=id_ok,
        pd_ok=pd_ok,
        soa_ok=soa_ok,
        margin_vds=margin_vds,
        margin_id=margin_id,
        margin_pd=margin_pd,
        note=note,
    )


def boot_reset_strap_plan(mcu_family: str) -> BootResetStrapPlan:
    """Return the recommended boot/reset strap resistors for a given MCU family.

    The plan lists each strap pin, its required default state, the pull
    resistor value, which rail to pull to, and the datasheet rationale.

    Supports: ``"stm32"``, ``"esp32"``, ``"rp2040"``, ``"nrf52"``,
    ``"generic"`` (fallback reset only).

    Args:
        mcu_family: MCU family name (case-insensitive).
    """
    key = mcu_family.lower().strip()
    table = _MCU_STRAP_TABLE.get(key) or _MCU_STRAP_TABLE["generic"]
    straps = [StrapPin(**dict(entry)) for entry in table]  # type: ignore[arg-type]
    note = f"{mcu_family} boot/reset straps: {len(straps)} pin(s) — " + "; ".join(
        f"{s.signal_name}→{s.rail} ({s.default_state})" for s in straps
    )
    return BootResetStrapPlan(mcu_family=mcu_family, strap_pins=straps, note=note)
