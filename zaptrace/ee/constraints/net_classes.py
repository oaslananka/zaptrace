"""Net class definitions and per-class routing rules."""

from __future__ import annotations

from dataclasses import dataclass

from zaptrace.core.models import NetClass


@dataclass
class NetClassRule:
    """Routing rules for a single net class.

    All dimensions in millimeters.
    """

    trace_width: float
    """Default trace width for this class."""

    clearance: float
    """Minimum clearance to other nets/copper."""

    max_vias: int
    """Maximum number of vias allowed per trace."""

    priority: int
    """Routing priority (lower = more important, routed first)."""

    description: str = ""
    """Human-readable description."""

    diff_pair_gap: float | None = None
    """Gap between traces in a differential pair (if applicable)."""

    max_parallel_length: float | None = None
    """Maximum parallel run length before separation rule applies."""

    impedance: float | None = None
    """Target impedance for controlled impedance nets (e.g., 50 for single-ended, 90 for diff pair)."""


# ---------------------------------------------------------------------------
# Default rules for each net class
# ---------------------------------------------------------------------------
CLASS_RULES: dict[NetClass, NetClassRule] = {
    NetClass.SIGNAL_LOW: NetClassRule(
        trace_width=0.20,
        clearance=0.15,
        max_vias=2,
        priority=5,
        description="GPIO, I2C, UART, SPI <10MHz — standard routing",
    ),
    NetClass.SIGNAL_HIGH: NetClassRule(
        trace_width=0.25,
        clearance=0.20,
        max_vias=2,
        priority=4,
        description=">10MHz digital — tighter clearance, impedance awareness",
    ),
    NetClass.SIGNAL_ANALOG: NetClassRule(
        trace_width=0.30,
        clearance=0.25,
        max_vias=1,
        priority=3,
        description="Analog signals — shielding, no vias under sensitive paths",
    ),
    NetClass.POWER_LOW: NetClassRule(
        trace_width=0.30,
        clearance=0.20,
        max_vias=4,
        priority=2,
        description="<100mA power — standard width",
    ),
    NetClass.POWER_MED: NetClassRule(
        trace_width=0.50,
        clearance=0.20,
        max_vias=4,
        priority=2,
        description="100–500mA power — medium width",
    ),
    NetClass.POWER_HIGH: NetClassRule(
        trace_width=1.00,
        clearance=0.30,
        max_vias=8,
        priority=1,
        description=">500mA power — width per IPC-2221, thermal relief",
    ),
    NetClass.GROUND: NetClassRule(
        trace_width=0.50,
        clearance=0.15,
        max_vias=99,
        priority=0,
        description="Ground — copper pour flood preferred",
    ),
    NetClass.DIFFERENTIAL: NetClassRule(
        trace_width=0.20,
        clearance=0.15,
        max_vias=0,
        priority=3,
        description="Differential pair (USB, HDMI) — length matched, coupled",
        diff_pair_gap=0.40,
        max_parallel_length=50.0,
    ),
    NetClass.RF: NetClassRule(
        trace_width=0.30,
        clearance=0.30,
        max_vias=0,
        priority=3,
        description="50Ω RF — impedance controlled, no vias in signal path",
    ),
}
