"""Bounded architecture candidate: provenance is emitted, never inferred by names."""

from __future__ import annotations

import copy

import pytest

from zaptrace.synthesis.architecture import build_architecture_design
from zaptrace.synthesis.candidate import _emitted_provenance, compile_intent
from zaptrace.synthesis.requirements import parse_requirements

INTENT = "USB-C powered STM32 MCU board, 3.3V rail at 100 mA, I2C temperature sensor"


def test_bounded_mcu_sensor_candidate_is_reproducible_and_not_fabrication_approved() -> None:
    design, report = compile_intent(INTENT)
    other, repeated = compile_intent(INTENT)
    assert report.to_dict() == repeated.to_dict()
    assert design.model_dump(mode="json") == other.model_dump(mode="json")
    assert len(report.candidate_id) == len(report.requirements_hash) == len(report.design_hash) == 64
    assert report.frozen_requirements["mcu"] == "stm32"
    assert report.frozen_requirements["max_current_a"] == 0.1
    assert report.status == "review_required"
    assert len(report.emitted_components) == len(design.components) == 12
    assert len(report.emitted_nets) == len(design.nets) == 8
    assert all(x["block_id"] and (x["requirement_ids"] or x["reusable_block"]) for x in report.emitted_components)
    assert all(x["block_ids"] and x["connected_nodes"] > 0 for x in report.emitted_nets)
    assert not any(x["field"] == "emitted_pin_inventory" for x in report.pending_assumptions)
    assert all(x["id"] != "" for x in report.emitted_components)
    assert report.blockers == []
    assert len(report.footprint_evidence["qualified"]) == 9
    assert report.footprint_evidence["unresolved"] == []
    assert any(item["field"] == "selected_ldo_part_and_enable" for item in report.pending_assumptions)
    assert any(item["field"] == "generic_passive_footprint_qualification" for item in report.pending_assumptions)
    assert report.verification["internal_erc"] == "passed_with_known_limitations"
    assert report.internal_erc_evidence["checks_run"] == 29
    assert report.internal_erc_evidence["errors"] == 0
    assert report.internal_erc_evidence["warnings"] == 0
    assert report.verification["native_erc"] == "not_checked"
    assert report.verification["native_drc"] == "not_checked"
    assert report.verification["simulation"] == "not_checked"
    assert report.verification["fabrication_approved"] is False


def test_peripheral_and_connector_are_attributed_to_actual_emitting_blocks() -> None:
    design, report = compile_intent(INTENT)
    by_id = {row["id"]: row for row in report.emitted_components}
    usb = next(row for row in report.emitted_components if design.components[row["id"]].type == "connector")
    assert usb["block_id"] == "J_USB_C"
    assert usb["requirement_ids"] == ["REQ-USB-C"]
    sensor = next(row for row in report.emitted_components if design.components[row["id"]].type == "sensor")
    assert sensor["block_id"].startswith("PERIPH_")
    assert sensor["assumptions"] == ["peripheral_part_selected_by_bounded_keyword_rule"]
    assert sensor["requirement_ids"] == ["REQ-IFACE-I2C"]
    assert by_id["R1"]["block_id"] == "PB_USB_C_CC"
    assert by_id["R3"]["block_id"] == "IF_I2C"


def test_missing_bus_controller_stays_blocked_even_if_a_sensor_netlist_exists() -> None:
    design, report = compile_intent("USB-C powered board, 3.3V rail at 100mA, I2C sensor")
    assert design.components
    assert len(design.nets) > 0
    assert report.status == "blocked"
    assert "i2c_host_or_external_connector_missing" in {x["code"] for x in report.blockers}
    assert all(
        status == "not_checked"
        for key, status in report.verification.items()
        if key not in {"fabrication_approved", "internal_erc"}
    )


def test_unrealized_ble_is_never_marked_complete() -> None:
    design, report = compile_intent(INTENT + ", BLE radio")
    assert design.components
    assert report.status == "blocked"
    assert any(x["subject"] == "IF_BLE" for x in report.blockers)


def test_unpowered_breakout_and_undecodable_intent_fail_closed() -> None:
    _, no_rail = compile_intent("tiny I2C sensor breakout")
    assert no_rail.status == "blocked"
    assert any(x["code"] == "unmet_block_contract" for x in no_rail.blockers)
    empty, unknown = compile_intent("unrecognized hypothetical quantum control network")
    assert not empty.components
    assert unknown.status == "blocked"
    assert any(x["code"] == "no_usable_canonical_design" for x in unknown.blockers)


def test_usb_c_conflicting_power_budget_blocks_even_with_existing_netlist() -> None:
    _, report = compile_intent("USB-C powered STM32 board, 3.3V rail at 5 A, I2C temperature sensor")
    assert report.status == "blocked"
    assert any(x["subject"] == "usb_c_current_over_budget" for x in report.blockers)


def test_missing_actual_emission_owner_cannot_be_inferred_from_component_name() -> None:
    requirements = parse_requirements(INTENT)
    ownership: dict[str, str] = {}
    design, plan, _ = build_architecture_design(requirements, component_owners=ownership)
    original_id = sorted(ownership)[0]
    del ownership[original_id]
    components, nets, blockers, _ = _emitted_provenance(design, plan, ownership, requirements)
    assert len(components) == len(design.components)
    assert len(nets) == len(design.nets)
    assert {"code": "component_without_emission_provenance", "subject": original_id} in blockers


def test_wrong_pin_when_actual_pin_inventory_exists_is_rejected() -> None:
    requirements = parse_requirements(INTENT)
    ownership: dict[str, str] = {}
    design, plan, _ = build_architecture_design(requirements, component_owners=ownership)
    altered = copy.deepcopy(design)
    altered.nets["SDA"].nodes[0].pin_name = "nonexistent"
    _, _, blockers, _ = _emitted_provenance(altered, plan, ownership, requirements)
    # The first SDA node is on a passive without defined pin inventory and remains pending.
    assert not [b for b in blockers if b["code"] == "net_node_without_known_pin"]
    altered.nets["SDA"].nodes[-1].pin_name = "nonexistent"
    _, _, blockers, _ = _emitted_provenance(altered, plan, ownership, requirements)
    assert any(b["code"] == "net_node_without_known_pin" for b in blockers)


def test_existing_architecture_api_design_is_unchanged_when_trace_is_requested() -> None:
    req = parse_requirements(INTENT)
    baseline, plan1, log1 = build_architecture_design(req)
    owners: dict[str, str] = {}
    candidate, plan2, log2 = build_architecture_design(req, component_owners=owners)
    assert baseline.model_dump() == candidate.model_dump()
    assert plan1.to_dict() == plan2.to_dict()
    assert log1.to_dicts() == log2.to_dicts()
    assert len(owners) == len(candidate.components)


def test_local_candidate_artifacts_are_sha_bound_and_non_overwriting(tmp_path) -> None:
    import hashlib
    import json

    from scripts.ai_native_candidate_pilot import write_local_candidate

    output = tmp_path / "candidate"
    result = write_local_candidate(INTENT, output)
    assert result["status"] == "review_required"
    assert result["fabrication_approved"] is False
    for filename, expected_sha in result["files_sha256"].items():
        assert hashlib.sha256((output / filename).read_bytes()).hexdigest() == expected_sha
    assert json.loads((output / "candidate-report.json").read_text())["candidate_id"] == result["candidate_id"]
    with pytest.raises(ValueError, match="fresh local folder"):
        write_local_candidate(INTENT, output)


def test_local_candidate_rejects_preexisting_output_symlink(tmp_path) -> None:
    from scripts.ai_native_candidate_pilot import write_local_candidate

    existing = tmp_path / "my_precious_data"
    existing.mkdir()
    (existing / "file.txt").write_text("must stay untouched")
    linked = tmp_path / "candidate"
    linked.symlink_to(existing, target_is_directory=True)
    with pytest.raises(ValueError):
        write_local_candidate(INTENT, linked)
    assert (existing / "file.txt").read_text() == "must stay untouched"


def test_unrealized_provider_cannot_satisfy_a_real_consumers_contract() -> None:
    from zaptrace.synthesis.architecture import (
        ArchitecturePlan,
        BlockContract,
        PlannedBlock,
        _check_composition,
    )

    plan = ArchitecturePlan(
        blocks=[
            PlannedBlock(
                block_id="IMAGINARY_RAIL",
                kind="regulator",
                rationale="unsupported boost",
                contract=BlockContract(provides=("rail:VDD_5V",)),
                realized=False,
            ),
            PlannedBlock(
                block_id="REAL_LOAD",
                kind="interface",
                rationale="needs actual rail",
                contract=BlockContract(requires=("rail:VDD_5V",)),
                realized=True,
            ),
        ]
    )
    _check_composition(plan)
    assert [(x.block_id, x.token) for x in plan.unmet] == [("REAL_LOAD", "rail:VDD_5V")]


def test_internal_erc_warning_never_turns_native_erc_or_simulation_green() -> None:
    _, report = compile_intent(INTENT)
    assert report.internal_erc_evidence["checker"] == "zaptrace_internal_erc_not_native_kicad"
    assert report.internal_erc_evidence["coverage_gaps"]
    assert report.verification["internal_erc"] == "passed_with_known_limitations"
    assert report.verification["simulation"] == "not_checked"
    assert report.verification["native_erc"] == "not_checked"
    assert report.verification["fabrication_approved"] is False


def test_raw_intent_change_invalidates_candidate_even_when_structured_fields_match() -> None:
    from zaptrace.synthesis.requirements import freeze_requirements

    a = parse_requirements("USB-C powered STM32 MCU, 3.3V rail at 100 mA, I2C temperature sensor")
    b = parse_requirements("USB-C powered STM32 MCU, 3.3V rail at 100 mA, I2C humidity sensor")
    assert freeze_requirements(a)["hash"] == freeze_requirements(b)["hash"]
    _, ca = compile_intent(a.raw_intent)
    _, cb = compile_intent(b.raw_intent)
    assert ca.requirements_hash == cb.requirements_hash
    assert ca.intent_hash != cb.intent_hash
    assert ca.candidate_id != cb.candidate_id


def test_pilot_real_ap2112_uses_local_documented_physical_pin_map() -> None:
    design, report = compile_intent(INTENT)
    reg = design.components["U1"]
    assert reg.mpn == "AP2112K-3.3TRG1"
    assert reg.package_pin_map == {"1": "VIN", "2": "GND", "3": "EN", "4": "NC", "5": "VOUT"}
    assert sorted(pad.id for pad in reg.footprint_def.pads) == ["1", "2", "3", "4", "5"]
    expected = {"VIN": "VBUS", "EN": "VBUS", "GND": "GND", "VOUT": "VDD_3V3"}
    assert {pin: design.get_net_for_pin("U1", pin).id for pin in expected} == expected
    assert design.get_net_for_pin("U1", "NC") is None
    assert report.internal_erc_evidence["warnings"] == 0
    assert report.verification["native_erc"] == "not_checked"


def test_different_power_budget_does_not_invent_part_compatibility() -> None:
    _, report = compile_intent("USB-C powered STM32 MCU board, 3.3V rail at 700mA, I2C temperature sensor")
    assert report.status == "blocked"
    assert any(item["code"] == "no_part_specific_footprint_evidence" for item in report.blockers)


def test_mismatched_ldo_source_library_pin_map_is_rejected(monkeypatch) -> None:
    from zaptrace.library.loader import LibraryLoader

    original = LibraryLoader.get

    def corrupted(self, part_id):
        spec = original(self, part_id)
        if part_id == "ap2112k-3.3":
            spec.package_pin_map = {"1": "VOUT", "2": "GND", "3": "EN", "4": "NC", "5": "VIN"}
        return spec

    monkeypatch.setattr(LibraryLoader, "get", corrupted)
    design, report = compile_intent(INTENT)
    assert design.components["U1"].mpn is None
    assert report.status == "blocked"
    assert any(item["code"] == "no_part_specific_footprint_evidence" for item in report.blockers)


def test_pilot_footprint_resolution_covers_every_emitted_two_terminal_passive() -> None:
    design, report = compile_intent(INTENT)
    for component in design.components.values():
        if component.type not in {"resistor", "capacitor"}:
            continue
        assert component.footprint == "0402"
        assert sorted(component.pins) == ["1", "2"]
        assert sorted(component.package_pin_map.items()) == [("1", "1"), ("2", "2")]
        assert sorted(pad.id for pad in component.footprint_def.pads) == ["1", "2"]
    assert report.footprint_evidence["unresolved"] == []
    assert report.internal_erc_evidence["warnings"] == 0
    assert not any(a["field"] == "emitted_pin_inventory" for a in report.pending_assumptions)


def test_footprint_geometry_mismatch_is_not_faked(monkeypatch) -> None:
    import zaptrace.synthesis.candidate_footprints as footprint_module

    original = footprint_module.generate_footprint_for_component

    def bogus(package, kind):
        result = original(package, kind)
        if kind == "resistor":
            result.pads[1].id = "3"
        return result

    monkeypatch.setattr(footprint_module, "generate_footprint_for_component", bogus)
    design, report = compile_intent(INTENT)
    assert report.status == "blocked"
    assert any(
        x["reason"] == "passive_pad_number_or_connectivity_inconsistent"
        for x in report.footprint_evidence["unresolved"]
    )
    assert design.components["R1"].pins == {}


def test_source_pin_map_corruption_never_assigns_ldo_identity(monkeypatch) -> None:
    from zaptrace.library.loader import LibraryLoader

    original = LibraryLoader.get

    def tampered(self, part_id):
        record = original(self, part_id)
        if part_id == "ap2112k-3.3":
            record.package_pin_map["1"] = "VOUT"
        return record

    monkeypatch.setattr(LibraryLoader, "get", tampered)
    design, report = compile_intent(INTENT)
    assert design.components["U1"].mpn is None
    assert report.status == "blocked"
    assert report.internal_erc_evidence["warnings"] > 0
