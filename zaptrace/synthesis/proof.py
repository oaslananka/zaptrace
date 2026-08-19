"""Synthesis → Proof Pack: an auditable verification bundle for a synthesized board.

Connects the from-scratch composition synthesizer to the proof-pack system so a
one-sentence intent yields not just a netlist but a portable, hash-stamped record
of *what was built, why, and how it verifies*: the routed design, every synthesis
decision (component, topology, value — with rationale and confidence), and the
ERC/DRC results captured as accepted baselines, plus the runtime environment.

The pack is evidence, not a fabrication certificate — the manifest's limitations
say so, mirroring the honest hand-off of :mod:`zaptrace.synthesis.fab`. The DRC
and ERC checks record the design's measured violation counts as the accepted
baseline: re-running the pack reproduces it, and a change that makes the design
worse fails the pack, so it doubles as a regression guard.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from zaptrace.analysis.layout_quality import build_layout_quality_report, write_layout_quality_report
from zaptrace.core.parser import design_to_dict
from zaptrace.export.evidence import collect_manufacturing_evidence
from zaptrace.export.ipcd356 import write_ipcd356, write_ipcd356_parity_report
from zaptrace.export.kicad import export_kicad_netlist_evidence, export_kicad_pcb
from zaptrace.export.manufacturing import generate_manufacturing_bundle
from zaptrace.generation import (
    architecture_traceability_report_json,
    build_architecture_traceability_report,
    compile_electronics_intent_to_architecture,
    electronics_architecture_artifact_json,
)
from zaptrace.kicad.parity import write_kicad_netlist_parity_report, write_kicad_pcb_parity_report
from zaptrace.proof import (
    ArchitectureProofEvidence,
    ArtifactRecord,
    AssumptionsEvidence,
    CheckDefinition,
    InputRecord,
    LayoutQualityEvidence,
    ManufacturingProofEvidence,
    NetlistParityEvidence,
    ProofManifest,
    ProofPack,
    ProofRunner,
    RequirementsCoverageEvidence,
    capture_environment,
    hash_file,
)
from zaptrace.proof.checker import CheckResult, CheckStatus
from zaptrace.proof.manifest import AgentDecisionRecord, CheckCategory, CheckRecord
from zaptrace.proof.pack import hash_bytes
from zaptrace.synthesis.fab import route_synthesized_design
from zaptrace.synthesis.requirements import (
    parse_requirements,
    requirements_assumption_report,
    requirements_coverage_report,
)

_ARCHITECTURE_ARTIFACT_NAME = "electronics-architecture.json"
_ARCHITECTURE_TRACEABILITY_NAME = "architecture-traceability.json"
_ASSUMPTIONS_REPORT_NAME = "assumptions.json"
_LAYOUT_QUALITY_REPORT_NAME = "layout-quality.json"
_DESIGN_ARTIFACT_NAME = "design.yaml"
_KICAD_SCHEMATIC_PARITY_NAME = "kicad_schematic_parity.json"
_KICAD_PCB_PARITY_NAME = "kicad_pcb_parity.json"
_IPC_D356_PARITY_NAME = "ipc_d356_parity.json"
_REQUIREMENTS_COVERAGE_NAME = "requirements_coverage.json"

if TYPE_CHECKING:
    from zaptrace.core.models import Design
    from zaptrace.synthesis.explain import SynthesisDecisionLog

# CheckResult statuses map onto the manifest's record vocabulary; an errored
# check is recorded as a failure (it did not pass) so the bundle never hides it.
_STATUS_TO_RECORD: dict[CheckStatus, str] = {
    CheckStatus.PASS: "pass",
    CheckStatus.FAIL: "fail",
    CheckStatus.ERROR: "fail",
    CheckStatus.SKIP: "skipped",
}


def _baseline_checks(design: Design) -> list[CheckDefinition]:
    """Standard checks for a synthesized board, with ERC/DRC baselines snapshotted.

    The board is run through ERC and DRC once so the accepted violation count is
    captured as ``expected_count``: the pack then passes at this baseline and
    fails only if a later change increases the count.
    """
    from zaptrace.ee.drc.engine import DRCEngine
    from zaptrace.erc.runner import ERCRunner

    erc_count = len(ERCRunner().run(design).violations)
    drc_count = len(DRCEngine().run(design).violations)
    return [
        CheckDefinition(
            name="erc",
            type="erc",
            category=CheckCategory.ERC,
            description="Electrical rule check; accepted violation baseline captured at synthesis",
            expected_count=erc_count,
        ),
        CheckDefinition(
            name="drc",
            type="drc",
            category=CheckCategory.DRC,
            description="Design rule check; accepted violation baseline captured at synthesis",
            expected_count=drc_count,
        ),
        CheckDefinition(
            name="footprints",
            type="footprint_exists",
            category=CheckCategory.FOOTPRINT,
            description="Every component has an assigned footprint",
        ),
    ]


def _decision_records(log: SynthesisDecisionLog) -> list[AgentDecisionRecord]:
    """Map the synthesis decision log into auditable agent-decision records."""
    records: list[AgentDecisionRecord] = []
    for i, d in enumerate(log.decisions, 1):
        summary = f"{d.parameter}: {d.value}".strip(": ") or d.category
        records.append(
            AgentDecisionRecord(
                decision_id=f"SYN-{i:03d}",
                actor="zaptrace-synthesis",
                decision_type=d.category,
                summary=summary,
                rationale=d.rationale,
                evidence_refs=[d.calculator] if d.calculator else [],
            )
        )
    return records


def _check_records(results: list[CheckResult]) -> list[CheckRecord]:
    return [
        CheckRecord(
            name=r.check.name,
            source="zaptrace",
            status=_STATUS_TO_RECORD.get(r.status, "fail"),
            severity=r.check.severity.value,
            summary=r.message,
        )
        for r in results
    ]


def generate_synthesis_proof(
    intent: str,
    output_dir: str | Path,
    *,
    name: str = "SynthesizedBoard",
    fab_profile: str | None = None,
    approved_dfm_skip_reason: str = "",
    approved_dfm_skip_id: str = "",
) -> ProofPack:
    """Synthesize a board from *intent* and emit an auditable proof pack in *output_dir*.

    Writes ``design.yaml`` (the routed design, hashed), KiCad netlist evidence,
    ``kicad_schematic_parity.json`` (IR ↔ KiCad netlist parity),
    ``kicad_pcb_parity.json`` (schematic ↔ PCB netlist parity),
    ``ipc_d356_parity.json`` (IR ↔ manufacturing netlist parity),
    ``electronics-architecture.json`` and ``architecture-traceability.json``
    (canonical requirements-to-architecture evidence), ``requirements_coverage.json``
    (requirement ID traceability), ``assumptions.json`` (explicit unresolved
    assumptions), ``layout-quality.json`` (constraint-driven placement/routing evidence),
    ``proof.yaml`` (the manifest with synthesis
    decisions, input/environment provenance, and check records), and ``report.json``
    (the check results). Returns the completed
    :class:`~zaptrace.proof.ProofPack`.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    architecture = compile_electronics_intent_to_architecture(intent, design_name=name)
    architecture_path = out_dir / _ARCHITECTURE_ARTIFACT_NAME
    architecture_path.write_text(electronics_architecture_artifact_json(architecture), encoding="utf-8")
    architecture_traceability = build_architecture_traceability_report(architecture)
    architecture_traceability_path = out_dir / _ARCHITECTURE_TRACEABILITY_NAME
    architecture_traceability_path.write_text(
        architecture_traceability_report_json(architecture_traceability),
        encoding="utf-8",
    )

    design, synth = route_synthesized_design(intent, name=name)
    layout_quality_report = build_layout_quality_report(design)
    layout_quality_path = write_layout_quality_report(layout_quality_report, out_dir / _LAYOUT_QUALITY_REPORT_NAME)

    # The routed design is the artifact the pack verifies; serialize it losslessly
    # so the bundle is portable and re-verifiable, then hash it for the manifest.
    design_yaml = out_dir / _DESIGN_ARTIFACT_NAME
    design_yaml.write_text(yaml.safe_dump(design_to_dict(design), sort_keys=False), encoding="utf-8")
    kicad_netlist_path = export_kicad_netlist_evidence(design, out_dir)["netlist_evidence"]
    parity_path = write_kicad_netlist_parity_report(
        design,
        kicad_netlist_path,
        out_dir / _KICAD_SCHEMATIC_PARITY_NAME,
    )
    parity_report = yaml.safe_load(parity_path.read_text(encoding="utf-8"))
    kicad_pcb_path = export_kicad_pcb(design, out_dir)["pcb"]
    pcb_parity_path = write_kicad_pcb_parity_report(
        design,
        kicad_netlist_path,
        kicad_pcb_path,
        out_dir / _KICAD_PCB_PARITY_NAME,
    )
    pcb_parity_report = yaml.safe_load(pcb_parity_path.read_text(encoding="utf-8"))
    ipc_d356_path = write_ipcd356(design, out_dir / f"{name}.ipc")
    ipc_d356_parity_path = write_ipcd356_parity_report(
        design,
        ipc_d356_path,
        out_dir / _IPC_D356_PARITY_NAME,
    )
    ipc_d356_parity_report = yaml.safe_load(ipc_d356_parity_path.read_text(encoding="utf-8"))

    manufacturing_proof: ManufacturingProofEvidence | None = None
    manufacturing_artifacts: list[ArtifactRecord] = []
    if fab_profile or (approved_dfm_skip_reason.strip() and approved_dfm_skip_id.strip()):
        manufacturing_dir = out_dir / "manufacturing"
        manufacturing_bundle = generate_manufacturing_bundle(
            design,
            manufacturing_dir,
            prefix=name,
            fab_profile=fab_profile,
            approved_dfm_skip_reason=approved_dfm_skip_reason,
            approved_dfm_skip_id=approved_dfm_skip_id,
        )
        manufacturing_evidence = collect_manufacturing_evidence(manufacturing_dir)
        readiness_path = Path(str(manufacturing_bundle["dfm_readiness"]))
        manufacturing_proof = ManufacturingProofEvidence.from_evidence_bundle(
            manufacturing_evidence,
            report_path=readiness_path.relative_to(out_dir).as_posix(),
        )
        manufacturing_artifacts = [
            ArtifactRecord(
                path=(manufacturing_dir / artifact.path).relative_to(out_dir).as_posix(),
                kind=f"manufacturing-{artifact.kind.value}",
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
            )
            for artifact in manufacturing_evidence.artifacts
        ]

    checks = _baseline_checks(design)
    results = ProofRunner(design).run_checks(checks)
    parsed_requirements = parse_requirements(intent)
    coverage_report = requirements_coverage_report(
        parsed_requirements,
        design=design,
        checks=checks,
        exports=[
            _DESIGN_ARTIFACT_NAME,
            "proof.yaml",
            "report.json",
            _ASSUMPTIONS_REPORT_NAME,
            _ARCHITECTURE_ARTIFACT_NAME,
            _ARCHITECTURE_TRACEABILITY_NAME,
            _LAYOUT_QUALITY_REPORT_NAME,
        ],
    )
    coverage_path = out_dir / _REQUIREMENTS_COVERAGE_NAME
    coverage_path.write_text(json.dumps(coverage_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assumptions_report = requirements_assumption_report(parsed_requirements)
    assumptions_path = out_dir / _ASSUMPTIONS_REPORT_NAME
    assumptions_path.write_text(json.dumps(assumptions_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = ProofManifest(
        name=f"{name} synthesis proof",
        description=f"Auditable verification of the board synthesized from: {intent}",
        design_path=_DESIGN_ARTIFACT_NAME,
        checks=checks,
        author="zaptrace-synthesis",
        tags=["synthesis", "auto-generated"],
        captured_intent=intent,
        input_record=InputRecord(
            source_type="intent",
            normalized_intent_checksum_sha256=hash_bytes(intent.strip().lower().encode("utf-8")),
        ),
        environment=capture_environment(),
        agent_decisions=_decision_records(synth["decision_log"]),
        check_records=_check_records(results),
        requires_kicad_oracle=True,
        manufacturing_evidence=[manufacturing_proof] if manufacturing_proof is not None else [],
        layout_quality=LayoutQualityEvidence.from_report(
            layout_quality_report,
            report_path=_LAYOUT_QUALITY_REPORT_NAME,
        ),
        kicad_schematic_parity=NetlistParityEvidence(
            report_path=_KICAD_SCHEMATIC_PARITY_NAME,
            passed=bool(parity_report["passed"]),
            missing_net_count=len(parity_report["missing_nets"]),
            extra_net_count=len(parity_report["extra_nets"]),
            pin_mismatch_count=len(parity_report["pin_mismatches"]),
            message=str(parity_report["message"]),
        ),
        kicad_pcb_parity=NetlistParityEvidence(
            report_path=_KICAD_PCB_PARITY_NAME,
            check="kicad_schematic_to_pcb_netlist",
            passed=bool(pcb_parity_report["passed"]),
            missing_net_count=len(pcb_parity_report["missing_nets"]),
            extra_net_count=len(pcb_parity_report["extra_nets"]),
            pin_mismatch_count=len(pcb_parity_report["pin_mismatches"]),
            message=str(pcb_parity_report["message"]),
        ),
        ipc_d356_parity=NetlistParityEvidence(
            report_path=_IPC_D356_PARITY_NAME,
            check="ipc_d356_netlist",
            passed=bool(ipc_d356_parity_report["passed"]),
            missing_net_count=len(ipc_d356_parity_report["missing_nets"]),
            extra_net_count=len(ipc_d356_parity_report["extra_nets"]),
            pin_mismatch_count=len(ipc_d356_parity_report["pin_mismatches"]),
            message=str(ipc_d356_parity_report["message"]),
        ),
        architecture_evidence=ArchitectureProofEvidence(
            report_path=_ARCHITECTURE_TRACEABILITY_NAME,
            artifact_path=_ARCHITECTURE_ARTIFACT_NAME,
            artifact_sha256=architecture_traceability.artifact_sha256,
            status=architecture.status.value,
            requirement_count=len(architecture.requirements),
            assumption_count=len(architecture.assumptions),
            conflict_count=len(architecture.conflicts),
            untraced_element_count=len(architecture_traceability.untraced_elements),
            uncovered_requirement_count=len(architecture_traceability.uncovered_requirement_ids),
            fully_traced=architecture_traceability.fully_traced,
            blocked=architecture_traceability.blocked,
            human_review_required=architecture_traceability.human_review_required,
            message=(
                "requirements architecture is ready and fully traced"
                if not architecture_traceability.blocked
                else "requirements architecture is blocked or incomplete"
            ),
        ),
        assumptions_evidence=AssumptionsEvidence(
            report_path=_ASSUMPTIONS_REPORT_NAME,
            requirements_hash=str(assumptions_report["requirements_hash"]),
            approved=bool(assumptions_report["approved"]),
            assumption_count=len(assumptions_report["assumptions"]),
            unconfirmed_high_risk_count=int(assumptions_report["unconfirmed_high_risk_count"]),
            message=(
                "requirements assumptions confirmed"
                if assumptions_report["approved"]
                else "requirements assumptions require confirmation"
            ),
        ),
        requirements_coverage=RequirementsCoverageEvidence(
            report_path=_REQUIREMENTS_COVERAGE_NAME,
            requirements_hash=str(coverage_report["requirements_hash"]),
            fully_covered=bool(coverage_report["fully_covered"]),
            fully_traced=bool(coverage_report["fully_traced"]),
            requirement_count=len(coverage_report["requirements"]),
            untraced_artifact_count=len(coverage_report["untraced_artifacts"]),
            message=(
                "requirements coverage complete"
                if coverage_report["fully_covered"]
                else "requirements coverage has gaps or untraced artifacts"
            ),
        ),
        artifacts=[
            ArtifactRecord(
                path=_DESIGN_ARTIFACT_NAME,
                kind="netlist",
                sha256=hash_file(design_yaml),
                size_bytes=design_yaml.stat().st_size,
            ),
            ArtifactRecord(
                path=kicad_netlist_path.name,
                kind="netlist",
                sha256=hash_file(kicad_netlist_path),
                size_bytes=kicad_netlist_path.stat().st_size,
            ),
            ArtifactRecord(
                path=kicad_pcb_path.name,
                kind="kicad",
                sha256=hash_file(kicad_pcb_path),
                size_bytes=kicad_pcb_path.stat().st_size,
            ),
            ArtifactRecord(
                path=_KICAD_SCHEMATIC_PARITY_NAME,
                kind="report",
                sha256=hash_file(parity_path),
                size_bytes=parity_path.stat().st_size,
            ),
            ArtifactRecord(
                path=_KICAD_PCB_PARITY_NAME,
                kind="report",
                sha256=hash_file(pcb_parity_path),
                size_bytes=pcb_parity_path.stat().st_size,
            ),
            ArtifactRecord(
                path=ipc_d356_path.name,
                kind="netlist",
                sha256=hash_file(ipc_d356_path),
                size_bytes=ipc_d356_path.stat().st_size,
            ),
            ArtifactRecord(
                path=_IPC_D356_PARITY_NAME,
                kind="report",
                sha256=hash_file(ipc_d356_parity_path),
                size_bytes=ipc_d356_parity_path.stat().st_size,
            ),
            ArtifactRecord(
                path=_ARCHITECTURE_ARTIFACT_NAME,
                kind="report",
                sha256=hash_file(architecture_path),
                size_bytes=architecture_path.stat().st_size,
            ),
            ArtifactRecord(
                path=_ARCHITECTURE_TRACEABILITY_NAME,
                kind="report",
                sha256=hash_file(architecture_traceability_path),
                size_bytes=architecture_traceability_path.stat().st_size,
            ),
            ArtifactRecord(
                path=_LAYOUT_QUALITY_REPORT_NAME,
                kind="report",
                sha256=hash_file(layout_quality_path),
                size_bytes=layout_quality_path.stat().st_size,
            ),
            ArtifactRecord(
                path=_REQUIREMENTS_COVERAGE_NAME,
                kind="report",
                sha256=hash_file(coverage_path),
                size_bytes=coverage_path.stat().st_size,
            ),
            ArtifactRecord(
                path=_ASSUMPTIONS_REPORT_NAME,
                kind="report",
                sha256=hash_file(assumptions_path),
                size_bytes=assumptions_path.stat().st_size,
            ),
        ],
    )
    manifest.artifacts.extend(manufacturing_artifacts)

    pack = ProofPack(manifest=manifest, base_path=out_dir, results=results)
    pack.update_autonomous_signoff()
    (out_dir / "proof.yaml").write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    (out_dir / "report.json").write_text(pack.report_json(), encoding="utf-8")
    return pack
