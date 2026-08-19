"""Tests for mechanical / enclosure review and MCAD export."""

from __future__ import annotations

import json

from zaptrace.analysis.mechanical import (
    mcad_component_table,
    mechanical_review,
)
from zaptrace.core.models import BoardDefinition, Component, Design, DesignMeta, MountingHole


def _design(width: float, height: float, holes: list[MountingHole]) -> Design:
    return Design(
        meta=DesignMeta(name="mech"),
        board_def=BoardDefinition(width=width, height=height, mounting_holes=holes),
    )


def _topics(design: Design) -> list[str]:
    return [f.topic for f in mechanical_review(design)]


def test_no_mounting_holes_is_flagged() -> None:
    findings = mechanical_review(_design(100, 80, []))
    assert len(findings) == 1
    assert findings[0].topic == "mounting-holes"
    assert findings[0].severity == "warning"


def test_well_placed_four_holes_is_clean() -> None:
    holes = [
        MountingHole(position=(5, 5), diameter=3.0),
        MountingHole(position=(95, 5), diameter=3.0),
        MountingHole(position=(5, 75), diameter=3.0),
        MountingHole(position=(95, 75), diameter=3.0),
    ]
    assert mechanical_review(_design(100, 80, holes)) == []


def test_large_board_with_one_hole_gets_info() -> None:
    holes = [MountingHole(position=(50, 40), diameter=3.0)]
    topics = _topics(_design(100, 80, holes))
    assert "mounting-holes" in topics  # the "fewer than 4" info


def test_hole_off_board_is_flagged() -> None:
    holes = [
        MountingHole(position=(5, 5), diameter=3.0),
        MountingHole(position=(200, 5), diameter=3.0),  # off the 100x80 board
    ]
    findings = mechanical_review(_design(100, 80, holes))
    assert any(f.topic == "hole-edge-clearance" for f in findings)


def test_hole_too_close_to_edge_is_flagged() -> None:
    holes = [MountingHole(position=(1, 1), diameter=3.0)]  # margin = 1.5 + 1.5 = 3 mm
    findings = mechanical_review(_design(100, 80, holes))
    assert any(f.topic == "hole-edge-clearance" for f in findings)


def test_findings_serializable() -> None:
    data = mechanical_review(_design(100, 80, []))[0].to_dict()
    assert set(data) == {"topic", "severity", "detail"}


# ---------------------------------------------------------------------------
# MCAD component position table
# ---------------------------------------------------------------------------


def _design_with_components() -> Design:
    d = Design(
        meta=DesignMeta(name="McadBoard"),
        board_def=BoardDefinition(width=100, height=80, mounting_holes=[]),
    )
    d.components["r1"] = Component(id="r1", ref="R1", type="resistor", value="10k", footprint="Resistor_SMD:R_0603")
    d.components["c1"] = Component(id="c1", ref="C1", type="capacitor", value="100nF", footprint="Capacitor_SMD:C_0603")
    return d


class TestMcadComponentTable:
    def test_empty_design(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        table = mcad_component_table(d)
        assert table.rows == []
        assert table.board_width_mm > 0

    def test_components_included(self) -> None:
        d = _design_with_components()
        table = mcad_component_table(d)
        assert len(table.rows) == 2
        refs = {r.ref for r in table.rows}
        assert "R1" in refs
        assert "C1" in refs

    def test_placement_applied(self) -> None:
        d = _design_with_components()
        placement = {"r1": (25.0, 30.0), "c1": (60.0, 40.0)}
        table = mcad_component_table(d, placement=placement)
        r1_row = next(r for r in table.rows if r.ref == "R1")
        assert r1_row.x_mm == 25.0
        assert r1_row.y_mm == 30.0

    def test_step_model_inferred(self) -> None:
        d = _design_with_components()
        table = mcad_component_table(d)
        r1_row = next(r for r in table.rows if r.ref == "R1")
        assert r1_row.step_model == "Resistor_SMD:R_0603.step"

    def test_to_csv_format(self) -> None:
        d = _design_with_components()
        csv_out = mcad_component_table(d).to_csv()
        assert "PosX(mm)" in csv_out
        assert "R1" in csv_out
        assert "C1" in csv_out

    def test_to_json_format(self) -> None:
        d = _design_with_components()
        json_out = mcad_component_table(d).to_json()
        data = json.loads(json_out)
        assert data["component_count"] == 2
        assert len(data["rows"]) == 2
        assert "non_claims" in data

    def test_to_idf_placement_format(self) -> None:
        d = _design_with_components()
        idf = mcad_component_table(d).to_idf_placement()
        assert idf.startswith(".PLACE")
        assert idf.endswith(".END_PLACE")
        assert '"R1"' in idf
        assert "TOP" in idf

    def test_non_claims_present(self) -> None:
        table = mcad_component_table(Design(meta=DesignMeta(name="x")))
        assert len(table.non_claims) >= 2

    def test_default_side_is_top(self) -> None:
        d = _design_with_components()
        table = mcad_component_table(d)
        for row in table.rows:
            assert row.side in ("top", "bottom")

    def test_ref_key_rotation_and_dnp_behavior(self) -> None:
        d = _design_with_components()
        d.components["r1"].properties = {"rotation": 90}
        d.components["c1"].dnp = True

        table = mcad_component_table(d, placement={"R1": (12.34567, 8.76543)})

        assert [row.ref for row in table.rows] == ["R1"]
        assert table.rows[0].x_mm == 12.3457
        assert table.rows[0].y_mm == 8.7654
        assert table.rows[0].rotation_deg == 90.0

    def test_component_position_fallback_is_used(self) -> None:
        d = _design_with_components()
        object.__setattr__(d.components["r1"], "position", (7.0, 9.0))

        table = mcad_component_table(d)
        r1_row = next(row for row in table.rows if row.ref == "R1")

        assert r1_row.x_mm == 7.0
        assert r1_row.y_mm == 9.0
