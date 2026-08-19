"""Generated board-project evidence workflow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.generation.architecture import (
    ElectronicsArchitectureArtifact,
    architecture_intent_bridge_report_json,
    convert_architecture_to_board_generation_intent_report,
    electronics_architecture_artifact_json,
)
from zaptrace.generation.compiler import CompiledDesignIR, design_ir_compilation_report_json
from zaptrace.generation.intent import BoardGenerationIntent, board_generation_intent_json
from zaptrace.generation.kicad_pcb import GeneratedKiCadPcbProject, generate_kicad_pcb_project
from zaptrace.generation.kicad_schematic import GeneratedKiCadSchematicProject, generate_kicad_schematic_project

GeneratedProjectArtifactKind = Literal[
    "architecture",
    "architecture-intent-bridge-report",
    "intent",
    "design-ir-compile-report",
    "kicad-project",
    "kicad-schematic",
    "kicad-pcb",
    "schematic-generation-report",
    "pcb-generation-report",
    "manufacturing-export-manifest",
    "review-handoff",
]


class GeneratedProjectArtifact(BaseModel):
    """One generated-project evidence artifact."""

    model_config = ConfigDict(strict=False)

    kind: GeneratedProjectArtifactKind
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    required: bool = True


class GeneratedProjectEvidenceBundle(BaseModel):
    """Strict evidence bundle for a generated reviewable board project."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    design_name: str
    family_id: str
    output_dir: str
    passed: bool
    artifact_count: int = Field(ge=0)
    required_artifact_count: int = Field(ge=0)
    missing_required_artifact_count: int = Field(ge=0)
    requirement_trace_count: int = Field(ge=0)
    provenance_record_count: int = Field(ge=0)
    schematic_passed: bool
    pcb_passed: bool
    manufacturing_manifest_present: bool
    review_handoff_present: bool
    architecture_present: bool = False
    architecture_status: str | None = None
    architecture_requirement_count: int = Field(default=0, ge=0)
    architecture_bridge_status: str | None = None
    artifacts: list[GeneratedProjectArtifact]
    non_claims: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class GeneratedProjectEvidenceResult(BaseModel):
    """Generated schematic/PCB projects plus aggregate evidence bundle."""

    model_config = ConfigDict(strict=False, arbitrary_types_allowed=True)

    schematic: GeneratedKiCadSchematicProject
    pcb: GeneratedKiCadPcbProject
    bundle_path: Path
    bundle: GeneratedProjectEvidenceBundle


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _artifact(
    kind: GeneratedProjectArtifactKind,
    path: Path,
    root: Path,
    *,
    required: bool = True,
) -> GeneratedProjectArtifact:
    return GeneratedProjectArtifact(
        kind=kind,
        path=_relative(path, root),
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
        required=required,
    )


def generated_project_evidence_bundle_json(bundle: GeneratedProjectEvidenceBundle) -> str:
    """Serialize a generated-project evidence bundle as stable JSON."""
    return json.dumps(bundle.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, payload: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8", newline="\n")
    return path


def _write_manufacturing_manifest(compiled: CompiledDesignIR, output_dir: Path) -> Path:
    path = output_dir / "exports" / "manifest.json"
    payload = {
        "schema_version": "1.0",
        "family_id": compiled.report.family_id,
        "design_name": compiled.design.meta.name,
        "artifact_kind": "generated-manufacturing-export-manifest",
        "status": "review-only",
        "artifacts": [],
        "blocked": False,
        "warnings": [
            "No fabrication-ready Gerber/drill/BOM files are claimed by this generated-project evidence bundle.",
            "KiCad oracle, DRC/ERC, manufacturing export, and qualified human review are required before fabrication.",
        ],
        "non_claims": [
            "not fabrication-ready",
            "not manufacturer-approved",
            "not production-ready",
        ],
    }
    return _write_json(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_review_handoff(compiled: CompiledDesignIR, output_dir: Path) -> Path:
    path = output_dir / "review" / "handoff.json"
    payload = {
        "schema_version": "1.0",
        "family_id": compiled.report.family_id,
        "design_name": compiled.design.meta.name,
        "status": "human-review-required",
        "summary": "Generated board project is ready for engineering review, not fabrication.",
        "required_review_items": [
            "KiCad ERC/DRC oracle evidence",
            "netlist/parity evidence",
            "proof-pack sign-off",
            "manufacturing export validation",
            "qualified human engineering review",
        ],
        "non_claims": compiled.report.non_claims,
    }
    return _write_json(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _blocking_reasons(
    *,
    missing_required: int,
    schematic: GeneratedKiCadSchematicProject,
    pcb: GeneratedKiCadPcbProject,
    manufacturing_manifest_present: bool,
    review_handoff_present: bool,
) -> list[str]:
    reasons: list[str] = []
    if missing_required:
        reasons.append(f"{missing_required} required generated-project artifact(s) are missing")
    if not schematic.report.passed:
        reasons.append("schematic generation report did not pass")
    if not pcb.report.passed:
        reasons.append("PCB generation report did not pass")
    if not manufacturing_manifest_present:
        reasons.append("manufacturing export manifest is missing")
    if not review_handoff_present:
        reasons.append("review handoff is missing")
    return reasons


def generate_project_evidence_bundle(
    intent: BoardGenerationIntent,
    compiled: CompiledDesignIR,
    output_dir: str | Path,
    architecture: ElectronicsArchitectureArtifact | None = None,
) -> GeneratedProjectEvidenceResult:
    """Generate schematic/PCB artifacts and aggregate generated-project evidence."""
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    architecture_path: Path | None = None
    architecture_bridge_path: Path | None = None
    architecture_bridge_status: str | None = None
    if architecture is not None:
        architecture_path = _write_json(
            out / "architecture" / "electronics-architecture.json",
            electronics_architecture_artifact_json(architecture),
        )
        bridge_report = convert_architecture_to_board_generation_intent_report(
            architecture,
            family_id=intent.family_id,
        )
        architecture_bridge_status = bridge_report.status.value
        architecture_bridge_path = _write_json(
            out / "architecture" / "architecture-intent-bridge.json",
            architecture_intent_bridge_report_json(bridge_report),
        )

    intent_path = _write_json(out / "board-generation-intent.json", board_generation_intent_json(intent))
    compile_report_path = _write_json(
        out / f"{compiled.design.meta.name}.design_ir_compilation.json",
        design_ir_compilation_report_json(compiled.report),
    )
    schematic = generate_kicad_schematic_project(compiled, out)
    pcb = generate_kicad_pcb_project(compiled, out)
    manufacturing_manifest = _write_manufacturing_manifest(compiled, out)
    review_handoff = _write_review_handoff(compiled, out)

    artifacts = []
    if architecture_path is not None:
        artifacts.append(_artifact("architecture", architecture_path, out))
    if architecture_bridge_path is not None:
        artifacts.append(_artifact("architecture-intent-bridge-report", architecture_bridge_path, out))
    artifacts.extend(
        [
            _artifact("intent", intent_path, out),
            _artifact("design-ir-compile-report", compile_report_path, out),
            _artifact("kicad-project", schematic.project_path, out),
            _artifact("kicad-schematic", schematic.schematic_path, out),
            _artifact("schematic-generation-report", schematic.report_path, out),
            _artifact("kicad-pcb", pcb.pcb_path, out),
            _artifact("pcb-generation-report", pcb.report_path, out),
            _artifact("manufacturing-export-manifest", manufacturing_manifest, out),
            _artifact("review-handoff", review_handoff, out),
        ]
    )
    missing_required = sum(1 for artifact in artifacts if artifact.required and not (out / artifact.path).is_file())
    manufacturing_present = manufacturing_manifest.is_file()
    review_present = review_handoff.is_file()
    reasons = _blocking_reasons(
        missing_required=missing_required,
        schematic=schematic,
        pcb=pcb,
        manufacturing_manifest_present=manufacturing_present,
        review_handoff_present=review_present,
    )
    bundle = GeneratedProjectEvidenceBundle(
        design_name=compiled.design.meta.name,
        family_id=compiled.report.family_id,
        output_dir=out.as_posix(),
        passed=not reasons,
        artifact_count=len(artifacts),
        required_artifact_count=sum(1 for artifact in artifacts if artifact.required),
        missing_required_artifact_count=missing_required,
        requirement_trace_count=len(compiled.report.requirement_traces),
        provenance_record_count=len(compiled.design.prov_records),
        schematic_passed=schematic.report.passed,
        pcb_passed=pcb.report.passed,
        manufacturing_manifest_present=manufacturing_present,
        review_handoff_present=review_present,
        architecture_present=architecture is not None,
        architecture_status=architecture.status.value if architecture is not None else None,
        architecture_requirement_count=len(architecture.requirements) if architecture is not None else 0,
        architecture_bridge_status=architecture_bridge_status,
        artifacts=artifacts,
        non_claims=compiled.report.non_claims,
        blocking_reasons=reasons,
    )
    bundle_path = out / f"{compiled.design.meta.name}.generated_project_evidence.json"
    bundle_path.write_text(generated_project_evidence_bundle_json(bundle), encoding="utf-8", newline="\n")
    return GeneratedProjectEvidenceResult(
        schematic=schematic,
        pcb=pcb,
        bundle_path=bundle_path,
        bundle=bundle,
    )
