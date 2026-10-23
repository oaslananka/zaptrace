"""Fail-closed partial copper paths must connect authentic pad centers and nets."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.issue91_native_copper_review import (
    ROUTES,
    _blocking_finding_signatures,
    _file_sha256,
    _read_native_report,
    _require_paths,
    _violations,
    finalize_review,
)
from zaptrace.core.parser import parse_file

_DESIGN = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"


def test_native_copper_review_has_only_verified_complete_net_terminal_endpoints() -> None:
    design = parse_file(_DESIGN)
    assert design.placement is not None
    assert len(ROUTES) == 25
    assert sum(len(route.points) - 1 for route in ROUTES) == 61
    for route in ROUTES:
        assert route.net in design.nets
        assert route.points[0] == route.source[2]
        assert route.points[-1] == route.target[2]
        assert len(route.points) >= 2
        for component_ref, pin_number, expected in (route.source, route.target):
            component = design.components[component_ref]
            assert component.footprint_def is not None
            pads = [pad for pad in component.footprint_def.pads if pad.id == pin_number]
            assert pads
            origin_x, origin_y = design.placement[component_ref]
            assert any(
                abs(origin_x + pad.position[0] - expected[0]) < 1e-6
                and abs(origin_y + pad.position[1] - expected[1]) < 1e-6
                for pad in pads
            )
            connected_pin = component.package_pin_map.get(pin_number, pin_number)
            assert component.pins[connected_pin].net == route.net


def test_new_ground_connection_is_verified_pad_center_to_pad_center() -> None:
    additional = [route for route in ROUTES if route.source[0:2] == ("R3", "2") and route.target[0:2] == ("C3", "2")]
    assert len(additional) == 1
    route = additional[0]
    assert route.net == "GND"
    assert route.points == (
        (72.51, 60.0),
        (72.51, 57.2),
        (69.6, 57.2),
        (69.6, 66.5),
        (68.48, 68.0),
    )


def test_new_independent_ground_paths_keep_verified_pad_centers_and_layers() -> None:
    additions = {
        ("U1", "38", "U3", "1"): (
            (38.75, 25.75),
            (44.0, 25.75),
            (44.0, 33.7),
            (61.85, 33.7),
        ),
        ("D1", "2", "U2", "5"): (
            (63.05, 68.0),
            (63.05, 72.5),
            (47.975, 72.5),
            (47.975, 61.025),
        ),
    }
    for (from_ref, from_pad, to_ref, to_pad), points in additions.items():
        candidates = [
            route
            for route in ROUTES
            if route.source[0:2] == (from_ref, from_pad) and route.target[0:2] == (to_ref, to_pad)
        ]
        assert len(candidates) == 1
        assert candidates[0].net == "GND"
        assert candidates[0].points == points
        assert len(points) == 4


def test_three_more_native_verified_review_routes_preserve_exact_pad_centers() -> None:
    additions = {
        ("U1", "1", "U1", "39"): (
            "GND",
            ((21.25, 25.75), (24.5, 25.75), (24.5, 30.5), (27.795, 31.565)),
        ),
        ("C1", "1", "U1", "2"): (
            "VCC_3V3",
            ((29.52, 60.0), (18.0, 60.0), (18.0, 27.02), (21.25, 27.02)),
        ),
        ("U1", "33", "U2", "3"): (
            "I2C_SDA",
            ((38.75, 32.1), (42.5, 32.1), (42.5, 56.0), (47.325, 56.0), (47.325, 58.975)),
        ),
    }
    for (source_ref, source_pad, target_ref, target_pad), (expected_net, points) in additions.items():
        matches = [
            route
            for route in ROUTES
            if route.source[0:2] == (source_ref, source_pad) and route.target[0:2] == (target_ref, target_pad)
        ]
        assert len(matches) == 1
        assert matches[0].net == expected_net
        assert matches[0].points == points
        assert matches[0].source[2] == points[0]
        assert matches[0].target[2] == points[-1]


def test_native_drc_result_cannot_hide_new_finding_classes() -> None:
    sample = (
        "[drill_out_of_range]: 0.20 mm\n"
        "[drill_out_of_range]: 0.20 mm\n"
        "[hole_clearance]: 0.1944 mm\n"
        "[unconnected_items]: gap\n"
        "[shorting_items]: dangerous\n"
    )
    result = _violations(sample)
    assert result == {
        "drill_out_of_range": 2,
        "hole_clearance": 1,
        "unconnected_items": 1,
        "shorting_items": 1,
    }


def test_native_report_fail_closed_on_missing_and_unparseable(tmp_path: Path) -> None:
    report = tmp_path / "native.rpt"
    with pytest.raises(RuntimeError, match="Missing or empty"):
        _read_native_report(report)
    report.write_text("unparseable gibberish\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not parseable"):
        _read_native_report(report)
    report.write_text("[shorting_items]: gap\n", encoding="utf-8")
    assert _read_native_report(report) == {"shorting_items": 1}


def test_review_requires_distinct_same_directory_pcb_paths(tmp_path: Path) -> None:
    source = tmp_path / "source.kicad_pcb"
    source.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="distinct"):
        _require_paths(source, source)
    with pytest.raises(ValueError, match="distinct"):
        _require_paths(source, tmp_path / "different" / "other.kicad_pcb")
    with pytest.raises(ValueError, match="KiCad PCB"):
        _require_paths(source, tmp_path / "other.txt")


def test_finalize_rejects_tampered_candidate_before_loading_pcbnew(tmp_path: Path) -> None:
    source = tmp_path / "source.kicad_pcb"
    source.write_text("source content", encoding="utf-8")
    output = tmp_path / "review.kicad_pcb"
    candidate = tmp_path / "review.candidate.kicad_pcb"
    manifest = tmp_path / "review.candidate-evidence.json"
    candidate.write_text("candidate", encoding="utf-8")
    import json

    manifest.write_text(
        json.dumps({"sourceSha256": _file_sha256(source), "candidateSha256": _file_sha256(candidate)}),
        encoding="utf-8",
    )
    candidate.write_text("tampered candidate", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed between routing"):
        finalize_review(source, output, "10.0.6")
    assert not output.exists()


def test_finalize_rejects_new_native_drc_class_without_publishing(tmp_path: Path) -> None:
    source = tmp_path / "source.kicad_pcb"
    source.write_text("source content", encoding="utf-8")
    output = tmp_path / "review.kicad_pcb"
    candidate = tmp_path / "review.candidate.kicad_pcb"
    candidate.write_text("candidate", encoding="utf-8")
    import json

    (tmp_path / "review.candidate-evidence.json").write_text(
        json.dumps({"sourceSha256": _file_sha256(source), "candidateSha256": _file_sha256(candidate)}),
        encoding="utf-8",
    )
    (tmp_path / "review.baseline-drc.rpt").write_text(
        "[drill_out_of_range]: x\n" * 12 + "[hole_clearance]: y\n" * 4 + "[unconnected_items]: z\n" * 37,
        encoding="utf-8",
    )
    (tmp_path / "review.review-drc.rpt").write_text(
        "[drill_out_of_range]: x\n" * 12
        + "[hole_clearance]: y\n" * 4
        + "[unconnected_items]: z\n" * 12
        + "[shorting_items]: new short\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="rejected"):
        finalize_review(source, output, "10.0.6")
    assert not output.exists()


def test_blocking_findings_detect_replaced_defect_with_unchanged_category_count() -> None:
    before = (
        "[hole_clearance]: Hole spacing 0.1944 mm\n"
        "    Rule: board setup hole; error\n"
        "    @(1.0000 mm, 2.0000 mm): Pad J1.A1 [GND]\n"
        "[unconnected_items]: First unrouted net\n"
    )
    after = (
        "[unconnected_items]: Remaining unrouted net\n"
        "[hole_clearance]: Hole spacing 0.1944 mm\n"
        "    Rule: board setup hole; error\n"
        "    @(9.0000 mm, 2.0000 mm): Pad J1.A1 [GND]\n"
    )
    assert _violations(before) == _violations(after)
    assert _blocking_finding_signatures(before) != _blocking_finding_signatures(after)
    assert _blocking_finding_signatures(before) == _blocking_finding_signatures(before.split("[unconnected_items]")[0])


def test_finalize_rejects_same_count_but_relocated_hole_violation(tmp_path: Path) -> None:
    """A newly introduced physical DRC finding cannot replace an old one."""
    import json

    source = tmp_path / "source.kicad_pcb"
    source.write_text("source content", encoding="utf-8")
    output = tmp_path / "review.kicad_pcb"
    candidate = tmp_path / "review.candidate.kicad_pcb"
    candidate.write_text("candidate", encoding="utf-8")
    (tmp_path / "review.candidate-evidence.json").write_text(
        json.dumps({"sourceSha256": _file_sha256(source), "candidateSha256": _file_sha256(candidate)}),
        encoding="utf-8",
    )
    drills = "[drill_out_of_range]: undersized\n    @(1, 1): U1 pad 39\n" * 12
    holes = "[hole_clearance]: too close\n    @(1, 2): J1 peg\n" * 4
    before = drills + holes + "[unconnected_items]: gap\n" * 37
    after = drills + holes.replace("@(1, 2): J1 peg", "@(9, 2): new J1 peg", 1)
    # One report entry changes, but the category counts remain exactly equal.
    after += "[unconnected_items]: gap\n" * 12
    (tmp_path / "review.baseline-drc.rpt").write_text(before, encoding="utf-8")
    (tmp_path / "review.review-drc.rpt").write_text(after, encoding="utf-8")
    assert _violations(before) == {"drill_out_of_range": 12, "hole_clearance": 4, "unconnected_items": 37}
    assert _violations(after) == {"drill_out_of_range": 12, "hole_clearance": 4, "unconnected_items": 12}
    with pytest.raises(RuntimeError, match="changed physical defect"):
        finalize_review(source, output, "10.0.7")
    assert not output.exists()
