from __future__ import annotations

from pathlib import Path

from zaptrace.ee.footprint_proof import (
    FootprintSourceProvenance,
    FootprintSourceType,
    build_footprint_proof,
    file_sha256,
    validate_footprint_proof,
)
from zaptrace.ee.footprint_vendor import VENDOR_FOOTPRINTS, resolve_vendored_footprint, vendored_footprint_path
from zaptrace.library.loader import ComponentSpec

_ATTRIBUTION = "data/footprints/vendor/ATTRIBUTION.md"


def assert_vendored_candidate_footprint(
    spec: ComponentSpec,
    *,
    footprint_name: str,
    filename: str,
    source_sha256: str,
    physical_pin_ids: set[str],
    repository_pad_size_mm: list[float],
    manufacturer_pad_size_mm: list[float],
    source_name: str,
) -> None:
    """Check one candidate's pinned vendored footprint without duplicating candidate tests."""
    registered_filename = VENDOR_FOOTPRINTS[footprint_name]
    source_path = vendored_footprint_path(footprint_name)
    assert source_path is not None
    expected_path = Path("data/footprints/vendor", filename).resolve()
    assert (registered_filename, source_path, file_sha256(source_path)) == (
        filename,
        expected_path,
        source_sha256,
    )

    repository_land_pattern = spec.properties["repository_land_pattern"]
    assert (
        repository_land_pattern["pad_size_mm"],
        spec.properties["manufacturer_recommended_pad_mm"],
    ) == (repository_pad_size_mm, manufacturer_pad_size_mm)
    assert "human" in repository_land_pattern["review_note"].lower()

    footprint = resolve_vendored_footprint(footprint_name)
    assert footprint is not None
    assert {pad.id for pad in footprint.pads} == physical_pin_ids

    source = FootprintSourceProvenance.model_validate(
        {
            "source_type": FootprintSourceType.VENDORED,
            "source_name": source_name,
            "source_path": str(Path("data/footprints/vendor", filename)),
            "source_sha256": source_sha256,
            "attribution": _ATTRIBUTION,
        }
    )
    proof = build_footprint_proof(
        spec.package,
        footprint,
        footprint_name=spec.footprint,
        source=source,
        expected_pin_count=len(physical_pin_ids),
        pin_map={pin_id: pin_id for pin_id in physical_pin_ids},
    )
    assert validate_footprint_proof(proof, expected_physical_pins=physical_pin_ids).blocked is False
