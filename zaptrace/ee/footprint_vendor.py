"""Verified vendored land patterns for packages with no parametric generator.

Module / DFN / LGA / aQFN / magjack packages cannot be produced by the IPC-7351
generators in :mod:`zaptrace.ee.footprints`, so their geometry is sourced from
peer-reviewed, datasheet-derived KiCad land patterns vendored under
``data/footprints/vendor/`` (see that directory's ``ATTRIBUTION.md`` for license
and provenance). Sourcing verified files — rather than transcribing pad
coordinates from a datasheet by hand — is what keeps this safe: a single wrong
coordinate would be a fabrication hazard.

:data:`VENDOR_FOOTPRINTS` is the only trusted-by-name surface: a synthesis
footprint name resolves to a vendored file only via an explicit entry here.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from zaptrace.kicad.importer import load_kicad_footprint

if TYPE_CHECKING:
    from zaptrace.core.models import FootprintDef

_VENDOR_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "footprints" / "vendor"

# Synthesis footprint name -> vendored .kicad_mod file. Each entry pairs a
# library part's footprint name with the verified land pattern for its package.
VENDOR_FOOTPRINTS: dict[str, str] = {
    "AT24C02D-SSHM-T-SOIC8-SN": "SOIC-8_3.9x4.9mm_P1.27mm.kicad_mod",
    "ATECC608B-SSHDA-T-SOIC8": "SOIC-8_3.9x4.9mm_P1.27mm.kicad_mod",
    "MCP9808-E-MS-MSOP8": "MSOP-8_3x3mm_P0.65mm.kicad_mod",
    "INA219AIDCNR-SOT23-8": "SOT-23-8.kicad_mod",
    "INA226-MSOP10": "MSOP-10_3x3mm_P0.5mm.kicad_mod",
    "ADS1115IDGSR-DGS10": "MSOP-10_3x3mm_P0.5mm.kicad_mod",
    "AP2112K-3.3TRG1-SOT25": "SOT-23-5.kicad_mod",
    "W25Q128JVSIQ-SOIC8-208MIL": "SOIC-8_5.3x5.3mm_P1.27mm.kicad_mod",
    "STM32G0B1CET6-LQFP48": "LQFP-48_7x7mm_P0.5mm.kicad_mod",
    "USBLC6-2SC6-SOT23-6L": "SOT-23-6.kicad_mod",
    "BME280-LGA8": "Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering.kicad_mod",
    "LGA-8": "Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering.kicad_mod",
    "ESP32-WROOM-32": "ESP32-WROOM-32.kicad_mod",
    "USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal": (
        "USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.kicad_mod"
    ),
    "USB-C-16P-SMD": "USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.kicad_mod",
    "SHT31-DIS-DFN8": "Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm.kicad_mod",
    "Potentiometer_Bourns_3296W_Vertical": "Potentiometer_Bourns_3296W_Vertical.kicad_mod",
    "Potentiometer_Bourns_3296X_Horizontal": "Potentiometer_Bourns_3296X_Horizontal.kicad_mod",
    "nRF52840-QIAA": "Nordic_AQFN-73-1EP_7x7mm_P0.5mm.kicad_mod",
    "RJ45-8P8C-SHIELDED": "RJ45_Hanrun_HR911105A_Horizontal.kicad_mod",
    "ESP32-C3-MINI-1": "ESP32-C3-MINI-1.kicad_mod",
}


def vendored_footprint_path(name: str) -> Path | None:
    """Return the registered vendored source path for *name*, if present."""
    filename = VENDOR_FOOTPRINTS.get(name)
    if filename is None:
        return None
    path = _VENDOR_DIR / filename
    return path if path.exists() else None


@cache
def _load_cached(filename: str) -> FootprintDef | None:
    path = _VENDOR_DIR / filename
    if not path.exists():
        return None
    return load_kicad_footprint(path)


def resolve_vendored_footprint(name: str) -> FootprintDef | None:
    """Return the verified land pattern registered for *name*, or ``None``.

    A fresh copy is returned each call so callers may attach and mutate it on a
    component without disturbing the cached parse.
    """
    filename = VENDOR_FOOTPRINTS.get(name)
    if filename is None:
        return None
    footprint = _load_cached(filename)
    return footprint.model_copy(deep=True) if footprint is not None else None
