"""Tests for constraint-aware placement intelligence."""

from __future__ import annotations

from zaptrace.core.models import (
    Component,
    Design,
    DesignMeta,
    Net,
    NetNode,
    Pin,
    PinType,
    PlacementIntent,
)
from zaptrace.synthesis.placement import (
    PlacementAnalysis,
    _check_keepouts,
    _is_decoupling_cap,
    _score_placement_for_component,
    analyze_placement,
    group_components,
)


def _make_design(
    placement_data: dict[str, tuple[float, float]] | None = None,
) -> Design:
    d = Design(meta=DesignMeta(name="test"))
    d.components["u1"] = Component(
        id="u1",
        ref="U1",
        type="ic",
        pins={
            "VCC": Pin(name="VCC", type=PinType.POWER),
            "GND": Pin(name="GND", type=PinType.POWER),
            "SDA": Pin(name="SDA", type=PinType.BIDIRECTIONAL),
            "SCL": Pin(name="SCL", type=PinType.INPUT),
        },
    )
    d.components["c1"] = Component(id="c1", ref="C1", type="capacitor", value="100nF")
    d.components["c2"] = Component(id="c2", ref="C2", type="capacitor", value="10uF")
    d.components["r1"] = Component(id="r1", ref="R1", type="resistor", value="10k")
    d.components["j1"] = Component(id="j1", ref="J1", type="connector")
    d.components["sensor1"] = Component(id="sensor1", ref="U2", type="sensor")
    d.nets["vcc"] = Net(
        id="vcc",
        name="VCC_3V3",
        nodes=[
            NetNode(component_ref="U1", pin_name="VCC"),
            NetNode(component_ref="C1", pin_name="p1"),
            NetNode(component_ref="C2", pin_name="p1"),
        ],
    )
    d.nets["gnd"] = Net(
        id="gnd",
        name="GND",
        nodes=[
            NetNode(component_ref="U1", pin_name="GND"),
            NetNode(component_ref="C1", pin_name="p2"),
            NetNode(component_ref="C2", pin_name="p2"),
            NetNode(component_ref="R1", pin_name="p2"),
        ],
    )
    d.nets["i2c"] = Net(
        id="i2c",
        name="I2C_BUS",
        nodes=[
            NetNode(component_ref="U1", pin_name="SDA"),
            NetNode(component_ref="U1", pin_name="SCL"),
            NetNode(component_ref="U2", pin_name="SDA"),
            NetNode(component_ref="U2", pin_name="SCL"),
        ],
    )
    if placement_data is not None:
        d.placement = placement_data
    return d


class TestGroupComponents:
    def test_returns_groups(self) -> None:
        d = _make_design()
        groups = group_components(d)
        # There should be groups based on shared nets
        group_names = {g.name for g in groups}
        assert any("VCC_3V3" in gn for gn in group_names), f"No VCC_3V3 group in {group_names}"
        assert any("GND" in gn for gn in group_names), f"No GND group in {group_names}"

    def test_disjoint_groups(self) -> None:
        d = _make_design()
        groups = group_components(d)
        # No component should be in more than one group
        all_comps: list[str] = []
        for g in groups:
            all_comps.extend(g.component_ids)
        assert len(all_comps) == len(set(all_comps)), "Component appears in multiple groups"

    def test_empty_design(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        groups = group_components(d)
        assert groups == []

    def test_no_nets_no_groups(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        d.components["r1"] = Component(id="r1", ref="R1", type="resistor")
        groups = group_components(d)
        assert groups == []


class TestDecouplingProximity:
    def test_decap_too_far_from_ic(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (50.0, 28.0),  # 12mm from U1 → warning (>10mm)
                "r1": (20.0, 20.0),
                "j1": (5.0, 5.0),
                "sensor1": (80.0, 60.0),
            }
        )
        # Override c2 to be a decoupling cap (100nF) and place it far away
        d.components["c2"] = Component(id="c2", ref="C2", type="capacitor", value="100nF")
        assert d.placement is not None
        d.placement["c2"] = (10.0, 10.0)

        analysis = analyze_placement(d)
        proximity_obs = [o for o in analysis.observations if o.category == "proximity"]
        assert len(proximity_obs) >= 2, f"Expected ≥2 proximity obs, got: {proximity_obs}"
        warn_obs = [o for o in proximity_obs if o.severity == "warning"]
        # Both c1 (12mm) and c2 (~53mm) are >10mm from nearest IC → warnings
        assert len(warn_obs) >= 1, f"No warning-level proximity obs: {proximity_obs}"

    def test_decap_close_to_ic_no_warning(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (52.0, 42.0),  # ~2.8mm from U1 — ideal
                "c2": (48.0, 38.0),  # ~2.8mm from U1 — ideal
                "r1": (10.0, 10.0),
                "j1": (5.0, 5.0),
                "sensor1": (80.0, 60.0),
            }
        )
        analysis = analyze_placement(d)
        proximity_obs = [o for o in analysis.observations if o.category == "proximity"]
        # All caps are within 5mm of U1, so no warnings/infos
        assert len(proximity_obs) == 0, f"Unexpected proximity obs: {proximity_obs}"


class TestKeepoutConstraints:
    def test_edge_placement_violation(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (50.0, 30.0),
                "c2": (50.0, 20.0),
                "r1": (10.0, 10.0),
                "j1": (50.0, 40.0),  # center of board, not at bottom edge
                "sensor1": (80.0, 60.0),
            }
        )
        # Add a constraint that expects J* at bottom edge
        d.constraints.placement.append(
            PlacementIntent(component="J*", edge="bottom", reason="USB connector on board edge")
        )
        analysis = analyze_placement(d)
        edge_obs = [o for o in analysis.observations if o.category == "edge"]
        assert len(edge_obs) >= 1, f"No edge observations: {analysis.observations}"
        assert any("J1" in o.message for o in edge_obs), f"J1 not in edge obs: {edge_obs}"

    def test_near_constraint_violation(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (50.0, 30.0),
                "c2": (50.0, 20.0),
                "r1": (10.0, 10.0),
                "j1": (5.0, 5.0),
                "sensor1": (80.0, 60.0),
            }
        )
        # Decoupling caps should be near U1
        d.constraints.placement.append(
            PlacementIntent(
                component="C*",
                near="U1",
                max_distance_mm=5.0,
                reason="decoupling caps near IC",
            )
        )
        analysis = analyze_placement(d)
        keepout_obs = [o for o in analysis.observations if o.category == "keepout"]
        assert len(keepout_obs) >= 1, f"No keepout observations: {analysis.observations}"

    def test_all_constraints_satisfied(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (52.0, 42.0),  # near U1
                "c2": (48.0, 38.0),  # near U1
                "r1": (10.0, 10.0),
                "j1": (50.0, 2.0),  # at bottom edge
                "sensor1": (80.0, 60.0),
            }
        )
        d.constraints.placement.append(
            PlacementIntent(component="J*", edge="bottom", reason="connector on bottom edge")
        )
        d.constraints.placement.append(
            PlacementIntent(
                component="C*",
                near="U1",
                max_distance_mm=5.0,
                reason="decoupling caps",
            )
        )
        analysis = analyze_placement(d)
        warning_obs = [o for o in analysis.observations if o.severity != "info"]
        assert len(warning_obs) == 0, f"Unexpected warnings: {warning_obs}"


class TestAnalogDigitalSeparation:
    def test_analog_too_close_to_digital(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (52.0, 42.0),
                "c2": (48.0, 38.0),
                "r1": (10.0, 10.0),
                "j1": (5.0, 5.0),
                "sensor1": (52.0, 38.0),  # 2mm from U1 → warning
            }
        )
        analysis = analyze_placement(d)
        separation_obs = [o for o in analysis.observations if o.category == "separation"]
        assert len(separation_obs) >= 1, f"No separation observations: {analysis.observations}"
        assert any("sensor" in o.message.lower() for o in separation_obs)


class TestPlacementCandidateScoring:
    def test_score_perfect_placement(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (51.0, 41.0),
                "c2": (49.0, 39.0),
                "r1": (20.0, 20.0),
                "j1": (50.0, 2.0),
                "sensor1": (80.0, 60.0),
            }
        )
        analysis = analyze_placement(d)
        assert len(analysis.candidates) == len(d.components)
        for cand in analysis.candidates:
            assert 0.0 <= cand.score <= 1.0, f"Candidate {cand.component_id} has invalid score {cand.score}"

    def test_score_drops_with_constraint_violations(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (50.0, 5.0),  # far from U1
                "c2": (70.0, 30.0),  # far from U1
                "r1": (10.0, 10.0),
                "j1": (50.0, 40.0),  # not at bottom edge
                "sensor1": (80.0, 60.0),
            }
        )
        d.constraints.placement.append(PlacementIntent(component="J*", edge="bottom", reason="connector at bottom"))
        d.constraints.placement.append(
            PlacementIntent(
                component="C*",
                near="U1",
                max_distance_mm=5.0,
                reason="decoupling",
            )
        )
        analysis = analyze_placement(d)
        # Some candidates should have slightly lower scores from violations
        low_scores = [c for c in analysis.candidates if c.score < 0.95]
        assert len(low_scores) >= 4, f"Not enough low scores: {[c.score for c in analysis.candidates]}"
        # Overall score should be < 1.0
        assert analysis.score < 1.0, f"Overall score should be < 1.0, got {analysis.score}"

    def test_reasons_are_recorded(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (52.0, 42.0),
                "c2": (48.0, 38.0),
                "r1": (80.0, 20.0),
                "j1": (5.0, 5.0),
                "sensor1": (80.0, 60.0),
            }
        )
        analysis = analyze_placement(d)
        candidates_with_reasons = [c for c in analysis.candidates if c.reasons]
        assert len(candidates_with_reasons) >= 1, "No candidates have reasons"


class TestOverallScore:
    def test_perfect_placement_scores_one(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (51.0, 41.0),
                "c2": (49.0, 39.0),
                "r1": (20.0, 20.0),
                "j1": (50.0, 2.0),
                "sensor1": (80.0, 60.0),
            }
        )
        d.constraints.placement.append(PlacementIntent(component="J*", edge="bottom", reason="edge connector"))
        analysis = analyze_placement(d)
        # Should be close to 1.0 since constraints are met and no violations
        assert analysis.score > 0.8, f"Score too low: {analysis.score}"

    def test_no_placement_data_has_minimal_observations(self) -> None:
        d = _make_design()  # no placement data
        analysis = analyze_placement(d)
        assert analysis.score == 1.0  # no placement to score
        # No observations either — nothing to check
        assert len(analysis.observations) == 0, f"Unexpected observations: {analysis.observations}"


class TestPlacementAnalysisStructure:
    def test_analysis_has_all_fields(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (51.0, 41.0),
            }
        )
        analysis = analyze_placement(d)
        assert isinstance(analysis, PlacementAnalysis)
        assert isinstance(analysis.groups, list)
        assert isinstance(analysis.observations, list)
        assert isinstance(analysis.candidates, list)
        assert isinstance(analysis.score, float)

    def test_groups_include_all_components(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (51.0, 41.0),
                "c2": (49.0, 39.0),
                "r1": (10.0, 10.0),
                "j1": (5.0, 5.0),
                "sensor1": (80.0, 60.0),
            }
        )
        analysis = analyze_placement(d)
        grouped_comps: set[str] = set()
        for g in analysis.groups:
            grouped_comps.update(g.component_ids)
        # Components on nets: u1, c1, c2, r1, sensor1 (j1 is not on any net)
        assert "u1" in grouped_comps
        assert "sensor1" in grouped_comps
        # j1 has no nets, so it's not grouped
        assert "j1" not in grouped_comps


class TestPlacementScorecard:
    def test_scorecard_is_machine_readable_and_covers_required_sections(self) -> None:
        from zaptrace.synthesis.placement import build_placement_scorecard

        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (52.0, 42.0),
                "c2": (48.0, 38.0),
                "r1": (10.0, 10.0),
                "j1": (50.0, 2.0),
                "sensor1": (80.0, 60.0),
            }
        )
        d.constraints.placement.append(PlacementIntent(component="J*", edge="bottom", reason="connector on edge"))

        card = build_placement_scorecard(d)
        payload = card.model_dump(mode="json")
        sections = {section["name"] for section in payload["section_scores"]}

        assert payload["schema_version"] == "1.0"
        assert 0.0 <= payload["overall_score"] <= 1.0
        assert sections >= {
            "block_grouping",
            "connector_constraints",
            "decoupling_proximity",
            "keepouts",
            "thermal_spacing",
        }
        assert payload["component_count"] == len(d.components)

    def test_scorecard_records_connector_decoupling_keepout_and_thermal_warnings(self) -> None:
        from zaptrace.synthesis.placement import build_placement_scorecard

        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (10.0, 10.0),
                "c2": (15.0, 10.0),
                "r1": (10.0, 10.0),
                "j1": (50.0, 40.0),
                "sensor1": (52.0, 40.0),
            }
        )
        d.components["u1"].properties["thermal_power_w"] = 1.0
        d.components["reg1"] = Component(id="reg1", ref="U3", type="regulator", properties={"power_w": 1.0})
        assert d.placement is not None
        d.placement["reg1"] = (53.0, 40.0)
        d.constraints.placement.append(PlacementIntent(component="J*", edge="bottom", reason="connector on edge"))
        d.constraints.placement.append(PlacementIntent(component="C*", near="U1", max_distance_mm=5.0, reason="decaps"))

        card = build_placement_scorecard(d)
        section_status = {section.name: section.status for section in card.section_scores}
        categories = {obs["category"] for obs in card.observations}

        assert card.status in {"warning", "fail"}
        assert section_status["connector_constraints"] == "warning"
        assert section_status["decoupling_proximity"] == "warning"
        assert section_status["keepouts"] == "warning"
        assert section_status["thermal_spacing"] == "warning"
        assert {"edge", "proximity", "keepout", "thermal_spacing"} <= categories

    def test_scorecard_blocks_when_below_autonomous_threshold(self) -> None:
        from zaptrace.synthesis.placement import build_placement_scorecard

        d = _make_design(placement_data={"u1": (50.0, 40.0)})
        card = build_placement_scorecard(d, min_autonomous_score=0.95, min_review_score=0.98)

        assert card.blocked is True
        assert card.status == "fail"
        assert card.overall_score < 0.95

    def test_scorecard_human_review_when_warning_but_not_blocked(self) -> None:
        from zaptrace.synthesis.placement import build_placement_scorecard

        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (52.0, 42.0),
                "c2": (48.0, 38.0),
                "r1": (10.0, 10.0),
                "j1": (50.0, 40.0),
                "sensor1": (80.0, 60.0),
            }
        )
        d.constraints.placement.append(PlacementIntent(component="J*", edge="bottom", reason="connector on edge"))
        card = build_placement_scorecard(d, min_autonomous_score=0.1, min_review_score=0.99)

        assert card.blocked is False
        assert card.human_review_required is True
        assert card.status == "warning"


def _placement_refactor_design() -> Design:
    design = _make_design(
        placement_data={
            "u1": (50.0, 40.0),
            "c1": (50.0, 30.0),
            "c2": (50.0, 20.0),
            "r1": (10.0, 10.0),
            "j1": (50.0, 40.0),
            "sensor1": (80.0, 60.0),
        }
    )
    design.constraints.placement.extend(
        [
            PlacementIntent(component="C*", near="U1", max_distance_mm=5.0, reason="decap"),
            PlacementIntent(component="J*", edge="bottom", reason="edge"),
        ]
    )
    return design


class TestPlacementRefactorCharacterization:
    def test_grouping_preserves_semantic_cluster_identity(self) -> None:
        groups = group_components(_make_design())
        assert sorted((group.name, group.component_ids, group.net_ids) for group in groups) == [
            ("GND, I2C_BUS, VCC_3V3", ("c1", "c2", "r1", "sensor1", "u1"), ("gnd", "i2c", "vcc"))
        ]

    def test_decoupling_heuristic_preserves_value_boundaries(self) -> None:
        def component(value: str, *, ref: str = "C1", component_type: str = "capacitor") -> Component:
            return Component(id="c", ref=ref, type=component_type, value=value)

        assert _is_decoupling_cap(component("100nF")) is True
        assert _is_decoupling_cap(component("9.9uF")) is True
        assert _is_decoupling_cap(component("10uF")) is False
        assert _is_decoupling_cap(component("10µF")) is False
        assert _is_decoupling_cap(component("0.1F")) is True
        assert _is_decoupling_cap(component("1F")) is True
        assert _is_decoupling_cap(component("bad")) is True
        assert _is_decoupling_cap(component("")) is True
        assert _is_decoupling_cap(component("100nF", ref="C99", component_type="resistor")) is True
        assert _is_decoupling_cap(component("100nF", ref="R1", component_type="resistor")) is False

    def test_keepout_observation_order_and_payload_are_stable(self) -> None:
        design = _placement_refactor_design()
        observations = _check_keepouts(design, design.constraints)
        assert [(item.category, item.component_ids, item.message) for item in observations] == [
            ("keepout", ["c1", "u1"], "C1 (c1) is 10.0 mm from U1, exceeds max_distance_mm=5.0 mm"),
            ("keepout", ["c2", "u1"], "C2 (c2) is 20.0 mm from U1, exceeds max_distance_mm=5.0 mm"),
            ("edge", ["j1"], "J1 (j1) should be near the bottom board edge (current: x=50.0, y=40.0)"),
        ]

    def test_candidate_scores_and_reason_order_are_stable(self) -> None:
        design = _placement_refactor_design()
        center = _score_placement_for_component(design, "j1", 50.0, 40.0, design.constraints)
        edge = _score_placement_for_component(design, "j1", 50.0, 2.0, design.constraints)
        connected = _score_placement_for_component(design, "sensor1", 52.0, 40.0, design.constraints)
        unknown = _score_placement_for_component(design, "unknown", 10.0, 10.0, design.constraints)
        assert (center.score, center.reasons) == (0.97, [])
        assert edge.score == 0.8999999999999999
        assert edge.reasons == [
            "too close to board edge (2.0 mm < 5.0 mm margin)",
            "on correct board edge (bottom)",
        ]
        assert (connected.score, connected.reasons) == (1.0, ["close to 1 connected component(s) (avg 2.0 mm)"])
        assert (unknown.score, unknown.reasons) == (0.0, ["unknown component"])
