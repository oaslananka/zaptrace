"""Proof Pack integration for unified simulation sign-off evidence."""

from __future__ import annotations

import zipfile

import pytest

from zaptrace.analysis.simulation_signoff import (
    SimulationDomain,
    SimulationEvidenceMethod,
    SimulationFamilyReport,
    normalize_simulation_gate,
)
from zaptrace.proof import ProofManifest, attach_simulation_signoff_evidence
from zaptrace.proof.pack import ProofPack
from zaptrace.proof.simulation_signoff import _existing_model_artifact


def _report(*, engine_status: str, method: SimulationEvidenceMethod) -> SimulationFamilyReport:
    hints = ["increase output capacitance"] if engine_status == "fail" else []
    check = normalize_simulation_gate(
        check_id="simulation",
        domain=SimulationDomain.TRANSIENT,
        engine_status=engine_status,
        method=method,
        summary=f"simulation {engine_status}",
        models=[],
        repair_hints=hints,
    )
    return SimulationFamilyReport.build(
        family_id="fixture",
        title="Fixture",
        design_state_hash="a" * 64,
        models=[],
        checks=[check],
        assumptions=["fixture assumption"],
    )


def test_attach_simulation_signoff_evidence_updates_manifest_and_signoff() -> None:
    report = _report(engine_status="pass", method=SimulationEvidenceMethod.ANALYTICAL)
    manifest = ProofManifest(name="test", design_path="design.yaml")

    evidence = attach_simulation_signoff_evidence(manifest, report, report_path="simulation-signoff.json")
    decision = ProofPack(manifest=manifest).update_autonomous_signoff()

    assert manifest.simulation_signoff == evidence
    assert evidence.human_review_required is True
    assert "simulation-signoff" in decision.human_review_checks


def test_failed_simulation_signoff_blocks_proof_pack() -> None:
    report = _report(engine_status="fail", method=SimulationEvidenceMethod.NGSPICE)
    manifest = ProofManifest(name="test", design_path="design.yaml")
    attach_simulation_signoff_evidence(manifest, report, report_path="simulation-signoff.json")

    decision = ProofPack(manifest=manifest).update_autonomous_signoff()

    assert "simulation-signoff" in decision.blocking_checks


def test_unfinalized_or_tampered_report_cannot_be_attached() -> None:
    report = _report(engine_status="pass", method=SimulationEvidenceMethod.ANALYTICAL)
    report.assumptions.append("tampered")
    manifest = ProofManifest(name="test", design_path="design.yaml")

    with pytest.raises(ValueError, match="hash-valid"):
        attach_simulation_signoff_evidence(manifest, report, report_path="simulation-signoff.json")


def test_proof_attachment_includes_input_model_artifacts(tmp_path) -> None:
    from zaptrace.analysis.simulation_signoff import SimulationModelEvidence

    root = tmp_path / "artifacts"
    family = root / "fixture"
    family.mkdir(parents=True)
    model_file = family / "input-model.json"
    netlist_file = family / "input-model.spice"
    model_file.write_text("{}\n", encoding="utf-8")
    netlist_file.write_text("* model\n.end\n", encoding="utf-8")
    report = _report(engine_status="pass", method=SimulationEvidenceMethod.ANALYTICAL)
    report.models = [
        SimulationModelEvidence(
            model_id="fixture-model",
            source="fixture:test",
            version="1.0",
            model_sha256="b" * 64,
            method=SimulationEvidenceMethod.ANALYTICAL,
            binding="family-fixture",
            degraded=True,
            confidence=0.6,
            artifact_path="fixture/input-model.json",
            netlist_path="fixture/input-model.spice",
            netlist_sha256="c" * 64,
        )
    ]
    report.report_sha256 = report.compute_sha256()
    report_path = family / "simulation-signoff.json"
    from zaptrace.analysis.simulation_signoff import simulation_family_report_json

    report_path.write_text(simulation_family_report_json(report), encoding="utf-8")
    manifest = ProofManifest(name="test", design_path="design.yaml")

    attach_simulation_signoff_evidence(
        manifest,
        report,
        report_path=report_path,
        artifact_root=root,
    )

    assert manifest.references["simulation-models/fixture/input-model.json"] == str(model_file)
    assert manifest.references["simulation-models/fixture/input-model.spice"] == str(netlist_file)
    archive = ProofPack(manifest=manifest, base_path=tmp_path).bundle(tmp_path / "bundle")
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
    assert "artifacts/simulation-signoff.json" in names
    assert "artifacts/simulation-models/fixture/input-model.json" in names
    assert "artifacts/simulation-models/fixture/input-model.spice" in names


def test_existing_model_artifact_resolves_relative_and_absolute_paths(tmp_path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    relative = root / "model.json"
    absolute = tmp_path / "absolute.spice"
    relative.write_text("{}\n", encoding="utf-8")
    absolute.write_text("* model\n.end\n", encoding="utf-8")

    assert _existing_model_artifact("model.json", root) == relative
    assert _existing_model_artifact(str(absolute), root) == absolute
    assert _existing_model_artifact("", root) is None
    assert _existing_model_artifact("missing.json", root) is None
