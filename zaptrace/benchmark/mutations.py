"""Known-failure mutation corpus for benchmark gates."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.analysis.current_density import build_current_density_report
from zaptrace.analysis.sipi_risk import build_sipi_risk_report
from zaptrace.core.models import Design


class MutationClass(StrEnum):
    REMOVE_DECOUPLING = "remove-decoupling"
    NARROW_HIGH_CURRENT_TRACE = "narrow-high-current-trace"
    REMOVE_RETURN_PATH = "remove-return-path"


class KnownFailureMutation(BaseModel):
    """One known-failure mutation definition."""

    model_config = ConfigDict(strict=False)

    mutation_id: str
    mutation_class: MutationClass
    description: str
    expected_detector: str
    release_blocking: bool = True


class MutationDetectionResult(BaseModel):
    """Detection outcome for one known-failure mutation."""

    mutation_id: str
    mutation_class: MutationClass
    expected_detector: str
    caught: bool
    detail: str = ""


class MutationCorpusReport(BaseModel):
    """Machine-readable known-failure mutation benchmark report."""

    schema_version: str = "1.0"
    mutation_count: int = Field(ge=0)
    caught_count: int = Field(ge=0)
    missed_count: int = Field(ge=0)
    passed: bool
    results: list[MutationDetectionResult]


BUILTIN_MUTATIONS: tuple[KnownFailureMutation, ...] = (
    KnownFailureMutation(
        mutation_id="MUT-001",
        mutation_class=MutationClass.REMOVE_DECOUPLING,
        description="Remove decoupling capacitor evidence from a power rail",
        expected_detector="sipi-risk.decoupling",
    ),
    KnownFailureMutation(
        mutation_id="MUT-002",
        mutation_class=MutationClass.NARROW_HIGH_CURRENT_TRACE,
        description="Force a high-current trace width below required copper width",
        expected_detector="current-density.violation",
    ),
    KnownFailureMutation(
        mutation_id="MUT-003",
        mutation_class=MutationClass.REMOVE_RETURN_PATH,
        description="Remove return-path constraint from a controlled/high-speed net",
        expected_detector="sipi-risk.return-path",
    ),
)


def _remove_decoupling(design: Design) -> None:
    for component_id, component in design.components.items():
        if "cap" in component.type.lower() or "cap" in (component.value or "").lower():
            del design.components[component_id]
            return


def _narrow_high_current_trace(design: Design) -> None:
    if design.routing is None:
        return
    high_current = {
        net_id for net_id, net in design.nets.items() if net.constraints and net.constraints.is_high_current
    }
    for segment in design.routing.traces:
        if segment.net_id in high_current:
            segment.width = 0.05
            return


def _remove_return_path(design: Design) -> None:
    for net in design.nets.values():
        if net.constraints and net.constraints.return_path_net:
            net.constraints.return_path_net = None
            return


_MUTATION_APPLIERS: dict[MutationClass, Callable[[Design], None]] = {
    MutationClass.REMOVE_DECOUPLING: _remove_decoupling,
    MutationClass.NARROW_HIGH_CURRENT_TRACE: _narrow_high_current_trace,
    MutationClass.REMOVE_RETURN_PATH: _remove_return_path,
}


def apply_known_failure_mutation(design: Design, mutation: KnownFailureMutation) -> Design:
    """Apply a known-failure mutation to a deep copy of a design."""
    mutated = design.model_copy(deep=True)
    applier = _MUTATION_APPLIERS.get(mutation.mutation_class)
    if applier is not None:
        applier(mutated)
    return mutated


def detect_known_failure(design: Design, mutation: KnownFailureMutation) -> MutationDetectionResult:
    """Run the expected detector for one mutated design."""
    if mutation.mutation_class == MutationClass.REMOVE_DECOUPLING:
        report = build_sipi_risk_report(design)
        caught = report.decoupling_issue_count > 0
        detail = f"decoupling_issue_count={report.decoupling_issue_count}"
    elif mutation.mutation_class == MutationClass.NARROW_HIGH_CURRENT_TRACE:
        report = build_current_density_report(design)
        caught = report.violation_count > 0
        detail = f"violation_count={report.violation_count}"
    elif mutation.mutation_class == MutationClass.REMOVE_RETURN_PATH:
        report = build_sipi_risk_report(design)
        caught = any(item.category == "return_path" and item.status.value != "pass" for item in report.findings)
        detail = f"return_path_diagnostic_count={report.return_path_diagnostic_count}"
    else:
        caught = False
        detail = "unsupported mutation class"
    return MutationDetectionResult(
        mutation_id=mutation.mutation_id,
        mutation_class=mutation.mutation_class,
        expected_detector=mutation.expected_detector,
        caught=caught,
        detail=detail,
    )


def run_known_failure_mutation_corpus(
    design: Design,
    *,
    mutations: tuple[KnownFailureMutation, ...] = BUILTIN_MUTATIONS,
) -> MutationCorpusReport:
    """Apply known-failure mutations and report caught/missed detectors."""
    results: list[MutationDetectionResult] = []
    for mutation in mutations:
        mutated = apply_known_failure_mutation(design, mutation)
        results.append(detect_known_failure(mutated, mutation))
    caught_count = sum(1 for result in results if result.caught)
    missed_count = len(results) - caught_count
    return MutationCorpusReport(
        mutation_count=len(results),
        caught_count=caught_count,
        missed_count=missed_count,
        passed=missed_count == 0,
        results=results,
    )


def mutation_corpus_json(report: MutationCorpusReport) -> str:
    """Serialize a mutation corpus report as stable JSON."""
    import json

    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
