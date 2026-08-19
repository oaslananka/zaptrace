"""Compile board generation intent into ZapTrace Design IR."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace import __version__
from zaptrace.core.models import (
    ConstraintSet,
    Design,
    ManufacturingIntent,
    ProvRecord,
    RoutingIntent,
    VoltageDomainConstraint,
)
from zaptrace.generation.intent import BoardGenerationIntent, board_generation_intent_json
from zaptrace.synthesis.engine import TemplateSelection, synthesize_with_provenance

SUPPORTED_FAMILY_TEMPLATES: dict[str, str] = {
    "esp32_usb_sensor": "esp32 i2c sensor usb-c",
}


class CompilationStatus(StrEnum):
    """Intent-to-IR compilation status."""

    COMPILED = "compiled"
    UNSUPPORTED_FAMILY = "unsupported-family"


class RequirementTrace(BaseModel):
    """Requirement trace recorded during intent compilation."""

    model_config = ConfigDict(strict=False)

    requirement_id: str
    release_blocking: bool
    source: str
    target_artifact: str = "design-ir"


class DesignIRCompilationReport(BaseModel):
    """Machine-readable report for intent-to-Design IR compilation."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    status: CompilationStatus
    family_id: str
    design_name: str
    template_id: str | None = None
    template_name: str | None = None
    template_match_score: int | None = None
    method: str = "template_selection"
    requirement_traces: list[RequirementTrace] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    non_claims: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)

    @property
    def compiled(self) -> bool:
        return self.status == CompilationStatus.COMPILED

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class CompiledDesignIR(BaseModel):
    """Design IR plus compilation report."""

    model_config = ConfigDict(strict=False, arbitrary_types_allowed=True)

    design: Design
    report: DesignIRCompilationReport


def supported_generation_families() -> list[str]:
    """Return board families supported by the first intent-to-IR compiler."""
    return sorted(SUPPORTED_FAMILY_TEMPLATES)


def _intent_hash(intent: BoardGenerationIntent) -> str:
    return hashlib.sha256(board_generation_intent_json(intent).encode("utf-8")).hexdigest()


def _requirement_traces(intent: BoardGenerationIntent) -> list[RequirementTrace]:
    return [
        RequirementTrace(requirement_id=req.id, release_blocking=req.release_blocking, source=req.source)
        for req in intent.requirements
    ]


def _voltage_domain_id(net_name: str) -> str:
    return net_name.replace(" ", "_").replace("-", "_").upper()


def _voltage_domains(intent: BoardGenerationIntent) -> list[VoltageDomainConstraint]:
    domains: list[VoltageDomainConstraint] = []
    for power in intent.power:
        if power.voltage_v is None:
            continue
        domains.append(
            VoltageDomainConstraint(
                id=_voltage_domain_id(power.net_name),
                nominal=f"{power.voltage_v:g}V",
                tolerance="review-required",
            )
        )
    return domains


def _routing_intents(intent: BoardGenerationIntent) -> list[RoutingIntent]:
    routing: list[RoutingIntent] = []
    for interface in intent.interfaces:
        for net in interface.nets:
            routing.append(
                RoutingIntent(
                    net=net,
                    differential_pair=interface.controlled_impedance,
                    impedance_ohm=90.0 if interface.controlled_impedance else None,
                    reason=f"{interface.name}:{interface.role} from board generation intent",
                )
            )
    return routing


def _apply_intent_to_design(
    design: Design,
    intent: BoardGenerationIntent,
    selection: TemplateSelection,
) -> Design:
    design.meta.name = intent.design_name
    design.meta.description = intent.description or design.meta.description
    tags = set(design.meta.tags)
    tags.update(
        {
            "generated-board-intent",
            f"family:{intent.family_id}",
            "not-fabrication-ready",
            f"template:{selection.template_id}",
        }
    )
    design.meta.tags = sorted(tags)
    design.constraints = ConstraintSet(
        voltage_domains=_voltage_domains(intent),
        routing=_routing_intents(intent),
        manufacturing=ManufacturingIntent(
            profile="reviewable-generated-board",
            min_trace_mm="profile",
            min_space_mm="profile",
            reason="generated from board generation intent; review required before fabrication",
        ),
    )
    design.prov_records.append(
        ProvRecord(
            record_id=f"intent-compile:{intent.family_id}:{intent.design_name}",
            tool="zaptrace.generation.compiler",
            tool_version=__version__,
            input_artifact_ids=[f"board-generation-intent:{intent.family_id}:{intent.design_name}"],
            output_artifact_ids=[f"design-ir:{intent.design_name}"],
            artifact_hashes={"board_generation_intent": _intent_hash(intent)},
            decision_summary=(
                "Compiled board generation intent to reviewable Design IR via bounded template selection; "
                "not fabrication-ready."
            ),
        )
    )
    return design


def compile_intent_to_design_ir(intent: BoardGenerationIntent) -> CompiledDesignIR:
    """Compile a supported board generation intent into ZapTrace Design IR."""
    traces = _requirement_traces(intent)
    if intent.family_id not in SUPPORTED_FAMILY_TEMPLATES:
        report = DesignIRCompilationReport(
            status=CompilationStatus.UNSUPPORTED_FAMILY,
            family_id=intent.family_id,
            design_name=intent.design_name,
            requirement_traces=traces,
            non_claims=intent.non_claims,
            blocking_reasons=[
                f"No intent-to-Design IR compiler template is registered for family '{intent.family_id}'"
            ],
        )
        raise ValueError(json.dumps(report.model_dump(mode="json"), sort_keys=True))

    design, selection = synthesize_with_provenance(SUPPORTED_FAMILY_TEMPLATES[intent.family_id])
    design = _apply_intent_to_design(design, intent, selection)
    report = DesignIRCompilationReport(
        status=CompilationStatus.COMPILED,
        family_id=intent.family_id,
        design_name=intent.design_name,
        template_id=selection.template_id,
        template_name=selection.template_name,
        template_match_score=selection.match_score,
        method=selection.method,
        requirement_traces=traces,
        assumptions=[
            "compiler uses deterministic template selection, not from-scratch circuit synthesis",
            "generated Design IR requires KiCad generation and proof-pack review before fabrication",
        ],
        non_claims=intent.non_claims,
    )
    return CompiledDesignIR(design=design, report=report)


def design_ir_compilation_report_json(report: DesignIRCompilationReport) -> str:
    """Serialize a Design IR compilation report as stable JSON."""
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
