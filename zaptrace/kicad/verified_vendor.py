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
