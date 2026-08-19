"""Generate reviewable KiCad PCB projects from compiled Design IR."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.core.board import canonical_board_definition
from zaptrace.export.kicad import export_kicad_pcb
from zaptrace.generation.compiler import CompiledDesignIR
from zaptrace.generation.kicad_schematic import _claim_violations

PcbArtifactKind = Literal["pcb"]


class GeneratedPcbArtifact(BaseModel):
    """One generated KiCad PCB artifact."""

    model_config = ConfigDict(strict=False)

    kind: PcbArtifactKind
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)


class GeneratedKiCadPcbReport(BaseModel):
    """Evidence report for a generated KiCad PCB project."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    design_name: str
    family_id: str
    output_dir: str
    passed: bool
    generated_files: list[GeneratedPcbArtifact]
    board_width_mm: float = Field(gt=0)
    board_height_mm: float = Field(gt=0)
    layer_count: int = Field(ge=1)
    net_count: int = Field(ge=0)
    component_count: int = Field(ge=0)
    placement_count: int = Field(ge=0)
    routed_segment_count: int = Field(ge=0)
    routed_via_count: int = Field(ge=0)
    routing_constraint_count: int = Field(ge=0)
    requirement_trace_count: int = Field(ge=0)
    provenance_record_count: int = Field(ge=0)
    non_claims: list[str] = Field(default_factory=list)
    claim_violations: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class GeneratedKiCadPcbProject(BaseModel):
    """Generated KiCad PCB file and evidence report."""

    model_config = ConfigDict(strict=False, arbitrary_types_allowed=True)

    pcb_path: Path
    report_path: Path
    report: GeneratedKiCadPcbReport


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _stabilize_kicad_uuids(path: Path, *, seed: str) -> None:
    """Rewrite KiCad UUID atoms deterministically for generated-board evidence."""
    text = path.read_text(encoding="utf-8")
    counter = 0

    def replacement(_match: re.Match[str]) -> str:
        nonlocal counter
        counter += 1
        stable = uuid.uuid5(uuid.NAMESPACE_URL, f"zaptrace:{seed}:kicad-pcb:{counter}")
        return f'(uuid "{stable}")'

    path.write_text(re.sub(r'\(uuid "[^"]+"\)', replacement, text), encoding="utf-8", newline="\n")


def _artifact(path: Path, root: Path) -> GeneratedPcbArtifact:
    return GeneratedPcbArtifact(
        kind="pcb",
        path=_relative(path, root),
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
    )


def generated_kicad_pcb_report_json(report: GeneratedKiCadPcbReport) -> str:
    """Serialize a generated PCB report as stable JSON."""
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def generate_kicad_pcb_project(
    compiled: CompiledDesignIR,
    output_dir: str | Path,
) -> GeneratedKiCadPcbProject:
    """Generate a reviewable KiCad PCB file from compiled Design IR.

    This emits `.kicad_pcb` plus a machine-readable evidence report. It does not
    claim the generated PCB is routed, DRC-clean, or fabrication-ready.
    """
    out = Path(output_dir).resolve()
    files = export_kicad_pcb(compiled.design, out)
    pcb_path = files["pcb"]
    _stabilize_kicad_uuids(pcb_path, seed=compiled.design.meta.name)
    claim_violations = _claim_violations([pcb_path])
    board = canonical_board_definition(compiled.design)
    routing = compiled.design.routing
    placement_count = len(compiled.design.placement or {})
    report = GeneratedKiCadPcbReport(
        design_name=compiled.design.meta.name,
        family_id=compiled.report.family_id,
        output_dir=".",
        passed=not claim_violations,
        generated_files=[_artifact(pcb_path, out)],
        board_width_mm=board.width,
        board_height_mm=board.height,
        layer_count=board.layers,
        net_count=len(compiled.design.nets),
        component_count=len(compiled.design.components),
        placement_count=placement_count,
        routed_segment_count=len(routing.traces) if routing else 0,
        routed_via_count=len(routing.vias) if routing else 0,
        routing_constraint_count=len(compiled.design.constraints.routing),
        requirement_trace_count=len(compiled.report.requirement_traces),
        provenance_record_count=len(compiled.design.prov_records),
        non_claims=compiled.report.non_claims,
        claim_violations=claim_violations,
    )
    report_path = out / f"{compiled.design.meta.name}.kicad_pcb_generation.json"
    report_path.write_text(generated_kicad_pcb_report_json(report), encoding="utf-8", newline="\n")
    return GeneratedKiCadPcbProject(
        pcb_path=pcb_path,
        report_path=report_path,
        report=report,
    )
