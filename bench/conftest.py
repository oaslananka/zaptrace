"""Shared fixtures for the CodSpeed performance benchmarks."""

from __future__ import annotations

from pathlib import Path

import pytest

from zaptrace.algo.placer import place_components
from zaptrace.algo.router import route_design_smart
from zaptrace.core.models import Design
from zaptrace.core.parser import parse_str

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DESIGN_PATH = ROOT / "examples" / "esp32_i2c_sensor_node" / "design.yaml"
SCALED_CHANNELS = 12


def scaled_design_yaml(channels: int) -> str:
    """Return a deterministic multi-channel RC/LED design used to exercise scaling."""
    lines = [
        "meta:",
        f"  name: Scaled Benchmark {channels}ch",
        "  author: codspeed",
        "board:",
        f"  width_mm: {max(40, channels * 6)}",
        f"  height_mm: {max(30, channels * 4)}",
        "  layers: 2",
        "components:",
    ]
    for index in range(1, channels + 1):
        lines += [
            f"  R{index}:",
            f'    ref: "R{index}"',
            "    type: resistor",
            "    value: 1k",
            '    footprint: "0805"',
            f"  C{index}:",
            f'    ref: "C{index}"',
            "    type: capacitor",
            "    value: 100n",
            '    footprint: "0603"',
            f"  D{index}:",
            f'    ref: "D{index}"',
            "    type: led",
            "    value: red",
            '    footprint: "0805"',
        ]
    lines.append("nets:")
    vcc = [f"R{index}.p1" for index in range(1, channels + 1)]
    gnd = [node for index in range(1, channels + 1) for node in (f"C{index}.p2", f"D{index}.K")]
    lines += ["  vcc:", "    name: VCC_3V3", "    nodes:", *(f"      - {node}" for node in vcc)]
    lines += ["  gnd:", "    name: GND", "    nodes:", *(f"      - {node}" for node in gnd)]
    for index in range(1, channels + 1):
        lines += [
            f"  sig{index}:",
            f"    name: SIG{index}",
            "    nodes:",
            f"      - R{index}.p2",
            f"      - C{index}.p1",
            f"      - D{index}.A",
        ]
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="session")
def example_yaml() -> str:
    return EXAMPLE_DESIGN_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def scaled_yaml() -> str:
    return scaled_design_yaml(SCALED_CHANNELS)


def _placed(source: str) -> tuple[Design, dict[str, tuple[float, float]]]:
    design = parse_str(source)
    positions = place_components(design)
    design.placement = positions
    return design, positions


def _routed(source: str) -> Design:
    design, positions = _placed(source)
    _, route_result, _ = route_design_smart(design, positions)
    design.routing = route_result
    return design


@pytest.fixture
def example_design(example_yaml: str) -> Design:
    return parse_str(example_yaml)


@pytest.fixture
def scaled_design(scaled_yaml: str) -> Design:
    return parse_str(scaled_yaml)


@pytest.fixture
def example_placed(example_yaml: str) -> tuple[Design, dict[str, tuple[float, float]]]:
    return _placed(example_yaml)


@pytest.fixture
def scaled_placed(scaled_yaml: str) -> tuple[Design, dict[str, tuple[float, float]]]:
    return _placed(scaled_yaml)


@pytest.fixture
def example_routed(example_yaml: str) -> Design:
    return _routed(example_yaml)


@pytest.fixture
def scaled_routed(scaled_yaml: str) -> Design:
    return _routed(scaled_yaml)
