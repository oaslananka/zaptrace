"""Real gate and repair adapters for release verify/repair orchestration."""

from __future__ import annotations

import copy
from typing import Any

from zaptrace.analysis.sim_gate import run_simulation_gate
from zaptrace.core.models import Design, DRCSeverity
from zaptrace.core.state import design_state_hash
from zaptrace.ee.drc.engine import DRCEngine
from zaptrace.erc.models import ERCSeverity
from zaptrace.erc.runner import ERCRunner
from zaptrace.fab.dfm import DFMChecker
from zaptrace.fab.profile import load_profile
from zaptrace.pipeline.verify_repair import GateAdapter, RepairAdapter, VerifyRepairContext
from zaptrace.pipeline.verify_repair_models import (
    FailureEvidence,
    FailureSeverity,
    GateDomain,
    GateEvidence,
    GateVerdict,
    Repairability,
    RepairApplication,
)
from zaptrace.security.release import ReleaseEvidenceStatus, build_component_coverage
from zaptrace.synthesis.repair import REPAIR_REGISTRY, repair_design


def _failure_severity(value: str) -> FailureSeverity:
    normalized = value.lower()
    if normalized == "critical":
        return FailureSeverity.CRITICAL
    if normalized == "error":
        return FailureSeverity.ERROR
    if normalized == "warning":
        return FailureSeverity.WARNING
    return FailureSeverity.INFO


def _erc_handler_can_apply(design: Design, violation: Any) -> bool:
    """Return whether the registered handler produces a patch for this exact finding."""
    handler = REPAIR_REGISTRY.get_handler(violation.rule_id)
    if handler is None:
        return False
    candidate = copy.deepcopy(design)
    try:
        return bool(handler(candidate, [violation]))
    except Exception:
        return False


def erc_gate(design: Design, context: VerifyRepairContext) -> GateEvidence:
    """Run ERC and classify each violation by registered repair capability."""
    result = ERCRunner().run(design)
    state_hash = design_state_hash(design)
    findings: list[FailureEvidence] = []
    for index, violation in enumerate(result.active_violations, 1):
        auto_repairable = _erc_handler_can_apply(design, violation)
        severity = _failure_severity(violation.severity.value)
        warning_needs_review = violation.severity == ERCSeverity.WARNING and context.policy.erc_warnings_require_review
        if violation.severity == ERCSeverity.ERROR:
            verdict = GateVerdict.BLOCKED
        elif warning_needs_review:
            verdict = GateVerdict.HUMAN_REVIEW_REQUIRED
        else:
            verdict = GateVerdict.WARNING
        findings.append(
            FailureEvidence(
                failure_id=f"erc:{violation.rule_id}:{index}",
                domain=GateDomain.ERC,
                rule_id=violation.rule_id,
                severity=severity,
                verdict=verdict,
                repairability=(Repairability.AUTO_REPAIRABLE if auto_repairable else Repairability.HUMAN_REPAIRABLE),
                message=violation.message,
                affected_refs=[*violation.component_refs, *violation.net_refs],
                requires_human_review=(not auto_repairable and verdict != GateVerdict.WARNING) or warning_needs_review,
                details={
                    "component_refs": violation.component_refs,
                    "net_refs": violation.net_refs,
                    "patch_suggestion": violation.patch_suggestion or "",
                },
            )
        )
    if not findings:
        return GateEvidence.pass_result(GateDomain.ERC, state_hash, result.coverage_summary())
    return GateEvidence.from_findings(
        domain=GateDomain.ERC,
        design_state_hash=state_hash,
        findings=findings,
        summary=(
            f"ERC: {result.total_errors} error(s), {result.total_warnings} warning(s), "
            f"{len(result.checks_run)} check(s)"
        ),
        metadata={
            "errors": result.total_errors,
            "warnings": result.total_warnings,
            "info": result.total_info,
            "checks_run": len(result.checks_run),
            "coverage_gaps": result.coverage_gaps,
        },
    )


def erc_registry_repair(
    design: Design,
    failures: list[FailureEvidence],
    _context: VerifyRepairContext,
) -> RepairApplication | None:
    """Apply one bounded ERC registry iteration and retain its provenance."""
    erc_failures = [
        item
        for item in failures
        if item.domain == GateDomain.ERC and item.repairability == Repairability.AUTO_REPAIRABLE
    ]
    if not erc_failures:
        return None
    result = repair_design(design, max_iterations=1)
    if not result.patches and not result.decisions and not result.remaining:
        return None
    return RepairApplication(
        repair_id="erc-repair-registry",
        domains=[GateDomain.ERC],
        rationale="apply one bounded pass of registered ERC repair handlers and re-run configured gates",
        patches=[item.to_dict() for item in result.patches],
        decisions=[item.to_dict() for item in result.decisions],
        human_review_required=bool(result.remaining) or any(item.confidence < 1.0 for item in result.patches),
    )


def drc_gate(design: Design, context: VerifyRepairContext) -> GateEvidence:
    """Run native DRC; geometric failures are never silently auto-repaired."""
    state_hash = design_state_hash(design)
    working = copy.deepcopy(design)
    result = DRCEngine().run(working)
    findings: list[FailureEvidence] = []
    for index, violation in enumerate(result.violations, 1):
        warning_needs_review = violation.severity == DRCSeverity.WARNING and context.policy.drc_warnings_require_review
        if violation.severity == DRCSeverity.ERROR:
            verdict = GateVerdict.BLOCKED
        elif warning_needs_review:
            verdict = GateVerdict.HUMAN_REVIEW_REQUIRED
        else:
            verdict = GateVerdict.WARNING
        findings.append(
            FailureEvidence(
                failure_id=f"drc:{violation.rule_id}:{index}",
                domain=GateDomain.DRC,
                rule_id=violation.rule_id,
                severity=_failure_severity(violation.severity.value),
                verdict=verdict,
                repairability=Repairability.HUMAN_REPAIRABLE,
                message=violation.message,
                affected_refs=[item for item in (violation.component_id, violation.net_id) if item],
                requires_human_review=verdict != GateVerdict.WARNING,
                details={"location": violation.location or ""},
            )
        )
    if not findings:
        return GateEvidence.pass_result(GateDomain.DRC, state_hash, "DRC passed")
    return GateEvidence.from_findings(
        domain=GateDomain.DRC,
        design_state_hash=state_hash,
        findings=findings,
        summary=f"DRC: {result.errors} error(s), {result.warnings} warning(s)",
        metadata={
            "errors": result.errors,
            "warnings": result.warnings,
            "info": result.info,
            "total": result.total_violations,
        },
    )


def dfm_gate(design: Design, context: VerifyRepairContext) -> GateEvidence:
    """Run manufacturer-aware DFM against the policy-bound fab profile."""
    state_hash = design_state_hash(design)
    profile = load_profile(context.policy.fab_profile)
    result = DFMChecker(profile).check(design)
    findings: list[FailureEvidence] = []
    for index, violation in enumerate(result.violations, 1):
        if violation.severity == "error":
            verdict = GateVerdict.BLOCKED
            repairability = Repairability.HUMAN_REPAIRABLE
            human_review = True
        elif violation.severity == "human-review-required":
            verdict = GateVerdict.HUMAN_REVIEW_REQUIRED
            repairability = Repairability.NON_REPAIRABLE
            human_review = True
        else:
            verdict = GateVerdict.WARNING
            repairability = Repairability.HUMAN_REPAIRABLE
            human_review = False
        findings.append(
            FailureEvidence(
                failure_id=f"dfm:{violation.rule_id}:{index}",
                domain=GateDomain.DFM,
                rule_id=violation.rule_id,
                severity=_failure_severity(violation.severity),
                verdict=verdict,
                repairability=repairability,
                message=violation.message,
                affected_refs=[violation.location] if violation.location else [],
                requires_human_review=human_review,
                details={
                    "actual": violation.actual,
                    "expected": violation.expected,
                    "profile": profile.name,
                },
            )
        )
    if not findings:
        return GateEvidence.pass_result(GateDomain.DFM, state_hash, f"DFM passed for {profile.name}")
    return GateEvidence.from_findings(
        domain=GateDomain.DFM,
        design_state_hash=state_hash,
        findings=findings,
        summary=f"DFM {result.readiness_status.value} for {profile.name}",
        metadata=result.to_dict(),
    )


def simulation_gate(design: Design, context: VerifyRepairContext) -> GateEvidence:
    """Run DC simulation with strict skip/no-reference policy when configured."""
    state_hash = design_state_hash(design)
    result = run_simulation_gate(design, strict=context.policy.strict_simulation)
    status = str(getattr(result.status, "value", result.status))
    if status == "pass" and not result.blocking:
        return GateEvidence.pass_result(GateDomain.SIMULATION, state_hash, result.reason)
    if status in {"skipped", "no_reference"} and not result.blocking:
        verdict = GateVerdict.WARNING
        repairability = Repairability.NON_REPAIRABLE
        human_review = False
    elif status in {"skipped", "no_reference"}:
        verdict = GateVerdict.HUMAN_REVIEW_REQUIRED
        repairability = Repairability.NON_REPAIRABLE
        human_review = True
    else:
        verdict = GateVerdict.BLOCKED
        repairability = Repairability.NON_REPAIRABLE
        human_review = True
    finding = FailureEvidence(
        failure_id=f"simulation:{status}",
        domain=GateDomain.SIMULATION,
        rule_id=f"simulation-{status.replace('_', '-')}",
        severity=FailureSeverity.ERROR if verdict == GateVerdict.BLOCKED else FailureSeverity.WARNING,
        verdict=verdict,
        repairability=repairability,
        message=result.reason,
        requires_human_review=human_review,
        details=result.to_dict(),
    )
    return GateEvidence.from_findings(
        domain=GateDomain.SIMULATION,
        design_state_hash=state_hash,
        findings=[finding],
        summary=result.reason,
        metadata=result.to_dict(),
    )


def supply_chain_gate(design: Design, _context: VerifyRepairContext) -> GateEvidence:
    """Require complete component geometry and risky-package evidence."""
    state_hash = design_state_hash(design)
    coverage = build_component_coverage(design)
    status = str(getattr(coverage["status"], "value", coverage["status"]))
    if status == ReleaseEvidenceStatus.PASS.value:
        return GateEvidence(
            domain=GateDomain.SUPPLY_CHAIN,
            verdict=GateVerdict.PASS,
            design_state_hash=state_hash,
            summary="component and package evidence complete",
            metadata=coverage,
        )
    findings: list[FailureEvidence] = []
    groups = (
        ("unresolved-component", coverage.get("unresolved_components", [])),
        ("placement-missing", coverage.get("placement_missing_components", [])),
        ("release-blocked-component", coverage.get("blocked_components", [])),
    )
    for rule_id, rows in groups:
        for index, row in enumerate(rows, 1):
            ref = str(row.get("component_ref") or row.get("ref") or row.get("component_id") or "")
            findings.append(
                FailureEvidence(
                    failure_id=f"supply-chain:{rule_id}:{index}",
                    domain=GateDomain.SUPPLY_CHAIN,
                    rule_id=rule_id,
                    severity=FailureSeverity.ERROR,
                    verdict=GateVerdict.HUMAN_REVIEW_REQUIRED,
                    repairability=Repairability.HUMAN_REPAIRABLE,
                    message=f"{rule_id.replace('-', ' ')}: {ref or 'component evidence'}",
                    affected_refs=[ref] if ref else [],
                    requires_human_review=True,
                    details=row,
                )
            )
    if not findings:
        findings.append(
            FailureEvidence(
                failure_id="supply-chain:missing-evidence",
                domain=GateDomain.SUPPLY_CHAIN,
                rule_id="missing-evidence",
                severity=FailureSeverity.ERROR,
                verdict=GateVerdict.HUMAN_REVIEW_REQUIRED,
                repairability=Repairability.NON_REPAIRABLE,
                message=f"component coverage status is {status}",
                requires_human_review=True,
            )
        )
    return GateEvidence.from_findings(
        domain=GateDomain.SUPPLY_CHAIN,
        design_state_hash=state_hash,
        findings=findings,
        summary=f"component coverage status={status}",
        metadata=coverage,
    )


def kicad_oracle_gate(design: Design, context: VerifyRepairContext) -> GateEvidence:
    """Export the current state and run KiCad ERC/DRC when the CLI is available."""
    from zaptrace.export.kicad import export_kicad
    from zaptrace.kicad.oracle import detect_kicad

    state_hash = design_state_hash(design)
    if context.output_dir is None:
        reason = "KiCad oracle requires an artifact output directory"
        finding = FailureEvidence(
            failure_id="kicad-oracle:missing-output-dir",
            domain=GateDomain.KICAD_ORACLE,
            rule_id="missing-output-dir",
            severity=FailureSeverity.ERROR,
            verdict=GateVerdict.HUMAN_REVIEW_REQUIRED,
            repairability=Repairability.NON_REPAIRABLE,
            message=reason,
            requires_human_review=True,
        )
        return GateEvidence.from_findings(
            domain=GateDomain.KICAD_ORACLE,
            design_state_hash=state_hash,
            findings=[finding],
            summary=reason,
        )
    oracle = detect_kicad()
    if not oracle.available:
        reason = "KiCad CLI is unavailable; oracle evidence is missing"
        finding = FailureEvidence(
            failure_id="kicad-oracle:unavailable",
            domain=GateDomain.KICAD_ORACLE,
            rule_id="oracle-unavailable",
            severity=FailureSeverity.ERROR,
            verdict=GateVerdict.HUMAN_REVIEW_REQUIRED,
            repairability=Repairability.NON_REPAIRABLE,
            message=reason,
            requires_human_review=True,
        )
        return GateEvidence.from_findings(
            domain=GateDomain.KICAD_ORACLE,
            design_state_hash=state_hash,
            findings=[finding],
            summary=reason,
            metadata={"available": False},
        )
    artifact_dir = context.output_dir / "kicad-oracle"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    exported = export_kicad(design, artifact_dir)
    erc = oracle.run_erc(exported["project"], output_path=artifact_dir / "erc.json")
    drc = oracle.run_drc(exported["pcb"], output_path=artifact_dir / "drc.json")
    findings: list[FailureEvidence] = []
    for check, result in (("erc", erc), ("drc", drc)):
        if result.passed:
            continue
        findings.append(
            FailureEvidence(
                failure_id=f"kicad-oracle:{check}",
                domain=GateDomain.KICAD_ORACLE,
                rule_id=f"kicad-{check}",
                severity=FailureSeverity.ERROR,
                verdict=GateVerdict.BLOCKED,
                repairability=Repairability.HUMAN_REPAIRABLE,
                message=result.message or f"KiCad {check.upper()} failed",
                requires_human_review=True,
                details={
                    "errors": result.errors,
                    "warnings": result.warnings,
                    "report_path": result.report_path or "",
                    "report_sha256": result.report_sha256,
                },
            )
        )
    metadata = {
        "available": True,
        "version": oracle.version,
        "erc": {"passed": erc.passed, "errors": erc.errors, "warnings": erc.warnings},
        "drc": {"passed": drc.passed, "errors": drc.errors, "warnings": drc.warnings},
    }
    if not findings:
        return GateEvidence(
            domain=GateDomain.KICAD_ORACLE,
            verdict=GateVerdict.PASS,
            design_state_hash=state_hash,
            summary="KiCad ERC and DRC passed",
            metadata=metadata,
        )
    return GateEvidence.from_findings(
        domain=GateDomain.KICAD_ORACLE,
        design_state_hash=state_hash,
        findings=findings,
        summary="KiCad oracle found blocking violations",
        metadata=metadata,
    )


def proof_pack_gate(design: Design, _context: VerifyRepairContext) -> GateEvidence:
    """Run current-state baseline proof checks without re-synthesizing the design."""
    from zaptrace.proof.checker import CheckStatus, ProofRunner
    from zaptrace.synthesis.proof import _baseline_checks

    state_hash = design_state_hash(design)
    working = copy.deepcopy(design)
    results = ProofRunner(working).run_checks(_baseline_checks(working))
    findings: list[FailureEvidence] = []
    for index, result in enumerate(results, 1):
        if result.status == CheckStatus.PASS:
            continue
        verdict = GateVerdict.BLOCKED if result.status in {CheckStatus.FAIL, CheckStatus.ERROR} else GateVerdict.WARNING
        findings.append(
            FailureEvidence(
                failure_id=f"proof-pack:{result.check.name}:{index}",
                domain=GateDomain.PROOF_PACK,
                rule_id=result.check.name,
                severity=_failure_severity(result.check.severity.value),
                verdict=verdict,
                repairability=Repairability.HUMAN_REPAIRABLE,
                message=result.message or f"proof check {result.check.name} did not pass",
                requires_human_review=verdict == GateVerdict.BLOCKED,
                details=result.to_dict(),
            )
        )
    metadata: dict[str, Any] = {
        "check_count": len(results),
        "passed_count": sum(item.status == CheckStatus.PASS for item in results),
        "checks": [item.to_dict() for item in results],
    }
    if not findings:
        return GateEvidence(
            domain=GateDomain.PROOF_PACK,
            verdict=GateVerdict.PASS,
            design_state_hash=state_hash,
            summary=f"{len(results)} baseline proof check(s) passed",
            metadata=metadata,
        )
    return GateEvidence.from_findings(
        domain=GateDomain.PROOF_PACK,
        design_state_hash=state_hash,
        findings=findings,
        summary="baseline proof checks contain failures",
        metadata=metadata,
    )


def default_gate_adapters() -> dict[GateDomain, GateAdapter]:
    """Return the complete release-domain gate registry."""
    return {
        GateDomain.ERC: erc_gate,
        GateDomain.DRC: drc_gate,
        GateDomain.KICAD_ORACLE: kicad_oracle_gate,
        GateDomain.DFM: dfm_gate,
        GateDomain.SIMULATION: simulation_gate,
        GateDomain.SUPPLY_CHAIN: supply_chain_gate,
        GateDomain.PROOF_PACK: proof_pack_gate,
    }


def default_repair_adapters() -> list[RepairAdapter]:
    """Return only bounded, code-owned autonomous repair adapters."""
    return [erc_registry_repair]


__all__ = [
    "default_gate_adapters",
    "default_repair_adapters",
    "dfm_gate",
    "drc_gate",
    "erc_gate",
    "erc_registry_repair",
    "kicad_oracle_gate",
    "proof_pack_gate",
    "simulation_gate",
    "supply_chain_gate",
]
