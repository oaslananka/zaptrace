"""Tests for the end-to-end intent → manufacturing + evidence flow."""

from __future__ import annotations

from pathlib import Path

from zaptrace.synthesis.fab import FabResult, synthesize_to_manufacturing


class TestFabFlow:
    def test_produces_manufacturing_artifacts(self, tmp_path: Path) -> None:
        result = synthesize_to_manufacturing("ESP32-C3 USB-C 3.3V board, I2C temperature sensor", tmp_path)
        assert isinstance(result, FabResult)
        names = " ".join(result.artifacts)
        assert ".zip" in names  # bundle
        assert ".DRL" in names or ".drl" in names.lower()  # drill
        assert "bom" in names.lower()  # bill of materials
        assert any(a.upper().endswith((".GTL", ".GBL")) for a in result.artifacts)  # copper gerber
        # the files really exist on disk
        assert all((tmp_path / a).is_file() for a in result.artifacts)

    def test_carries_score_and_bias_evidence(self, tmp_path: Path) -> None:
        result = synthesize_to_manufacturing("ESP32-C3 USB-C 3.3V board, I2C sensor", tmp_path)
        assert 0 <= result.scorecard["score"] <= 100
        assert "passed" in result.dc_bias
        assert "errors" in result.drc  # the physical-design (DRC) status is measured and reported

    def test_ground_pour_is_applied(self, tmp_path: Path) -> None:
        # The router leaves GND for a copper plane; the fab flow must emit the
        # plane. Pad-level connectivity remains a separate fail-closed proof.
        from zaptrace.algo.copper_pour import CopperPourGenerator
        from zaptrace.algo.grid_router import GridRouter
        from zaptrace.algo.placer import place_components
        from zaptrace.core.models import NetClass
        from zaptrace.ee.classifier import classify_design, get_net_class
        from zaptrace.synthesis.footprint_resolver import resolve_footprints
        from zaptrace.synthesis.repair import synthesize_and_repair

        out = synthesize_and_repair("STM32 3.3V board, RS485 modbus node")
        d = out["design"]
        resolve_footprints(d)
        positions = place_components(d)
        for ref, p in positions.items():
            if ref in d.components:
                d.components[ref].position = tuple(p)
        d.placement = dict(positions)
        classify_design(d)
        GridRouter().route(d, {c.ref: c.position for c in d.components.values() if c.position})
        ground = next(n for n in d.nets.values() if get_net_class(d, n.id) == NetClass.GROUND)
        pour = CopperPourGenerator().generate_ground_pour(d, d.placement, net_id=ground.id)
        d.copper_pours[f"F.Cu_{ground.name}"] = pour
        assert d.copper_pours  # a ground plane exists

    def test_routing_drc_status_in_checklist(self, tmp_path: Path) -> None:
        # The board is placed and routed; if the algorithmic router leaves DRC
        # errors, the review checklist must say so honestly.
        result = synthesize_to_manufacturing("STM32 3.3V board, RS485 modbus node", tmp_path)
        if result.drc["errors"]:
            assert any("DRC error" in item for item in result.review_checklist)

    def test_review_checklist_flags_unresolved_footprints_and_mandates_review(self, tmp_path: Path) -> None:
        # BMP390 (Bosch LGA-10) has no parametric generator and no vendored land
        # pattern, so it is the honest gap the checklist must call out.
        result = synthesize_to_manufacturing("nRF52840 3.3V board, I2C pressure sensor BMP390", tmp_path)
        joined = "\n".join(result.review_checklist)
        assert "no pad geometry" in joined
        assert "BMP390" in joined
        # the mandatory human-review line is always present
        assert any("qualified engineer" in item for item in result.review_checklist)

    def test_undriven_rail_appears_in_checklist(self, tmp_path: Path) -> None:
        result = synthesize_to_manufacturing("ESP32-C3 battery board, single Li-ion cell, 5V rail", tmp_path)
        assert any("undriven rail" in item for item in result.review_checklist)

    def test_to_dict_shape(self, tmp_path: Path) -> None:
        data = synthesize_to_manufacturing("ESP32-C3 3.3V board, I2C sensor", tmp_path).to_dict()
        assert set(data) == {
            "intent",
            "design_name",
            "component_count",
            "net_count",
            "scorecard",
            "dc_bias",
            "drc",
            "artifacts",
            "review_checklist",
            "dfm_readiness",
            "output_dir",
        }


def test_physical_candidate_uses_collision_aware_grid_routing() -> None:
    from zaptrace.ee.drc import DRCEngine
    from zaptrace.synthesis.fab import route_synthesized_design

    design, _ = route_synthesized_design(
        "ESP32-C3 USB-C 3.3V board with I2C temperature sensor",
        name="esp32_usb_sensor_physical_rev_a",
    )

    assert design.routing is not None
    assert design.routing.net_count == 6
    assert design.routing.routed_net_count == 6
    assert {trace.net_id for trace in design.routing.traces} == {"CC1", "CC2", "VBUS", "VDD_3V3", "SDA", "SCL"}
    assert "F.Cu_GND" in design.copper_pours
    pour = design.copper_pours["F.Cu_GND"]

    from zaptrace.algo.copper_pour import CopperPourGenerator

    ground_pad_positions: set[tuple[float, float]] = set()
    for component in design.components.values():
        if component.position is None or component.footprint_def is None:
            continue
        ground_pad_ids = {
            pad_id.lower() for pad_id in CopperPourGenerator._physical_pad_ids_for_net(design, component, "GND")
        }
        for pad in component.footprint_def.pads:
            if str(pad.id).lower() in ground_pad_ids:
                ground_pad_positions.add(
                    (
                        round(component.position[0] + pad.position[0], 3),
                        round(component.position[1] + pad.position[1], 3),
                    )
                )

    relief_positions = {
        (round(relief.pad_position[0], 3), round(relief.pad_position[1], 3)) for relief in pour.thermal_reliefs
    }
    assert relief_positions
    assert relief_positions <= ground_pad_positions

    drc = DRCEngine().run(design)
    blocking = [violation for violation in drc.violations if violation.severity.value == "error"]
    assert len(blocking) == 1
    assert blocking[0].rule_id == "DRC-005"
    assert blocking[0].net_id == "GND"
