"""Calculators agent tool implementations."""

from __future__ import annotations

from .deps import (
    Any,
    asdict,
    buck_inductor_capacitor,
    decoupling_plan,
    divider_for_output,
    e_series_ceil,
    e_series_floor,
    i2c_pullup,
    led_series_resistor,
    lipo_charge_resistor,
    nearest_e_series,
    rc_cutoff_hz,
    usb_c_cc_termination,
)


def tool_calc_led_resistor(supply_v: float, forward_v: float, current_ma: float, series: int = 24) -> dict[str, Any]:
    """Size an LED current-limiting resistor (E-series; rounds up so current stays at/under target)."""
    return asdict(led_series_resistor(supply_v, forward_v, current_ma, series=series))


def tool_calc_voltage_divider(input_v: float, output_v: float, r_bottom: float, series: int = 24) -> dict[str, Any]:
    """Choose the top resistor of a divider for a target output voltage (E-series)."""
    return asdict(divider_for_output(input_v, output_v, r_bottom, series=series))


def tool_calc_rc_filter(r_ohms: float, c_farads: float) -> dict[str, Any]:
    """Compute the -3 dB cutoff frequency of a first-order RC filter."""
    return {"cutoff_hz": rc_cutoff_hz(r_ohms, c_farads), "r_ohms": r_ohms, "c_farads": c_farads}


def tool_calc_i2c_pullup(
    supply_v: float,
    bus_capacitance_pf: float,
    bus_speed_hz: int = 100_000,
    series: int = 24,
) -> dict[str, Any]:
    """Compute the I2C pull-up range and a recommended E-series value (NXP UM10204)."""
    return asdict(i2c_pullup(supply_v, bus_capacitance_pf, bus_speed_hz=bus_speed_hz, series=series))


def tool_calc_e_series(value: float, series: int = 24, mode: str = "nearest") -> dict[str, Any]:
    """Snap a value to an E-series preferred value. mode: nearest | ceil | floor."""
    funcs = {"nearest": nearest_e_series, "ceil": e_series_ceil, "floor": e_series_floor}
    if mode not in funcs:
        raise ValueError(f"mode must be one of {sorted(funcs)}")
    return {"value": funcs[mode](value, series), "series": series, "mode": mode}


def tool_calc_usb_c_cc(role: str, advertised_current_a: float | None = None) -> dict[str, Any]:
    """Resolve the USB-C CC-pin termination resistor for a port role (USB-C spec §4.5.1)."""
    return asdict(usb_c_cc_termination(role, advertised_current_a))


def tool_calc_decoupling(power_pins: int, rail_v: float, bulk_uf: float | None = None) -> dict[str, Any]:
    """Plan decoupling caps for a rail: 100 nF per power pin + bulk, with a derated voltage rating."""
    return asdict(decoupling_plan(power_pins, rail_v, bulk_uf=bulk_uf))


def tool_calc_lipo_charge(charge_current_ma: float, series: int = 24) -> dict[str, Any]:
    """Size the PROG resistor for an MCP73831/2 Li-ion/Li-Po charger from a target charge current."""
    return asdict(lipo_charge_resistor(charge_current_ma, series=series))


def tool_calc_buck_lc(
    vin: float,
    vout: float,
    iout: float,
    f_sw_hz: float,
    ripple_ratio: float = 0.3,
    output_ripple_v: float | None = None,
) -> dict[str, Any]:
    """Size a buck converter's inductor + output capacitor (CCM) from Vin/Vout/Iout/Fsw."""
    return asdict(
        buck_inductor_capacitor(vin, vout, iout, f_sw_hz, ripple_ratio=ripple_ratio, output_ripple_v=output_ripple_v)
    )


__all__ = [
    "tool_calc_led_resistor",
    "tool_calc_voltage_divider",
    "tool_calc_rc_filter",
    "tool_calc_i2c_pullup",
    "tool_calc_e_series",
    "tool_calc_usb_c_cc",
    "tool_calc_decoupling",
    "tool_calc_lipo_charge",
    "tool_calc_buck_lc",
]
