from __future__ import annotations

import json
from pathlib import Path

from tests.test_kicad_export import _make_test_design
from zaptrace.export.ipcd356 import (
    compare_ir_to_ipcd356,
    compare_ir_to_ipcd356_file,
    design_ref_net_map,
    generate_ipcd356,
    parse_ipcd356,
    write_ipcd356,
    write_ipcd356_parity_report,
)


def test_generate_ipcd356_contains_connectivity_records() -> None:
    text = generate_ipcd356(_make_test_design())

    assert "ZapTrace IPC-D-356 connectivity subset" in text
    assert "P NET VCC REF R1 PIN 1" in text
    assert "P NET GND REF C1 PIN 2" in text
    assert text.rstrip().endswith("999")


def test_parse_ipcd356_roundtrips_expected_map() -> None:
    design = _make_test_design()
    parsed = parse_ipcd356(generate_ipcd356(design))

    assert parsed == design_ref_net_map(design)
    assert parsed["VCC"] == {"R1.1", "C1.1"}


def test_ipcd356_parity_passes_for_exported_file(tmp_path: Path) -> None:
    design = _make_test_design()
    ipc = write_ipcd356(design, tmp_path / "board.ipc")

    report = compare_ir_to_ipcd356_file(design, ipc)

    assert report.passed is True
    assert report.error_count == 0
    assert report.ir_net_count == 2
    assert report.ipc_d356_net_count == 2


def test_ipcd356_parity_detects_missing_and_extra_nets() -> None:
    design = _make_test_design()
    text = "P NET VCC REF R1 PIN 1\nP NET EXTRA REF X1 PIN 1\n999\n"

    report = compare_ir_to_ipcd356(design, text)

    assert report.passed is False
    assert report.missing_nets == ["GND"]
    assert report.extra_nets == ["EXTRA"]


def test_ipcd356_parity_detects_pin_mismatch() -> None:
    design = _make_test_design()
    text = generate_ipcd356(design).replace("P NET VCC REF C1 PIN 1", "P NET VCC REF C1 PIN 2")

    report = compare_ir_to_ipcd356(design, text)

    assert report.passed is False
    mismatch = next(item for item in report.pin_mismatches if item.net_id == "VCC")
    assert mismatch.missing_nodes == ["C1.1"]
    assert mismatch.extra_nodes == ["C1.2"]


def test_write_ipcd356_parity_report(tmp_path: Path) -> None:
    design = _make_test_design()
    ipc = write_ipcd356(design, tmp_path / "board.ipc")
    out = write_ipcd356_parity_report(design, ipc, tmp_path / "ipc_d356_parity.json")

    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.0"
    assert data["check"] == "ipc_d356_netlist"
    assert data["passed"] is True
