"""IPC-7351-oriented land-pattern calculator skeleton.

This is a deliberately small, auditable starting point. It provides a stable API
and a passive chip fixture; it does not claim full IPC-7351 coverage.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from zaptrace import __version__
from zaptrace.core.models import FootprintDef, LayerSet, Pad, PadShape
from zaptrace.ee.footprint_proof import (
    FootprintProof,
    FootprintSourceProvenance,
    FootprintSourceType,
    build_footprint_proof,
)


class Ipc7351DensityLevel(StrEnum):
    LEAST = "least"
    NOMINAL = "nominal"
    MOST = "most"


class Ipc7351ChipFixture(BaseModel):
    """Minimal passive chip package input fixture."""

    model_config = ConfigDict(strict=False)

    package_code: str
    body_length_mm: float = Field(gt=0)
    body_width_mm: float = Field(gt=0)
    pad_width_mm: float = Field(gt=0)
    pad_height_mm: float = Field(gt=0)
    pad_pitch_mm: float = Field(gt=0)
    courtyard_x_mm: float = Field(gt=0)
    courtyard_y_mm: float = Field(gt=0)


class Ipc7351LandPatternResult(BaseModel):
    """Calculator result with generated footprint and proof evidence."""

    model_config = ConfigDict(arbitrary_types_allowed=True, strict=False)

    standard_family: str = "IPC-7351-oriented"
    coverage: str = "skeleton-passive-chip-only"
    density: Ipc7351DensityLevel
    fixture: Ipc7351ChipFixture
    footprint: FootprintDef
    proof: FootprintProof
    notes: list[str] = Field(default_factory=list)


_CHIP_FIXTURES: dict[str, Ipc7351ChipFixture] = {
    "0603": Ipc7351ChipFixture(
        package_code="0603",
        body_length_mm=1.6,
        body_width_mm=0.8,
        pad_width_mm=0.9,
        pad_height_mm=0.95,
        pad_pitch_mm=1.3,
        courtyard_x_mm=2.3,
        courtyard_y_mm=1.5,
    )
}

_DENSITY_SCALE: dict[Ipc7351DensityLevel, float] = {
    Ipc7351DensityLevel.LEAST: 0.9,
    Ipc7351DensityLevel.NOMINAL: 1.0,
    Ipc7351DensityLevel.MOST: 1.1,
}


def supported_ipc7351_chip_packages() -> list[str]:
    """Return passive chip packages supported by the skeleton calculator."""
    return sorted(_CHIP_FIXTURES)


def calculate_ipc7351_chip(
    package_code: str,
    *,
    density: Ipc7351DensityLevel = Ipc7351DensityLevel.NOMINAL,
    layer: LayerSet = LayerSet.TOP,
) -> Ipc7351LandPatternResult:
    """Generate a passive chip footprint and proof from the skeleton calculator."""
    key = package_code.strip().upper()
    if key not in _CHIP_FIXTURES:
        supported = ", ".join(supported_ipc7351_chip_packages())
        raise ValueError(f"unsupported IPC-7351 skeleton chip package {package_code!r}; supported: {supported}")
    fixture = _CHIP_FIXTURES[key]
    scale = _DENSITY_SCALE[density]
    pad_width = round(fixture.pad_width_mm * scale, 4)
    pad_height = round(fixture.pad_height_mm * scale, 4)
    half_pitch = fixture.pad_pitch_mm / 2
    footprint = FootprintDef(
        pads=[
            Pad(
                id="1",
                layer=layer,
                shape=PadShape.RECT,
                position=(-half_pitch, 0.0),
                size=(pad_width, pad_height),
            ),
            Pad(
                id="2",
                layer=layer,
                shape=PadShape.RECT,
                position=(half_pitch, 0.0),
                size=(pad_width, pad_height),
            ),
        ],
        courtyard=(fixture.courtyard_x_mm, fixture.courtyard_y_mm),
        description=f"IPC-7351-oriented {fixture.package_code} passive chip skeleton ({density.value})",
        source="IPC-7351-oriented skeleton",
    )
    source = FootprintSourceProvenance(
        source_type=FootprintSourceType.GENERATED,
        source_name=f"ipc7351-chip-{fixture.package_code}",
        generator="zaptrace.ee.ipc7351.calculate_ipc7351_chip",
        generator_version=__version__,
        attribution="Skeleton calculator; verify against the applicable IPC-7351 edition before production use.",
    )
    proof = build_footprint_proof(
        fixture.package_code,
        footprint,
        footprint_name=footprint.description,
        source=source,
        expected_pin_count=2,
    )
    return Ipc7351LandPatternResult(
        density=density,
        fixture=fixture,
        footprint=footprint,
        proof=proof,
        notes=["skeleton passive chip fixture; not full IPC-7351 implementation"],
    )
