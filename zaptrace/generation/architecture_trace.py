"""Deterministic traceability evidence derived from architecture artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.generation.architecture import (
    ArchitectureCompileStatus,
    ElectronicsArchitectureArtifact,
    electronics_architecture_artifact_json,
)

ArchitectureTraceKind = Literal[
    "subsystem",
    "power",
    "interface",
    "constraint",
    "risk",
    "acceptance-test",
]


class ArchitectureTraceRow(BaseModel):
    """Requirement and assumption references for one architecture element."""

    model_config = ConfigDict(extra="forbid")

    kind: ArchitectureTraceKind
    id: str = Field(min_length=1)
    requirement_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)


class ArchitectureTraceabilityReport(BaseModel):
    """Machine-checkable coverage and blocking verdict for an architecture."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    architecture_status: ArchitectureCompileStatus
    requirement_ids: list[str]
    assumption_ids: list[str]
    traceability: list[ArchitectureTraceRow]
    uncovered_requirement_ids: list[str]
    untraced_elements: list[str]
    unconfirmed_assumption_ids: list[str]
    conflict_ids: list[str]
    fully_traced: bool
    blocked: bool
    human_review_required: bool
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "architecture traceability does not prove electrical correctness",
            "architecture traceability is not fabrication approval",
            "qualified engineering review remains required for production decisions",
        ],
        min_length=1,
    )


def _trace_rows(artifact: ElectronicsArchitectureArtifact) -> list[ArchitectureTraceRow]:
    rows: list[ArchitectureTraceRow] = []
    rows.extend(
        ArchitectureTraceRow(
            kind="subsystem",
            id=item.id,
            requirement_ids=sorted(set(item.requirement_ids)),
            assumption_ids=sorted(set(item.assumption_ids)),
        )
        for item in artifact.subsystems
    )
    rows.extend(
        ArchitectureTraceRow(
            kind="power",
            id=item.net_name,
            requirement_ids=sorted(set(item.requirement_ids)),
            assumption_ids=sorted(set(item.assumption_ids)),
        )
        for item in artifact.power_tree
    )
    rows.extend(
        ArchitectureTraceRow(
            kind="interface",
            id=item.name,
            requirement_ids=sorted(set(item.requirement_ids)),
            assumption_ids=sorted(set(item.assumption_ids)),
        )
        for item in artifact.interfaces
    )
    rows.extend(
        ArchitectureTraceRow(
            kind="constraint",
            id=item.id,
            requirement_ids=sorted(set(item.requirement_ids)),
            assumption_ids=sorted(set(item.assumption_ids)),
        )
        for item in artifact.constraints
    )
    rows.extend(
        ArchitectureTraceRow(
            kind="risk",
            id=item.id,
            requirement_ids=sorted(set(item.requirement_ids)),
            assumption_ids=sorted(set(item.assumption_ids)),
        )
        for item in artifact.risks
    )
    rows.extend(
        ArchitectureTraceRow(
            kind="acceptance-test",
            id=item.id,
            requirement_ids=sorted(set(item.requirement_ids)),
            assumption_ids=sorted(set(item.assumption_ids)),
        )
        for item in artifact.acceptance_tests
    )
    return sorted(rows, key=lambda item: (item.kind, item.id))


def build_architecture_traceability_report(
    artifact: ElectronicsArchitectureArtifact,
) -> ArchitectureTraceabilityReport:
    """Derive a deterministic traceability and autonomous-gate verdict."""

    artifact_json = electronics_architecture_artifact_json(artifact)
    artifact_sha256 = hashlib.sha256(artifact_json.encode("utf-8")).hexdigest()
    rows = _trace_rows(artifact)
    coverage = artifact.requirement_coverage_matrix()
    uncovered_requirement_ids = sorted(
        req_id for req_id in artifact.release_blocking_requirement_ids if not coverage.get(req_id)
    )
    untraced_elements = sorted(
        f"{row.kind}:{row.id}" for row in rows if not row.requirement_ids and not row.assumption_ids
    )
    unconfirmed_assumption_ids = sorted(item.id for item in artifact.assumptions if item.requires_confirmation)
    conflict_ids = sorted(item.id for item in artifact.conflicts)
    fully_traced = not uncovered_requirement_ids and not untraced_elements
    blocked = artifact.status != ArchitectureCompileStatus.READY or not fully_traced or bool(conflict_ids)
    return ArchitectureTraceabilityReport(
        artifact_sha256=artifact_sha256,
        architecture_status=artifact.status,
        requirement_ids=sorted(artifact.requirement_ids),
        assumption_ids=sorted(item.id for item in artifact.assumptions),
        traceability=rows,
        uncovered_requirement_ids=uncovered_requirement_ids,
        untraced_elements=untraced_elements,
        unconfirmed_assumption_ids=unconfirmed_assumption_ids,
        conflict_ids=conflict_ids,
        fully_traced=fully_traced,
        blocked=blocked,
        human_review_required=blocked or bool(unconfirmed_assumption_ids),
    )


def architecture_traceability_report_json(report: ArchitectureTraceabilityReport) -> str:
    """Serialize a traceability report as stable JSON."""

    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
