from __future__ import annotations

import json
from pathlib import Path

from zaptrace.core.models import (
    BoardDefinition,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    LayerSet,
    MountingHole,
    Pad,
    PadShape,
)
from zaptrace.export.evidence import (
    ManufacturingArtifactKind,
    ManufacturingValidationStatus,
    classify_manufacturing_artifact,
    collect_manufacturing_evidence,
    smoke_validate_gerber,
    validate_gerber_job_file,
    validate_gerber_x2_file,
)
from zaptrace.export.manufacturing import generate_manufacturing_bundle
from zaptrace.fab.dfm import DFMChecker
from zaptrace.fab.profile import FabProfile
from zaptrace.proof.manifest import ManufacturingProofEvidence, ProofManifest


def _design() -> Design:
    footprint = FootprintDef(
        pads=[Pad(id="1", layer=LayerSet.TOP, shape=PadShape.CIRCLE, position=(0.0, 0.0), size=(1.0, 1.0), drill=0.4)]
    )
    return Design(
        meta=DesignMeta(name="EvidenceBoard"),
        components={
            "j1": Component(
                id="j1",
                ref="J1",
                type="connector",
                value="TEST",
                footprint="TH-1P",
                footprint_def=footprint,
                position=(10.0, 10.0),
            )
        },
        board_def=BoardDefinition(
            width=50.0,
            height=40.0,
            mounting_holes=[MountingHole(position=(5.0, 5.0), diameter=3.0, plated=True)],
        ),
        placement={"j1": (10.0, 10.0)},
    )


def test_manufacturing_artifact_classification_preserves_supported_families() -> None:
    cases = {
        "board.GTL": ManufacturingArtifactKind.GERBER,
        "board.drl": ManufacturingArtifactKind.EXCELLON,
        "board-pick-place.csv": ManufacturingArtifactKind.PICK_AND_PLACE,
        "board-bom.csv": ManufacturingArtifactKind.BOM,
        "board-dfm-readiness.json": ManufacturingArtifactKind.DFM_REPORT,
        "manufacturing-manifest.json": ManufacturingArtifactKind.MANIFEST,
        "board.gbrjob": ManufacturingArtifactKind.GERBER_JOB,
        "bundle.zip": ManufacturingArtifactKind.BUNDLE,
        "board-odb.zip": ManufacturingArtifactKind.ODBPP,
        "board.odbpp": ManufacturingArtifactKind.ODBPP,
        "board.glb": ManufacturingArtifactKind.MECHANICAL_REVIEW,
        "board-ipc2581.xml": ManufacturingArtifactKind.IPC2581,
        "board-stackup.txt.md": ManufacturingArtifactKind.STACKUP,
        "notes.md": ManufacturingArtifactKind.OTHER,
    }

    assert {name: classify_manufacturing_artifact(Path(name)) for name in cases} == cases


def test_collect_manufacturing_evidence_from_bundle(tmp_path: Path) -> None:
    generate_manufacturing_bundle(_design(), tmp_path, prefix="EvidenceBoard", fab_profile="jlcpcb-2layer")

    evidence = collect_manufacturing_evidence(tmp_path, fab_profile="jlcpcb-2layer")

    kinds = {artifact.kind for artifact in evidence.artifacts}
    assert ManufacturingArtifactKind.GERBER in kinds
    assert ManufacturingArtifactKind.EXCELLON in kinds
    assert ManufacturingArtifactKind.BOM in kinds
    assert ManufacturingArtifactKind.PICK_AND_PLACE in kinds
    assert ManufacturingArtifactKind.MANIFEST in kinds
    assert ManufacturingArtifactKind.GERBER_JOB in kinds
    assert ManufacturingArtifactKind.BUNDLE in kinds
    assert evidence.fab_profile == "jlcpcb-2layer"
    assert evidence.blocked is False
    assert evidence.evidence_identity.mode == "snapshot"
    assert len(evidence.evidence_identity.source_commit) == 40
    assert len(evidence.evidence_identity.identity_sha256) == 64
    assert "zaptrace/export/evidence.py" in evidence.evidence_identity.source_inputs
    assert all(len(artifact.sha256) == 64 for artifact in evidence.artifacts)
    assert any(validation.name.startswith("gerber-smoke:") for validation in evidence.validations)
    assert any(validation.name.startswith("gerber-x2:") for validation in evidence.validations)
    assert any(validation.name.startswith("gerber-job:") for validation in evidence.validations)
    assert any(validation.name.startswith("excellon-smoke:") for validation in evidence.validations)


def test_invalid_gerber_smoke_validation_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.GTL"
    path.write_text("G04 incomplete*\n", encoding="utf-8")

    validation = smoke_validate_gerber(path)

    assert validation.status == ManufacturingValidationStatus.FAIL
    assert validation.blocks_release
    assert "M02*" in validation.details["missing_tokens"]


def test_fab_profile_dtm_result_blocks_release(tmp_path: Path) -> None:
    design = _design()
    design.board_def = BoardDefinition(width=50.0, height=40.0)
    profile = FabProfile(name="tiny-fab", manufacturer="TestFab", max_board_width_mm=30.0)
    dfm_result = DFMChecker(profile).check(design)
    generate_manufacturing_bundle(design, tmp_path, prefix="EvidenceBoard")

    evidence = collect_manufacturing_evidence(tmp_path, fab_profile=profile.name, dfm_result=dfm_result)

    assert evidence.blocked is True
    assert any(validation.name == "fab-profile-dfm" for validation in evidence.validations)
    assert any(validation.blocks_release for validation in evidence.validations)


def test_proof_manifest_attaches_external_manufacturing_evidence() -> None:
    manufacturing = ManufacturingProofEvidence(
        fab_profile="jlcpcb-2layer",
        report_path="reports/manufacturing-evidence.json",
        blocked=False,
        artifact_count=9,
        validation_count=8,
        gerber_smoke_status="pass",
        excellon_smoke_status="pass",
        odbpp_status="attached",
        ipc2581_status="attached",
        message="Gerber, Excellon, ODB++, and IPC-2581 evidence attached.",
    )
    manifest = ProofManifest(
        name="manufacturing-proof",
        design_path="design.yaml",
        manufacturing_evidence=[manufacturing],
    )

    dumped = manifest.model_dump(mode="json")
    assert dumped["manufacturing_evidence"][0]["odbpp_status"] == "attached"
    assert dumped["manufacturing_evidence"][0]["ipc2581_status"] == "attached"


def test_evidence_bundle_json_shape(tmp_path: Path) -> None:
    generate_manufacturing_bundle(_design(), tmp_path, prefix="EvidenceBoard", fab_profile="jlcpcb-2layer")
    evidence = collect_manufacturing_evidence(tmp_path, fab_profile="jlcpcb-2layer")

    encoded = json.dumps(evidence.model_dump(mode="json"), sort_keys=True)

    assert "jlcpcb-2layer" in encoded
    assert "Manufacturing evidence is not manufacturer approval" in encoded
    assert "evidence_identity" in encoded


def test_missing_gerber_x2_validation_blocks_release(tmp_path: Path) -> None:
    path = tmp_path / "legacy.GTL"
    path.write_text("G04 legacy*\nMOMM\n%FSLAX36Y36*%\nM02*\n", encoding="utf-8")

    validation = validate_gerber_x2_file(path)

    assert validation.status == ManufacturingValidationStatus.FAIL
    assert validation.blocks_release
    assert "%TF.GenerationSoftware" in validation.details["missing_attributes"]


def test_gerber_job_file_validation(tmp_path: Path) -> None:
    path = tmp_path / "board.gbrjob"
    path.write_text('{"format":"Gerber Job File","board":{},"files":[{"path":"board.GTL"}]}\n', encoding="utf-8")

    validation = validate_gerber_job_file(path)

    assert validation.status == ManufacturingValidationStatus.PASS
    assert not validation.blocks_release


def test_unprofiled_manufacturing_bundle_requires_human_review(tmp_path: Path) -> None:
    result = generate_manufacturing_bundle(_design(), tmp_path, prefix="Unprofiled")

    evidence = collect_manufacturing_evidence(tmp_path)

    assert evidence.readiness_status == "human-review-required"
    assert evidence.blocked is True
    assert Path(result["dfm_readiness"]).is_file()


def test_proof_metadata_surfaces_odb_and_mechanical_review_attachments(tmp_path: Path) -> None:
    (tmp_path / "board-odb.zip").write_bytes(b"odb")
    (tmp_path / "board.glb").write_bytes(b"glb")
    evidence = collect_manufacturing_evidence(tmp_path)
    proof = ManufacturingProofEvidence.from_evidence_bundle(evidence)
    assert proof.odbpp_status == "attached"
    assert proof.mechanical_review_status == "attached-degraded"
