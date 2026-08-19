"""Default routing parameters — trace widths, clearances, vias, and stackup presets.

All values in mm unless otherwise noted. These follow IPC-2221B and IPC-7351B
standards and are appropriate for standard FR-4 PCB fabrication.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Default trace widths per net class
# ---------------------------------------------------------------------------
DEFAULT_TRACE_WIDTHS: dict[str, float] = {
    "signal_low": 0.20,  # GPIO, I2C, UART, SPI <10MHz
    "signal_high": 0.25,  # >10MHz digital
    "signal_analog": 0.30,  # ADC, sensor, op-amp
    "power_low": 0.30,  # <100mA rails
    "power_med": 0.50,  # 100mA-500mA
    "power_high": 1.00,  # >500mA (should be calculated per IPC-2221)
    "ground": 0.50,  # Ground — flood preferred over traces
    "differential": 0.20,  # Differential pairs (e.g., USB, HDMI)
    "rf": 0.30,  # 50Ω impedance traces
}

# ---------------------------------------------------------------------------
# Clearance matrix: (class_a, class_b) → mm
# From IPC-2221B Table 6-1 (external conductors, <3050m altitude)
# ---------------------------------------------------------------------------
CLEARANCE_MATRIX: dict[tuple[str, str], float] = {
    ("signal", "signal"): 0.15,
    ("signal", "power"): 0.20,
    ("signal", "ground"): 0.15,
    ("signal", "high_voltage"): 0.30,
    ("power", "power"): 0.20,
    ("power", "ground"): 0.20,
    ("power", "high_voltage"): 0.40,
    ("ground", "ground"): 0.15,
    ("ground", "high_voltage"): 0.30,
    ("high_voltage", "high_voltage"): 0.60,
}

# ---------------------------------------------------------------------------
# Default via specifications
# ---------------------------------------------------------------------------
DEFAULT_VIA_SPECS: dict[str, float] = {
    "pad_diameter": 0.45,  # mm
    "hole_diameter": 0.20,  # mm
    "min_annular_ring": 0.13,
}

# ---------------------------------------------------------------------------
# Standard board stackup presets
# ---------------------------------------------------------------------------
STACKUP_PRESETS: dict[str, dict] = {
    "2layer_standard": {
        "name": "2layer_standard",
        "description": "Standard 2-layer PCB for simple IoT and breakout boards. 1.6mm FR-4, 1oz copper both sides.",
        "layers": 2,
        "total_thickness": 1.6,
        "layer_stack": [
            {"name": "F.Cu", "type": "signal", "thickness": 0.035, "material": "copper"},
            {"name": "B.Cu", "type": "signal", "thickness": 0.035, "material": "copper"},
        ],
        "core_thickness": 1.53,
        "constraints": {
            "min_trace": 0.15,
            "min_clearance": 0.15,
            "min_hole": 0.15,
            "min_annular_ring": 0.13,
            "via_pad": 0.45,
            "via_hole": 0.20,
        },
    },
    "4layer_standard": {
        "name": "4layer_standard",
        "description": "Standard 4-layer PCB. 1.6mm FR-4, 1oz outer, 0.5oz inner. "
        "Signal layers on outer, power/ground planes on inner.",
        "layers": 4,
        "total_thickness": 1.6,
        "layer_stack": [
            {"name": "F.Cu", "type": "signal", "thickness": 0.035, "material": "copper"},
            {"name": "In1.Cu", "type": "ground", "thickness": 0.018, "material": "copper"},
            {"name": "In2.Cu", "type": "power", "thickness": 0.018, "material": "copper"},
            {"name": "B.Cu", "type": "signal", "thickness": 0.035, "material": "copper"},
        ],
        "core_thickness": 1.53,
        "constraints": {
            "min_trace": 0.10,
            "min_clearance": 0.10,
            "min_hole": 0.15,
            "min_annular_ring": 0.13,
            "via_pad": 0.40,
            "via_hole": 0.20,
        },
    },
    "4layer_iot": {
        "name": "4layer_iot",
        "description": "4-layer optimized for IoT modules. Signal-GND-PWR-Signal stackup for EMI reduction.",
        "layers": 4,
        "total_thickness": 1.2,
        "layer_stack": [
            {"name": "F.Cu", "type": "signal", "thickness": 0.035, "material": "copper"},
            {"name": "GND.Cu", "type": "ground", "thickness": 0.035, "material": "copper"},
            {"name": "PWR.Cu", "type": "power", "thickness": 0.035, "material": "copper"},
            {"name": "B.Cu", "type": "signal", "thickness": 0.035, "material": "copper"},
        ],
        "core_thickness": 1.06,
        "constraints": {
            "min_trace": 0.10,
            "min_clearance": 0.10,
            "min_hole": 0.15,
            "min_annular_ring": 0.13,
            "via_pad": 0.40,
            "via_hole": 0.20,
        },
    },
}
