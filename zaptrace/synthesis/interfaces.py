"""High-speed interface signal-integrity profiles.

A small, datasheet-grounded registry of the impedance / termination / skew
constraints a high-speed interface needs, so an agent can apply the right
routing rules for USB, Ethernet, HDMI, PCIe, LVDS, CAN, DDR, etc. instead of
routing them as ordinary signals.

Impedances and termination in ohms, skew in mm.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class InterfaceProfile:
    name: str
    differential_impedance_ohms: float | None = None
    single_ended_impedance_ohms: float | None = None
    bus_termination_ohms: float | None = None
    intra_pair_skew_mm: float | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PROFILES: dict[str, InterfaceProfile] = {
    "usb2": InterfaceProfile(
        "usb2", differential_impedance_ohms=90.0, intra_pair_skew_mm=0.15, notes="USB 2.0 High-Speed, 90Ω ±15%"
    ),
    "usb3": InterfaceProfile(
        "usb3", differential_impedance_ohms=90.0, intra_pair_skew_mm=0.13, notes="USB 3.x SuperSpeed, 90Ω per lane"
    ),
    "ethernet-100": InterfaceProfile(
        "ethernet-100", differential_impedance_ohms=100.0, notes="100BASE-TX, 100Ω differential pairs"
    ),
    "ethernet-1000": InterfaceProfile(
        "ethernet-1000",
        differential_impedance_ohms=100.0,
        intra_pair_skew_mm=0.5,
        notes="1000BASE-T, 100Ω, length-matched pairs",
    ),
    "hdmi": InterfaceProfile(
        "hdmi", differential_impedance_ohms=100.0, intra_pair_skew_mm=0.15, notes="HDMI TMDS, 100Ω differential"
    ),
    "mipi-dphy": InterfaceProfile(
        "mipi-dphy", differential_impedance_ohms=100.0, intra_pair_skew_mm=0.1, notes="MIPI D-PHY, 100Ω"
    ),
    "lvds": InterfaceProfile(
        "lvds", differential_impedance_ohms=100.0, intra_pair_skew_mm=0.2, notes="LVDS, 100Ω differential"
    ),
    "pcie": InterfaceProfile(
        "pcie", differential_impedance_ohms=85.0, intra_pair_skew_mm=0.13, notes="PCI Express, 85Ω differential"
    ),
    "can": InterfaceProfile(
        "can", differential_impedance_ohms=120.0, bus_termination_ohms=120.0, notes="CAN bus, 120Ω line + termination"
    ),
    "ddr3": InterfaceProfile("ddr3", single_ended_impedance_ohms=40.0, notes="DDR3 data/address, ~40Ω single-ended"),
}


def list_interfaces() -> list[str]:
    """All known high-speed interface profile names."""
    return sorted(_PROFILES)


def get_interface_profile(name: str) -> InterfaceProfile:
    """Look up an interface profile by name (case-insensitive)."""
    key = name.lower().strip()
    if key not in _PROFILES:
        raise ValueError(f"Unknown interface '{name}'. Known: {list_interfaces()}")
    return _PROFILES[key]


# ---------------------------------------------------------------------------
# Via-stub resonance warning
# ---------------------------------------------------------------------------

# Speed of light in mm/ps (used to convert stub length to resonant frequency)
_C_MM_PER_PS = 0.299792458  # mm/ps
_DEFAULT_ER_PCB = 4.3  # FR-4 effective dielectric constant


@dataclass(frozen=True)
class ViaStubWarning:
    stub_length_mm: float
    resonant_freq_ghz: float
    interface: str
    max_data_rate_gbps: float | None
    risk: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _max_interface_data_rate(interface_key: str, profile: InterfaceProfile) -> float | None:
    if interface_key == "pcie":
        return 8.0
    if interface_key == "usb3" or "SuperSpeed" in profile.notes:
        return 10.0
    if interface_key == "usb2":
        return 0.48
    return None


def _via_stub_risk(resonant_freq_ghz: float, max_data_rate_gbps: float | None) -> str:
    if max_data_rate_gbps is None:
        return "unknown"
    nyquist_ghz = max_data_rate_gbps / 2.0
    if resonant_freq_ghz < nyquist_ghz:
        return "high"
    if resonant_freq_ghz < nyquist_ghz * 2:
        return "medium"
    return "low"


def _via_stub_note(
    interface_name: str,
    stub_mm: float,
    resonant_freq_ghz: float,
    risk: str,
    backdrilled_depth_mm: float,
) -> str:
    backdrill = (
        "No backdrilling applied." if backdrilled_depth_mm == 0 else f"Backdrilled {backdrilled_depth_mm:.2f} mm."
    )
    return (
        f"{interface_name.upper()} via stub {stub_mm:.2f} mm → resonance at {resonant_freq_ghz:.2f} GHz "
        f"(risk={risk}). {backdrill} Consider backdrilling or HDI micro-vias to eliminate stub."
    )


def via_stub_resonance(
    via_length_mm: float,
    backdrilled_depth_mm: float,
    interface_name: str,
    *,
    er: float = _DEFAULT_ER_PCB,
) -> ViaStubWarning:
    """Estimate the resonant frequency of a via stub and flag if it threatens the interface.

    A via stub is the portion of a through-hole via below the signal breakout
    point. It acts as a shorted transmission-line stub, with a resonant null
    at ``f = c / (4 * L_stub * sqrt(er))``. Signal energy near the resonant
    frequency is absorbed, causing insertion loss and eye-closure.

    Args:
        via_length_mm: Total drilled length of the via (board thickness for a
            through-hole via).
        backdrilled_depth_mm: How far the stub has been backdrilled (removed);
            0 = no backdrilling.
        interface_name: Interface name to look up max data rate (e.g. ``"pcie"``).
        er: Effective dielectric constant of the via fill material (default FR-4).
    """
    if via_length_mm <= 0:
        raise ValueError("via_length_mm must be positive")
    if backdrilled_depth_mm < 0 or backdrilled_depth_mm >= via_length_mm:
        raise ValueError("backdrilled_depth_mm must be in [0, via_length_mm)")
    stub_mm = via_length_mm - backdrilled_depth_mm
    # Quarter-wave resonant frequency: f = c / (4 * L * sqrt(er))
    # c in mm/ps → result in THz; multiply by 1e3 to get GHz.
    f_res_ghz = _C_MM_PER_PS * 1e3 / (4.0 * stub_mm * math.sqrt(er))

    interface_key = interface_name.lower().strip()
    profile = _PROFILES.get(interface_key)
    if profile is None:
        raise ValueError(f"Unknown interface '{interface_name}'. Known: {list_interfaces()}")

    max_dr = _max_interface_data_rate(interface_key, profile)
    risk = _via_stub_risk(f_res_ghz, max_dr)
    note = _via_stub_note(interface_name, stub_mm, f_res_ghz, risk, backdrilled_depth_mm)
    return ViaStubWarning(
        stub_length_mm=round(stub_mm, 4),
        resonant_freq_ghz=round(f_res_ghz, 4),
        interface=interface_name,
        max_data_rate_gbps=max_dr,
        risk=risk,
        note=note,
    )


# ---------------------------------------------------------------------------
# BGA breakout rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BgaBreakoutRule:
    """Breakout routing guidance for a BGA package."""

    pitch_mm: float
    max_trace_width_mm: float
    recommended_via_drill_mm: float
    recommended_via_pad_mm: float
    max_breakout_length_mm: float
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Standard BGA breakout rules keyed by pitch (mm).
# Values derived from IPC-7351, IPC-2226 and board-house DFM guidelines.
_BGA_BREAKOUT_RULES: dict[float, BgaBreakoutRule] = {
    1.0: BgaBreakoutRule(
        pitch_mm=1.0,
        max_trace_width_mm=0.1,
        recommended_via_drill_mm=0.2,
        recommended_via_pad_mm=0.4,
        max_breakout_length_mm=0.5,
        note="1.0 mm pitch BGA: dogleg escapes, via-in-pad or adjacent via rows allowed",
    ),
    0.8: BgaBreakoutRule(
        pitch_mm=0.8,
        max_trace_width_mm=0.08,
        recommended_via_drill_mm=0.15,
        recommended_via_pad_mm=0.3,
        max_breakout_length_mm=0.3,
        note="0.8 mm pitch BGA: micro-via or NSMD pad with tented via recommended",
    ),
    0.65: BgaBreakoutRule(
        pitch_mm=0.65,
        max_trace_width_mm=0.075,
        recommended_via_drill_mm=0.1,
        recommended_via_pad_mm=0.25,
        max_breakout_length_mm=0.25,
        note="0.65 mm pitch BGA: HDI micro-via (≤ 100 µm drill) required; check fab capability",
    ),
    0.5: BgaBreakoutRule(
        pitch_mm=0.5,
        max_trace_width_mm=0.05,
        recommended_via_drill_mm=0.075,
        recommended_via_pad_mm=0.175,
        max_breakout_length_mm=0.15,
        note="0.5 mm pitch BGA: advanced HDI / laser micro-via only; consult fab early",
    ),
}


def bga_breakout_rules(pitch_mm: float) -> BgaBreakoutRule:
    """Return BGA breakout routing rules for the given ball pitch (mm).

    Looks up the nearest *equal or smaller* pitch entry. Raises ``ValueError``
    if the pitch is smaller than the smallest known entry.

    Args:
        pitch_mm: BGA ball pitch in mm.
    """
    if pitch_mm <= 0:
        raise ValueError("pitch_mm must be positive")
    # Find the largest key that is <= pitch_mm
    candidates = [p for p in sorted(_BGA_BREAKOUT_RULES) if p <= pitch_mm]
    if not candidates:
        raise ValueError(f"No breakout rule for pitch {pitch_mm} mm (smallest known: {min(_BGA_BREAKOUT_RULES)} mm)")
    return _BGA_BREAKOUT_RULES[candidates[-1]]
