"""Allowlisted, digest-pinned vendored KiCad footprint geometry.

These bindings verify the exact bytes of checked-in land patterns. They do NOT
confer part approval, datasheet/pin-map review, electrical compatibility, or
fabrication acceptance. Design input supplies an identifier, never a path.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from zaptrace.core.models import FootprintDef
from zaptrace.kicad.importer import load_kicad_footprint

# Identifier -> (repository-controlled file name, committed SHA-256).
# Deliberately limited to reviewed assets for the ESP32 demo. Extend only
# with a supplier/package and checksum review; do not accept a user path.
_PINNED_FOOTPRINTS: dict[str, tuple[str, str]] = {
    "esp32-wroom-32": (
        "ESP32-WROOM-32.kicad_mod",
        "62127c6680f44ce358890322adc2c764c4120fc0af2f87b636378de5a34b08b7",
    ),
    "bme280-lga8": (
        "Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering.kicad_mod",
        "533735a1edf6b96a54dbfd1958c232b7f3800ce05295e6d783837ee24b74c5c8",
    ),
    "r-0402": (
        "R_0402_1005Metric.kicad_mod",
        "e05c7605248c220836f642ed1f526133edf0374acdfd5bb2631e58b4e377acfb",
    ),
    "c-0402": (
        "C_0402_1005Metric.kicad_mod",
        "0403382fc4583ed510b461b1fa4a36dfaec6f4c0d9b1a67e6b0027837a54e1b5",
    ),
    "c-0805": (
        "C_0805_2012Metric.kicad_mod",
        "62775a51fe74ba7f1b572de327bdbd3fc92582721b2abcaa47787865590d89cb",
    ),
    "testpoint-pad-d1": (
        "TestPoint_Pad_D1.0mm.kicad_mod",
        "6d602c576b4ab0de29fa4cc096f419a62e828ba45ceee30c1263d86b420b2b12",
    ),
    "ams1117-sot223-tabpin2": (
        "SOT-223-3_TabPin2.kicad_mod",
        "8ae5f03e2c16377abed15e51af6864e23a934e1457b97fb7ea930e17fa99f11d",
    ),
}


def resolve_verified_footprint(asset_id: str) -> FootprintDef:
    """Load a pinned checked-in footprint or fail closed on unknown/modified data."""
    if asset_id not in _PINNED_FOOTPRINTS:
        raise ValueError(f"Unknown verified footprint asset: {asset_id!r}")
    filename, expected_digest = _PINNED_FOOTPRINTS[asset_id]
    # `data/` is included beside `zaptrace/` in source and built wheels.
    vendored_dir = Path(__file__).resolve().parents[2] / "data" / "footprints" / "vendor"
    source = vendored_dir / filename
    try:
        actual_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(f"Verified footprint asset unavailable: {asset_id!r}") from exc
    if actual_digest != expected_digest:
        raise ValueError(f"Verified footprint SHA-256 mismatch: {asset_id!r}")
    footprint = load_kicad_footprint(source)
    if footprint is None or not footprint.pads:
        raise ValueError(f"Verified footprint has no parseable pads: {asset_id!r}")
    return footprint
