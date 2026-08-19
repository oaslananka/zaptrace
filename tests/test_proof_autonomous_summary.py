from __future__ import annotations

import json

from zaptrace.proof import CheckDefinition, CheckResult, CheckStatus, ManifestModel, ProofManifest, ProofPack
from zaptrace.proof.manifest import CheckSeverity
from zaptrace.proof.signoff import AutonomousSignoffStatus, SignoffCheckStatus


def _pack_with_results(results: list[CheckResult]) -> ProofPack:
    manifest = ProofManifest(
        name="SignoffSummary",
        design_path="design.yaml",
        model=ManifestModel(),
        checks=[result.check for result in results],
    )
    return ProofPack(manifest=manifest, results=results)


def test_report_json_includes_autonomous_pass_status() -> None:
    pack = _pack_with_results([CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)])

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS
    assert report["autonomous_signoff"]["blocking_checks"] == []
    assert "Autonomous status: autonomous-pass" in pack.summary


def test_report_json_includes_blocked_status_and_blocking_evidence() -> None:
    pack = _pack_with_results(
        [CheckResult(check=CheckDefinition(name="kicad-drc", type="drc"), status=CheckStatus.FAIL)]
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["kicad-drc"]
    assert "Blocking evidence: kicad-drc" in pack.summary


def test_report_json_includes_human_review_required_status() -> None:
    pack = _pack_with_results(
        [
            CheckResult(
                check=CheckDefinition(name="rf-layout-risk", type="custom", severity=CheckSeverity.WARNING),
                status=CheckStatus.FAIL,
            )
        ]
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert report["autonomous_signoff"]["human_review_checks"] == ["rf-layout-risk"]
    assert "Human review: rf-layout-risk" in pack.summary


def test_manifest_stores_autonomous_signoff_decision() -> None:
    pack = _pack_with_results([CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)])

    pack.update_autonomous_signoff()

    assert pack.manifest.autonomous_signoff.status == AutonomousSignoffStatus.AUTONOMOUS_PASS
    assert pack.manifest.model_dump(mode="json")["autonomous_signoff"]["status"] == "autonomous-pass"


def test_requirements_coverage_blocks_autonomous_pass_when_incomplete() -> None:
    from zaptrace.proof.manifest import RequirementsCoverageEvidence

    manifest = ProofManifest(
        name="CoverageBlocked",
        design_path="design.yaml",
        requirements_coverage=RequirementsCoverageEvidence(
            report_path="requirements_coverage.json",
            requirements_hash="abc123",
            fully_covered=False,
            fully_traced=False,
            requirement_count=2,
            untraced_artifact_count=1,
            message="requirements coverage has gaps",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["requirements-coverage"]
    assert "Blocking evidence: requirements-coverage" in pack.summary


def test_requirements_coverage_allows_pass_when_complete() -> None:
    from zaptrace.proof.manifest import RequirementsCoverageEvidence

    manifest = ProofManifest(
        name="CoveragePass",
        design_path="design.yaml",
        requirements_coverage=RequirementsCoverageEvidence(
            report_path="requirements_coverage.json",
            requirements_hash="abc123",
            fully_covered=True,
            fully_traced=True,
            requirement_count=2,
            untraced_artifact_count=0,
            message="requirements coverage complete",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS
    assert report["autonomous_signoff"]["blocking_checks"] == []


def test_unconfirmed_high_risk_assumptions_block_autonomous_pass() -> None:
    from zaptrace.proof.manifest import AssumptionsEvidence

    manifest = ProofManifest(
        name="AssumptionsBlocked",
        design_path="design.yaml",
        assumptions_evidence=AssumptionsEvidence(
            report_path="assumptions.json",
            requirements_hash="abc123",
            approved=False,
            assumption_count=2,
            unconfirmed_high_risk_count=1,
            message="requirements assumptions require confirmation",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["requirements-assumptions"]
    assert "Blocking evidence: requirements-assumptions" in pack.summary


def test_confirmed_assumptions_do_not_block_autonomous_pass() -> None:
    from zaptrace.proof.manifest import AssumptionsEvidence

    manifest = ProofManifest(
        name="AssumptionsPass",
        design_path="design.yaml",
        assumptions_evidence=AssumptionsEvidence(
            report_path="assumptions.json",
            requirements_hash="abc123",
            approved=True,
            assumption_count=1,
            unconfirmed_high_risk_count=0,
            message="requirements assumptions confirmed",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS


def test_stable_id_ignores_runtime_requirements_and_assumptions_evidence() -> None:
    from zaptrace.proof.manifest import AssumptionsEvidence, RequirementsCoverageEvidence

    base_manifest = ProofManifest(name="StableRuntimeEvidence", design_path="design.yaml")
    with_runtime = ProofManifest(
        name="StableRuntimeEvidence",
        design_path="design.yaml",
        requirements_coverage=RequirementsCoverageEvidence(
            report_path="requirements_coverage.json",
            requirements_hash="hash-a",
            fully_covered=False,
            fully_traced=False,
            requirement_count=3,
            untraced_artifact_count=2,
            message="runtime coverage state",
        ),
        assumptions_evidence=AssumptionsEvidence(
            report_path="assumptions.json",
            requirements_hash="hash-b",
            approved=False,
            assumption_count=2,
            unconfirmed_high_risk_count=1,
            message="runtime assumptions state",
        ),
    )
    result = CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)

    assert (
        ProofPack(manifest=base_manifest, results=[result]).stable_id
        == ProofPack(
            manifest=with_runtime,
            results=[result],
        ).stable_id
    )


def test_failed_kicad_schematic_erc_evidence_blocks_autonomous_pass() -> None:
    from zaptrace.kicad.oracle import KiCadErcResult

    erc = KiCadErcResult(
        available=True,
        success=False,
        message="1 ERC errors, 0 warnings",
        version="9.0.0",
        cli_path="/usr/bin/kicad-cli",
        command=["/usr/bin/kicad-cli", "sch", "erc", "design.kicad_sch"],
        exit_code=1,
        report_path="erc.json",
        errors=1,
        warnings=0,
    )
    manifest = ProofManifest(
        name="FailedSchematicErc",
        design_path="design.yaml",
        kicad_oracle=[erc.to_oracle_evidence()],
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["kicad:schematic_erc"]
    assert "Blocking evidence: kicad:schematic_erc" in pack.summary


def test_failed_kicad_pcb_drc_evidence_blocks_autonomous_pass() -> None:
    from zaptrace.kicad.oracle import KiCadDrcResult

    drc = KiCadDrcResult(
        available=True,
        success=False,
        message="1 DRC errors, 0 warnings",
        version="9.0.0",
        cli_path="/usr/bin/kicad-cli",
        command=["/usr/bin/kicad-cli", "pcb", "drc", "board.kicad_pcb"],
        exit_code=1,
        report_path="drc.json",
        errors=1,
        warnings=0,
    )
    manifest = ProofManifest(
        name="FailedPcbDrc",
        design_path="design.yaml",
        kicad_oracle=[drc.to_oracle_evidence()],
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="drc", type="drc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["kicad:pcb_drc"]
    assert "Blocking evidence: kicad:pcb_drc" in pack.summary


def test_required_missing_kicad_oracle_blocks_autonomous_pass() -> None:
    manifest = ProofManifest(
        name="MissingRequiredKiCad",
        design_path="design.yaml",
        requires_kicad_oracle=True,
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["kicad:missing_oracle"]
    assert "Blocking evidence: kicad:missing_oracle" in pack.summary


def test_skipped_required_kicad_oracle_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import KiCadOracleEvidence

    manifest = ProofManifest(
        name="SkippedRequiredKiCad",
        design_path="design.yaml",
        requires_kicad_oracle=True,
        kicad_oracle=[
            KiCadOracleEvidence(
                check="proof_pack_oracle",
                status="skipped",
                skip_reason="kicad-cli not found",
                message="KiCad oracle unavailable",
            )
        ],
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["kicad:proof_pack_oracle"]


def test_approved_kicad_waiver_does_not_block_but_keeps_counts_visible() -> None:
    from zaptrace.proof.manifest import KiCadOracleEvidence

    manifest = ProofManifest(
        name="ApprovedKiCadWaiver",
        design_path="design.yaml",
        requires_kicad_oracle=True,
        kicad_oracle=[
            KiCadOracleEvidence(
                check="pcb_drc",
                status="waived",
                errors=1,
                warnings=0,
                approval_id="WAIVER-DRC-1",
                waiver_reason="Approved mechanical courtyard exception",
                message="1 DRC errors, 0 warnings",
            )
        ],
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="drc", type="drc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS
    assert pack.manifest.kicad_oracle[0].errors == 1
    assert pack.manifest.kicad_oracle[0].approval_id == "WAIVER-DRC-1"


def test_unapproved_kicad_waiver_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import KiCadOracleEvidence

    manifest = ProofManifest(
        name="UnapprovedKiCadWaiver",
        design_path="design.yaml",
        requires_kicad_oracle=True,
        kicad_oracle=[
            KiCadOracleEvidence(
                check="schematic_erc",
                status="waived",
                errors=1,
                warnings=0,
                approval_id="WAIVER-ERC-1",
                waiver_reason="",
                message="1 ERC errors, 0 warnings",
            )
        ],
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["kicad:schematic_erc"]


def test_failed_kicad_netlist_parity_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import NetlistParityEvidence

    manifest = ProofManifest(
        name="FailedNetlistParity",
        design_path="design.yaml",
        kicad_schematic_parity=NetlistParityEvidence(
            report_path="kicad_schematic_parity.json",
            passed=False,
            missing_net_count=1,
            extra_net_count=0,
            pin_mismatch_count=1,
            message="IR and KiCad netlist evidence differ",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["kicad:ir_to_kicad_schematic_netlist"]


def test_failed_kicad_pcb_parity_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import NetlistParityEvidence

    manifest = ProofManifest(
        name="FailedPcbParity",
        design_path="design.yaml",
        kicad_pcb_parity=NetlistParityEvidence(
            report_path="kicad_pcb_parity.json",
            check="kicad_schematic_to_pcb_netlist",
            passed=False,
            missing_net_count=1,
            extra_net_count=0,
            pin_mismatch_count=1,
            message="KiCad schematic and PCB connectivity differ",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="drc", type="drc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["kicad:kicad_schematic_to_pcb_netlist"]


def test_failed_ipc_d356_parity_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import NetlistParityEvidence

    manifest = ProofManifest(
        name="FailedIpcD356Parity",
        design_path="design.yaml",
        ipc_d356_parity=NetlistParityEvidence(
            report_path="ipc_d356_parity.json",
            check="ipc_d356_netlist",
            passed=False,
            missing_net_count=1,
            extra_net_count=0,
            pin_mismatch_count=1,
            message="IR and IPC-D-356 netlist differ",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="manufacturing", type="custom"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["manufacturing:ipc_d356_netlist"]


def test_failed_component_metadata_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import ComponentMetadataEvidence

    manifest = ProofManifest(
        name="ComponentMetadataBlocked",
        design_path="design.yaml",
        component_metadata=ComponentMetadataEvidence(
            report_path="component-metadata-gate.json",
            valid=False,
            component_count=3,
            critical_issue_count=1,
            warning_count=2,
            message="component metadata gate failed",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["component-metadata"]
    assert "Blocking evidence: component-metadata" in pack.summary


def test_schema_valid_but_release_blocked_component_metadata_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import ComponentMetadataEvidence

    manifest = ProofManifest(
        name="ComponentMetadataTrustBlocked",
        design_path="design.yaml",
        component_metadata=ComponentMetadataEvidence(
            report_path="component-metadata-gate.json",
            valid=True,
            component_count=3,
            critical_issue_count=0,
            warning_count=0,
            release_eligible_count=2,
            blocked_component_count=1,
            human_review_required_count=1,
            trust_tier_counts={"verified": 2, "heuristic": 1},
            message="schema valid; one heuristic component blocks release",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["component-metadata"]
    evidence = next(item for item in pack.manifest.autonomous_signoff.evidence if item.name == "component-metadata")
    assert evidence.status == SignoffCheckStatus.FAIL
    assert "1 release-blocked component" in evidence.summary


def test_valid_component_metadata_does_not_block_autonomous_pass() -> None:
    from zaptrace.proof.manifest import ComponentMetadataEvidence

    manifest = ProofManifest(
        name="ComponentMetadataPass",
        design_path="design.yaml",
        component_metadata=ComponentMetadataEvidence(
            report_path="component-metadata-gate.json",
            valid=True,
            component_count=3,
            critical_issue_count=0,
            warning_count=0,
            message="component metadata gate passed",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS


def test_blocked_supply_chain_risk_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import BomProvenanceEvidence

    manifest = ProofManifest(
        name="SupplyBlocked",
        design_path="design.yaml",
        bom_provenance=[
            BomProvenanceEvidence(
                provider="fixture",
                cache_policy="fixture-only",
                report_path="bom-risk.json",
                highest_risk="critical",
                blocked=True,
                unresolved_required_parts=1,
                obsolete_required_parts=1,
                message="BOM risk blocks acceptance",
            )
        ],
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["supply-chain-risk"]


def test_clean_supply_chain_risk_does_not_block_autonomous_pass() -> None:
    from zaptrace.proof.manifest import BomProvenanceEvidence

    manifest = ProofManifest(
        name="SupplyPass",
        design_path="design.yaml",
        bom_provenance=[
            BomProvenanceEvidence(
                provider="fixture",
                cache_policy="fixture-only",
                report_path="bom-risk.json",
                highest_risk="low",
                blocked=False,
                message="BOM risk passed",
            )
        ],
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS


def test_failed_derating_evidence_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import DeratingEvidence

    manifest = ProofManifest(
        name="DeratingBlocked",
        design_path="design.yaml",
        derating_evidence=DeratingEvidence(
            report_path="derating.json",
            passed=False,
            component_count=2,
            finding_count=3,
            blocking_finding_count=1,
            message="derating policy failed",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["component-derating"]


def test_passing_derating_evidence_does_not_block_autonomous_pass() -> None:
    from zaptrace.proof.manifest import DeratingEvidence

    manifest = ProofManifest(
        name="DeratingPass",
        design_path="design.yaml",
        derating_evidence=DeratingEvidence(
            report_path="derating.json",
            passed=True,
            component_count=2,
            finding_count=2,
            blocking_finding_count=0,
            message="derating policy passed",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS


def test_conflicting_datasheet_provenance_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import DatasheetProvenanceEvidence

    manifest = ProofManifest(
        name="DatasheetConflict",
        design_path="design.yaml",
        datasheet_provenance=DatasheetProvenanceEvidence(
            report_path="datasheet-validation.json",
            component_count=1,
            fact_count=2,
            conflict_count=1,
            blocked=True,
            message="datasheet fact validation failed",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["datasheet-provenance"]


def test_low_confidence_datasheet_provenance_requires_human_review() -> None:
    from zaptrace.proof.manifest import DatasheetProvenanceEvidence

    manifest = ProofManifest(
        name="DatasheetLowConfidence",
        design_path="design.yaml",
        datasheet_provenance=DatasheetProvenanceEvidence(
            report_path="datasheet-validation.json",
            component_count=1,
            fact_count=2,
            low_confidence_count=1,
            human_review_required=True,
            blocked=False,
            message="datasheet fact validation needs review",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert report["autonomous_signoff"]["human_review_checks"] == ["datasheet-provenance"]


def test_stale_datasheet_hash_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import DatasheetProvenanceEvidence

    manifest = ProofManifest(
        name="DatasheetStale",
        design_path="design.yaml",
        datasheet_provenance=DatasheetProvenanceEvidence(
            report_path="datasheet-hash-gate.json",
            component_count=1,
            fact_count=4,
            stale_fact_count=4,
            hash_mismatch_count=1,
            blocked=True,
            message="datasheet source hash changed",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["datasheet-provenance"]
    evidence = next(item for item in pack.manifest.autonomous_signoff.evidence if item.name == "datasheet-provenance")
    assert "stale datasheet fact" in evidence.summary


def test_failed_footprint_proof_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import FootprintProofEvidence

    manifest = ProofManifest(
        name="FootprintProofBlocked",
        design_path="design.yaml",
        footprint_proof=FootprintProofEvidence(
            report_path="footprint-proof-validation.json",
            passed=False,
            proof_count=1,
            error_count=1,
            warning_count=0,
            message="footprint proof validation failed",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["footprint-proof"]


def test_passing_footprint_proof_does_not_block_autonomous_pass() -> None:
    from zaptrace.proof.manifest import FootprintProofEvidence

    manifest = ProofManifest(
        name="FootprintProofPass",
        design_path="design.yaml",
        footprint_proof=FootprintProofEvidence(
            report_path="footprint-proof-validation.json",
            passed=True,
            proof_count=1,
            error_count=0,
            warning_count=0,
            message="footprint proof validation passed",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS


def test_failed_placement_scorecard_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import PlacementScorecardEvidence

    manifest = ProofManifest(
        name="PlacementBlocked",
        design_path="design.yaml",
        placement_scorecard=PlacementScorecardEvidence(
            report_path="placement-scorecard.json",
            passed=False,
            overall_score=0.55,
            min_autonomous_score=0.75,
            warning_count=4,
            blocking_observation_count=0,
            message="placement score below autonomous threshold",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["placement-scorecard"]


def test_warning_placement_scorecard_requires_human_review() -> None:
    from zaptrace.proof.manifest import PlacementScorecardEvidence

    manifest = ProofManifest(
        name="PlacementReview",
        design_path="design.yaml",
        placement_scorecard=PlacementScorecardEvidence(
            report_path="placement-scorecard.json",
            passed=True,
            overall_score=0.86,
            min_autonomous_score=0.75,
            warning_count=2,
            human_review_required=True,
            message="placement score requires review",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert report["autonomous_signoff"]["human_review_checks"] == ["placement-scorecard"]


def test_failed_diffpair_length_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import DiffPairLengthEvidence

    manifest = ProofManifest(
        name="DiffPairBlocked",
        design_path="design.yaml",
        diffpair_length=DiffPairLengthEvidence(
            report_path="diffpair-length.json",
            passed=False,
            pair_count=1,
            violation_count=1,
            missing_route_count=0,
            message="USB pair exceeds skew tolerance",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["diff-pair-length"]


def test_passing_diffpair_length_does_not_block_autonomous_pass() -> None:
    from zaptrace.proof.manifest import DiffPairLengthEvidence

    manifest = ProofManifest(
        name="DiffPairPass",
        design_path="design.yaml",
        diffpair_length=DiffPairLengthEvidence(
            report_path="diffpair-length.json",
            passed=True,
            pair_count=1,
            violation_count=0,
            missing_route_count=0,
            message="diff-pair length clean",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS


def test_impedance_return_path_review_requires_human_review() -> None:
    from zaptrace.proof.manifest import ImpedanceReturnPathEvidence

    manifest = ProofManifest(
        name="SiReview",
        design_path="design.yaml",
        impedance_return_path=ImpedanceReturnPathEvidence(
            report_path="si-risk.json",
            passed=True,
            assumption_count=1,
            diagnostic_count=1,
            human_review_required=True,
            blocked=False,
            message="return-path risk needs review",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert report["autonomous_signoff"]["human_review_checks"] == ["impedance-return-path"]


def test_impedance_return_path_blocking_evidence_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import ImpedanceReturnPathEvidence

    manifest = ProofManifest(
        name="SiBlocked",
        design_path="design.yaml",
        impedance_return_path=ImpedanceReturnPathEvidence(
            report_path="si-risk.json",
            passed=False,
            assumption_count=1,
            diagnostic_count=1,
            human_review_required=False,
            blocked=True,
            message="return-path discontinuity blocks signoff",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["impedance-return-path"]


def test_repair_proposal_evidence_requires_human_review() -> None:
    from zaptrace.proof.manifest import RepairProposalEvidence

    manifest = ProofManifest(
        name="RepairReview",
        design_path="design.yaml",
        repair_proposals=RepairProposalEvidence(
            report_path="repair-proposals.json",
            passed=True,
            proposal_count=2,
            verified_count=2,
            silent_repair_count=0,
            human_review_required=True,
            blocked=False,
            message="repair proposals include low-confidence defaults",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert report["autonomous_signoff"]["human_review_checks"] == ["repair-proposals"]


def test_silent_repair_evidence_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import RepairProposalEvidence

    manifest = ProofManifest(
        name="RepairBlocked",
        design_path="design.yaml",
        repair_proposals=RepairProposalEvidence(
            report_path="repair-proposals.json",
            passed=False,
            proposal_count=0,
            verified_count=0,
            silent_repair_count=1,
            human_review_required=False,
            blocked=True,
            message="silent repair without proposal evidence",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["repair-proposals"]


def test_rail_current_budget_failure_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import RailCurrentBudgetEvidence

    manifest = ProofManifest(
        name="RailBudgetBlocked",
        design_path="design.yaml",
        rail_current_budget=RailCurrentBudgetEvidence(
            report_path="rail-current-budget.json",
            passed=False,
            rail_count=1,
            failure_count=1,
            missing_metadata_count=0,
            human_review_required=False,
            blocked=True,
            message="rail current budget exceeded",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["rail-current-budget"]


def test_missing_rail_current_metadata_requires_human_review() -> None:
    from zaptrace.proof.manifest import RailCurrentBudgetEvidence

    manifest = ProofManifest(
        name="RailBudgetReview",
        design_path="design.yaml",
        rail_current_budget=RailCurrentBudgetEvidence(
            report_path="rail-current-budget.json",
            passed=True,
            rail_count=1,
            failure_count=0,
            missing_metadata_count=1,
            human_review_required=True,
            blocked=False,
            message="rail current metadata incomplete",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert report["autonomous_signoff"]["human_review_checks"] == ["rail-current-budget"]


def test_regulator_margin_failure_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import RegulatorMarginEvidence

    manifest = ProofManifest(
        name="RegulatorMarginBlocked",
        design_path="design.yaml",
        regulator_margin=RegulatorMarginEvidence(
            report_path="regulator-margin.json",
            passed=False,
            regulator_count=1,
            failure_count=1,
            missing_metadata_count=0,
            human_review_required=False,
            blocked=True,
            message="regulator thermal margin failed",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["regulator-margin"]


def test_regulator_margin_missing_metadata_requires_human_review() -> None:
    from zaptrace.proof.manifest import RegulatorMarginEvidence

    manifest = ProofManifest(
        name="RegulatorMarginReview",
        design_path="design.yaml",
        regulator_margin=RegulatorMarginEvidence(
            report_path="regulator-margin.json",
            passed=True,
            regulator_count=1,
            failure_count=0,
            missing_metadata_count=2,
            human_review_required=True,
            blocked=False,
            message="regulator margin metadata incomplete",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert report["autonomous_signoff"]["human_review_checks"] == ["regulator-margin"]


def test_current_density_violation_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import CurrentDensityEvidence

    manifest = ProofManifest(
        name="CurrentDensityBlocked",
        design_path="design.yaml",
        current_density=CurrentDensityEvidence(
            report_path="current-density.json",
            passed=False,
            high_current_net_count=1,
            trace_count=1,
            violation_count=1,
            missing_route_count=0,
            human_review_required=False,
            blocked=True,
            message="trace width below required current-carrying width",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["current-density"]


def test_missing_current_density_route_requires_human_review() -> None:
    from zaptrace.proof.manifest import CurrentDensityEvidence

    manifest = ProofManifest(
        name="CurrentDensityReview",
        design_path="design.yaml",
        current_density=CurrentDensityEvidence(
            report_path="current-density.json",
            passed=True,
            high_current_net_count=1,
            trace_count=0,
            violation_count=0,
            missing_route_count=1,
            human_review_required=True,
            blocked=False,
            message="high-current net missing routed trace evidence",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert report["autonomous_signoff"]["human_review_checks"] == ["current-density"]


def test_sipi_risk_review_requires_human_review() -> None:
    from zaptrace.proof.manifest import SipiRiskEvidence

    manifest = ProofManifest(
        name="SipiReview",
        design_path="design.yaml",
        sipi_risk=SipiRiskEvidence(
            report_path="sipi-risk.json",
            passed=True,
            high_speed_net_count=1,
            impedance_assumption_count=1,
            return_path_diagnostic_count=1,
            decoupling_issue_count=1,
            unsupported_high_speed_count=0,
            human_review_required=True,
            blocked=False,
            message="SI/PI risk requires review",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert report["autonomous_signoff"]["human_review_checks"] == ["sipi-risk"]


def test_sipi_risk_blocking_evidence_blocks_autonomous_pass() -> None:
    from zaptrace.proof.manifest import SipiRiskEvidence

    manifest = ProofManifest(
        name="SipiBlocked",
        design_path="design.yaml",
        sipi_risk=SipiRiskEvidence(
            report_path="sipi-risk.json",
            passed=False,
            high_speed_net_count=1,
            impedance_assumption_count=1,
            return_path_diagnostic_count=1,
            decoupling_issue_count=0,
            unsupported_high_speed_count=0,
            human_review_required=False,
            blocked=True,
            message="SI/PI risk failed",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["sipi-risk"]


def _component_selection_manifest(*, blocked: int, review: int) -> ProofManifest:
    from zaptrace.proof import ComponentSelectionProofEvidence, ComponentSelectionRecord

    return ProofManifest(
        name="ComponentSelectionEvidence",
        design_path="design.yaml",
        component_selection=ComponentSelectionProofEvidence(
            report_path="component-selection.json",
            report_sha256="a" * 64,
            requirement_count=1,
            selected_count=0 if blocked else 1,
            blocked_count=blocked,
            human_review_required_count=review,
            selections=[
                ComponentSelectionRecord(
                    requirement_id="rail-3v3",
                    position="U1",
                    selected_component_id="" if blocked else "ldo-a",
                    decision_hash="b" * 64,
                    rationale="no candidate passed" if blocked else "selected ldo-a",
                    extracted_constraints={"package": "SOT-23-5", "recommended_voltage_max_v": 5.0},
                    blocked=bool(blocked),
                    human_review_required=bool(review),
                )
            ],
            message="component selection evaluated",
        ),
    )


def test_blocked_component_selection_blocks_autonomous_pass() -> None:
    manifest = _component_selection_manifest(blocked=1, review=1)
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["component-selection"]
    evidence = next(item for item in pack.manifest.autonomous_signoff.evidence if item.name == "component-selection")
    assert evidence.status == SignoffCheckStatus.FAIL


def test_review_required_component_selection_requires_human_review() -> None:
    manifest = _component_selection_manifest(blocked=0, review=1)
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert report["autonomous_signoff"]["human_review_checks"] == ["component-selection"]
    evidence = next(item for item in pack.manifest.autonomous_signoff.evidence if item.name == "component-selection")
    assert evidence.status == SignoffCheckStatus.WARNING


def test_fully_eligible_component_selection_allows_autonomous_pass() -> None:
    manifest = _component_selection_manifest(blocked=0, review=0)
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS
    evidence = next(item for item in pack.manifest.autonomous_signoff.evidence if item.name == "component-selection")
    assert evidence.status == SignoffCheckStatus.PASS
    dumped = pack.manifest.model_dump(mode="json")["component_selection"]
    assert dumped["selections"][0]["extracted_constraints"]["package"] == "SOT-23-5"


def test_stable_id_ignores_runtime_component_selection_evidence() -> None:
    base = ProofManifest(name="StableSelectionEvidence", design_path="design.yaml")
    with_selection = _component_selection_manifest(blocked=0, review=1)
    with_selection.name = "StableSelectionEvidence"
    result = CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)

    assert (
        ProofPack(manifest=base, results=[result]).stable_id
        == ProofPack(
            manifest=with_selection,
            results=[result],
        ).stable_id
    )


def _architecture_evidence_manifest(
    *,
    blocked: bool,
    review: bool,
    artifact_sha256: str = "a" * 64,
    artifact_path: str = "electronics-architecture.json",
    report_path: str = "architecture-traceability.json",
    untraced_element_count: int = 0,
    uncovered_requirement_count: int = 0,
) -> ProofManifest:
    from zaptrace.proof import ArchitectureProofEvidence

    return ProofManifest(
        name="ArchitectureEvidence",
        design_path="design.yaml",
        architecture_evidence=ArchitectureProofEvidence(
            report_path=report_path,
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha256,
            status="needs-clarification" if blocked else "ready",
            requirement_count=3,
            assumption_count=1 if review else 0,
            conflict_count=1 if blocked else 0,
            untraced_element_count=untraced_element_count,
            uncovered_requirement_count=uncovered_requirement_count,
            fully_traced=not blocked,
            blocked=blocked,
            human_review_required=review,
            message="architecture traceability evaluated",
        ),
    )


def test_blocked_architecture_evidence_blocks_autonomous_pass() -> None:
    manifest = _architecture_evidence_manifest(blocked=True, review=True)
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["requirements-architecture"]
    evidence = next(
        item for item in pack.manifest.autonomous_signoff.evidence if item.name == "requirements-architecture"
    )
    assert evidence.status == SignoffCheckStatus.FAIL


def test_review_required_architecture_evidence_requires_human_review() -> None:
    manifest = _architecture_evidence_manifest(blocked=False, review=True)
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert report["autonomous_signoff"]["human_review_checks"] == ["requirements-architecture"]


def test_fully_traced_architecture_evidence_allows_autonomous_pass() -> None:
    manifest = _architecture_evidence_manifest(blocked=False, review=False)
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS
    evidence = next(
        item for item in pack.manifest.autonomous_signoff.evidence if item.name == "requirements-architecture"
    )
    assert evidence.status == SignoffCheckStatus.PASS


def test_stable_id_uses_architecture_hash_but_ignores_runtime_paths() -> None:
    first = _architecture_evidence_manifest(
        blocked=False,
        review=False,
        artifact_sha256="a" * 64,
        artifact_path="one/electronics-architecture.json",
        report_path="one/architecture-traceability.json",
    )
    second = _architecture_evidence_manifest(
        blocked=False,
        review=False,
        artifact_sha256="a" * 64,
        artifact_path="two/electronics-architecture.json",
        report_path="two/architecture-traceability.json",
    )
    changed = _architecture_evidence_manifest(
        blocked=False,
        review=False,
        artifact_sha256="b" * 64,
    )
    result = CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)

    first_id = ProofPack(manifest=first, results=[result]).stable_id
    second_id = ProofPack(manifest=second, results=[result]).stable_id
    changed_id = ProofPack(manifest=changed, results=[result]).stable_id

    assert first_id == second_id
    assert first_id != changed_id


def test_architecture_evidence_summary_lists_traceability_gaps() -> None:
    manifest = _architecture_evidence_manifest(
        blocked=True,
        review=True,
        untraced_element_count=2,
        uncovered_requirement_count=3,
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    pack.update_autonomous_signoff()

    evidence = next(
        item for item in pack.manifest.autonomous_signoff.evidence if item.name == "requirements-architecture"
    )
    assert "2 untraced element(s)" in evidence.summary
    assert "3 uncovered requirement(s)" in evidence.summary
