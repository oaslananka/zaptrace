"""Architecture-derived schematic topology planning."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from zaptrace import __version__
from zaptrace.core.models import Design, NetType
from zaptrace.generation.architecture import ArchitectureCompileStatus, ElectronicsArchitectureArtifact
from zaptrace.generation.compiler import CompiledDesignIR
from zaptrace.generation.intent import BoardGenerationIntent


class TopologySynthesisStatus(StrEnum):
    """Status emitted by topology-aware schematic planning."""

    SYNTHESIZED = "synthesized"
    BLOCKED = "blocked"


class SchematicTopologyBlock(BaseModel):
    """Architecture-derived functional schematic block."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    component_refs: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)


type TopologyNetType = Literal["power", "ground", "signal", "data", "clock", "differential", "analog"]


class SchematicTopologyNet(BaseModel):
    """Topology-level net with requirement trace."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    net_type: TopologyNetType
    nodes: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    evidence_required: bool = True


class SchematicTopologyInterface(BaseModel):
    """Architecture interface mapped into schematic nets."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    protocol: str = Field(min_length=1)
    role: str = Field(default="unspecified")
    nets: list[str] = Field(default_factory=list)
    controlled_impedance: bool = False
    requirement_ids: list[str] = Field(default_factory=list)


class SchematicTopologyPlan(BaseModel):
    """Topology-aware schematic plan derived from architecture and Design IR."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    status: TopologySynthesisStatus
    design_name: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    method: Literal["architecture_topology_planning"] = "architecture_topology_planning"
    source_architecture_status: ArchitectureCompileStatus
    source_compiler_method: str
    blocks: list[SchematicTopologyBlock] = Field(default_factory=list)
    interfaces: list[SchematicTopologyInterface] = Field(default_factory=list)
    nets: list[SchematicTopologyNet] = Field(default_factory=list)
    requirement_trace_count: int = Field(default=0, ge=0)
    blocking_reasons: list[str] = Field(default_factory=list)
    non_claims: list[str] = Field(default_factory=list)

    @property
    def synthesized(self) -> bool:
        """Return whether topology planning succeeded."""
        return self.status == TopologySynthesisStatus.SYNTHESIZED

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return self.model_dump(mode="json")


def schematic_topology_plan_json(plan: SchematicTopologyPlan) -> str:
    """Serialize a schematic topology plan as stable JSON."""
    return json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


_TOPOLOGY_TOOL_NAME = "zaptrace.generation.topology"


_COMPONENT_KIND_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mcu": ("esp", "mcu", "microcontroller"),
    "sensor": ("sensor", "bme", "imu", "temperature"),
    "power": ("reg", "ldo", "ams", "buck", "charger"),
    "interface": ("usb", "connector", "j"),
}


def _component_refs_for_kind(design: Design, kind: str) -> list[str]:
    keywords = _COMPONENT_KIND_KEYWORDS.get(kind, ())
    matches: list[str] = []
    for ref, component in design.components.items():
        type_text = f"{component.type} {component.value or ''} {component.ref}".lower()
        if any(token in type_text for token in keywords):
            matches.append(ref)
    return sorted(matches)


def _block_for_subsystem(
    architecture: ElectronicsArchitectureArtifact,
    design: Design,
) -> list[SchematicTopologyBlock]:
    blocks: list[SchematicTopologyBlock] = []
    for subsystem in architecture.subsystems:
        refs = _component_refs_for_kind(design, subsystem.kind)
        blocks.append(
            SchematicTopologyBlock(
                id=subsystem.id,
                name=subsystem.name,
                kind=subsystem.kind,
                component_refs=refs,
                requirement_ids=subsystem.requirement_ids,
            )
        )
    return blocks


def _net_type(net_type: NetType) -> TopologyNetType:
    value = net_type.value
    if value in {"power", "ground", "data", "clock", "differential", "analog"}:
        return value
    return "signal"


def _requirement_ids_for_net(
    net_name: str,
    architecture: ElectronicsArchitectureArtifact,
) -> list[str]:
    ids: set[str] = set()
    for rail in architecture.power_tree:
        if rail.net_name == net_name:
            ids.update(rail.requirement_ids)
    for interface in architecture.interfaces:
        if net_name in interface.nets:
            ids.update(interface.requirement_ids)
    if net_name == "GND":
        ids.update(req.id for req in architecture.requirements if req.category.value == "power")
    return sorted(ids)


def _topology_nets(
    architecture: ElectronicsArchitectureArtifact,
    design: Design,
) -> list[SchematicTopologyNet]:
    nets: list[SchematicTopologyNet] = []
    for net in design.nets.values():
        nodes = [f"{node.component_ref}.{node.pin_name}" for node in net.nodes]
        nets.append(
            SchematicTopologyNet(
                name=net.name,
                net_type=_net_type(net.type),
                nodes=sorted(nodes),
                requirement_ids=_requirement_ids_for_net(net.name, architecture),
            )
        )
    return sorted(nets, key=lambda item: item.name)


def _topology_interfaces(
    architecture: ElectronicsArchitectureArtifact,
) -> list[SchematicTopologyInterface]:
    return [
        SchematicTopologyInterface(
            name=interface.name,
            protocol=interface.protocol,
            role=interface.role,
            nets=interface.nets,
            controlled_impedance=interface.controlled_impedance,
            requirement_ids=interface.requirement_ids,
        )
        for interface in architecture.interfaces
    ]


def synthesize_schematic_topology_plan(
    architecture: ElectronicsArchitectureArtifact,
    intent: BoardGenerationIntent,
    compiled: CompiledDesignIR,
) -> SchematicTopologyPlan:
    """Create a topology-aware schematic plan from architecture and compiled Design IR."""
    if architecture.status != ArchitectureCompileStatus.READY:
        return SchematicTopologyPlan(
            status=TopologySynthesisStatus.BLOCKED,
            design_name=compiled.design.meta.name,
            family_id=intent.family_id,
            source_architecture_status=architecture.status,
            source_compiler_method=compiled.report.method,
            requirement_trace_count=len(compiled.report.requirement_traces),
            blocking_reasons=architecture.blocking_reasons or [f"architecture status is {architecture.status.value}"],
            non_claims=compiled.report.non_claims,
        )

    blocks = _block_for_subsystem(architecture, compiled.design)
    interfaces = _topology_interfaces(architecture)
    nets = _topology_nets(architecture, compiled.design)
    reasons: list[str] = []
    if not blocks:
        reasons.append("architecture does not define schematic topology blocks")
    if not nets:
        reasons.append("compiled Design IR does not define topology nets")

    return SchematicTopologyPlan(
        status=TopologySynthesisStatus.BLOCKED if reasons else TopologySynthesisStatus.SYNTHESIZED,
        design_name=compiled.design.meta.name,
        family_id=intent.family_id,
        source_architecture_status=architecture.status,
        source_compiler_method=compiled.report.method,
        blocks=blocks,
        interfaces=interfaces,
        nets=nets,
        requirement_trace_count=len(compiled.report.requirement_traces),
        blocking_reasons=reasons,
        non_claims=compiled.report.non_claims,
    )


def _topology_plan_hash(plan: SchematicTopologyPlan) -> str:
    import hashlib

    return hashlib.sha256(schematic_topology_plan_json(plan).encode("utf-8")).hexdigest()


def apply_schematic_topology_to_design_ir(
    compiled: CompiledDesignIR,
    plan: SchematicTopologyPlan,
) -> CompiledDesignIR:
    """Apply a synthesized topology plan to Design IR functional blocks."""
    from zaptrace.core.models import Block, ProvRecord

    if not plan.synthesized:
        raise ValueError(
            json.dumps(
                {
                    "status": plan.status.value,
                    "blocking_reasons": plan.blocking_reasons,
                    "design_name": plan.design_name,
                },
                sort_keys=True,
            )
        )

    design = compiled.design.model_copy(deep=True)
    design.blocks = [
        Block(
            id=block.id,
            name=block.name,
            components=[ref for ref in block.component_refs if ref in design.components],
        )
        for block in plan.blocks
    ]
    tags = set(design.meta.tags)
    tags.update({"architecture-topology-applied", "topology-driven-schematic"})
    design.meta.tags = sorted(tags)
    design.prov_records.append(
        ProvRecord(
            record_id=f"topology-plan:{plan.family_id}:{plan.design_name}",
            tool=_TOPOLOGY_TOOL_NAME,
            tool_version=__version__,
            input_artifact_ids=[f"schematic-topology-plan:{plan.family_id}:{plan.design_name}"],
            output_artifact_ids=[f"design-ir-topology-blocks:{plan.design_name}"],
            artifact_hashes={"schematic_topology_plan": _topology_plan_hash(plan)},
            decision_summary=(
                "Applied architecture-derived schematic topology plan to Design IR functional blocks; "
                "not fabrication-ready."
            ),
        )
    )
    report = compiled.report.model_copy(
        update={
            "method": f"{compiled.report.method}+architecture_topology_planning",
            "assumptions": [
                *compiled.report.assumptions,
                "architecture-derived schematic topology plan applied to Design IR functional blocks",
            ],
        },
        deep=True,
    )
    return CompiledDesignIR(design=design, report=report)


class ComponentDecisionStatus(StrEnum):
    """Status emitted by topology component decision planning."""

    PLANNED = "planned"
    BLOCKED = "blocked"


class SchematicComponentDecision(BaseModel):
    """Topology-derived role and value decision for one component."""

    model_config = ConfigDict(extra="forbid")

    component_ref: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    selected_value: str | None = None
    current_value: str | None = None
    rationale: str = Field(min_length=1)
    requirement_ids: list[str] = Field(default_factory=list)
    evidence_required: bool = True


class SchematicComponentDecisionPlan(BaseModel):
    """Component role/value decision plan derived from schematic topology."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    status: ComponentDecisionStatus
    design_name: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    method: Literal["topology_component_decision_planning"] = "topology_component_decision_planning"
    source_topology_status: TopologySynthesisStatus
    decisions: list[SchematicComponentDecision] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    non_claims: list[str] = Field(default_factory=list)

    @property
    def planned(self) -> bool:
        """Return whether component decisions were planned."""
        return self.status == ComponentDecisionStatus.PLANNED

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return self.model_dump(mode="json")


def schematic_component_decision_plan_json(plan: SchematicComponentDecisionPlan) -> str:
    """Serialize a component decision plan as stable JSON."""
    return json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def _infer_component_role(component_type: str, value: str | None, ref: str) -> str:
    text = f"{component_type} {value or ''} {ref}".lower()
    if any(token in text for token in ("esp", "mcu", "microcontroller")):
        return "microcontroller"
    if any(token in text for token in ("usb", "connector", "j")):
        return "external_connector"
    if any(token in text for token in ("sensor", "bme", "imu", "temperature")):
        return "sensor"
    if "resistor" in text or ref.upper().startswith("R"):
        return "pullup_or_bias_resistor"
    if "capacitor" in text or ref.upper().startswith("C"):
        return "decoupling_or_bulk_capacitor"
    if any(token in text for token in ("reg", "ldo", "buck", "charger")):
        return "power_regulation"
    return "support_component"


def _selected_value_for_role(role: str, current_value: str | None) -> str | None:
    if current_value:
        return current_value
    defaults = {
        "pullup_or_bias_resistor": "4.7k",
        "decoupling_or_bulk_capacitor": "100nF",
        "power_regulation": "3.3V regulator",
    }
    return defaults.get(role)


def _decision_rationale(role: str, block_name: str) -> str:
    rationales = {
        "microcontroller": "Core controller selected for the MCU topology block.",
        "external_connector": "Connector role selected from architecture interface topology.",
        "sensor": "Sensor component selected for the sensor topology block.",
        "pullup_or_bias_resistor": "Resistor value is carried or defaulted for bus/support biasing review.",
        "decoupling_or_bulk_capacitor": "Capacitor value is carried or defaulted for local rail stability review.",
        "power_regulation": "Power regulation role selected from power topology requirements.",
    }
    return rationales.get(role, f"Support component assigned to topology block {block_name}.")


def synthesize_component_decision_plan(
    plan: SchematicTopologyPlan,
    compiled: CompiledDesignIR,
) -> SchematicComponentDecisionPlan:
    """Create topology-derived component role/value decisions."""
    if not plan.synthesized:
        return SchematicComponentDecisionPlan(
            status=ComponentDecisionStatus.BLOCKED,
            design_name=plan.design_name,
            family_id=plan.family_id,
            source_topology_status=plan.status,
            blocking_reasons=plan.blocking_reasons or ["topology plan is not synthesized"],
            non_claims=plan.non_claims,
        )

    decisions: list[SchematicComponentDecision] = []
    for block in plan.blocks:
        for ref in block.component_refs:
            component = compiled.design.components.get(ref)
            if component is None:
                continue
            role = _infer_component_role(component.type, component.value, component.ref)
            decisions.append(
                SchematicComponentDecision(
                    component_ref=ref,
                    block_id=block.id,
                    role=role,
                    selected_value=_selected_value_for_role(role, component.value),
                    current_value=component.value,
                    rationale=_decision_rationale(role, block.name),
                    requirement_ids=block.requirement_ids,
                )
            )

    reasons: list[str] = []
    if not decisions:
        reasons.append("topology plan did not produce component decisions")

    return SchematicComponentDecisionPlan(
        status=ComponentDecisionStatus.BLOCKED if reasons else ComponentDecisionStatus.PLANNED,
        design_name=plan.design_name,
        family_id=plan.family_id,
        source_topology_status=plan.status,
        decisions=sorted(decisions, key=lambda item: (item.block_id, item.component_ref, item.role)),
        blocking_reasons=reasons,
        non_claims=plan.non_claims,
    )


def _component_decision_plan_hash(plan: SchematicComponentDecisionPlan) -> str:
    import hashlib

    return hashlib.sha256(schematic_component_decision_plan_json(plan).encode("utf-8")).hexdigest()


def apply_component_decision_plan_to_design_ir(
    compiled: CompiledDesignIR,
    plan: SchematicComponentDecisionPlan,
) -> CompiledDesignIR:
    """Apply component role/value decisions to Design IR component metadata."""
    from zaptrace.core.models import ProvRecord

    if not plan.planned:
        raise ValueError(
            json.dumps(
                {
                    "status": plan.status.value,
                    "blocking_reasons": plan.blocking_reasons,
                    "design_name": plan.design_name,
                },
                sort_keys=True,
            )
        )

    design = compiled.design.model_copy(deep=True)
    for decision in plan.decisions:
        component = design.components.get(decision.component_ref)
        if component is None:
            continue
        properties = dict(component.properties)
        properties["topology_role"] = decision.role
        properties["topology_block_id"] = decision.block_id
        properties["topology_selected_value"] = decision.selected_value or ""
        properties["topology_decision_rationale"] = decision.rationale
        component.properties = properties
        if component.value is None and decision.selected_value is not None:
            component.value = decision.selected_value

    tags = set(design.meta.tags)
    tags.add("topology-component-decisions-applied")
    design.meta.tags = sorted(tags)
    design.prov_records.append(
        ProvRecord(
            record_id=f"component-decisions:{plan.family_id}:{plan.design_name}",
            tool=_TOPOLOGY_TOOL_NAME,
            tool_version=__version__,
            input_artifact_ids=[f"component-decision-plan:{plan.family_id}:{plan.design_name}"],
            output_artifact_ids=[f"design-ir-component-decisions:{plan.design_name}"],
            artifact_hashes={"component_decision_plan": _component_decision_plan_hash(plan)},
            decision_summary=(
                "Applied topology-derived component role/value decisions to Design IR metadata; not fabrication-ready."
            ),
        )
    )
    report = compiled.report.model_copy(
        update={
            "method": f"{compiled.report.method}+topology_component_decision_planning",
            "assumptions": [
                *compiled.report.assumptions,
                "topology-derived component role/value decisions applied to Design IR metadata",
            ],
        },
        deep=True,
    )
    return CompiledDesignIR(design=design, report=report)


class BlockPlacementStatus(StrEnum):
    """Status emitted by topology block placement planning."""

    PLANNED = "planned"
    BLOCKED = "blocked"


class SchematicBlockPlacement(BaseModel):
    """Schematic sheet placement decision for one topology block."""

    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(min_length=1)
    block_name: str = Field(min_length=1)
    position: tuple[float, float]
    lane: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    requirement_ids: list[str] = Field(default_factory=list)


class SchematicBlockPlacementPlan(BaseModel):
    """Topology-derived schematic block placement plan."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    status: BlockPlacementStatus
    design_name: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    method: Literal["topology_block_placement_planning"] = "topology_block_placement_planning"
    source_topology_status: TopologySynthesisStatus
    placements: list[SchematicBlockPlacement] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    non_claims: list[str] = Field(default_factory=list)

    @property
    def planned(self) -> bool:
        """Return whether block placements were planned."""
        return self.status == BlockPlacementStatus.PLANNED

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return self.model_dump(mode="json")


def schematic_block_placement_plan_json(plan: SchematicBlockPlacementPlan) -> str:
    """Serialize a block placement plan as stable JSON."""
    return json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


_BLOCK_LANE_POSITIONS: dict[str, tuple[str, tuple[float, float]]] = {
    "power": ("left-power-entry", (20.0, 30.0)),
    "interface": ("left-external-interface", (20.0, 90.0)),
    "mcu": ("center-control", (110.0, 60.0)),
    "sensor": ("right-sensing", (200.0, 60.0)),
    "protection": ("left-protection", (55.0, 30.0)),
    "mechanical": ("bottom-mechanical", (110.0, 135.0)),
    "generic": ("support", (110.0, 110.0)),
}


def _placement_for_block(block: SchematicTopologyBlock, index: int) -> SchematicBlockPlacement:
    lane, base = _BLOCK_LANE_POSITIONS.get(block.kind, _BLOCK_LANE_POSITIONS["generic"])
    x, y = base
    return SchematicBlockPlacement(
        block_id=block.id,
        block_name=block.name,
        position=(x, y + index * 18.0),
        lane=lane,
        rationale=f"Placed {block.name} in the {lane} schematic lane for topology readability.",
        requirement_ids=block.requirement_ids,
    )


def synthesize_block_placement_plan(plan: SchematicTopologyPlan) -> SchematicBlockPlacementPlan:
    """Create deterministic schematic sheet placements from a topology plan."""
    if not plan.synthesized:
        return SchematicBlockPlacementPlan(
            status=BlockPlacementStatus.BLOCKED,
            design_name=plan.design_name,
            family_id=plan.family_id,
            source_topology_status=plan.status,
            blocking_reasons=plan.blocking_reasons or ["topology plan is not synthesized"],
            non_claims=plan.non_claims,
        )

    placements = [_placement_for_block(block, index) for index, block in enumerate(plan.blocks)]
    reasons: list[str] = []
    if not placements:
        reasons.append("topology plan did not produce block placements")
    return SchematicBlockPlacementPlan(
        status=BlockPlacementStatus.BLOCKED if reasons else BlockPlacementStatus.PLANNED,
        design_name=plan.design_name,
        family_id=plan.family_id,
        source_topology_status=plan.status,
        placements=placements,
        blocking_reasons=reasons,
        non_claims=plan.non_claims,
    )


def _block_placement_plan_hash(plan: SchematicBlockPlacementPlan) -> str:
    import hashlib

    return hashlib.sha256(schematic_block_placement_plan_json(plan).encode("utf-8")).hexdigest()


def apply_block_placement_plan_to_design_ir(
    compiled: CompiledDesignIR,
    plan: SchematicBlockPlacementPlan,
) -> CompiledDesignIR:
    """Apply block placement decisions to Design IR blocks."""
    from zaptrace.core.models import ProvRecord

    if not plan.planned:
        payload = {
            "status": plan.status.value,
            "blocking_reasons": plan.blocking_reasons,
            "design_name": plan.design_name,
        }
        raise ValueError(json.dumps(payload, sort_keys=True))

    design = compiled.design.model_copy(deep=True)
    by_id = {placement.block_id: placement for placement in plan.placements}
    for block in design.blocks:
        placement = by_id.get(block.id)
        if placement is not None:
            block.position = placement.position
    tags = set(design.meta.tags)
    tags.add("topology-block-placements-applied")
    design.meta.tags = sorted(tags)
    design.prov_records.append(
        ProvRecord(
            record_id=f"block-placement:{plan.family_id}:{plan.design_name}",
            tool=_TOPOLOGY_TOOL_NAME,
            tool_version=__version__,
            input_artifact_ids=[f"block-placement-plan:{plan.family_id}:{plan.design_name}"],
            output_artifact_ids=[f"design-ir-block-placement:{plan.design_name}"],
            artifact_hashes={"block_placement_plan": _block_placement_plan_hash(plan)},
            decision_summary="Applied topology-derived schematic block placements; not fabrication-ready.",
        )
    )
    report = compiled.report.model_copy(
        update={
            "method": f"{compiled.report.method}+topology_block_placement_planning",
            "assumptions": [
                *compiled.report.assumptions,
                "topology-derived schematic block placements applied to Design IR blocks",
            ],
        },
        deep=True,
    )
    return CompiledDesignIR(design=design, report=report)
