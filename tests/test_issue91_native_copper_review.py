"""Fail-closed partial copper paths must connect authentic pad centers and nets."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.issue91_native_copper_review import (
    ROUTES,
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
    assert len(ROUTES) == 19
    assert sum(len(route.points) - 1 for route in ROUTES) == 41
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
        + "[unconnected_items]: z\n" * 18
        + "[shorting_items]: new short\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="rejected"):
        finalize_review(source, output, "10.0.6")
    assert not output.exists()
