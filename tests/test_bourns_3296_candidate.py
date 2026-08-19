from __future__ import annotations

from datetime import date
from pathlib import Path

from zaptrace.ee.footprint_proof import (
    FootprintSourceProvenance,
    FootprintSourceType,
    build_footprint_proof,
    file_sha256,
    validate_footprint_proof,
)
from zaptrace.ee.footprint_vendor import VENDOR_FOOTPRINTS, resolve_vendored_footprint, vendored_footprint_path
from zaptrace.library.integrity import run_library_integrity_gate
from zaptrace.library.loader import LibraryLoader
from zaptrace.library.schema import ComponentField, ComponentTrustTier, ProvenanceConfidence, ProvenanceSourceType

_DATASHEET_SHA256 = "8492a5d67ee2785d4716ec3131b8fa6f9aaef9fa9e9eff65999b1d1a50d9baef"
_KICAD_REVISION = "a2cd6bea801640f3b5c0067744ac7f84dc324f1e"
_W_FOOTPRINT = "Potentiometer_Bourns_3296W_Vertical"
_X_FOOTPRINT = "Potentiometer_Bourns_3296X_Horizontal"
_W_FOOTPRINT_SHA256 = "6d2547bdf6885984bb561dd44a76b89e3e270d386debe2e385fe997ad316db11"
_X_FOOTPRINT_SHA256 = "3dd87ed8d9318cf0c7569895a7319fdfd11d330f7a5208fdcd648d2ab487a69e"
_PACKAGE_MAP = {"1": "P1", "2": "P2", "3": "P3"}


def _assert_common_3296_evidence(component_id: str) -> None:
    spec = LibraryLoader().get(component_id)

    assert spec.manufacturer == "Bourns"
    assert spec.datasheet == "https://www.bourns.com/docs/product-datasheets/3296.pdf"
    assert spec.package_pin_map == _PACKAGE_MAP
    assert spec.pins["P1"]["description"] == "Terminal 1 (CCW)"
    assert spec.pins["P2"]["description"] == "Wiper"
    assert spec.pins["P3"]["description"] == "Terminal 3 (CW)"
    assert spec.properties["turns"] == 25
    assert spec.properties["power_rating_w_70c"] == 0.5
    assert spec.properties["temperature_coefficient_ppm_per_c"] == 100
    assert spec.properties["resistance_tolerance_percent"] == 10
    assert spec.electrical_limits["max_voltage_v"] == 300
    assert spec.electrical_limits["rated_power_w"] == 0.5
    assert spec.electrical_limits["temperature_range"] == [-55, 125]
    assert spec.properties["power_rating_w_125c"] == 0.0
    assert spec.trust_tier is ComponentTrustTier.HEURISTIC
    assert spec.human_review is None

    for field in (
        ComponentField.MPN,
        ComponentField.DATASHEET,
        ComponentField.PIN_MAP,
        ComponentField.PACKAGE,
        ComponentField.FOOTPRINT,
        ComponentField.ELECTRICAL_LIMITS,
        ComponentField.LIFECYCLE,
        ComponentField.SOURCING,
    ):
        evidence = spec.field_provenance[field]
        assert evidence.source_type is ProvenanceSourceType.MANUFACTURER_DOCUMENT
        assert evidence.source_identity == "Bourns 3296 Trimpot datasheet"
        assert evidence.source_sha256 == _DATASHEET_SHA256
        assert evidence.source_version == "REV. 02/26"
        assert evidence.extracted_at == date(2026, 8, 11)
        assert evidence.reviewed_by == ""
        assert evidence.reviewed_at is None
        assert evidence.confidence is ProvenanceConfidence.MEDIUM


def test_bourns_3296w_10k_candidate_matches_exact_orderable_part() -> None:
    spec = LibraryLoader().get("pot-trim-3296w")

    _assert_common_3296_evidence(spec.id)
    assert spec.mpn == "3296W-1-103LF"
    assert spec.package == "3296W-1"
    assert spec.footprint == _W_FOOTPRINT
    assert spec.properties["resistance_ohms"] == 10_000
    assert spec.properties["resistance_code"] == "103"
    assert spec.properties["adjustment_orientation"] == "top-adjust"
    assert spec.sourcing["status"] == "current-manufacturer-datasheet"
    assert spec.compliance["rohs"] == "manufacturer-datasheet-declared"


def test_bourns_3296w_100k_record_uses_exact_resistance_code() -> None:
    spec = LibraryLoader().get("pot-trim-3296w-100k-100k")

    _assert_common_3296_evidence(spec.id)
    assert spec.mpn == "3296W-1-104LF"
    assert spec.package == "3296W-1"
    assert spec.footprint == _W_FOOTPRINT
    assert spec.properties["resistance_ohms"] == 100_000
    assert spec.properties["resistance_code"] == "104"
    assert spec.properties["adjustment_orientation"] == "top-adjust"


def test_bourns_3296x_1k_record_uses_exact_style_and_resistance_code() -> None:
    spec = LibraryLoader().get("pot-trim-3296x-1k-1k")

    _assert_common_3296_evidence(spec.id)
    assert spec.mpn == "3296X-1-102LF"
    assert spec.package == "3296X-1"
    assert spec.footprint == _X_FOOTPRINT
    assert spec.properties["resistance_ohms"] == 1_000
    assert spec.properties["resistance_code"] == "102"
    assert spec.properties["adjustment_orientation"] == "side-adjust"


def test_bourns_3296w_legacy_10k_id_is_safe_canonical_mirror() -> None:
    loader = LibraryLoader()
    canonical = loader.get("pot-trim-3296w")
    legacy = loader.get("pot-trim-3296w-10k")

    assert legacy.properties["canonical_component_id"] == canonical.id
    assert legacy.properties["compatibility_role"] == "legacy-id-mirror"
    assert legacy.manufacturer == canonical.manufacturer
    assert legacy.mpn == canonical.mpn
    assert legacy.datasheet == canonical.datasheet
    assert legacy.package == canonical.package
    assert legacy.footprint == canonical.footprint
    assert legacy.pins == canonical.pins
    assert legacy.package_pin_map == canonical.package_pin_map
    assert legacy.electrical_limits == canonical.electrical_limits


def test_bourns_3296_vendored_footprints_are_pinned_and_match_three_terminal_geometry() -> None:
    expected = {
        _W_FOOTPRINT: (
            "Potentiometer_Bourns_3296W_Vertical.kicad_mod",
            _W_FOOTPRINT_SHA256,
            "3296W-1",
        ),
        _X_FOOTPRINT: (
            "Potentiometer_Bourns_3296X_Horizontal.kicad_mod",
            _X_FOOTPRINT_SHA256,
            "3296X-1",
        ),
    }

    for footprint_name, (filename, digest, package) in expected.items():
        source_path = vendored_footprint_path(footprint_name)
        assert VENDOR_FOOTPRINTS[footprint_name] == filename
        assert source_path == Path(f"data/footprints/vendor/{filename}").resolve()
        assert file_sha256(source_path) == digest

        footprint = resolve_vendored_footprint(footprint_name)
        assert footprint is not None
        assert {pad.id for pad in footprint.pads} == {"1", "2", "3"}
        assert {(pad.id, pad.position[0], pad.position[1]) for pad in footprint.pads} == {
            ("1", 0.0, 0.0),
            ("2", -2.54, 0.0),
            ("3", -5.08, 0.0),
        }

        source = FootprintSourceProvenance(
            source_type=FootprintSourceType.VENDORED,
            source_name=f"KiCad official {footprint_name} footprint",
            source_path=f"data/footprints/vendor/{filename}",
            source_sha256=digest,
            attribution="data/footprints/vendor/ATTRIBUTION.md",
        )
        proof = build_footprint_proof(
            package,
            footprint,
            footprint_name=footprint_name,
            source=source,
            expected_pin_count=3,
            pin_map={pin_id: pin_id for pin_id in _PACKAGE_MAP},
        )
        validation = validate_footprint_proof(proof, expected_physical_pins={"1", "2", "3"})
        assert validation.blocked is False
        assert proof.pin_count == 3
        assert proof.pad_count == 3


def test_bourns_3296_duplicate_group_resolves_to_stable_canonical_id() -> None:
    report = run_library_integrity_gate()
    group = next(
        group
        for group in report.duplicate_groups
        if group.canonical_id == "pot-trim-3296w" and "pot-trim-3296w-10k" in group.alternate_ids
    )
    assert group.conflict is False


def test_library_expansion_does_not_regenerate_curated_bourns_3296_records() -> None:
    from scripts.generate_library_expansion import collect_all_parts

    generated_ids = {part_id for _category, part_id, _data in collect_all_parts()}
    assert {
        "pot-trim-3296w-10k",
        "pot-trim-3296w-100k-100k",
        "pot-trim-3296x-1k-1k",
    }.isdisjoint(generated_ids)


def test_bourns_3296_footprint_attribution_pins_exact_kicad_revision() -> None:
    text = Path("data/footprints/vendor/ATTRIBUTION.md").read_text(encoding="utf-8")
    assert _KICAD_REVISION in text
    assert "Potentiometer_Bourns_3296W_Vertical.kicad_mod" in text
    assert "Potentiometer_Bourns_3296X_Horizontal.kicad_mod" in text
