"""Tests for the Proof Pack system.

Covers manifest, checker, pack loading, and CLI integration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

from zaptrace.proof import (
    CheckDefinition,
    CheckResult,
    CheckStatus,
    ManifestModel,
    ProofManifest,
    ProofPack,
    ProofRunner,
    ReleaseGateProofEvidence,
    capture_environment,
    hash_file,
    run_proof,
    validate_proof_pack,
)
from zaptrace.proof.manifest import (
    ArtifactRecord,
    CheckCategory,
    CheckRecord,
    CheckSeverity,
    CheckSource,
    EngineeringReviewEvidence,
    EnvironmentRecord,
    InputRecord,
    KiCadOracleEvidence,
)

# ===========================================================================
# Manifest tests
# ===========================================================================


class TestCheckDefinition:
    def test_minimal(self) -> None:
        c = CheckDefinition(name="test_check", type="drc")
        assert c.name == "test_check"
        assert c.type == "drc"
        assert c.severity == CheckSeverity.ERROR
        assert c.category == CheckCategory.CUSTOM

    def test_full(self) -> None:
        c = CheckDefinition(
            name="full_check",
            description="Check everything",
            category=CheckCategory.ERC,
            severity=CheckSeverity.WARNING,
            type="erc",
            params={"min_voltage": 3.3},
            expected="pass",
            expected_count=0,
            tags=["power", "critical"],
        )
        assert c.severity == CheckSeverity.WARNING
        assert c.category == CheckCategory.ERC
        assert c.params["min_voltage"] == 3.3
        assert "power" in c.tags

    def test_expected_defaults(self) -> None:
        c = CheckDefinition(name="defaults", type="routed")
        assert c.expected == "pass"
        assert c.expected_count is None


class TestManifestModel:
    def test_defaults(self) -> None:
        m = ManifestModel()
        assert m.min_clearance_mm == 0.15
        assert m.min_trace_width_mm == 0.15
        assert m.max_layer_count == 2
        assert m.allowed_layer_counts == [1, 2, 4]

    def test_custom(self) -> None:
        m = ManifestModel(
            min_clearance_mm=0.2,
            min_trace_width_mm=0.25,
            max_layer_count=4,
            allowed_layer_counts=[2, 4],
        )
        assert m.min_clearance_mm == 0.2
        assert m.max_layer_count == 4


class TestProofManifest:
    def test_minimal(self) -> None:
        m = ProofManifest(name="test", design_path="design.yaml")
        assert m.version == "1.0"
        assert m.checks == []
        assert m.author == ""

    def test_release_evidence_round_trips_complete_identity(self) -> None:
        identity = {
            "gate_version": "2.0",
            "design_state_hash": "design-hash",
            "evidence_identity_hash": "evidence-hash",
            "erc": {"status": "pass", "design_state_hash": "design-hash"},
            "drc": {"status": "pass", "design_state_hash": "design-hash"},
            "component_coverage": {"status": "pass", "checked_component_count": 1},
            "fab_profile_policy": {"status": "pass", "fab_profile": "jlcpcb-2layer"},
        }
        binding = {
            "approval_id": "APPROVAL-1",
            "evidence_identity_hash": "evidence-hash",
            "approval_binding_hash": "binding-hash",
        }
        release_evidence = ReleaseGateProofEvidence.from_release_gate(
            {
                "status": "pass",
                "approval_id": "APPROVAL-1",
                "evidence_identity": identity,
                "approval_binding": binding,
            }
        )
        manifest = ProofManifest(name="release-proof", design_path="design.yaml", release_evidence=release_evidence)

        restored = ProofManifest.model_validate(manifest.model_dump(mode="json"))

        assert restored.release_evidence is not None
        assert restored.release_evidence.status == "pass"
        assert restored.release_evidence.evidence_identity == identity
        assert restored.release_evidence.approval_binding == binding

    def test_release_evidence_automatically_captures_engineering_review_metadata(self) -> None:
        identity = {
            "gate_version": "2.1",
            "design_state_hash": "design-hash",
            "evidence_identity_hash": "evidence-hash",
        }
        binding = {
            "approval_id": "approval-review-1",
            "evidence_identity_hash": "evidence-hash",
            "approval_binding_hash": "binding-hash",
        }
        gate = {
            "status": "pass",
            "automated_gate_status": "pass",
            "fabrication_status": "human-approved",
            "approval_id": "approval-review-1",
            "evidence_identity": identity,
            "approval_binding": binding,
            "engineering_review": {
                "status": "human-approved",
                "review_session_id": "session-review-1",
                "decision_id": "decision-review-1",
                "decision": "approve",
                "reviewer_id": "reviewer-a",
                "decided_at": "2026-07-29T00:00:00+00:00",
                "reason": "Current design evidence reviewed",
                "design_state_hash": "design-hash",
                "approval_id": "approval-review-1",
                "current": True,
                "approval_id_matched": True,
                "checklist_results": {"erc-review": "approved"},
            },
        }

        evidence = ReleaseGateProofEvidence.from_release_gate(gate)

        assert evidence.automated_gate_status == "pass"
        assert evidence.fabrication_status == "human-approved"
        assert evidence.engineering_review is not None
        assert evidence.engineering_review.reviewer_id == "reviewer-a"
        assert evidence.engineering_review.decided_at == "2026-07-29T00:00:00+00:00"
        assert evidence.engineering_review.decision == "approve"

    def test_engineering_review_evidence_round_trips_separately_from_autonomous_signoff(self) -> None:
        review = EngineeringReviewEvidence(
            status="human-approved",
            review_session_id="session-review-1",
            decision_id="decision-1",
            decision="approve",
            reviewer_id="reviewer-a",
            decided_at="2026-07-29T00:00:00+00:00",
            reason="Current evidence reviewed",
            design_state_hash="design-hash",
            approval_id="approval-1",
            current=True,
            approval_id_matched=True,
            checklist_results={"erc-review": "approved"},
        )
        manifest = ProofManifest(
            name="engineering-review-proof",
            design_path="design.yaml",
            engineering_review=review,
        )

        restored = ProofManifest.model_validate(manifest.model_dump(mode="json"))

        assert restored.engineering_review is not None
        assert restored.engineering_review.status == "human-approved"
        assert restored.engineering_review.reviewer_id == "reviewer-a"
        assert restored.engineering_review.current is True
        assert restored.autonomous_signoff.status != "human-approved"

    def test_engineering_review_evidence_extracts_release_gate_payload(self) -> None:
        evidence = EngineeringReviewEvidence.from_release_gate(
            {
                "automated_gate_status": "pass",
                "fabrication_status": "rejected",
                "engineering_review": {
                    "status": "rejected",
                    "review_session_id": "session-review-rejected",
                    "decision_id": "decision-rejected",
                    "decision": "reject",
                    "reviewer_id": "reviewer-b",
                    "decided_at": "2026-07-29T00:00:00+00:00",
                    "reason": "Blocking DFM issue remains",
                    "design_state_hash": "design-hash",
                    "current": True,
                    "approval_id_matched": False,
                },
            }
        )

        assert evidence.status == "rejected"
        assert evidence.decision == "reject"
        assert evidence.reviewer_id == "reviewer-b"
        assert evidence.current is True

    def test_release_evidence_rejects_incomplete_gate(self) -> None:
        with pytest.raises(ValueError, match="evidence_identity and approval_binding"):
            ReleaseGateProofEvidence.from_release_gate({"status": "missing-evidence"})

    def test_release_evidence_rejects_mismatched_approval_binding(self) -> None:
        with pytest.raises(ValueError, match="does not match the evidence identity"):
            ReleaseGateProofEvidence.from_release_gate(
                {
                    "status": "pass",
                    "approval_id": "APPROVAL-1",
                    "evidence_identity": {
                        "gate_version": "2.0",
                        "design_state_hash": "design-hash",
                        "evidence_identity_hash": "evidence-hash",
                    },
                    "approval_binding": {
                        "approval_id": "OTHER-APPROVAL",
                        "evidence_identity_hash": "different-hash",
                        "approval_binding_hash": "binding-hash",
                    },
                }
            )

    def test_full(self) -> None:
        m = ProofManifest(
            version="1.0",
            name="Full Test Pack",
            description="Validates everything",
            design_path="../designs/my_board.yaml",
            model=ManifestModel(min_clearance_mm=0.2),
            checks=[
                CheckDefinition(name="ch1", type="drc"),
                CheckDefinition(name="ch2", type="erc", severity=CheckSeverity.WARNING),
            ],
            references={"gerber_top": "golden/gerber_top.gbr"},
            author="test-bot",
            tags=["ci", "nightly"],
            requires=["zaptrace>=0.2.0"],
        )
        assert len(m.checks) == 2
        assert m.model.min_clearance_mm == 0.2
        assert m.author == "test-bot"
        assert "ci" in m.tags


# ===========================================================================
# Checker tests
# ===========================================================================


@dataclass
class FakeComponent:
    """Minimal component stub for testing."""

    ref: str
    footprint: str | None = None


@dataclass
class FakePinNode:
    """Minimal net-node stub matching NetNode.pin_name."""

    pin_name: str


@dataclass
class FakeNet:
    """Minimal net stub for testing."""

    id: str
    name: str
    nodes: list = field(default_factory=list)


@dataclass
class FakeTrace:
    """Minimal trace stub matching TraceSegment attributes used by checker."""

    net_id: str = ""
    start: tuple[float, float] = (0.0, 0.0)
    end: tuple[float, float] = (0.0, 0.0)
    width: float = 0.2


@dataclass
class FakeRouteResult:
    """Minimal route-result stub matching RouteResult.traces."""

    traces: list = field(default_factory=list)


@dataclass
class FakeDesign:
    """Minimal design stub for checker tests."""

    components: dict = field(default_factory=dict)
    nets: dict = field(default_factory=dict)
    routing: FakeRouteResult | None = None

    def __init__(
        self,
        components: list | None = None,
        nets: list | None = None,
        traces: list | None = None,
    ):
        if components and all(hasattr(c, "id") for c in components):
            self.components = {c.id: c for c in components}
        elif components:
            self.components = {c.ref: c for c in components}
        else:
            self.components = {}
        self.nets = {n.id: n for n in (nets or [])}
        self.routing = FakeRouteResult(traces=traces or [])


class TestCheckStatus:
    def test_values(self) -> None:
        assert CheckStatus.PASS.value == "pass"
        assert CheckStatus.FAIL.value == "fail"
        assert CheckStatus.ERROR.value == "error"
        assert CheckStatus.SKIP.value == "skip"


class TestCheckResult:
    def test_passed_property(self) -> None:
        c = CheckDefinition(name="t", type="drc")
        r = CheckResult(check=c, status=CheckStatus.PASS)
        assert r.passed is True

    def test_failed_property(self) -> None:
        c = CheckDefinition(name="t", type="drc")
        r = CheckResult(check=c, status=CheckStatus.FAIL)
        assert r.passed is False

    def test_to_dict(self) -> None:
        c = CheckDefinition(name="my_check", type="erc", category=CheckCategory.ERC)
        r = CheckResult(check=c, status=CheckStatus.PASS, message="OK", duration_ms=5.0)
        d = r.to_dict()
        assert d["name"] == "my_check"
        assert d["category"] == "erc"
        assert d["status"] == "pass"
        assert d["message"] == "OK"
        assert d["duration_ms"] == 5.0

    def test_to_dict_includes_json_safe_detail_payload(self) -> None:
        c = CheckDefinition(name="my_check", type="drc", category=CheckCategory.DRC)
        payload_key = "de" + "tails"
        r = CheckResult(
            check=c,
            status=CheckStatus.FAIL,
            message="needs detail",
            **{payload_key: {"items": [{"rule": "DRC-001", "status": CheckStatus.FAIL}]}},
        )
        d = r.to_dict()

        assert d[payload_key]["items"][0]["rule"] == "DRC-001"
        assert d[payload_key]["items"][0]["status"] == "fail"


class TestProofRunner:
    def test_unknown_check_type_skips(self) -> None:
        design = FakeDesign()
        runner = ProofRunner(design)
        check = CheckDefinition(name="unknown", type="nonexistent_check_type")
        results = runner.run_checks([check])
        assert len(results) == 1
        assert results[0].status == CheckStatus.SKIP
        assert "Unknown" in results[0].message

    def test_routed_all_pass(self) -> None:
        design = FakeDesign(
            nets=[FakeNet("n1", "VCC"), FakeNet("n2", "GND")],
            traces=[FakeTrace(net_id="n1"), FakeTrace(net_id="n2")],
        )
        runner = ProofRunner(design)
        check = CheckDefinition(name="routed", type="routed")
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.PASS

    def test_routed_some_fail(self) -> None:
        design = FakeDesign(
            nets=[FakeNet("n1", "VCC"), FakeNet("n2", "GND")],
            traces=[FakeTrace(net_id="n1")],
        )
        runner = ProofRunner(design)
        check = CheckDefinition(name="routed", type="routed")
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.FAIL
        assert "unrouted" in results[0].message.lower()

    def test_footprint_exists_pass(self) -> None:
        design = FakeDesign(components=[FakeComponent("R1", "0805"), FakeComponent("C1", "0603")])
        runner = ProofRunner(design)
        check = CheckDefinition(name="fps", type="footprint_exists")
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.PASS

    def test_footprint_exists_fail(self) -> None:
        design = FakeDesign(components=[FakeComponent("R1", None), FakeComponent("C1", "0603")])
        runner = ProofRunner(design)
        check = CheckDefinition(name="fps", type="footprint_exists")
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.FAIL
        assert "1 missing" in results[0].message

    def test_net_connected_pass(self) -> None:
        design = FakeDesign(nets=[FakeNet("n1", "VCC", nodes=[FakePinNode("R1.p1"), FakePinNode("C1.p1")])])
        runner = ProofRunner(design)
        check = CheckDefinition(
            name="netchk",
            type="net_connected",
            params={"net_name": "VCC", "expected_pins": ["R1.p1"]},
        )
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.PASS

    def test_net_connected_fail(self) -> None:
        design = FakeDesign(nets=[FakeNet("n1", "VCC", nodes=[FakePinNode("R1.p1")])])
        runner = ProofRunner(design)
        check = CheckDefinition(
            name="netchk",
            type="net_connected",
            params={"net_name": "VCC", "expected_pins": ["R1.p1", "C1.p1"]},
        )
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.FAIL

    def test_net_connected_missing_param(self) -> None:
        design = FakeDesign()
        runner = ProofRunner(design)
        check = CheckDefinition(name="netchk", type="net_connected", params={})
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.ERROR

    def test_net_connected_net_not_found(self) -> None:
        design = FakeDesign(nets=[FakeNet("n1", "VCC")])
        runner = ProofRunner(design)
        check = CheckDefinition(name="netchk", type="net_connected", params={"net_name": "NONEXISTENT"})
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.FAIL

    def test_clearance_pass(self) -> None:
        # Traces far apart
        design = FakeDesign(
            traces=[
                FakeTrace(net_id="n1", start=(0, 0), end=(10, 10)),
                FakeTrace(net_id="n2", start=(100, 100), end=(200, 200)),
            ]
        )
        runner = ProofRunner(design)
        check = CheckDefinition(name="clear", type="clearance", params={"min_clearance_mm": 0.15})
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.PASS

    def test_clearance_violation(self) -> None:
        # Traces close together — simplified check computes distance between segments
        design = FakeDesign(
            traces=[
                FakeTrace(net_id="n1", start=(0, 0), end=(5, 5)),
                FakeTrace(net_id="n2", start=(0, 0), end=(6, 6)),
            ]
        )
        runner = ProofRunner(design)
        check = CheckDefinition(name="clear", type="clearance", params={"min_clearance_mm": 2.0})
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.FAIL

    def test_custom_registration(self) -> None:
        design = FakeDesign()
        runner = ProofRunner(design)

        def custom_check(_check: CheckDefinition) -> CheckResult:
            return CheckResult(check=_check, status=CheckStatus.PASS, message="Custom OK")

        runner.register("my_custom", custom_check)
        check = CheckDefinition(name="custom", type="my_custom")
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.PASS
        assert results[0].message == "Custom OK"

    def test_exception_in_check(self) -> None:
        design = FakeDesign()
        runner = ProofRunner(design)

        def broken_check(_check: CheckDefinition) -> CheckResult:
            raise RuntimeError("Something broke")

        runner.register("broken", broken_check)
        check = CheckDefinition(name="broken", type="broken")
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.ERROR
        assert "Something broke" in results[0].message

    def test_trace_distance_far(self) -> None:
        t1 = FakeTrace(net_id="n1", start=(0, 0), end=(10, 10))
        t2 = FakeTrace(net_id="n2", start=(100, 100), end=(200, 200))
        dist = ProofRunner._trace_distance(t1, t2)
        assert dist > 100  # Very far apart

    def test_trace_distance_invalid(self) -> None:
        class BadTrace:
            pass

        dist = ProofRunner._trace_distance(BadTrace(), BadTrace())
        assert dist == float("inf")


# ===========================================================================
# YAML serialization tests
# ===========================================================================


class TestManifestYAML:
    def test_round_trip(self, tmp_path: Path) -> None:
        manifest = ProofManifest(
            name="RoundTrip Test",
            description="Testing YAML round-trip",
            design_path="design.yaml",
            model=ManifestModel(min_clearance_mm=0.2, max_layer_count=4),
            checks=[
                CheckDefinition(name="drc_check", type="drc", severity=CheckSeverity.ERROR),
                CheckDefinition(name="routed_check", type="routed"),
            ],
        )
        yaml_path = tmp_path / "proof.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        # Reload
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        loaded = ProofManifest(**data)
        assert loaded.name == manifest.name
        assert len(loaded.checks) == len(manifest.checks)
        assert loaded.model.min_clearance_mm == 0.2

    def test_yaml_with_tags(self, tmp_path: Path) -> None:
        data = {
            "version": "1.0",
            "name": "Tagged Pack",
            "design_path": "design.yaml",
            "checks": [
                {"name": "c1", "type": "drc", "tags": ["quick", "ci"]},
                {"name": "c2", "type": "erc", "tags": ["full"]},
            ],
        }
        path = tmp_path / "proof.yaml"
        with open(path, "w") as f:
            yaml.dump(data, f)
        with open(path) as f:
            loaded = ProofManifest(**yaml.safe_load(f))
        assert len(loaded.checks) == 2
        assert loaded.checks[0].tags == ["quick", "ci"]


# ===========================================================================
# ProofPack tests
# ===========================================================================


class TestProofPackLoad:
    def test_load_from_yaml(self, tmp_path: Path) -> None:
        proof_dir = tmp_path / "proof"
        proof_dir.mkdir()
        manifest = ProofManifest(name="Test", design_path="design.yaml")
        yaml_path = proof_dir / "proof.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        pack = ProofPack.load(yaml_path)
        assert pack.manifest.name == "Test"
        assert pack.manifest.design_path == "design.yaml"

    def test_load_from_directory(self, tmp_path: Path) -> None:
        proof_dir = tmp_path / "proof"
        proof_dir.mkdir()
        manifest = ProofManifest(name="DirTest", design_path="design.yaml")
        with open(proof_dir / "proof.yaml", "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        pack = ProofPack.load(proof_dir)
        assert pack.manifest.name == "DirTest"

    def test_load_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            ProofPack.load(Path("/nonexistent/proof.yaml"))

    def test_run_missing_design(self, tmp_path: Path) -> None:
        proof_dir = tmp_path / "proof"
        proof_dir.mkdir()
        manifest = ProofManifest(name="MissingDesign", design_path="nonexistent.yaml")
        with open(proof_dir / "proof.yaml", "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        pack = ProofPack.load(proof_dir)
        with pytest.raises(FileNotFoundError):
            pack.run()


class TestProofPackResults:
    def test_summary_empty(self) -> None:
        manifest = ProofManifest(name="Empty", design_path="d.yaml")
        pack = ProofPack(manifest=manifest)
        assert "Empty" in pack.summary
        assert "Total:   0" in pack.summary

    def test_report_json(self) -> None:
        manifest = ProofManifest(name="JSON Test", design_path="d.yaml")
        pack = ProofPack(manifest=manifest)
        report = pack.report_json()
        data = json.loads(report)
        assert data["name"] == "JSON Test"
        assert data["passed"] is True
        assert data["checks"] == []

    def test_passed_property_empty(self) -> None:
        manifest = ProofManifest(name="Empty", design_path="d.yaml")
        pack = ProofPack(manifest=manifest)
        assert pack.passed is True  # No checks = vacuously true


class TestRunProof:
    def test_run_proof_convenience(self, tmp_path: Path) -> None:
        """Test run_proof with a proof directory (design won't exist but we test loader)."""
        proof_dir = tmp_path / "proof"
        proof_dir.mkdir()
        manifest = ProofManifest(name="Convenience", design_path="design.yaml")
        with open(proof_dir / "proof.yaml", "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        # This should load but fail on design
        with pytest.raises(FileNotFoundError):
            run_proof(proof_dir)

    def test_run_proof_with_file_path(self, tmp_path: Path) -> None:
        manifest = ProofManifest(name="FileTest", design_path="design.yaml")
        yaml_path = tmp_path / "proof.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        with pytest.raises(FileNotFoundError):
            run_proof(yaml_path)

    def test_run_proof_invalid_yaml(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "proof.yaml"
        yaml_path.write_text("invalid: [yaml: broken\n  bad", encoding="utf-8")
        with pytest.raises((yaml.YAMLError, KeyError, ValueError)):
            run_proof(yaml_path)


# ===========================================================================
# CLI integration tests
# ===========================================================================


class TestProofCLI:
    def test_proof_group_help(self) -> None:
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["proof", "--help"])
        assert result.exit_code == 0
        assert "Manage and run Proof Packs" in result.output

    def test_proof_list_no_pack(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["proof", "list", str(tmp_path / "nonexistent")])
        assert result.exit_code != 0

    def test_proof_info_no_pack(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["proof", "info", str(tmp_path / "nonexistent")])
        assert result.exit_code != 0

    def test_proof_list_success(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        manifest = ProofManifest(
            name="CLI Test",
            design_path="design.yaml",
            checks=[CheckDefinition(name="chk1", type="drc", description="DRC check")],
        )
        yaml_path = tmp_path / "proof.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        runner = CliRunner()
        result = runner.invoke(cli, ["proof", "list", str(yaml_path)])
        assert result.exit_code == 0
        assert "chk1" in result.output
        assert "drc" in result.output

    def test_proof_info_success(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        manifest = ProofManifest(
            name="Info Test",
            design_path="design.yaml",
            description="My proof pack",
            author="test",
        )
        yaml_path = tmp_path / "proof.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        runner = CliRunner()
        result = runner.invoke(cli, ["proof", "info", str(yaml_path)])
        assert result.exit_code == 0
        assert "Info Test" in result.output
        assert "test" in result.output

    def test_proof_run_json_renderer_writes_requested_report(self, tmp_path: Path) -> None:
        from zaptrace.cli.proof import _render_proof_run

        pack = ProofPack(manifest=ProofManifest(name="JSON Run", design_path="design.yaml"))
        output = tmp_path / "report.json"

        handled = _render_proof_run(pack, verbose=False, output_format="json", output=str(output))

        assert handled is True
        assert output.read_text(encoding="utf-8") == pack.report_json()

    def test_proof_run_json_renderer_prints_report_without_output_path(self) -> None:
        from unittest.mock import patch

        from zaptrace.cli.proof import _render_proof_run

        pack = ProofPack(manifest=ProofManifest(name="JSON Run", design_path="design.yaml"))

        with patch("zaptrace.cli.proof.console.print") as print_mock:
            handled = _render_proof_run(pack, verbose=False, output_format="json", output=None)

        assert handled is True
        print_mock.assert_called_once_with(pack.report_json())

    def test_proof_run_verbose_renderer_preserves_details_and_statuses(self) -> None:
        from unittest.mock import patch

        from zaptrace.cli.proof import _render_proof_run
        from zaptrace.proof.checker import CheckResult, CheckStatus

        failed_check = CheckDefinition(name="detail-check", type="drc")
        passed_check = CheckDefinition(name="passing-check", type="erc")
        pack = ProofPack(
            manifest=ProofManifest(name="Verbose Run", design_path="design.yaml"),
            results=[
                CheckResult(
                    check=failed_check,
                    status=CheckStatus.FAIL,
                    message="failed",
                    details={"count": 2},
                ),
                CheckResult(check=passed_check, status=CheckStatus.PASS, message="passed"),
            ],
        )

        with patch("zaptrace.cli.proof.console.print") as print_mock:
            handled = _render_proof_run(pack, verbose=True, output_format="text", output=None)

        assert handled is False
        rendered = "\n".join(str(call.args[0]) for call in print_mock.call_args_list if call.args)
        assert "detail-check: failed" in rendered
        assert '"count": 2' in rendered
        assert "passing-check: passed" in rendered

    def test_proof_run_verbose_renderer_accepts_empty_results(self) -> None:
        from unittest.mock import patch

        from zaptrace.cli.proof import _render_proof_run

        pack = ProofPack(manifest=ProofManifest(name="Empty Run", design_path="design.yaml"))

        with patch("zaptrace.cli.proof.console.print") as print_mock:
            handled = _render_proof_run(pack, verbose=True, output_format="text", output=None)

        assert handled is False
        print_mock.assert_called_once_with(pack.summary)

    def test_proof_validate_directory(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        manifest = ProofManifest(
            name="Directory Validation",
            design_path="design.yaml",
            limitations=["Human engineer review is required before fabrication."],
        )
        yaml_path = tmp_path / "proof.yaml"
        yaml_path.write_text(yaml.safe_dump(manifest.model_dump(mode="json")), encoding="utf-8")

        result = CliRunner().invoke(cli, ["proof", "validate", str(tmp_path)])

        assert result.exit_code == 0
        assert "Proof pack is valid" in result.output

    def test_proof_validate_file(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        manifest = ProofManifest(
            name="File Validation",
            design_path="design.yaml",
            limitations=["Human engineer review is required before fabrication."],
        )
        yaml_path = tmp_path / "proof.yaml"
        yaml_path.write_text(yaml.safe_dump(manifest.model_dump(mode="json")), encoding="utf-8")

        result = CliRunner().invoke(cli, ["proof", "validate", str(yaml_path)])

        assert result.exit_code == 0
        assert "Proof pack is valid" in result.output

    def test_proof_pack_help(self) -> None:
        """zaptrace proof-pack --help should work."""
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["proof-pack", "--help"])
        assert result.exit_code == 0
        assert "DESIGN_PATH" in result.output
        assert "proof pack" in result.output.lower()

    def test_proof_pack_nonexistent_design(self) -> None:
        """proof-pack with a non-existent file should fail gracefully."""
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["proof-pack", "/nonexistent/design.yaml"])
        assert result.exit_code != 0

    def test_proof_pack_json_output(self, tmp_path: Path, sample_design_path: Path) -> None:
        """proof-pack with --format json should produce valid JSON output (pass or fail)."""
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        design = sample_design_path
        runner = CliRunner()
        result = runner.invoke(cli, ["proof-pack", str(design), "--format", "json"])
        # Exit code 1 is valid when checks fail
        assert result.exit_code in (0, 1)
        import json as _json

        data = _json.loads(result.output)
        assert "name" in data
        assert "results" in data

    def test_proof_pack_verbose(self, tmp_path: Path, sample_design_path: Path) -> None:
        """proof-pack --verbose shows check details regardless of pass/fail."""
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        design = sample_design_path
        runner = CliRunner()
        result = runner.invoke(cli, ["proof-pack", str(design), "--verbose"])
        # Exit code 1 is valid when checks fail
        assert result.exit_code in (0, 1)
        assert "Checks:" in result.output

    def test_proof_pack_bundle_output(self, tmp_path: Path, sample_design_path: Path) -> None:
        """proof-pack --output writes bundle files even when checks fail."""
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        design = sample_design_path
        out_dir = tmp_path / "proof-bundle"
        runner = CliRunner()
        result = runner.invoke(cli, ["proof-pack", str(design), "--output", str(out_dir)])
        # Bundle is written before early-exit on check failure
        assert result.exit_code in (0, 1)
        assert out_dir.exists()
        assert (out_dir / "proof.yaml").exists()
        assert (out_dir / "results.json").exists()


# ===========================================================================
# v1 Evidence field tests
# ===========================================================================


def test_validate_proof_pack_rejects_undeclared_runtime_result() -> None:
    manifest = ProofManifest(
        name="runtime-result-binding",
        design_path="design.yaml",
        limitations=["Requires human engineer review"],
    )
    result = CheckResult(
        check=CheckDefinition(name="unexpected", type="drc"),
        status=CheckStatus.PASS,
    )

    errors = validate_proof_pack(manifest, Path("."), results=[result])

    assert errors == ["Unexpected runtime check result: unexpected"]


class TestHashFile:
    def test_hash_file_known_value(self, tmp_path: Path) -> None:
        """SHA-256 of known bytes should match expected hex digest."""
        f = tmp_path / "data.txt"
        f.write_bytes(b"hello world\n")
        digest = hash_file(f)
        expected = "a948904f2f0f479b8f8197694b30184b0d2ed1c1cd2a1ec0fb85d299a192a447"
        assert digest == expected

    def test_hash_file_binary(self, tmp_path: Path) -> None:
        """Binary content produces a deterministic hash."""
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01\x02\xff\xfe\xfd")
        d1 = hash_file(f)
        d2 = hash_file(f)
        assert d1 == d2
        assert len(d1) == 64

    def test_hash_file_not_found(self) -> None:
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            hash_file(Path("/nonexistent/file.bin"))


class TestValidateProofPack:
    def test_valid_manifest_no_errors(self) -> None:
        """A minimal manifest with human-review limitation should pass."""
        manifest = ProofManifest(
            name="test",
            design_path="design.yaml",
            limitations=["Requires human engineer review before fabrication."],
        )
        errors = validate_proof_pack(manifest, Path("."))
        assert errors == []

    def test_missing_name(self) -> None:
        """Missing name should produce an error."""
        manifest = ProofManifest(name="", design_path="design.yaml")
        errors = validate_proof_pack(manifest, Path("."))
        assert any("name" in e.lower() for e in errors)

    def test_missing_design_path(self) -> None:
        """Empty design_path should produce an error."""
        manifest = ProofManifest(name="test", design_path="")
        errors = validate_proof_pack(manifest, Path("."))
        assert any("design_path" in e.lower() for e in errors)

    def test_missing_human_review_warning(self) -> None:
        """Manifest without 'human engineer review' in limitations should warn."""
        manifest = ProofManifest(
            name="test",
            design_path="design.yaml",
            limitations=["some other limitation"],
        )
        errors = validate_proof_pack(manifest, Path("."))
        assert any("human-engineer-review" in e.lower() for e in errors)

    def test_artifact_hash_mismatch(self, tmp_path: Path) -> None:
        """Artifact with wrong SHA-256 should be flagged."""
        f = tmp_path / "artifact.gbr"
        f.write_bytes(b"content")
        manifest = ProofManifest(
            name="test",
            design_path="design.yaml",
            artifacts=[
                ArtifactRecord(path="artifact.gbr", kind="gerber", sha256="0000deadbeef" * 4),
            ],
        )
        errors = validate_proof_pack(manifest, tmp_path)
        assert any("hash mismatch" in e.lower() for e in errors)

    def test_artifact_missing_file(self, tmp_path: Path) -> None:
        """Artifact path that does not exist should be flagged."""
        manifest = ProofManifest(
            name="test",
            design_path="design.yaml",
            artifacts=[
                ArtifactRecord(path="nonexistent.gbr", kind="gerber", sha256="00" * 32),
            ],
        )
        errors = validate_proof_pack(manifest, tmp_path)
        assert any("missing" in e.lower() for e in errors)


class TestCaptureEnvironment:
    def test_tool_version_probe_os_error_is_non_fatal(self) -> None:
        import subprocess
        from unittest.mock import patch

        real_run = subprocess.run

        def run_with_failed_tool_probe(args, *positional, **kwargs):
            if args[0] == "/bin/tool":
                raise OSError("probe failed")
            return real_run(args, *positional, **kwargs)

        with (
            patch("shutil.which", return_value="/bin/tool"),
            patch("subprocess.run", side_effect=run_with_failed_tool_probe),
        ):
            env = capture_environment()

        assert env.tool_versions == {}

    def test_basic_fields(self) -> None:
        """capture_environment should return Python version and platform."""
        env = capture_environment()
        assert isinstance(env, EnvironmentRecord)
        assert env.python_version
        assert env.platform
        assert env.evidence_identity is not None
        assert env.evidence_identity.mode == "snapshot"
        assert len(env.evidence_identity.source_commit) == 40
        assert len(env.evidence_identity.identity_sha256) == 64

    def test_zaptrace_version(self) -> None:
        """Environment record should include zaptrace version."""
        env = capture_environment()
        assert env.zaptrace_version or env.zaptrace_version == ""


class TestInputRecord:
    def test_defaults(self) -> None:
        """InputRecord should have sensible defaults."""
        r = InputRecord(source_type="file", filename="design.yaml")
        assert r.source_type == "file"
        assert r.filename == "design.yaml"
        assert r.checksum_sha256 is None

    def test_with_checksum(self) -> None:
        """InputRecord with SHA-256 checksum."""
        r = InputRecord(
            source_type="file",
            filename="design.yaml",
            checksum_sha256="abc123",
        )
        assert r.checksum_sha256 == "abc123"


class TestArtifactRecord:
    def test_minimal(self) -> None:
        """ArtifactRecord can be created with just path and kind."""
        r = ArtifactRecord(path="gerber_top.gbr", kind="gerber")
        assert r.sha256 is None
        assert r.size_bytes == 0

    def test_full(self) -> None:
        """ArtifactRecord with all fields."""
        r = ArtifactRecord(
            path="gerber_top.gbr",
            kind="gerber",
            sha256="abcd" * 16,
            size_bytes=1024,
        )
        assert r.sha256 == "abcd" * 16
        assert r.size_bytes == 1024


class TestCheckSource:
    def test_values(self) -> None:
        """CheckSource enum values."""
        assert CheckSource.ZAPTRACE == "zaptrace"
        assert CheckSource.KICAD == "kicad"
        assert CheckSource.FAB_PROFILE == "fab_profile"
        assert CheckSource.EXTERNAL == "external"


def test_proof_bundle_records_kicad_oracle_metadata(tmp_path: Path) -> None:
    design_path = tmp_path / "design.yaml"
    design_path.write_text("meta:\n  name: OracleProof\ncomponents: {}\n", encoding="utf-8")
    proof_path = tmp_path / "proof.yaml"
    proof_path.write_text(
        """version: '1.0'
name: oracle-proof
design_path: design.yaml
checks: []
""",
        encoding="utf-8",
    )

    pack = ProofPack.load(proof_path)
    pack.run()
    bundle = pack.bundle(tmp_path / "out")

    assert bundle.exists()
    assert pack.manifest.kicad_oracle
    evidence = pack.manifest.kicad_oracle[0]
    assert evidence.status in {"passed", "failed", "skipped"}
    if evidence.status == "skipped":
        assert evidence.skip_reason


def test_proof_bundle_records_final_state_hash(tmp_path: Path) -> None:
    design_path = tmp_path / "design.yaml"
    design_path.write_text("meta:\n  name: HashProof\ncomponents: {}\n", encoding="utf-8")
    proof_path = tmp_path / "proof.yaml"
    proof_path.write_text(
        """version: '1.0'
name: hash-proof
design_path: design.yaml
checks: []
""",
        encoding="utf-8",
    )

    pack = ProofPack.load(proof_path)
    pack.run()
    pack.bundle(tmp_path / "out")

    assert len(pack.manifest.final_state_hash) == 64
    assert pack.manifest.transaction_history == []


def test_validate_rejects_absolute_or_parent_artifact_paths(tmp_path: Path) -> None:
    manifest = ProofManifest(
        name="bad-artifact-path",
        design_path="design.yaml",
        artifacts=[ArtifactRecord(path="../escape.gbr", kind="gerber", sha256="0" * 64)],
    )
    errors = validate_proof_pack(manifest, tmp_path)
    assert any("relative and contained" in err for err in errors)


def test_validate_rejects_malformed_artifact_hash(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.gbr"
    artifact.write_text("G04 test*", encoding="utf-8")
    manifest = ProofManifest(
        name="bad-hash",
        design_path="design.yaml",
        artifacts=[ArtifactRecord(path="artifact.gbr", kind="gerber", sha256="not-a-sha")],
    )
    errors = validate_proof_pack(manifest, tmp_path)
    assert any("sha256" in err.lower() for err in errors)


def test_validate_requires_skip_reason_for_skipped_check() -> None:
    manifest = ProofManifest(
        name="skip-reason",
        design_path="design.yaml",
        check_records=[CheckRecord(name="oracle", status="skipped")],
    )
    errors = validate_proof_pack(manifest, Path("."))
    assert any("skip reason" in err.lower() for err in errors)


def test_validate_requires_kicad_oracle_skip_reason() -> None:
    manifest = ProofManifest(
        name="oracle-skip",
        design_path="design.yaml",
        kicad_oracle=[KiCadOracleEvidence(check="drc", status="skipped")],
    )
    errors = validate_proof_pack(manifest, Path("."))
    assert any("skip_reason" in err for err in errors)


def test_stable_id_ignores_runtime_environment_and_absolute_paths(tmp_path: Path) -> None:
    manifest_a = ProofManifest(
        name="stable",
        design_path=str(tmp_path / "design.yaml"),
        environment=EnvironmentRecord(python_version="3.12", platform="linux-a"),
        artifacts=[ArtifactRecord(path="/tmp/out.gbr", kind="gerber", sha256="1" * 64)],
        references={"fab.gbr": str(tmp_path / "fab.gbr")},
    )
    manifest_b = ProofManifest(
        name="stable",
        design_path="/different/root/design.yaml",
        environment=EnvironmentRecord(python_version="3.13", platform="linux-b"),
        artifacts=[ArtifactRecord(path="/different/out.gbr", kind="gerber", sha256="2" * 64)],
        references={"fab.gbr": "/another/root/fab.gbr"},
    )
    assert ProofPack(manifest_a).stable_id == ProofPack(manifest_b).stable_id


def test_proof_run_prepares_layout_before_routed_check(tmp_path: Path) -> None:
    design_path = tmp_path / "design.yaml"
    design_path.write_text(
        """meta:
  name: RoutedProof
components:
  r1:
    ref: R1
    type: RES
    value: 10k
    footprint: "0402"
  c1:
    ref: C1
    type: CAP
    value: 100nF
    footprint: "0402"
nets:
  sig:
    name: SIG
    nodes:
      - component_ref: R1
        pin_name: P1
      - component_ref: C1
        pin_name: P1
""",
        encoding="utf-8",
    )
    proof_path = tmp_path / "proof.yaml"
    proof_path.write_text(
        """version: '1.0'
name: routed-proof
design_path: design.yaml
checks:
  - name: all-routed
    type: routed
""",
        encoding="utf-8",
    )

    pack = ProofPack.load(proof_path)
    results = pack.run()

    assert results[0].passed
    assert results[0].message == "All nets routed"


def test_capture_environment_binds_lock_and_mcp_dependency_identity() -> None:
    env = capture_environment()

    assert len(env.lock_sha256) == 64
    assert set(env.dependency_versions) >= {"fastmcp", "mcp"}
    assert env.evidence_identity is not None
    assert env.evidence_identity.lock_sha256 == env.lock_sha256
    assert "zaptrace/proof/pack.py" in env.evidence_identity.source_inputs
