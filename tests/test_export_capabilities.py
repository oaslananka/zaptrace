from __future__ import annotations

import json
from pathlib import Path

import pytest

from zaptrace.export import (
    ExportBackend,
    ExportFormat,
    ExportSupport,
    UnsupportedExportError,
    build_export_artifact_log,
    build_export_log,
    export_capability_matrix,
    get_export_capability,
    require_export_capability,
)
from zaptrace.proof.manifest import ManufacturingExportEvidence, ProofManifest


def test_capability_matrix_documents_core_formats() -> None:
    matrix = export_capability_matrix()
    by_format = {item.format for item in matrix}

    assert ExportFormat.GERBER in by_format
    assert ExportFormat.DRILL in by_format
    assert ExportFormat.BOM in by_format
    assert ExportFormat.PICK_AND_PLACE in by_format
    assert ExportFormat.ODBPP in by_format
    assert ExportFormat.IPC2581 in by_format
    assert ExportFormat.GLB in by_format


def test_odb_and_ipc_are_external_evidence_paths() -> None:
    odb = get_export_capability(ExportFormat.ODBPP, ExportBackend.KICAD_CLI)
    ipc = get_export_capability(ExportFormat.IPC2581, ExportBackend.KICAD_CLI)

    assert odb is not None
    assert ipc is not None
    assert odb.support == ExportSupport.EXTERNAL
    assert ipc.support == ExportSupport.EXTERNAL
    assert odb.proof_pack_kind == "odbpp"
    assert ipc.proof_pack_kind == "ipc2581"


def test_unsupported_export_path_is_actionable() -> None:
    with pytest.raises(UnsupportedExportError) as excinfo:
        require_export_capability(ExportFormat.ODBPP, ExportBackend.ZAPTRACE)

    message = str(excinfo.value)
    assert "not supported" in message
    assert "external evidence" in message


def test_export_log_records_hashes_and_blocks_on_unsupported(tmp_path: Path) -> None:
    artifact = tmp_path / "board.GTL"
    artifact.write_text("G04 sample*\nMOMM\n%FSLAX36Y36*%\nM02*\n", encoding="utf-8")
    artifact_log = build_export_artifact_log(artifact, ExportFormat.GERBER, root=tmp_path)
    log = build_export_log(
        backend=ExportBackend.ZAPTRACE,
        tool_version="zaptrace-test",
        command=["zaptrace", "export", "gerber"],
        artifacts=[artifact_log],
        unsupported=["ipc2581-native-export"],
    )

    assert artifact_log.path == "board.GTL"
    assert len(artifact_log.sha256) == 64
    assert log.blocked is True
    encoded = json.dumps(log.model_dump(mode="json"), sort_keys=True)
    assert "ipc2581-native-export" in encoded


def test_proof_manifest_can_attach_manufacturing_export_evidence() -> None:
    evidence = ManufacturingExportEvidence(
        backend="kicad-cli",
        tool_version="8.0.0",
        command=["kicad-cli", "pcb", "export", "ipc2581"],
        artifact_kinds=["gerber", "excellon", "bom", "pick_and_place", "odbpp", "ipc2581"],
        report_path="reports/manufacturing-export-log.json",
        blocked=False,
    )
    manifest = ProofManifest(
        name="export-proof",
        design_path="design.yaml",
        manufacturing_exports=[evidence],
    )

    dumped = manifest.model_dump(mode="json")
    assert dumped["manufacturing_exports"][0]["artifact_kinds"][-1] == "ipc2581"
    assert dumped["manufacturing_exports"][0]["backend"] == "kicad-cli"


def test_glb_is_review_evidence_via_kicad_10() -> None:
    capability = get_export_capability(ExportFormat.GLB, ExportBackend.KICAD_CLI)
    assert capability is not None
    assert capability.support == ExportSupport.EXTERNAL
    assert capability.min_tool_version == "10.0"
    assert capability.proof_pack_kind == "mechanical_review"
    assert capability.release_blocking is False
