"""Generate reviewable KiCad schematic projects from compiled Design IR."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.export.kicad import export_kicad_schematic
from zaptrace.generation.compiler import CompiledDesignIR
from zaptrace.generation.topology import (
    SchematicBlockPlacementPlan,
    SchematicComponentDecisionPlan,
    SchematicTopologyPlan,
    schematic_block_placement_plan_json,
    schematic_component_decision_plan_json,
    schematic_topology_plan_json,
)

SchematicArtifactKind = Literal[
    "project",
    "schematic",
    "topology-plan",
    "component-decision-plan",
    "block-placement-plan",
]


class GeneratedSchematicArtifact(BaseModel):
    """One generated KiCad schematic-project artifact."""

    model_config = ConfigDict(strict=False)

    kind: SchematicArtifactKind
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)


class GeneratedKiCadSchematicReport(BaseModel):
    """Evidence report for a generated KiCad schematic project."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    design_name: str
    family_id: str
    output_dir: str
    passed: bool
    generated_files: list[GeneratedSchematicArtifact]
    requirement_trace_count: int = Field(ge=0)
    provenance_record_count: int = Field(ge=0)
    non_claims: list[str] = Field(default_factory=list)
    claim_violations: list[str] = Field(default_factory=list)
    topology_present: bool = False
    topology_status: str | None = None
    topology_block_count: int = Field(default=0, ge=0)
    topology_net_count: int = Field(default=0, ge=0)
    component_decision_present: bool = False
    component_decision_count: int = Field(default=0, ge=0)
    block_placement_present: bool = False
    block_placement_count: int = Field(default=0, ge=0)

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class GeneratedKiCadSchematicProject(BaseModel):
    """Generated KiCad schematic-project files and evidence report."""

    model_config = ConfigDict(strict=False, arbitrary_types_allowed=True)

    project_path: Path
    schematic_path: Path
    report_path: Path
    report: GeneratedKiCadSchematicReport


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _artifact(kind: SchematicArtifactKind, path: Path, root: Path) -> GeneratedSchematicArtifact:
    return GeneratedSchematicArtifact(
        kind=kind,
        path=_relative(path, root),
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
    )


def _has_unsafe_claim(text: str, claim: str) -> bool:
    positive = claim in text
    dashed_non_claim = f"not-{claim}" in text
    spaced_non_claim = f"not {claim}" in text
    return positive and not dashed_non_claim and not spaced_non_claim


def _claim_violations(paths: list[Path]) -> list[str]:
    """Return generated files that contain unsafe fabrication/production claims."""
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        if _has_unsafe_claim(text, "fabrication-ready") or _has_unsafe_claim(text, "production-ready"):
            violations.append(path.name)
    return sorted(violations)


def generated_kicad_schematic_report_json(report: GeneratedKiCadSchematicReport) -> str:
    """Serialize a generated schematic report as stable JSON."""
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def generate_kicad_schematic_project(
    compiled: CompiledDesignIR,
    output_dir: str | Path,
    topology_plan: SchematicTopologyPlan | None = None,
    component_decision_plan: SchematicComponentDecisionPlan | None = None,
    block_placement_plan: SchematicBlockPlacementPlan | None = None,
) -> GeneratedKiCadSchematicProject:
    """Generate a reviewable KiCad schematic project from compiled Design IR.

    This emits `.kicad_pro`, `.kicad_sch`, and a machine-readable evidence report.
    It does not claim the generated project is fabrication-ready.
    """
    out = Path(output_dir).resolve()
    files = export_kicad_schematic(compiled.design, out)
    project_path = files["project"]
    schematic_path = files["schematic"]
    generated_paths = [project_path, schematic_path]
    topology_path: Path | None = None
    component_decision_path: Path | None = None
    block_placement_path: Path | None = None
    if topology_plan is not None:
        topology_path = out / f"{compiled.design.meta.name}.schematic_topology.json"
        topology_path.write_text(
            schematic_topology_plan_json(topology_plan),
            encoding="utf-8",
            newline="\n",
        )
        generated_paths.append(topology_path)
    if component_decision_plan is not None:
        component_decision_path = out / f"{compiled.design.meta.name}.component_decisions.json"
        component_decision_path.write_text(
            schematic_component_decision_plan_json(component_decision_plan),
            encoding="utf-8",
            newline="\n",
        )
        generated_paths.append(component_decision_path)
    if block_placement_plan is not None:
        block_placement_path = out / f"{compiled.design.meta.name}.block_placements.json"
        block_placement_path.write_text(
            schematic_block_placement_plan_json(block_placement_plan),
            encoding="utf-8",
            newline="\n",
        )
        generated_paths.append(block_placement_path)
    claim_violations = _claim_violations(generated_paths)
    report = GeneratedKiCadSchematicReport(
        design_name=compiled.design.meta.name,
        family_id=compiled.report.family_id,
        output_dir=".",
        passed=not claim_violations,
        generated_files=[
            _artifact("project", project_path, out),
            _artifact("schematic", schematic_path, out),
            *([_artifact("topology-plan", topology_path, out)] if topology_path is not None else []),
            *(
                [_artifact("component-decision-plan", component_decision_path, out)]
                if component_decision_path is not None
                else []
            ),
            *(
                [_artifact("block-placement-plan", block_placement_path, out)]
                if block_placement_path is not None
                else []
            ),
        ],
        requirement_trace_count=len(compiled.report.requirement_traces),
        provenance_record_count=len(compiled.design.prov_records),
        non_claims=compiled.report.non_claims,
        claim_violations=claim_violations,
        topology_present=topology_plan is not None,
        topology_status=topology_plan.status.value if topology_plan is not None else None,
        topology_block_count=len(topology_plan.blocks) if topology_plan is not None else 0,
        topology_net_count=len(topology_plan.nets) if topology_plan is not None else 0,
        component_decision_present=component_decision_plan is not None,
        component_decision_count=len(component_decision_plan.decisions) if component_decision_plan is not None else 0,
        block_placement_present=block_placement_plan is not None,
        block_placement_count=len(block_placement_plan.placements) if block_placement_plan is not None else 0,
    )
    report_path = out / f"{compiled.design.meta.name}.kicad_schematic_generation.json"
    report_path.write_text(generated_kicad_schematic_report_json(report), encoding="utf-8", newline="\n")
    return GeneratedKiCadSchematicProject(
        project_path=project_path,
        schematic_path=schematic_path,
        report_path=report_path,
        report=report,
    )
