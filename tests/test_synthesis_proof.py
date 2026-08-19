"""Tests for synthesis → proof-pack integration."""

from __future__ import annotations

import json
from pathlib import Path

from zaptrace.proof import run_proof, validate_proof_pack
from zaptrace.synthesis.proof import generate_synthesis_proof

_INTENT = "USB-C powered board, 3.3V rail, I2C sensor"


class TestGenerateSynthesisProof:
    def test_writes_bundle_files(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        for fname in (
            "design.yaml",
            "proof.yaml",
            "report.json",
            "requirements_coverage.json",
            "assumptions.json",
            "kicad_schematic_parity.json",
            "kicad_pcb_parity.json",
            "ipc_d356_parity.json",
            "layout-quality.json",
        ):
            assert (tmp_path / fname).exists(), f"{fname} not written"
        report = json.loads((tmp_path / "layout-quality.json").read_text(encoding="utf-8"))
        evidence = pack.manifest.layout_quality
        assert evidence is not None
        assert evidence.policy_sha256 == report["policy_sha256"]
        assert evidence.design_state_hash == report["design_state_hash"]
        assert any(artifact.path == "layout-quality.json" for artifact in pack.manifest.artifacts)

    def test_pack_passes_at_baseline(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        # ERC/DRC baselines are snapshotted, so a freshly generated pack passes.
        assert pack.passed
        assert {r.check.name for r in pack.results} == {"erc", "drc", "footprints"}

    def test_bundle_validates(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        assert validate_proof_pack(pack.manifest, tmp_path) == []

    def test_records_synthesis_provenance(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        m = pack.manifest
        assert m.captured_intent == _INTENT
        assert m.input_record.source_type == "intent"
        assert m.input_record.normalized_intent_checksum_sha256
        assert m.agent_decisions, "synthesis decisions should be captured"
        assert all(d.actor == "zaptrace-synthesis" for d in m.agent_decisions)

    def test_reloaded_bundle_reproduces_verdict(self, tmp_path: Path) -> None:
        generated = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        # The portable audit path: load the on-disk bundle and re-run it.
        reloaded = run_proof(tmp_path)
        assert reloaded.passed == generated.passed
        gen_counts = {r.check.name: r.message for r in generated.results}
        rel_counts = {r.check.name: r.message for r in reloaded.results}
        assert gen_counts == rel_counts

    def test_report_json_is_wellformed(self, tmp_path: Path) -> None:
        generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        report = json.loads((tmp_path / "report.json").read_text())
        assert report["passed"] is True
        assert {c["name"] for c in report["checks"]} == {"erc", "drc", "footprints"}

    def test_requirements_coverage_report_is_written_and_manifested(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        report_path = tmp_path / "requirements_coverage.json"
        report = json.loads(report_path.read_text())

        assert report["schema_version"] == "1.0"
        assert report["requirements_hash"] == pack.manifest.requirements_coverage.requirements_hash
        assert pack.manifest.requirements_coverage.report_path == "requirements_coverage.json"
        assert pack.manifest.requirements_coverage.requirement_count == len(report["requirements"])
        assert any(a.path == "requirements_coverage.json" and a.kind == "report" for a in pack.manifest.artifacts)
        assert any(row["kind"] == "export" and row["id"] == "report.json" for row in report["traceability"])

    def test_assumptions_artifact_is_written_and_manifested(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        report = json.loads((tmp_path / "assumptions.json").read_text())

        assert report["schema_version"] == "1.0"
        assert pack.manifest.assumptions_evidence.report_path == "assumptions.json"
        assert pack.manifest.assumptions_evidence.assumption_count == len(report["assumptions"])
        assert pack.manifest.assumptions_evidence.unconfirmed_high_risk_count == report["unconfirmed_high_risk_count"]
        assert any(a.path == "assumptions.json" and a.kind == "report" for a in pack.manifest.artifacts)

    def test_kicad_schematic_parity_report_is_written_and_manifested(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        report = json.loads((tmp_path / "kicad_schematic_parity.json").read_text())

        assert report["schema_version"] == "1.0"
        assert report["check"] == "ir_to_kicad_schematic_netlist"
        assert pack.manifest.kicad_schematic_parity.report_path == "kicad_schematic_parity.json"
        assert pack.manifest.kicad_schematic_parity.passed == report["passed"]
        assert any(a.path == "kicad_schematic_parity.json" and a.kind == "report" for a in pack.manifest.artifacts)
        assert any(
            a.path.endswith(".kicad_netlist_evidence.json") and a.kind == "netlist" for a in pack.manifest.artifacts
        )

    def test_kicad_pcb_parity_report_is_written_and_manifested(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        report = json.loads((tmp_path / "kicad_pcb_parity.json").read_text())

        assert report["schema_version"] == "1.0"
        assert report["check"] == "kicad_schematic_to_pcb_netlist"
        assert pack.manifest.kicad_pcb_parity.report_path == "kicad_pcb_parity.json"
        assert pack.manifest.kicad_pcb_parity.passed == report["passed"]
        assert any(a.path == "kicad_pcb_parity.json" and a.kind == "report" for a in pack.manifest.artifacts)
        assert any(a.path.endswith(".kicad_pcb") and a.kind == "kicad" for a in pack.manifest.artifacts)

    def test_ipc_d356_parity_report_is_written_and_manifested(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        report = json.loads((tmp_path / "ipc_d356_parity.json").read_text())

        assert report["schema_version"] == "1.0"
        assert report["check"] == "ipc_d356_netlist"
        assert pack.manifest.ipc_d356_parity.report_path == "ipc_d356_parity.json"
        assert pack.manifest.ipc_d356_parity.passed == report["passed"]
        assert any(a.path == "ipc_d356_parity.json" and a.kind == "report" for a in pack.manifest.artifacts)
        assert any(a.path.endswith(".ipc") and a.kind == "netlist" for a in pack.manifest.artifacts)


def test_architecture_artifacts_are_written_and_manifested(tmp_path: Path) -> None:
    pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
    artifact_path = tmp_path / "electronics-architecture.json"
    trace_path = tmp_path / "architecture-traceability.json"

    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    evidence = pack.manifest.architecture_evidence

    assert artifact["status"] == "ready"
    assert trace["blocked"] is False
    assert trace["fully_traced"] is True
    assert evidence is not None
    assert evidence.artifact_path == "electronics-architecture.json"
    assert evidence.report_path == "architecture-traceability.json"
    assert evidence.artifact_sha256 == trace["artifact_sha256"]
    assert evidence.requirement_count == len(artifact["requirements"])
    assert evidence.blocked is False
    assert any(a.path == "electronics-architecture.json" and a.kind == "report" for a in pack.manifest.artifacts)
    assert any(a.path == "architecture-traceability.json" and a.kind == "report" for a in pack.manifest.artifacts)


def test_requirements_coverage_traces_architecture_exports(tmp_path: Path) -> None:
    generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
    coverage = json.loads((tmp_path / "requirements_coverage.json").read_text(encoding="utf-8"))
    traced_exports = {
        row["id"] for row in coverage["traceability"] if row["kind"] == "export" and row["requirement_ids"]
    }

    assert "electronics-architecture.json" in traced_exports
    assert "architecture-traceability.json" in traced_exports


def test_synthesis_proof_attaches_profile_bound_manufacturing_evidence(tmp_path: Path) -> None:
    pack = generate_synthesis_proof(
        _INTENT,
        tmp_path,
        name="UsbI2c",
        fab_profile="jlcpcb-2layer",
    )

    evidence = pack.manifest.manufacturing_evidence[0]
    report_path = tmp_path / str(evidence.report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert evidence.fab_profile == "jlcpcb-2layer"
    assert evidence.fab_profile_version
    assert len(evidence.fab_profile_sha256) == 64
    assert len(evidence.readiness_report_sha256) == 64
    assert evidence.artifact_sha256
    assert report["profile"]["sha256"] == evidence.fab_profile_sha256
    expected_paths = {f"manufacturing/{path}" for path in evidence.artifact_sha256}
    assert expected_paths <= {artifact.path for artifact in pack.manifest.artifacts}
    assert validate_proof_pack(pack.manifest, tmp_path) == []
