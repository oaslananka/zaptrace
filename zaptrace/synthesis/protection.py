"""Connector ESD and protection policy generator.

Returns datasheet-grounded ESD protection recommendations for common connector
types so an agent can automatically insert the right protection topology.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EsdPolicy:
    """ESD / protection recommendation for a connector type."""

    connector_type: str
    protection_topology: str
    recommended_parts: list[str]
    clamping_voltage_v: float | None
    max_data_rate_mbps: float | None
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_POLICIES: dict[str, EsdPolicy] = {
    "usb2": EsdPolicy(
        connector_type="usb2",
        protection_topology="TVS diode array on D+/D− to GND and VBus",
        recommended_parts=["USBLC6-2SC6", "TPD2E001", "SP0503BAHT"],
        clamping_voltage_v=5.5,
        max_data_rate_mbps=480.0,
        notes=(
            "Place ESD diode array within 500 mil of the USB connector. "
            "Keep D+/D− trace stubs short. Ferrite bead + bulk cap on VBus."
        ),
    ),
    "usb3": EsdPolicy(
        connector_type="usb3",
        protection_topology="Low-capacitance TVS array on SuperSpeed pairs + D+/D−",
        recommended_parts=["PRTR5V0U2X", "TPD6E002", "CDSOT23-SM712"],
        clamping_voltage_v=5.5,
        max_data_rate_mbps=10000.0,
        notes=("Use parts with <0.3 pF line capacitance for SuperSpeed. Separate protection on legacy USB 2.0 lines."),
    ),
    "ethernet": EsdPolicy(
        connector_type="ethernet",
        protection_topology="Common-mode choke + TVS on MDI pairs",
        recommended_parts=["SP3012-04JTG", "PRTR5V0U4X", "TPD4S012"],
        clamping_voltage_v=6.0,
        max_data_rate_mbps=1000.0,
        notes=("Place common-mode choke between PHY and magjack. TVS or rail-to-rail diode array after the choke."),
    ),
    "hdmi": EsdPolicy(
        connector_type="hdmi",
        protection_topology="Low-capacitance TVS array on TMDS pairs",
        recommended_parts=["HDMI02W6-P", "PRTR5V0U2X", "SP3004-04JTG"],
        clamping_voltage_v=5.5,
        max_data_rate_mbps=18000.0,
        notes=("Use parts with <0.2 pF per line. CEC and HPD lines can use higher-capacitance, lower-cost parts."),
    ),
    "rs232": EsdPolicy(
        connector_type="rs232",
        protection_topology="TVS diode array on TX/RX lines",
        recommended_parts=["SP3012", "PESD2RS232", "SMBJ12A"],
        clamping_voltage_v=15.0,
        max_data_rate_mbps=0.115,
        notes=(
            "RS-232 lines swing ±12 V. Use bidirectional TVS rated for ±15 V. "
            "A transient-surge TVS (e.g. SMBJ15CA) handles lightning-induced surges."
        ),
    ),
    "rs485": EsdPolicy(
        connector_type="rs485",
        protection_topology="Surge TVS + gas-discharge tube on A/B/GND",
        recommended_parts=["SP3060", "PESD2CAN", "SM712", "B72220S0301K101"],
        clamping_voltage_v=12.0,
        max_data_rate_mbps=40.0,
        notes=(
            "Industrial RS-485 installations require IEC 61000-4-5 surge immunity. "
            "GDT on the cable shield for lightning. Fail-safe biasing resistors (560 Ω) "
            "on A and B lines."
        ),
    ),
    "can": EsdPolicy(
        connector_type="can",
        protection_topology="Common-mode choke + TVS on CANH/CANL",
        recommended_parts=["PESD2CAN", "NUP2105L", "TCAN1042"],
        clamping_voltage_v=24.0,
        max_data_rate_mbps=1.0,
        notes=(
            "120 Ω termination at each end of the bus segment. "
            "CAN transceivers often include ±8 kV IEC ESD; add external TVS for "
            "exposed connectors in automotive or industrial environments."
        ),
    ),
    "gpio": EsdPolicy(
        connector_type="gpio",
        protection_topology="Series resistor + clamping diode to VCC and GND",
        recommended_parts=["BAV99", "PRTR5V0U2X", "ESD5B3.3ST1G"],
        clamping_voltage_v=3.6,
        max_data_rate_mbps=10.0,
        notes=(
            "33 Ω series resistor limits ESD current into IC. "
            "Schottky rail clamp keeps the signal within the device's abs-max. "
            "Use rail-to-rail TVS when the GPIO is accessible to the user."
        ),
    ),
    "power": EsdPolicy(
        connector_type="power",
        protection_topology="TVS or Zener clamp + reverse-polarity protection MOSFET",
        recommended_parts=["P6KE5.1CA", "SMBJ5.0CA", "AO3401"],
        clamping_voltage_v=6.0,
        max_data_rate_mbps=None,
        notes=(
            "P-FET reverse-polarity protection (body-diode blocks reverse input). "
            "TVS across the output rail for transient suppression. "
            "Fuse or resettable polyfuse at the connector for overcurrent."
        ),
    ),
}


def list_connector_types() -> list[str]:
    """All connector types that have a defined ESD policy."""
    return sorted(_POLICIES)


def connector_esd_policy(connector_type: str) -> EsdPolicy:
    """Return the ESD protection policy for a connector type (case-insensitive).

    Raises ``ValueError`` if the connector type is unknown.
    """
    key = connector_type.lower().strip()
    if key not in _POLICIES:
        raise ValueError(f"Unknown connector type '{connector_type}'. Known: {list_connector_types()}")
    return _POLICIES[key]
