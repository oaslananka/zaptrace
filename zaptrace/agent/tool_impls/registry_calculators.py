"""Declarative calculators tool registry fragment."""

# ruff: noqa: E501

from __future__ import annotations

from .calculators import (
    tool_calc_buck_lc,
    tool_calc_decoupling,
    tool_calc_e_series,
    tool_calc_i2c_pullup,
    tool_calc_led_resistor,
    tool_calc_lipo_charge,
    tool_calc_rc_filter,
    tool_calc_usb_c_cc,
    tool_calc_voltage_divider,
)
from .registry_shared import (
    _E_SERIES_DESCRIPTION,
)

CALCULATORS_REGISTRY: dict[str, dict[str, object]] = {
    "calc_led_resistor": {
        "name": "calc_led_resistor",
        "description": "Size an LED current-limiting resistor (E-series; current stays at/under target)",
        "fn": tool_calc_led_resistor,
        "params": {
            "supply_v": {"type": "number", "description": "Supply voltage driving the LED + resistor"},
            "forward_v": {"type": "number", "description": "LED forward voltage (Vf)"},
            "current_ma": {"type": "number", "description": "Target forward current in mA"},
            "series": {"type": "integer", "description": _E_SERIES_DESCRIPTION},
        },
    },
    "calc_voltage_divider": {
        "name": "calc_voltage_divider",
        "description": "Choose a divider top resistor for a target output voltage (E-series)",
        "fn": tool_calc_voltage_divider,
        "params": {
            "input_v": {"type": "number", "description": "Divider input voltage"},
            "output_v": {"type": "number", "description": "Target output voltage"},
            "r_bottom": {"type": "number", "description": "Fixed bottom resistor in ohms"},
            "series": {"type": "integer", "description": _E_SERIES_DESCRIPTION},
        },
    },
    "calc_rc_filter": {
        "name": "calc_rc_filter",
        "description": "Compute the -3 dB cutoff frequency of a first-order RC filter",
        "fn": tool_calc_rc_filter,
        "params": {
            "r_ohms": {"type": "number", "description": "Resistance in ohms"},
            "c_farads": {"type": "number", "description": "Capacitance in farads"},
        },
    },
    "calc_i2c_pullup": {
        "name": "calc_i2c_pullup",
        "description": "Compute I2C pull-up range and a recommended value (NXP UM10204)",
        "fn": tool_calc_i2c_pullup,
        "params": {
            "supply_v": {"type": "number", "description": "Bus supply voltage (Vdd)"},
            "bus_capacitance_pf": {"type": "number", "description": "Total bus capacitance in pF"},
            "bus_speed_hz": {"type": "integer", "description": "Bus speed: 100000, 400000, or 1000000"},
            "series": {"type": "integer", "description": _E_SERIES_DESCRIPTION},
        },
    },
    "calc_e_series": {
        "name": "calc_e_series",
        "description": "Snap a value to an E-series preferred value (mode: nearest|ceil|floor)",
        "fn": tool_calc_e_series,
        "params": {
            "value": {"type": "number", "description": "Value to snap"},
            "series": {"type": "integer", "description": "E-series (12 or 24)"},
            "mode": {"type": "string", "description": "nearest | ceil | floor"},
        },
    },
    "calc_usb_c_cc": {
        "name": "calc_usb_c_cc",
        "description": "Resolve the USB-C CC-pin termination resistor for a port role (USB-C spec)",
        "fn": tool_calc_usb_c_cc,
        "params": {
            "role": {"type": "string", "description": "Port role: sink/ufp or source/dfp"},
            "advertised_current_a": {
                "type": "number",
                "description": "For a source, current to advertise at 5V (default USB power if omitted)",
            },
        },
    },
    "calc_decoupling": {
        "name": "calc_decoupling",
        "description": "Plan decoupling/bypass caps for a rail (100 nF per power pin + bulk, derated rating)",
        "fn": tool_calc_decoupling,
        "params": {
            "power_pins": {"type": "integer", "description": "Number of power pins to bypass"},
            "rail_v": {"type": "number", "description": "Rail voltage feeding the pins"},
            "bulk_uf": {"type": "number", "description": "Bulk capacitance in uF (default 10)"},
        },
    },
    "calc_lipo_charge": {
        "name": "calc_lipo_charge",
        "description": "Size the MCP73831/2 PROG resistor for a Li-ion/Li-Po charge current",
        "fn": tool_calc_lipo_charge,
        "params": {
            "charge_current_ma": {"type": "number", "description": "Target charge current in mA (100-500)"},
            "series": {"type": "integer", "description": "E-series to snap onto (12 or 24)"},
        },
    },
    "calc_buck_lc": {
        "name": "calc_buck_lc",
        "description": "Size a buck converter's inductor + output capacitor (CCM) from Vin/Vout/Iout/Fsw",
        "fn": tool_calc_buck_lc,
        "params": {
            "vin": {"type": "number", "description": "Input voltage"},
            "vout": {"type": "number", "description": "Output voltage (< vin)"},
            "iout": {"type": "number", "description": "Maximum load current (A)"},
            "f_sw_hz": {"type": "number", "description": "Switching frequency (Hz)"},
            "ripple_ratio": {"type": "number", "description": "Inductor ripple as fraction of Iout (default 0.3)"},
            "output_ripple_v": {"type": "number", "description": "Allowed output ripple V (default 1% of Vout)"},
        },
    },
}

__all__ = ["CALCULATORS_REGISTRY"]
