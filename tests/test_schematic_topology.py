from __future__ import annotations

import json

import pytest

from zaptrace.generation import (
    BlockPlacementStatus,
    ComponentDecisionStatus,
    TopologySynthesisStatus,
    apply_block_placement_plan_to_design_ir,
    apply_component_decision_plan_to_design_ir,
    apply_schematic_topology_to_design_ir,
    compile_electronics_intent_to_architecture,
    compile_intent_to_design_ir,
    convert_architecture_to_board_generation_intent,
    generate_kicad_schematic_project,
    schematic_block_placement_plan_json,
    schematic_component_decision_plan_json,
    schematic_topology_plan_json,
    synthesize_block_placement_plan,
    synthesize_component_decision_plan,
    synthesize_schematic_topology_plan,
)


def _ready_architecture_intent_compiled():
    architecture = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail",
        design_name="esp32_usb_temperature_sensor_architecture_v1",
    )
    intent = convert_architecture_to_board_generation_intent(architecture)
    compiled = compile_intent_to_design_ir(intent)
    return architecture, intent, compiled


def test_synthesize_schematic_topology_plan_from_ready_architecture() -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()

    plan = synthesize_schematic_topology_plan(architecture, intent, compiled)

    assert plan.status == TopologySynthesisStatus.SYNTHESIZED
    assert plan.synthesized is True
    assert plan.design_name == intent.design_name
    assert plan.family_id == "esp32_usb_sensor"
    assert plan.source_architecture_status == "ready"
    assert plan.source_compiler_method == "template_selection"
    assert plan.blocking_reasons == []
    assert {block.kind for block in plan.blocks} >= {"mcu", "sensor", "interface"}
    assert any(block.component_refs for block in plan.blocks if block.kind == "mcu")
    assert {interface.name for interface in plan.interfaces} >= {"usb", "i2c"}
    assert {net.name for net in plan.nets} >= {"VCC_3V3", "GND", "I2C_SDA", "I2C_SCL"}
    assert "not fabrication-ready" in " ".join(plan.non_claims)


def test_schematic_topology_plan_json_round_trip() -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()
    plan = synthesize_schematic_topology_plan(architecture, intent, compiled)

    payload = json.loads(schematic_topology_plan_json(plan))

    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "synthesized"
    assert payload["method"] == "architecture_topology_planning"
    assert payload["blocks"]
    assert payload["nets"]


def test_non_ready_architecture_blocks_topology_synthesis() -> None:
    architecture = compile_electronics_intent_to_architecture("make a small board")
    _, intent, compiled = _ready_architecture_intent_compiled()

    plan = synthesize_schematic_topology_plan(architecture, intent, compiled)

    assert plan.status == TopologySynthesisStatus.BLOCKED
    assert plan.synthesized is False
    assert plan.blocking_reasons == ["intent is too vague to derive electronics architecture"]
    assert plan.blocks == []
    assert plan.nets == []


def test_generate_kicad_schematic_project_with_topology_plan(tmp_path) -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()
    plan = synthesize_schematic_topology_plan(architecture, intent, compiled)

    generated = generate_kicad_schematic_project(compiled, tmp_path, topology_plan=plan)

    topology_path = tmp_path / f"{compiled.design.meta.name}.schematic_topology.json"
    payload = json.loads(generated.report_path.read_text(encoding="utf-8"))

    assert topology_path.is_file()
    assert generated.report.topology_present is True
    assert generated.report.topology_status == "synthesized"
    assert generated.report.topology_block_count == len(plan.blocks)
    assert generated.report.topology_net_count == len(plan.nets)
    assert "topology-plan" in {artifact.kind for artifact in generated.report.generated_files}
    assert payload["topology_present"] is True
    assert payload["topology_status"] == "synthesized"


def test_apply_schematic_topology_to_design_ir_populates_functional_blocks() -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()
    plan = synthesize_schematic_topology_plan(architecture, intent, compiled)

    applied = apply_schematic_topology_to_design_ir(compiled, plan)

    assert compiled.design.blocks == []
    assert applied.design.blocks
    assert {block.id for block in applied.design.blocks} >= {"SUBSYS-MCU", "SUBSYS-SENSOR", "SUBSYS-USB"}
    assert any(block.components for block in applied.design.blocks if block.id == "SUBSYS-MCU")
    assert "topology-driven-schematic" in applied.design.meta.tags
    assert applied.report.method.endswith("+architecture_topology_planning")
    assert applied.report.assumptions[-1] == (
        "architecture-derived schematic topology plan applied to Design IR functional blocks"
    )
    assert len(applied.design.prov_records) == len(compiled.design.prov_records) + 1
    assert applied.design.prov_records[-1].tool == "zaptrace.generation.topology"
    assert "schematic_topology_plan" in applied.design.prov_records[-1].artifact_hashes


def test_apply_schematic_topology_to_design_ir_rejects_blocked_plan() -> None:
    architecture = compile_electronics_intent_to_architecture("make a small board")
    _, intent, compiled = _ready_architecture_intent_compiled()
    plan = synthesize_schematic_topology_plan(architecture, intent, compiled)

    with pytest.raises(ValueError) as excinfo:
        apply_schematic_topology_to_design_ir(compiled, plan)

    payload = json.loads(str(excinfo.value))
    assert payload["status"] == "blocked"
    assert payload["blocking_reasons"] == ["intent is too vague to derive electronics architecture"]


def test_synthesize_component_decision_plan_from_topology() -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()
    topology = synthesize_schematic_topology_plan(architecture, intent, compiled)

    plan = synthesize_component_decision_plan(topology, compiled)

    assert plan.status == ComponentDecisionStatus.PLANNED
    assert plan.planned is True
    assert plan.design_name == topology.design_name
    assert plan.family_id == "esp32_usb_sensor"
    assert plan.source_topology_status == "synthesized"
    assert plan.decisions
    assert {decision.role for decision in plan.decisions} >= {
        "microcontroller",
        "external_connector",
        "sensor",
    }
    assert all(decision.requirement_ids for decision in plan.decisions)
    assert "not fabrication-ready" in " ".join(plan.non_claims)


def test_component_decision_plan_json_round_trip() -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()
    topology = synthesize_schematic_topology_plan(architecture, intent, compiled)
    plan = synthesize_component_decision_plan(topology, compiled)

    payload = json.loads(schematic_component_decision_plan_json(plan))

    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "planned"
    assert payload["method"] == "topology_component_decision_planning"
    assert payload["decisions"]


def test_apply_component_decision_plan_to_design_ir_annotates_components() -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()
    topology = synthesize_schematic_topology_plan(architecture, intent, compiled)
    decision_plan = synthesize_component_decision_plan(topology, compiled)

    applied = apply_component_decision_plan_to_design_ir(compiled, decision_plan)

    assert "topology-component-decisions-applied" in applied.design.meta.tags
    assert applied.report.method.endswith("+topology_component_decision_planning")
    assert applied.report.assumptions[-1] == (
        "topology-derived component role/value decisions applied to Design IR metadata"
    )
    assert len(applied.design.prov_records) == len(compiled.design.prov_records) + 1
    assert applied.design.prov_records[-1].tool == "zaptrace.generation.topology"
    assert "component_decision_plan" in applied.design.prov_records[-1].artifact_hashes

    annotated = [
        component for component in applied.design.components.values() if component.properties.get("topology_role")
    ]
    assert annotated
    assert {component.properties["topology_role"] for component in annotated} >= {
        "microcontroller",
        "external_connector",
        "sensor",
    }


def test_component_decision_plan_blocks_when_topology_is_blocked() -> None:
    architecture = compile_electronics_intent_to_architecture("make a small board")
    _, intent, compiled = _ready_architecture_intent_compiled()
    topology = synthesize_schematic_topology_plan(architecture, intent, compiled)

    plan = synthesize_component_decision_plan(topology, compiled)

    assert plan.status == ComponentDecisionStatus.BLOCKED
    assert plan.planned is False
    assert plan.blocking_reasons == ["intent is too vague to derive electronics architecture"]

    with pytest.raises(ValueError) as excinfo:
        apply_component_decision_plan_to_design_ir(compiled, plan)

    payload = json.loads(str(excinfo.value))
    assert payload["status"] == "blocked"


def test_synthesize_block_placement_plan_from_topology() -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()
    topology = synthesize_schematic_topology_plan(architecture, intent, compiled)

    plan = synthesize_block_placement_plan(topology)

    assert plan.status == BlockPlacementStatus.PLANNED
    assert plan.planned is True
    assert plan.design_name == topology.design_name
    assert plan.family_id == "esp32_usb_sensor"
    assert plan.source_topology_status == "synthesized"
    assert plan.placements
    assert {placement.block_id for placement in plan.placements} >= {
        "SUBSYS-MCU",
        "SUBSYS-SENSOR",
        "SUBSYS-USB",
    }
    assert all(placement.requirement_ids for placement in plan.placements)
    assert "not fabrication-ready" in " ".join(plan.non_claims)


def test_block_placement_plan_json_round_trip() -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()
    topology = synthesize_schematic_topology_plan(architecture, intent, compiled)
    plan = synthesize_block_placement_plan(topology)

    payload = json.loads(schematic_block_placement_plan_json(plan))

    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "planned"
    assert payload["method"] == "topology_block_placement_planning"
    assert payload["placements"]


def test_apply_block_placement_plan_to_design_ir_positions_blocks() -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()
    topology = synthesize_schematic_topology_plan(architecture, intent, compiled)
    applied_topology = apply_schematic_topology_to_design_ir(compiled, topology)
    placement_plan = synthesize_block_placement_plan(topology)

    applied = apply_block_placement_plan_to_design_ir(applied_topology, placement_plan)

    assert "topology-block-placements-applied" in applied.design.meta.tags
    assert applied.report.method.endswith("+topology_block_placement_planning")
    assert applied.report.assumptions[-1] == ("topology-derived schematic block placements applied to Design IR blocks")
    assert all(block.position is not None for block in applied.design.blocks)
    assert len(applied.design.prov_records) == len(applied_topology.design.prov_records) + 1
    assert applied.design.prov_records[-1].tool == "zaptrace.generation.topology"
    assert "block_placement_plan" in applied.design.prov_records[-1].artifact_hashes


def test_block_placement_plan_blocks_when_topology_is_blocked() -> None:
    architecture = compile_electronics_intent_to_architecture("make a small board")
    _, intent, compiled = _ready_architecture_intent_compiled()
    topology = synthesize_schematic_topology_plan(architecture, intent, compiled)

    plan = synthesize_block_placement_plan(topology)

    assert plan.status == BlockPlacementStatus.BLOCKED
    assert plan.planned is False
    assert plan.blocking_reasons == ["intent is too vague to derive electronics architecture"]

    with pytest.raises(ValueError) as excinfo:
        apply_block_placement_plan_to_design_ir(compiled, plan)

    payload = json.loads(str(excinfo.value))
    assert payload["status"] == "blocked"


def test_generate_kicad_schematic_project_with_all_planning_artifacts(tmp_path) -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()
    topology = synthesize_schematic_topology_plan(architecture, intent, compiled)
    component_plan = synthesize_component_decision_plan(topology, compiled)
    placement_plan = synthesize_block_placement_plan(topology)

    generated = generate_kicad_schematic_project(
        compiled,
        tmp_path,
        topology_plan=topology,
        component_decision_plan=component_plan,
        block_placement_plan=placement_plan,
    )

    artifact_kinds = {artifact.kind for artifact in generated.report.generated_files}
    assert artifact_kinds >= {
        "topology-plan",
        "component-decision-plan",
        "block-placement-plan",
    }
    assert (tmp_path / f"{compiled.design.meta.name}.component_decisions.json").is_file()
    assert (tmp_path / f"{compiled.design.meta.name}.block_placements.json").is_file()
    assert generated.report.component_decision_present is True
    assert generated.report.component_decision_count == len(component_plan.decisions)
    assert generated.report.block_placement_present is True
    assert generated.report.block_placement_count == len(placement_plan.placements)

    payload = json.loads(generated.report_path.read_text(encoding="utf-8"))
    assert payload["component_decision_present"] is True
    assert payload["block_placement_present"] is True


def test_topology_application_records_share_tool_identity() -> None:
    architecture, intent, compiled = _ready_architecture_intent_compiled()
    topology = synthesize_schematic_topology_plan(architecture, intent, compiled)
    topology_applied = apply_schematic_topology_to_design_ir(compiled, topology)
    component_plan = synthesize_component_decision_plan(topology, compiled)
    component_applied = apply_component_decision_plan_to_design_ir(compiled, component_plan)
    placement_plan = synthesize_block_placement_plan(topology)
    placement_applied = apply_block_placement_plan_to_design_ir(topology_applied, placement_plan)

    assert {
        topology_applied.design.prov_records[-1].tool,
        component_applied.design.prov_records[-1].tool,
        placement_applied.design.prov_records[-1].tool,
    } == {"zaptrace.generation.topology"}
