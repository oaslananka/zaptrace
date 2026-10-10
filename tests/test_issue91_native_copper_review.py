"""Fail-closed partial copper paths must connect authentic pad centers and nets."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.issue91_native_copper_review import (
    ROUTES,
    _native_drc,
    _run_kicad_cli,
    _trusted_kicad_cli,
    _violations,
)
from zaptrace.core.parser import parse_file

_DESIGN = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"


def test_native_copper_review_has_only_verified_complete_net_terminal_endpoints() -> None:
    design = parse_file(_DESIGN)
    assert design.placement is not None
    assert len(ROUTES) == 14
    assert sum(len(route.points) - 1 for route in ROUTES) == 30
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


def test_native_cli_is_resolved_and_must_be_executable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    binary = tmp_path / "kicad-cli"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setattr("scripts.issue91_native_copper_review.shutil.which", lambda _: str(binary))
    assert _trusted_kicad_cli() == binary.resolve()
    binary.chmod(0o644)
    with pytest.raises(RuntimeError, match="not an executable"):
        _trusted_kicad_cli()
    monkeypatch.setattr("scripts.issue91_native_copper_review.shutil.which", lambda _: None)
    with pytest.raises(RuntimeError, match="not found"):
        _trusted_kicad_cli()


def test_run_kicad_rejects_partial_binaries_and_shell_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binary = tmp_path / "kicad-cli"
    binary.write_text("", encoding="utf-8")
    commands: list[tuple[object, ...]] = []

    def stub_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="10.0.6\n", stderr="")

    monkeypatch.setattr("scripts.issue91_native_copper_review.subprocess.run", stub_run)
    with pytest.raises(ValueError, match="absolute"):
        _run_kicad_cli(Path("kicad-cli"), ["version"])
    assert _run_kicad_cli(binary.resolve(), ["version"]) == "10.0.6\n"
    assert commands == [
        (
            [str(binary.resolve()), "version"],
            {
                "capture_output": True,
                "text": True,
                "check": False,
                "timeout": 120,
            },
        )
    ]


def test_native_drc_rejects_stale_report_after_incomplete_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stale_report = tmp_path / "stale.rpt"
    stale_report.write_text("[unconnected_items]: stale result\n", encoding="utf-8")
    board = tmp_path / "board.kicad_pcb"
    board.write_text("", encoding="utf-8")
    binary = tmp_path / "kicad-cli"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr("scripts.issue91_native_copper_review._run_kicad_cli", lambda *args: "ok")
    with pytest.raises(RuntimeError, match="did not create"):
        _native_drc(board, stale_report, binary)
    assert not stale_report.exists()
