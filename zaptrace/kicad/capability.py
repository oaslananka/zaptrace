"""KiCad version capability discovery and IPC feature flags."""

from __future__ import annotations

import re
from dataclasses import dataclass

from zaptrace.kicad.oracle import KiCadOracle, detect_kicad


@dataclass(frozen=True)
class KiCadCapabilitySet:
    """Capability set for a detected KiCad toolchain version."""

    available: bool
    version_string: str
    major_version: int
    minor_version: int
    patch_version: int
    supports_erc: bool
    supports_drc: bool
    supports_step_export: bool
    supports_python_ipc: bool
    supports_kicad_10_ipc: bool


_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def discover_kicad_capabilities(cli: KiCadOracle | None = None) -> KiCadCapabilitySet:
    """Discover capability set from a detected KiCad CLI installation."""
    oracle = cli if cli is not None else detect_kicad()
    if not oracle.available:
        return KiCadCapabilitySet(
            available=False,
            version_string="0.0.0",
            major_version=0,
            minor_version=0,
            patch_version=0,
            supports_erc=False,
            supports_drc=False,
            supports_step_export=False,
            supports_python_ipc=False,
            supports_kicad_10_ipc=False,
        )

    match = _VERSION_RE.search(oracle.version)
    if match:
        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
    else:
        major, minor, patch = 8, 0, 0

    return KiCadCapabilitySet(
        available=True,
        version_string=oracle.version,
        major_version=major,
        minor_version=minor,
        patch_version=patch,
        supports_erc=True,
        supports_drc=True,
        supports_step_export=major >= 7,
        supports_python_ipc=major >= 8,
        supports_kicad_10_ipc=major >= 10,
    )
