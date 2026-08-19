"""RF / wireless design calculators.

Deterministic RF maths — wavelength in a medium, quarter-wave length, free-
space path loss, link budget, antenna keep-out zones, L-network impedance
matching, and microstrip 50Ω trace width — so an agent can lay out antennas,
matching stubs and link budgets with correct values.

Units: frequency in hertz, distances/lengths in metres or millimetres as the
name says, loss in dB.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

_C_M_PER_S = 299_792_458.0

_POSITIVE_FREQUENCY_ERROR = "freq_hz must be positive"
_BAND_2_4_GHZ = "2.4 GHz"


def wavelength_mm(freq_hz: float, *, eff_dielectric: float = 1.0) -> float:
    """Wavelength in mm: ``lambda = c / (f * sqrt(eeff))``."""
    if freq_hz <= 0:
        raise ValueError(_POSITIVE_FREQUENCY_ERROR)
    if eff_dielectric < 1.0:
        raise ValueError("eff_dielectric must be >= 1")
    lambda_m = _C_M_PER_S / (freq_hz * math.sqrt(eff_dielectric))
    return round(lambda_m * 1000.0, 4)


def quarter_wave_mm(freq_hz: float, *, eff_dielectric: float = 1.0) -> float:
    """Quarter-wave length in mm (matching stub / monopole)."""
    return round(wavelength_mm(freq_hz, eff_dielectric=eff_dielectric) / 4.0, 4)


def free_space_path_loss_db(freq_hz: float, distance_m: float) -> float:
    """Free-space path loss in dB: ``20*log10(4*pi*d*f / c)``."""
    if freq_hz <= 0 or distance_m <= 0:
        raise ValueError("freq_hz and distance_m must be positive")
    ratio = 4.0 * math.pi * distance_m * freq_hz / _C_M_PER_S
    return round(20.0 * math.log10(ratio), 3)


def link_margin_db(
    tx_power_dbm: float, tx_gain_dbi: float, rx_gain_dbi: float, path_loss_db: float, rx_sensitivity_dbm: float
) -> float:
    """Link margin: received power minus receiver sensitivity (dB)."""
    rx_power_dbm = tx_power_dbm + tx_gain_dbi + rx_gain_dbi - path_loss_db
    return round(rx_power_dbm - rx_sensitivity_dbm, 3)


# ---------------------------------------------------------------------------
# Antenna keep-out zone
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AntennaKeepout:
    """Recommended antenna keep-out zone for a given frequency."""

    freq_hz: float
    wavelength_mm: float
    min_keepout_mm: float  # minimum clearance from metal / copper on the same layer
    recommended_keepout_mm: float  # rule-of-thumb (λ/4 from copper pour edge)
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def antenna_keepout(freq_hz: float, *, er: float = 1.0) -> AntennaKeepout:
    """Compute a recommended antenna keep-out zone (no copper within λ/4 of radiating element).

    For an inverted-F or chip antenna on a PCB:
    - Keep copper pour and solid ground plane at least λ/10 away (absolute minimum).
    - Aim for λ/4 clearance on the same layer for best radiation pattern.

    Args:
        freq_hz: Carrier frequency (Hz).
        er: Effective dielectric constant (1.0 for free-space / chip antenna on edge).
    """
    if freq_hz <= 0:
        raise ValueError(_POSITIVE_FREQUENCY_ERROR)
    lam = wavelength_mm(freq_hz, eff_dielectric=er)
    min_ko = round(lam / 10.0, 2)
    rec_ko = round(lam / 4.0, 2)
    note = (
        f"At {freq_hz / 1e9:.3f} GHz: λ={lam:.1f} mm. "
        f"Keep copper ≥ {min_ko:.1f} mm away (λ/10 hard min); "
        f"aim for {rec_ko:.1f} mm (λ/4) clearance for pattern fidelity."
    )
    return AntennaKeepout(
        freq_hz=freq_hz,
        wavelength_mm=lam,
        min_keepout_mm=min_ko,
        recommended_keepout_mm=rec_ko,
        note=note,
    )


# ---------------------------------------------------------------------------
# L-network impedance matching
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LNetworkResult:
    """L-network (low-pass or high-pass) impedance matching values."""

    topology: str  # "low-pass" or "high-pass"
    source_ohms: float
    load_ohms: float
    q_factor: float
    series_element_ohms: float  # reactance of the series element
    shunt_element_ohms: float  # reactance of the shunt element
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def l_network_matching(
    source_ohms: float,
    load_ohms: float,
    freq_hz: float,
    *,
    topology: str = "low-pass",
) -> LNetworkResult:
    """Compute L-network element reactances for impedance matching.

    Transforms ``source_ohms`` to ``load_ohms`` (or vice-versa) at ``freq_hz``.
    The two elements are:
    - **Shunt**: connected in parallel with the *higher*-impedance port.
    - **Series**: connected in series with the *lower*-impedance port.

    Sign convention: positive reactance = inductor, negative = capacitor.

    Args:
        source_ohms: Source impedance (typically 50 Ω for RF).
        load_ohms: Load impedance (antenna / PA).
        freq_hz: Centre frequency.
        topology: ``"low-pass"`` (default) or ``"high-pass"``.
    """
    if source_ohms <= 0 or load_ohms <= 0:
        raise ValueError("source_ohms and load_ohms must be positive")
    if freq_hz <= 0:
        raise ValueError(_POSITIVE_FREQUENCY_ERROR)
    if topology not in ("low-pass", "high-pass"):
        raise ValueError("topology must be 'low-pass' or 'high-pass'")
    rs, rl = (source_ohms, load_ohms) if source_ohms > load_ohms else (load_ohms, source_ohms)
    q = math.sqrt(rs / rl - 1.0)
    # Shunt element (parallel with high-Z port): Xp = rs / q
    # Series element (in series with low-Z port): Xs = q * rl
    xp = rs / q
    xs = q * rl
    if topology == "high-pass":
        # High-pass: swap inductor ↔ capacitor
        xs, xp = -xp, -xs
    note = (
        f"L-network {topology} {source_ohms}Ω → {load_ohms}Ω @ {freq_hz / 1e9:.3f} GHz: "
        f"Q={q:.2f}, shunt X={xp:.1f}Ω, series X={xs:.1f}Ω "
        f"({'ind' if xs > 0 else 'cap'} series, {'cap' if xp > 0 else 'ind'} shunt)"
    )
    return LNetworkResult(
        topology=topology,
        source_ohms=source_ohms,
        load_ohms=load_ohms,
        q_factor=round(q, 4),
        series_element_ohms=round(xs, 3),
        shunt_element_ohms=round(xp, 3),
        note=note,
    )


# ---------------------------------------------------------------------------
# 50Ω microstrip trace width
# ---------------------------------------------------------------------------


def microstrip_50ohm_width_mm(
    substrate_height_mm: float,
    er: float = 4.3,
    *,
    copper_thickness_um: float = 35.0,
) -> float:
    """Approximate trace width (mm) for a 50Ω microstrip on a given substrate.

    Uses the Hammerstad–Jensen closed-form approximation. The result is
    accurate to ~1-2 % for W/H ratios between 0.1 and 10.

    Args:
        substrate_height_mm: Dielectric substrate thickness (distance to reference plane) in mm.
        er: Substrate relative permittivity (default FR-4 = 4.3).
        copper_thickness_um: Copper trace thickness in µm (default 35 µm = 1 oz).
    """
    if substrate_height_mm <= 0:
        raise ValueError("substrate_height_mm must be positive")
    if er < 1.0:
        raise ValueError("er must be >= 1")
    # Target impedance: Z0 = 50 Ω
    z0 = 50.0
    # Hammerstad–Jensen narrow-strip approximation (W/H < 2)
    a = z0 / 60.0 * math.sqrt((er + 1) / 2.0) + (er - 1) / (er + 1) * (0.23 + 0.11 / er)
    b = 377.0 * math.pi / (2.0 * z0 * math.sqrt(er))
    w_over_h_narrow = 8 * math.exp(a) / (math.exp(2 * a) - 2)
    w_over_h_wide = (
        2.0 / math.pi * (b - 1.0 - math.log(2 * b - 1) + (er - 1) / (2 * er) * (math.log(b - 1) + 0.39 - 0.61 / er))
    )
    w_over_h = w_over_h_narrow if w_over_h_narrow < 2.0 else w_over_h_wide
    # Account for copper thickness (Hammerstad correction)
    t_mm = copper_thickness_um / 1000.0
    dw = (
        t_mm
        / math.pi
        * math.log(1 + 4 * math.e * substrate_height_mm / (t_mm * (1 / math.tanh(math.sqrt(6.517 * w_over_h))) ** 2))
    )
    w_mm = w_over_h * substrate_height_mm - dw
    return round(max(w_mm, 0.01), 4)


# ---------------------------------------------------------------------------
# Pre-certified module reference table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RfModuleRef:
    """Reference data for a pre-certified RF module."""

    module_id: str
    description: str
    freq_bands: list[str]
    protocols: list[str]
    certifications: list[str]
    antenna_type: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_RF_MODULES: list[RfModuleRef] = [
    RfModuleRef(
        module_id="ESP32-WROOM-32",
        description="Espressif ESP32 Wi-Fi/BLE module",
        freq_bands=[_BAND_2_4_GHZ],
        protocols=["Wi-Fi 802.11 b/g/n", "BLE 4.2"],
        certifications=["FCC", "CE", "IC"],
        antenna_type="PCB trace",
        notes="Most cost-effective pre-cert Wi-Fi+BLE option; requires RF keep-out as per ESP32 hardware design guide",
    ),
    RfModuleRef(
        module_id="NINA-W102",
        description="u-blox NINA-W102 Wi-Fi/BLE module",
        freq_bands=[_BAND_2_4_GHZ],
        protocols=["Wi-Fi 802.11 b/g/n", "BLE 5.0"],
        certifications=["FCC", "CE", "IC", "MIC"],
        antenna_type="PCB trace + U.FL connector",
        notes="Industrial-grade Wi-Fi; good for -40°C to +85°C; supports external antenna",
    ),
    RfModuleRef(
        module_id="SARA-R4",
        description="u-blox SARA-R4 LTE Cat-M1/NB1 module",
        freq_bands=["LTE Cat-M1", "NB-IoT"],
        protocols=["LTE-M", "NB-IoT", "EGPRS"],
        certifications=["FCC", "CE", "PTCRB"],
        antenna_type="External SMA/U.FL",
        notes="Requires carrier approval in some regions; check PTCRB listing",
    ),
    RfModuleRef(
        module_id="nRF52840-DK",
        description="Nordic nRF52840 BLE/Thread/Zigbee module",
        freq_bands=[_BAND_2_4_GHZ],
        protocols=["BLE 5.3", "Thread", "Zigbee", "IEEE 802.15.4"],
        certifications=["FCC", "CE", "IC"],
        antenna_type="PCB trace monopole",
        notes="Best for mesh networking (Thread/Zigbee); needs 3.3V ±3% supply",
    ),
    RfModuleRef(
        module_id="SX1276",
        description="Semtech SX1276 LoRa transceiver (chip, not module)",
        freq_bands=["433 MHz", "868 MHz", "915 MHz"],
        protocols=["LoRa", "FSK", "OOK"],
        certifications=["CE RED (via module-level)"],
        antenna_type="External 50Ω",
        notes="Requires external PA and separate module-level FCC/CE; use LoRa module for faster cert",
    ),
]


def list_rf_modules() -> list[RfModuleRef]:
    """Return the built-in pre-certified RF module reference list."""
    return list(_RF_MODULES)


def get_rf_module(module_id: str) -> RfModuleRef:
    """Look up a pre-certified RF module by ID (case-insensitive prefix match)."""
    key = module_id.lower()
    for m in _RF_MODULES:
        if m.module_id.lower() == key or m.module_id.lower().startswith(key):
            return m
    raise ValueError(f"No RF module found for '{module_id}'. Known: {[m.module_id for m in _RF_MODULES]}")
