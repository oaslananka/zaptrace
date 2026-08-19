from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from zaptrace.core.models import (
    BoardDefinition,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    LayerSet,
    Pad,
    PadShape,
    RouteResult,
    TraceSegment,
)
from zaptrace.export.evidence import (
    ManufacturingValidationStatus,
    collect_manufacturing_evidence,
    validation_from_dfm_result,
)
from zaptrace.export.manufacturing import generate_manufacturing_bundle
from zaptrace.fab.dfm import DFMChecker, DFMCheckResult, DFMViolation
from zaptrace.fab.profile import FabAssemblyLimits, FabProfile, load_profile
from zaptrace.fab.readiness import DFMReadinessStatus, require_dfm_release_ready
from zaptrace.proof.manifest import ManufacturingProofEvidence
from zaptrace.synthesis.engine import synthesize


def _footprint_design(*, name: str = "ReadinessBoard") -> Design:
    footprint = FootprintDef(
        pads=[
            Pad(id="1", layer=LayerSet.TOP, shape=PadShape.RECT, position=(0.0, 0.0), size=(0.5, 0.5)),
            Pad(id="2", layer=LayerSet.TOP, shape=PadShape.RECT, position=(0.8, 0.0), size=(0.5, 0.5)),
        ],
        height=1.2,
    )
    return Design(
        meta=DesignMeta(name=name),
        components={
            "u1": Component(
                id="u1",
                ref="U1",
                type="ic",
                footprint="SOIC-2",
                footprint_def=footprint,
                position=(10.0, 10.0),
            )
        },
        board_def=BoardDefinition(width=40.0, height=30.0, layers=2),
        placement={"u1": (10.0, 10.0)},
    )


def test_fab_profile_identity_is_versioned_and_stable() -> None:
    profile = load_profile("jlcpcb-2layer")

    assert profile.profile_version
    assert len(profile.identity_sha256()) == 64
    assert profile.identity_sha256() == load_profile("jlcpcb-2layer").identity_sha256()
    assert profile.model_copy(update={"profile_version": "next"}).identity_sha256() != profile.identity_sha256()


def test_dfm_readiness_json_schema_exposes_status_contract() -> None:
    from zaptrace.fab.readiness import DFMReadinessReport

    schema = DFMReadinessReport.model_json_schema()
    status_ref = schema["properties"]["status"]["$ref"].rsplit("/", 1)[-1]
    assert set(schema["$defs"][status_ref]["enum"]) == {
        "pass",
        "hard-fail",
        "warning",
        "approved-skip",
        "human-review-required",
    }


def test_stale_source_bound_assembly_profile_requires_human_review() -> None:
    profile = FabProfile(
        name="stale-assembly",
        manufacturer="FixtureFab",
        source_urls=["https://example.invalid/fab"],
        last_verified="2026-07-01",
        stale_after_days=30,
        assembly=FabAssemblyLimits(
            class_name="fixture-assembly",
            source_urls=["https://example.invalid/assembly"],
            last_verified="2020-01-01",
        ),
    )

    result = DFMChecker(profile).check(_footprint_design())

    assert result.readiness_status == DFMReadinessStatus.HUMAN_REVIEW_REQUIRED
    assert any("Assembly profile" in item.message for item in result.violations)


def test_builtin_profiles_publish_source_bound_assembly_classes() -> None:
    jlc_economic = load_profile("jlcpcb-2layer")
    jlc_four_layer = load_profile("jlcpcb-4layer")
    pcbway = load_profile("pcbway-standard")
    oshpark = load_profile("oshpark")

    assert jlc_economic.assembly.class_name == "jlcpcb-economic-pcba"
    assert jlc_economic.assembly.supports_double_sided_assembly is False
    assert jlc_economic.assembly.min_component_pitch_mm == 0.4
    assert jlc_four_layer.assembly.class_name == "jlcpcb-economic-pcba"
    assert jlc_four_layer.assembly.min_bga_pitch_mm == 0.5
    assert pcbway.assembly.supports_through_hole_assembly is True
    assert pcbway.assembly.min_component_pitch_mm == 0.3
    assert oshpark.assembly.service_available is False
    for profile in (jlc_economic, jlc_four_layer, pcbway, oshpark):
        assert profile.capabilities.copper_weights_oz
        assert profile.assembly.source_urls
        assert profile.assembly.last_verified == "2026-07-29"


def test_fabrication_only_profile_requires_external_assembly_review() -> None:
    result = DFMChecker(load_profile("oshpark")).check(_footprint_design())

    assert result.readiness_status == DFMReadinessStatus.HUMAN_REVIEW_REQUIRED
    assert any(item.rule_id == "assembly-service-unavailable" for item in result.violations)


def test_assembly_limits_are_enforced_as_blocking_failures() -> None:
    design = _footprint_design()
    component = design.components["u1"]
    component.properties["side"] = "bottom"
    component.footprint_def = component.footprint_def.model_copy(update={"height": 8.0})
    profile = FabProfile(
        name="assembly-limited",
        manufacturer="FixtureFab",
        assembly=FabAssemblyLimits(
            min_component_pitch_mm=1.0,
            max_component_height_mm=5.0,
            supports_double_sided_assembly=False,
        ),
    )

    result = DFMChecker(profile).check(design)

    assert result.readiness_status == DFMReadinessStatus.HARD_FAIL
    assert {item.rule_id for item in result.violations} >= {
        "assembly-component-pitch",
        "assembly-component-height",
        "assembly-bottom-side",
    }


def test_missing_assembly_geometry_requires_human_review() -> None:
    design = _footprint_design()
    design.components["u1"].footprint_def = None

    result = DFMChecker(load_profile("jlcpcb-2layer")).check(design)

    assert result.readiness_status == DFMReadinessStatus.HUMAN_REVIEW_REQUIRED
    assert any(item.severity == "human-review-required" for item in result.violations)


def test_warning_only_result_has_warning_readiness() -> None:
    design = _footprint_design()
    design.routing = RouteResult(
        traces=[TraceSegment(layer="F.Cu", start=(1.0, 1.0), end=(5.0, 1.0), width=0.1, net_id="signal")]
    )
    profile = FabProfile(name="warning-profile", manufacturer="FixtureFab", min_trace_mm=0.2)

    result = DFMChecker(profile).check(design)

    assert result.errors == 0
    assert result.readiness_status == DFMReadinessStatus.WARNING


def test_manufacturing_bundle_writes_hashed_readiness_report(tmp_path: Path) -> None:
    result = generate_manufacturing_bundle(
        _footprint_design(),
        tmp_path,
        prefix="ReadinessBoard",
        fab_profile="jlcpcb-2layer",
    )

    report_path = Path(result["dfm_readiness"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["profile"]["name"] == "jlcpcb-2layer"
    assert report["profile"]["version"]
    assert len(report["profile"]["sha256"]) == 64
    assert report["status"] in {status.value for status in DFMReadinessStatus}
    assert report["artifact_hashes"]
    assert all(len(value) == 64 for value in report["artifact_hashes"].values())

    with zipfile.ZipFile(result["zip"]) as archive:
        assert report_path.name in archive.namelist()


def test_approved_profile_skip_is_explicit_and_auditable(tmp_path: Path) -> None:
    result = generate_manufacturing_bundle(
        _footprint_design(),
        tmp_path,
        prefix="SkipBoard",
        approved_dfm_skip_reason="Prototype-only assembly review",
        approved_dfm_skip_id="DFM-SKIP-1",
    )

    report = json.loads(Path(result["dfm_readiness"]).read_text(encoding="utf-8"))
    assert report["status"] == DFMReadinessStatus.APPROVED_SKIP
    assert report["approved_skips"] == [
        {
            "rule_id": "manufacturer-profile",
            "reason": "Prototype-only assembly review",
            "approval_id": "DFM-SKIP-1",
        }
    ]
    assert report["blocks_autonomous_release"] is False


def test_manufacturing_evidence_and_proof_preserve_profile_and_artifact_hashes(tmp_path: Path) -> None:
    result = generate_manufacturing_bundle(
        _footprint_design(),
        tmp_path,
        prefix="ProofBoard",
        fab_profile="jlcpcb-2layer",
    )

    evidence = collect_manufacturing_evidence(tmp_path)
    proof = ManufacturingProofEvidence.from_evidence_bundle(
        evidence,
        report_path=Path(result["dfm_readiness"]).name,
    )

    assert evidence.fab_profile == "jlcpcb-2layer"
    assert evidence.fab_profile_version
    assert len(evidence.fab_profile_sha256) == 64
    assert evidence.readiness_status in {status.value for status in DFMReadinessStatus}
    assert proof.fab_profile_version == evidence.fab_profile_version
    assert proof.fab_profile_sha256 == evidence.fab_profile_sha256
    assert proof.readiness_status == evidence.readiness_status
    assert proof.artifact_sha256
    assert all(len(value) == 64 for value in proof.artifact_sha256.values())
    assert len(proof.readiness_report_sha256) == 64


@pytest.mark.parametrize(
    "intent",
    [
        "esp32 i2c sensor",
        "rp2040 usb hid keyboard",
        "stm32 rs485 modbus industrial",
    ],
)
def test_three_generated_board_families_emit_dfm_readiness_reports(tmp_path: Path, intent: str) -> None:
    design = synthesize(intent)
    output = tmp_path / design.meta.name

    result = generate_manufacturing_bundle(design, output, fab_profile="jlcpcb-2layer")
    report = json.loads(Path(result["dfm_readiness"]).read_text(encoding="utf-8"))

    assert report["design_name"] == design.meta.name
    assert report["profile"]["name"] == "jlcpcb-2layer"
    assert report["status"] in {status.value for status in DFMReadinessStatus}
    assert report["artifact_hashes"]


def test_assembly_freshness_handles_generic_missing_and_invalid_metadata() -> None:
    generic = FabAssemblyLimits()
    missing = FabAssemblyLimits(class_name="source-bound")
    invalid = FabAssemblyLimits(
        class_name="source-bound",
        source_urls=["https://example.invalid/assembly"],
        last_verified="not-a-date",
    )

    assert generic.is_stale() is False
    assert generic.freshness_warnings("generic") == []
    assert missing.is_stale() is True
    assert any("no source URL" in warning for warning in missing.freshness_warnings("fixture"))
    assert invalid.is_stale() is True


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        ("human-review-required", ManufacturingValidationStatus.HUMAN_REVIEW_REQUIRED),
        ("approved-skip", ManufacturingValidationStatus.APPROVED_SKIP),
        ("warning", ManufacturingValidationStatus.WARNING),
        ("", ManufacturingValidationStatus.PASS),
    ],
)
def test_dfm_result_maps_all_manufacturing_evidence_states(
    severity: str,
    expected: ManufacturingValidationStatus,
) -> None:
    violations = [DFMViolation(rule_id="fixture", severity=severity, message="fixture")] if severity else []
    result = DFMCheckResult(violations=violations, profile_name="fixture")

    evidence = validation_from_dfm_result(result)

    assert evidence.status == expected


def test_malformed_readiness_report_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "fixture-dfm-readiness.json").write_text("{not-json", encoding="utf-8")

    evidence = collect_manufacturing_evidence(tmp_path)

    assert evidence.readiness_status == "human-review-required"
    assert evidence.blocked is True


def test_dfm_result_without_report_populates_profile_identity(tmp_path: Path) -> None:
    result = DFMCheckResult(
        profile_name="fixture",
        profile_version="2.0",
        profile_sha256="a" * 64,
    )

    evidence = collect_manufacturing_evidence(tmp_path, dfm_result=result)

    assert evidence.fab_profile == "fixture"
    assert evidence.fab_profile_version == "2.0"
    assert evidence.fab_profile_sha256 == "a" * 64
    assert evidence.readiness_status == "pass"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["fail"], "fail"),
        (["human-review-required"], "human-review-required"),
        (["warning"], "warning"),
        (["pass"], "pass"),
        ([], "unknown"),
    ],
)
def test_manufacturing_proof_aggregates_smoke_statuses(statuses: list[str], expected: str) -> None:
    validations = [
        SimpleNamespace(
            name="gerber-smoke:fixture",
            status=SimpleNamespace(value=status),
        )
        for status in statuses
    ]
    bundle = SimpleNamespace(
        artifacts=[],
        validations=validations,
        fab_profile="fixture",
        fab_profile_version="1.0",
        fab_profile_sha256="b" * 64,
        readiness_status="pass",
        readiness_report_sha256="",
        blocked=False,
    )

    proof = ManufacturingProofEvidence.from_evidence_bundle(bundle)

    assert proof.gerber_smoke_status == expected


@pytest.mark.parametrize("status", ["pass", "warning", "approved-skip"])
def test_release_gate_allows_non_blocking_dfm_states(status: str) -> None:
    require_dfm_release_ready(status, report_path="fixture.json")


@pytest.mark.parametrize("status", ["hard-fail", "human-review-required", ""])
def test_release_gate_blocks_unready_dfm_states(status: str) -> None:
    with pytest.raises(ValueError, match="manufacturing release blocked"):
        require_dfm_release_ready(status, report_path="fixture.json")
