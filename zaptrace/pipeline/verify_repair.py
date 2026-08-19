"""Bounded, evidence-first verify/repair orchestration."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from zaptrace.core.diff import diff_designs
from zaptrace.core.models import Design
from zaptrace.core.state import design_state_hash
from zaptrace.pipeline.verify_repair_models import (
    FailureEvidence,
    FailureSeverity,
    GateDomain,
    GateEvidence,
    GateHistoryEntry,
    GateVerdict,
    Repairability,
    RepairApplication,
    RepairEvidence,
    SemanticDiffEvidence,
    VerifyRepairOutcome,
    VerifyRepairPolicy,
    VerifyRepairReport,
    VerifyRepairStopReason,
    resolve_verify_repair_output_path,
)


@dataclass(frozen=True)
class VerifyRepairContext:
    """Runtime context passed to gate and repair adapters."""

    policy: VerifyRepairPolicy
    output_dir: Path | None = None


GateAdapter = Callable[[Design, VerifyRepairContext], GateEvidence]
RepairAdapter = Callable[[Design, list[FailureEvidence], VerifyRepairContext], RepairApplication | None]


def _gate_error(domain: GateDomain, state_hash: str, message: str) -> GateEvidence:
    finding = FailureEvidence(
        failure_id=f"{domain.value}:gate-error",
        domain=domain,
        rule_id="gate-execution",
        severity=FailureSeverity.CRITICAL,
        verdict=GateVerdict.ERROR,
        repairability=Repairability.NON_REPAIRABLE,
        message=message,
        requires_human_review=True,
    )
    return GateEvidence.from_findings(
        domain=domain,
        design_state_hash=state_hash,
        findings=[finding],
        summary=message,
    )


def _run_gates(
    design: Design,
    context: VerifyRepairContext,
    adapters: dict[GateDomain, GateAdapter],
) -> list[GateEvidence]:
    state_hash = design_state_hash(design)
    results: list[GateEvidence] = []
    for domain in context.policy.enabled_domains:
        adapter = adapters.get(domain)
        if adapter is None:
            results.append(_gate_error(domain, state_hash, f"no gate adapter configured for {domain.value}"))
            continue
        try:
            result = adapter(copy.deepcopy(design), context)
        except Exception as exc:  # evidence must retain adapter failures
            result = _gate_error(domain, state_hash, f"{domain.value} gate raised {type(exc).__name__}: {exc}")
        if result.domain != domain:
            result = _gate_error(
                domain, state_hash, f"{domain.value} adapter returned evidence for {result.domain.value}"
            )
        elif result.design_state_hash != state_hash:
            result = _gate_error(
                domain, state_hash, f"{domain.value} evidence is not bound to the current design state"
            )
        results.append(result)
    return results


def _replace_gate_with_repair_error(
    gates: list[GateEvidence],
    *,
    domain: GateDomain,
    state_hash: str,
    message: str,
) -> list[GateEvidence]:
    """Replace one domain result with fail-closed repair-execution evidence."""
    previous = next((gate for gate in gates if gate.domain == domain), None)
    finding = FailureEvidence(
        failure_id=f"{domain.value}:repair-error",
        domain=domain,
        rule_id="repair-execution",
        severity=FailureSeverity.CRITICAL,
        verdict=GateVerdict.ERROR,
        repairability=Repairability.NON_REPAIRABLE,
        message=message,
        requires_human_review=True,
    )
    error_gate = GateEvidence.from_findings(
        domain=domain,
        design_state_hash=state_hash,
        findings=[*(previous.findings if previous is not None else []), finding],
        summary=message,
        metadata={
            **(previous.metadata if previous is not None else {}),
            "repair_execution_error": message,
        },
    )
    if previous is None:
        return [*gates, error_gate]
    return [error_gate if gate.domain == domain else gate for gate in gates]


def _blocking_count(gates: list[GateEvidence]) -> int:
    return sum(item.blocking_count for item in gates)


def _human_review_count(gates: list[GateEvidence]) -> int:
    return sum(item.human_review_required for item in gates)


def _auto_repairable_count(gates: list[GateEvidence]) -> int:
    return sum(finding.repairability == Repairability.AUTO_REPAIRABLE for gate in gates for finding in gate.findings)


def _history_entry(
    *,
    iteration: int,
    phase: Literal["initial", "post-repair"],
    design: Design,
    gates: list[GateEvidence],
) -> GateHistoryEntry:
    return GateHistoryEntry(
        iteration=iteration,
        phase=phase,
        design_state_hash=design_state_hash(design),
        blocking_count=_blocking_count(gates),
        human_review_count=_human_review_count(gates),
        gates=gates,
    )


def _active_failures(gates: list[GateEvidence]) -> list[FailureEvidence]:
    return [
        finding
        for gate in gates
        for finding in gate.findings
        if finding.verdict in {GateVerdict.BLOCKED, GateVerdict.HUMAN_REVIEW_REQUIRED, GateVerdict.ERROR}
        or finding.repairability == Repairability.AUTO_REPAIRABLE
    ]


def _all_gates_pass(gates: list[GateEvidence]) -> bool:
    return all(not gate.blocks_autonomous_release and not gate.human_review_required for gate in gates) and not any(
        finding.repairability == Repairability.AUTO_REPAIRABLE for gate in gates for finding in gate.findings
    )


def _semantic_diff(before: Design, after: Design) -> list[SemanticDiffEvidence]:
    return [
        SemanticDiffEvidence(
            type=entry.type.value,
            ref=entry.ref,
            detail=entry.detail,
            old_value=entry.old_value,
            new_value=entry.new_value,
        )
        for entry in diff_designs(before, after)
    ]


def _ordered_human_review_reasons(gates: list[GateEvidence]) -> list[str]:
    reasons: list[str] = []
    for gate in gates:
        for finding in gate.findings:
            if finding.requires_human_review and finding.message not in reasons:
                reasons.append(finding.message)
    return reasons


def _terminal_reason_before_repair(gates: list[GateEvidence]) -> VerifyRepairStopReason | None:
    failures = _active_failures(gates)
    if any(gate.verdict == GateVerdict.ERROR for gate in gates):
        return VerifyRepairStopReason.GATE_EXECUTION_ERROR
    if any(item.repairability == Repairability.AUTO_REPAIRABLE for item in failures):
        return None
    if any(item.repairability == Repairability.NON_REPAIRABLE for item in failures):
        return VerifyRepairStopReason.NON_REPAIRABLE
    if failures:
        return VerifyRepairStopReason.HUMAN_REVIEW_REQUIRED
    return None


def _build_report(
    *,
    design: Design,
    initial_hash: str,
    policy: VerifyRepairPolicy,
    gates: list[GateEvidence],
    history: list[GateHistoryEntry],
    repairs: list[RepairEvidence],
    iterations_used: int,
    stop_reason: VerifyRepairStopReason,
) -> VerifyRepairReport:
    converged = stop_reason == VerifyRepairStopReason.ALL_GATES_PASSED
    human_review_reasons = _ordered_human_review_reasons(gates)
    if not converged and not human_review_reasons:
        human_review_reasons.append(f"verify/repair stopped with {stop_reason.value}")
    report = VerifyRepairReport(
        design_name=design.meta.name,
        policy_version=policy.policy_version,
        policy_sha256=policy.identity_sha256(),
        enabled_domains=policy.enabled_domains,
        initial_design_state_hash=initial_hash,
        final_design_state_hash=design_state_hash(design),
        converged=converged,
        stop_reason=stop_reason,
        blocks_autonomous_release=not converged,
        human_review_required=not converged,
        iteration_budget=policy.max_iterations,
        iterations_used=iterations_used,
        gate_history=history,
        repairs=repairs,
        final_gates=gates,
        human_review_reasons=human_review_reasons,
        non_claims=policy.non_claims,
    )
    return report.finalize()


@dataclass(frozen=True)
class _RepairCycleResult:
    design: Design
    gates: list[GateEvidence]
    history: GateHistoryEntry
    repairs: list[RepairEvidence]
    progress: bool
    stop_reason: VerifyRepairStopReason | None = None


def _run_repair_cycle(
    candidate: Design,
    *,
    iteration: int,
    gates: list[GateEvidence],
    context: VerifyRepairContext,
    gate_adapters: dict[GateDomain, GateAdapter],
    repair_adapters: list[RepairAdapter],
) -> _RepairCycleResult:
    failures = _active_failures(gates)
    before = copy.deepcopy(candidate)
    working = copy.deepcopy(candidate)
    before_hash = design_state_hash(before)
    before_blocking = _blocking_count(gates)
    before_auto_repairable = _auto_repairable_count(gates)
    applications: list[RepairApplication] = []
    try:
        for adapter in repair_adapters:
            application = adapter(working, failures, context)
            if application is not None:
                applications.append(application)
    except Exception as exc:
        domain = failures[0].domain if failures else context.policy.enabled_domains[0]
        message = f"{domain.value} repair raised {type(exc).__name__}: {exc}"
        error_gates = _replace_gate_with_repair_error(
            gates,
            domain=domain,
            state_hash=before_hash,
            message=message,
        )
        return _RepairCycleResult(
            design=before,
            gates=error_gates,
            history=_history_entry(
                iteration=iteration,
                phase="post-repair",
                design=before,
                gates=error_gates,
            ),
            repairs=[],
            progress=False,
            stop_reason=VerifyRepairStopReason.REPAIR_EXECUTION_ERROR,
        )

    after_hash = design_state_hash(working)
    if not applications and after_hash != before_hash:
        domain = failures[0].domain if failures else context.policy.enabled_domains[0]
        message = f"{domain.value} repair mutated design without RepairApplication evidence"
        error_gates = _replace_gate_with_repair_error(
            gates,
            domain=domain,
            state_hash=before_hash,
            message=message,
        )
        return _RepairCycleResult(
            design=before,
            gates=error_gates,
            history=_history_entry(
                iteration=iteration,
                phase="post-repair",
                design=before,
                gates=error_gates,
            ),
            repairs=[],
            progress=False,
            stop_reason=VerifyRepairStopReason.REPAIR_EXECUTION_ERROR,
        )

    after_gates = _run_gates(working, context, gate_adapters)
    after_blocking = _blocking_count(after_gates)
    after_auto_repairable = _auto_repairable_count(after_gates)
    semantic_diff = _semantic_diff(before, working)
    improved = after_blocking < before_blocking or after_auto_repairable < before_auto_repairable
    evidence = [
        RepairEvidence(
            iteration=iteration,
            repair_id=application.repair_id,
            domains=application.domains,
            rationale=application.rationale,
            before_state_hash=before_hash,
            after_state_hash=after_hash,
            before_blocking_count=before_blocking,
            after_blocking_count=after_blocking,
            improved=improved,
            semantic_diff=semantic_diff,
            patches=application.patches,
            decisions=application.decisions,
            human_review_required=application.human_review_required,
        )
        for application in applications
    ]
    progress = bool(applications) and after_hash != before_hash and improved
    return _RepairCycleResult(
        design=working,
        gates=after_gates,
        history=_history_entry(
            iteration=iteration,
            phase="post-repair",
            design=working,
            gates=after_gates,
        ),
        repairs=evidence,
        progress=progress,
    )


@dataclass(frozen=True)
class _IterationResult:
    design: Design
    gates: list[GateEvidence]
    history: list[GateHistoryEntry]
    repairs: list[RepairEvidence]
    iterations_used: int
    stop_reason: VerifyRepairStopReason


def _resolve_adapters(
    gate_adapters: dict[GateDomain, GateAdapter] | None,
    repair_adapters: list[RepairAdapter] | None,
) -> tuple[dict[GateDomain, GateAdapter], list[RepairAdapter]]:
    """Fill omitted adapter registries from the code-owned defaults."""
    if gate_adapters is not None and repair_adapters is not None:
        return gate_adapters, repair_adapters
    from zaptrace.pipeline.verify_repair_gates import default_gate_adapters, default_repair_adapters

    return (
        gate_adapters if gate_adapters is not None else default_gate_adapters(),
        repair_adapters if repair_adapters is not None else default_repair_adapters(),
    )


def _cycle_stop_reason(
    cycle: _RepairCycleResult,
    gates: list[GateEvidence],
) -> VerifyRepairStopReason | None:
    """Return the terminal reason after one completed repair cycle, if any."""
    if cycle.stop_reason is not None:
        return cycle.stop_reason
    if _all_gates_pass(gates):
        return VerifyRepairStopReason.ALL_GATES_PASSED
    if not cycle.progress:
        return VerifyRepairStopReason.NO_PROGRESS
    return None


def _run_iterations(
    candidate: Design,
    *,
    policy: VerifyRepairPolicy,
    context: VerifyRepairContext,
    gate_adapters: dict[GateDomain, GateAdapter],
    repair_adapters: list[RepairAdapter],
) -> _IterationResult:
    """Execute the bounded gate/repair loop and return its complete terminal state."""
    gates = _run_gates(candidate, context, gate_adapters)
    history = [_history_entry(iteration=0, phase="initial", design=candidate, gates=gates)]
    repairs: list[RepairEvidence] = []
    if _all_gates_pass(gates):
        return _IterationResult(
            design=candidate,
            gates=gates,
            history=history,
            repairs=repairs,
            iterations_used=0,
            stop_reason=VerifyRepairStopReason.ALL_GATES_PASSED,
        )

    for iteration in range(1, policy.max_iterations + 1):
        terminal = _terminal_reason_before_repair(gates)
        if terminal is not None:
            return _IterationResult(candidate, gates, history, repairs, iteration - 1, terminal)
        cycle = _run_repair_cycle(
            candidate,
            iteration=iteration,
            gates=gates,
            context=context,
            gate_adapters=gate_adapters,
            repair_adapters=repair_adapters,
        )
        candidate = cycle.design
        gates = cycle.gates
        history.append(cycle.history)
        repairs.extend(cycle.repairs)
        terminal = _cycle_stop_reason(cycle, gates)
        if terminal is not None:
            return _IterationResult(candidate, gates, history, repairs, iteration, terminal)

    return _IterationResult(
        candidate,
        gates,
        history,
        repairs,
        policy.max_iterations,
        VerifyRepairStopReason.ITERATION_BUDGET_EXHAUSTED,
    )


def run_verify_repair(
    design: Design,
    *,
    policy: VerifyRepairPolicy | None = None,
    gate_adapters: dict[GateDomain, GateAdapter] | None = None,
    repair_adapters: list[RepairAdapter] | None = None,
    output_dir: str | Path | None = None,
    trusted_output_root: str | Path | None = None,
) -> VerifyRepairOutcome:
    """Run configured gates and bounded repairs against an isolated design copy."""
    resolved_policy = policy or VerifyRepairPolicy.release_default()
    resolved_gates, resolved_repairs = _resolve_adapters(gate_adapters, repair_adapters)
    candidate = copy.deepcopy(design)
    initial_hash = design_state_hash(candidate)
    resolved_output_dir = (
        resolve_verify_repair_output_path(output_dir, trusted_root=trusted_output_root)
        if output_dir is not None
        else None
    )
    context = VerifyRepairContext(policy=resolved_policy, output_dir=resolved_output_dir)
    result = _run_iterations(
        candidate,
        policy=resolved_policy,
        context=context,
        gate_adapters=resolved_gates,
        repair_adapters=resolved_repairs,
    )
    report = _build_report(
        design=result.design,
        initial_hash=initial_hash,
        policy=resolved_policy,
        gates=result.gates,
        history=result.history,
        repairs=result.repairs,
        iterations_used=result.iterations_used,
        stop_reason=result.stop_reason,
    )
    return VerifyRepairOutcome(design=result.design, report=report)


__all__ = [
    "GateAdapter",
    "RepairAdapter",
    "VerifyRepairContext",
    "run_verify_repair",
]
