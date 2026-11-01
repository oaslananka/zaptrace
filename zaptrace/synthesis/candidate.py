"""Bounded, deterministic architecture candidate with non-inferred provenance.

A candidate is NOT ERC/DRC/simulation/EDA verified and is never fabrication
approved. Exact emitting block ownership is captured during composition;
there is no guessed component-name-to-requirement trace.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from zaptrace.core.models import Design
from zaptrace.erc.runner import ERCRunner
from zaptrace.synthesis.architecture import ArchitecturePlan, build_architecture_design
from zaptrace.synthesis.candidate_footprints import qualify_candidate_footprints
from zaptrace.synthesis.candidate_physical import qualify_pilot_physical_pins
from zaptrace.synthesis.requirements import (
    Requirements,
    freeze_requirements,
    parse_requirements,
    requirement_ids,
    requirements_assumptions,
    requirements_conflicts,
)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class CandidateReport:
    schema_version: Literal["1.0"]
    requirements_hash: str
    intent_hash: str
    candidate_id: str
    design_hash: str
    status: Literal["blocked", "review_required", "bounded_candidate"]
    requirements: list[dict[str, Any]]
    frozen_requirements: dict[str, Any]
    architecture: dict[str, Any]
    emitted_components: list[dict[str, Any]]
    emitted_nets: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    internal_erc_evidence: dict[str, Any]
    footprint_evidence: dict[str, Any]
    blockers: list[dict[str, str]]
    pending_assumptions: list[dict[str, Any]]
    verification: dict[str, str | bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "requirements_hash": self.requirements_hash,
            "intent_hash": self.intent_hash,
            "candidate_id": self.candidate_id,
            "design_hash": self.design_hash,
            "status": self.status,
            "requirements": self.requirements,
            "frozen_requirements": self.frozen_requirements,
            "architecture": self.architecture,
            "emitted_components": self.emitted_components,
            "emitted_nets": self.emitted_nets,
            "decisions": self.decisions,
            "internal_erc_evidence": self.internal_erc_evidence,
            "footprint_evidence": self.footprint_evidence,
            "blockers": self.blockers,
            "pending_assumptions": self.pending_assumptions,
            "verification": self.verification,
        }


def _block_requirement_ids(block_id: str, plan: ArchitecturePlan, existing: set[str]) -> list[str]:
    block = next((b for b in plan.blocks if b.block_id == block_id), None)
    if block is None:
        return []
    ids: list[str] = []
    if block_id in ("PB_USB_C_CC", "J_USB_C") and "REQ-USB-C" in existing:
        ids.append("REQ-USB-C")
    if (block_id.startswith("PB_REG_") or block_id.startswith("J_DC_")) and "REQ-POWER-RAILS" in existing:
        ids.append("REQ-POWER-RAILS")
    if block_id.startswith("IF_"):
        key = f"REQ-IFACE-{block_id.removeprefix('IF_')}"
        if key in existing:
            ids.append(key)
    if block_id == "CORE_MCU" and "REQ-MCU" in existing:
        ids.append("REQ-MCU")
    if block.kind == "peripheral":
        key = f"REQ-IFACE-{str(block.params.get('bus', '')).upper()}"
        if key in existing:
            ids.append(key)
    return sorted(set(ids))


def _emitted_provenance(
    design: Design, plan: ArchitecturePlan, ownership: dict[str, str], requirements: Requirements
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]], list[str]]:
    known = {row["id"] for row in requirement_ids(requirements)}
    blocks = {block.block_id: block for block in plan.blocks}
    blockers: list[dict[str, str]] = []
    unverified_pin_refs: set[str] = set()
    component_rows: list[dict[str, Any]] = []
    for cid in sorted(design.components):
        owner = ownership.get(cid)
        if owner not in blocks:
            blockers.append({"code": "component_without_emission_provenance", "subject": cid})
        source = blocks.get(owner) if owner else None
        component_rows.append(
            {
                "id": cid,
                "block_id": owner,
                "requirement_ids": _block_requirement_ids(owner, plan, known) if owner else [],
                "reusable_block": source.kind if source else None,
                "calculator": source.calculator if source else None,
                "assumptions": (
                    ["peripheral_part_selected_by_bounded_keyword_rule"]
                    if source is not None and source.kind == "peripheral"
                    else []
                ),
            }
        )
    net_rows: list[dict[str, Any]] = []
    for nid, net in sorted(design.nets.items()):
        linked: set[str] = set()
        for node in net.nodes:
            component = design.get_component(node.component_ref)
            if component is None:
                blockers.append({"code": "net_node_without_component", "subject": f"{nid}:{node.component_ref}"})
                continue
            if not component.pins:
                # Legacy passive and regulator blocks omit a pin dictionary.
                # Keep the unverified pin relationship explicit; do not infer it.
                unverified_pin_refs.add(component.id)
            elif node.pin_name not in component.pins:
                blockers.append(
                    {"code": "net_node_without_known_pin", "subject": f"{nid}:{node.component_ref}.{node.pin_name}"}
                )
            owner = ownership.get(component.id)
            if owner:
                linked.add(owner)
        if not linked:
            blockers.append({"code": "net_without_emission_provenance", "subject": nid})
        net_rows.append(
            {
                "id": nid,
                "block_ids": sorted(linked),
                "requirement_ids": sorted(
                    {requirement for owner in linked for requirement in _block_requirement_ids(owner, plan, known)}
                ),
                "connected_nodes": len(net.nodes),
                "assumptions": (
                    ["peripheral_part_selected_by_bounded_keyword_rule"]
                    if any(blocks[owner].kind == "peripheral" for owner in linked)
                    else []
                ),
            }
        )
    return component_rows, net_rows, blockers, sorted(unverified_pin_refs)


def _interface_connectivity_blockers(
    design: Design, plan: ArchitecturePlan, requirements: Requirements
) -> list[dict[str, str]]:
    if "i2c" not in requirements.interfaces:
        return []
    if requirements.mcu is None:
        return [{"code": "i2c_host_or_external_connector_missing", "subject": "i2c"}]
    core = next((b for b in plan.blocks if b.block_id == "CORE_MCU"), None)
    if core is None or not core.realized:
        return [{"code": "i2c_controller_unrealized", "subject": "i2c"}]
    # The actual MCU must be electrically present on both existing bus nets.
    for net_id in ("SDA", "SCL"):
        net = design.nets.get(net_id)
        if net is None or not any(
            (comp := design.get_component(node.component_ref)) is not None and comp.type == "mcu" for node in net.nodes
        ):
            return [{"code": "i2c_host_not_wired_to_bus", "subject": net_id}]
    return []


def compile_candidate(requirements: Requirements, *, name: str = "SynthesizedBoard") -> tuple[Design, CandidateReport]:
    """Compile only supported canonical blocks; never assert ERC/DFM approval."""
    owners: dict[str, str] = {}
    design, plan, decision_log = build_architecture_design(requirements, name=name, component_owners=owners)
    footprint_evidence = qualify_candidate_footprints(design, requirements)
    physical_pin_evidence = qualify_pilot_physical_pins(design, requirements)
    freeze = freeze_requirements(requirements)
    component_rows, net_rows, provenance_blockers, unverified_pin_refs = _emitted_provenance(
        design, plan, owners, requirements
    )
    blockers: list[dict[str, str]] = [
        {"code": "contradictory_requirements", "subject": row["conflict"]}
        for row in requirements_conflicts(requirements)
    ]
    blockers.extend({"code": "unmet_block_contract", "subject": f"{gap.block_id}:{gap.token}"} for gap in plan.unmet)
    blockers.extend(
        {"code": "unsupported_architecture_block", "subject": block.block_id} for block in plan.unrealized_blocks
    )
    blockers.extend(provenance_blockers)
    blockers.extend(physical_pin_evidence["blockers"])
    blockers.extend(_interface_connectivity_blockers(design, plan, requirements))
    # Never accept generic LDO pin claims: the library has no identified
    # manufacturer device/pin map for LDO_3.3V.
    for item in footprint_evidence.unresolved:
        blockers.append({"code": "no_part_specific_footprint_evidence", "subject": item["ref"]})
    if not component_rows or not net_rows:
        blockers.append({"code": "no_usable_canonical_design", "subject": "design"})
    # Explicit low-confidence emission decisions must not count as verified.
    blockers.extend(
        {"code": "unsupported_emission_decision", "subject": decision.parameter}
        for decision in decision_log.decisions
        if decision.category in {"gap", "note"} and not decision.confidence
    )
    erc = ERCRunner().run(design)
    blockers.extend(
        {"code": "internal_erc_error", "subject": violation.rule_id}
        for violation in erc.violations
        if violation.severity == "error"
    )
    assumptions = requirements_assumptions(requirements)
    if unverified_pin_refs:
        assumptions.append(
            {
                "field": "emitted_pin_inventory",
                "assumption": (
                    "Pin inventories missing for emitted components "
                    + ", ".join(unverified_pin_refs)
                    + "; native pin identity not confirmed"
                ),
                "risk": "high",
                "requires_confirmation": True,
            }
        )
    if physical_pin_evidence["qualified"]:
        assumptions.append(
            {
                "field": "source_documented_stm32_and_usb_pin_geometry",
                "assumption": (
                    "ST DS5319 LQFP48 and RM0008 I2C1 function mapping, plus GCT USB4105 "
                    "SHA-vetted KiCad pad geometry are source documented only. "
                    "Physical assembly, alternate functions, orientation and engineering "
                    "review must still be independently qualified."
                ),
                "risk": "high",
                "requires_confirmation": True,
            }
        )
    if any(item.get("mpn") for item in footprint_evidence.qualified):
        assumptions.append(
            {
                "field": "selected_ldo_part_and_enable",
                "assumption": (
                    "Starter-library AP2112K-3.3TRG1 5-pin mapping selected for 3.3V USB-C pilot; "
                    "EN tied to VBUS. Land pattern, load stability, manufacturer evidence, "
                    "thermal, sourcing and procurement need independent review."
                ),
                "risk": "high",
                "requires_confirmation": True,
            }
        )
    if footprint_evidence.qualified:
        assumptions.append(
            {
                "field": "generic_passive_footprint_qualification",
                "assumption": (
                    "0402 two-pad geometry resolved for generic passives; "
                    "manufacturer part, voltage/current limits, tolerance and sourcing still unverified"
                ),
                "risk": "medium",
                "requires_confirmation": True,
            }
        )
    if any(block.kind == "peripheral" and block.realized for block in plan.blocks):
        assumptions.append(
            {
                "field": "peripheral_part_choice",
                "assumption": (
                    "Named part selected deterministically from bounded keyword rule, not explicit MPN approval"
                ),
                "risk": "medium",
                "requires_confirmation": True,
            }
        )
    if erc.total_warnings:
        assumptions.append(
            {
                "field": "internal_erc_warnings",
                "assumption": f"{erc.total_warnings} native-independent ERC warnings need review or typed repair",
                "risk": "high",
                "requires_confirmation": True,
            }
        )
    if blockers:
        status: Literal["blocked", "review_required", "bounded_candidate"] = "blocked"
    elif assumptions:
        status = "review_required"
    else:
        status = "bounded_candidate"
    serialized = design.model_dump(mode="json", exclude_none=True)
    design_hash = _digest(serialized)
    intent_hash = _digest({"raw_intent": requirements.raw_intent})
    candidate_id = _digest(
        {
            "schema_version": "1.0",
            "requirements_hash": freeze["hash"],
            "intent_hash": intent_hash,
            "architecture": plan.to_dict(),
            "design_hash": design_hash,
            "component_provenance": component_rows,
            "net_provenance": net_rows,
        }
    )
    report = CandidateReport(
        schema_version="1.0",
        requirements_hash=freeze["hash"],
        intent_hash=intent_hash,
        candidate_id=candidate_id,
        design_hash=design_hash,
        status=status,
        requirements=requirement_ids(requirements),
        frozen_requirements=freeze["frozen"],
        architecture=plan.to_dict(),
        emitted_components=component_rows,
        emitted_nets=net_rows,
        decisions=decision_log.to_dicts(),
        footprint_evidence={**footprint_evidence.to_dict(), "device_pin_source_evidence": physical_pin_evidence},
        internal_erc_evidence={
            "checker": "zaptrace_internal_erc_not_native_kicad",
            "errors": erc.total_errors,
            "warnings": erc.total_warnings,
            "checks_run": len(erc.checks_run),
            "coverage_gaps": erc.coverage_gaps,
            "violations": [
                {"rule_id": item.rule_id, "severity": str(item.severity), "message": item.message}
                for item in erc.violations
            ],
        },
        blockers=blockers,
        pending_assumptions=assumptions,
        verification={
            "internal_erc": (
                "blocked" if erc.total_errors else "warning" if erc.total_warnings else "passed_with_known_limitations"
            ),
            "native_erc": "not_checked",
            "simulation": "not_checked",
            "pcb_routing": "not_checked",
            "native_drc": "not_checked",
            "kicad_roundtrip": "not_checked",
            "easyeda_standard_roundtrip": "not_checked",
            "fabrication_approved": False,
        },
    )
    return design, report


def compile_intent(intent: str, *, name: str = "SynthesizedBoard") -> tuple[Design, CandidateReport]:
    return compile_candidate(parse_requirements(intent), name=name)
