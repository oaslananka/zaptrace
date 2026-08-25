from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from zaptrace.library.loader import ComponentSpec
from zaptrace.library.schema import (
    ComponentField,
    ComponentTrustTier,
    FieldProvenance,
    HumanReviewApproval,
    ProvenanceConfidence,
    ProvenanceSourceType,
    ReviewScope,
)
from zaptrace.library.trust_baseline import (
    TrustBaseline,
    compare_trust_baseline,
    generate_trust_baseline,
    load_trust_baseline,
    write_trust_baseline,
)


def _evidence(*, verified: bool = False, curated: bool = False) -> FieldProvenance:
    if verified or curated:
        return FieldProvenance(
            source_type=ProvenanceSourceType.MANUFACTURER_DOCUMENT,
            source_locator="https://manufacturer.example/part.pdf",
            source_identity="PART-DS",
            source_sha256="a" * 64 if verified else "",
            source_version="Rev A",
            extraction_method="manual-review",
            extracted_at=date(2026, 7, 27),
            reviewed_by="engineer@example.com",
            reviewed_at=date(2026, 7, 27),
            confidence=(ProvenanceConfidence.HIGH if verified else ProvenanceConfidence.MEDIUM),
        )
    return FieldProvenance(
        source_type=ProvenanceSourceType.INTERNAL_MANIFEST,
        source_locator="offline-manifest",
        source_identity="legacy-library-v1",
        source_version="1",
        extraction_method="migration",
        confidence=ProvenanceConfidence.LOW,
    )


def _approval() -> HumanReviewApproval:
    return HumanReviewApproval(
        approval_id="REVIEW-1",
        reviewed_by="engineer@example.com",
        reviewed_at=date(2026, 7, 27),
        scopes={ReviewScope.RELEASE, ReviewScope.FABRICATION},
    )


def _spec(part_id: str, tier: ComponentTrustTier) -> ComponentSpec:
    verified = tier is ComponentTrustTier.VERIFIED
    curated = tier is ComponentTrustTier.CURATED
    return ComponentSpec(
        id=part_id,
        name=part_id,
        category="power",
        manufacturer="Acme",
        mpn=f"{part_id}-MPN",
        description="part",
        datasheet="https://manufacturer.example/part.pdf",
        package="SOT-23-5",
        footprint="Package:SOT-23-5",
        pins={"1": {"type": "input", "description": "VIN"}},
        electrical_limits={"max_voltage_v": 6.0},
        sourcing={"mpn": f"{part_id}-MPN", "manufacturer": "Acme"},
        compliance={"rohs": True},
        provenance={"source": "fixture"},
        trust_tier=tier,
        field_provenance={field: _evidence(verified=verified, curated=curated) for field in ComponentField},
        human_review=_approval() if verified or curated else None,
    )


def _baseline(**tiers: ComponentTrustTier) -> TrustBaseline:
    return generate_trust_baseline({part_id: _spec(part_id, tier) for part_id, tier in tiers.items()})


def test_trust_baseline_rejects_existing_record_downgrade() -> None:
    baseline = _baseline(part=ComponentTrustTier.CURATED)

    report = compare_trust_baseline({"part": _spec("part", ComponentTrustTier.HEURISTIC)}, baseline)

    assert report.passed is False
    assert report.downgraded_component_ids == ["part"]
    assert report.violations[0].code == "trust-tier-downgrade"


def test_valid_curated_upgrade_is_reported_and_allowed() -> None:
    baseline = _baseline(part=ComponentTrustTier.HEURISTIC)

    report = compare_trust_baseline({"part": _spec("part", ComponentTrustTier.CURATED)}, baseline)

    assert report.passed is True
    assert report.upgraded_component_ids == ["part"]
    assert report.violations == []


def test_invalid_verified_upgrade_is_rejected() -> None:
    baseline = _baseline(part=ComponentTrustTier.HEURISTIC)
    invalid = _spec("part", ComponentTrustTier.VERIFIED)
    invalid.field_provenance[ComponentField.PIN_MAP] = _evidence()

    report = compare_trust_baseline({"part": invalid}, baseline)

    assert report.passed is False
    assert report.invalid_stronger_claim_ids == ["part"]
    assert report.violations[0].code == "invalid-stronger-trust-claim"


def test_removed_baseline_record_is_not_silent() -> None:
    baseline = _baseline(part=ComponentTrustTier.HEURISTIC)

    report = compare_trust_baseline({}, baseline)

    assert report.passed is False
    assert report.removed_component_ids == ["part"]
    assert report.violations[0].code == "baseline-component-removed"


def test_new_valid_record_is_allowed_and_reported() -> None:
    baseline = _baseline(part=ComponentTrustTier.HEURISTIC)
    current = {
        "part": _spec("part", ComponentTrustTier.HEURISTIC),
        "new": _spec("new", ComponentTrustTier.HEURISTIC),
    }

    report = compare_trust_baseline(current, baseline)

    assert report.passed is True
    assert report.new_component_ids == ["new"]


def test_baseline_write_and_load_are_deterministic(tmp_path: Path) -> None:
    baseline = _baseline(
        zeta=ComponentTrustTier.HEURISTIC,
        alpha=ComponentTrustTier.CURATED,
    )
    first = write_trust_baseline(baseline, tmp_path / "first.json")
    second = write_trust_baseline(baseline, tmp_path / "second.json")

    assert first.read_bytes() == second.read_bytes()
    loaded = load_trust_baseline(first, allowed_root=tmp_path)
    assert loaded == baseline
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert list(payload["component_tiers"]) == ["alpha", "zeta"]
    assert len(payload["library_digest"]) == 64


def test_baseline_load_rejects_workspace_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = write_trust_baseline(_baseline(part=ComponentTrustTier.HEURISTIC), tmp_path / "outside.json")

    with pytest.raises(ValueError, match="outside allowed root"):
        load_trust_baseline(outside, allowed_root=workspace)


def test_baseline_load_rejects_symlink(tmp_path: Path) -> None:
    real = write_trust_baseline(_baseline(part=ComponentTrustTier.HEURISTIC), tmp_path / "real.json")
    link = tmp_path / "baseline.json"
    try:
        link.symlink_to(real)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="symbolic link"):
        load_trust_baseline(link, allowed_root=tmp_path)
