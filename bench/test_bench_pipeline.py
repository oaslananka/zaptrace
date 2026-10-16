"""CodSpeed benchmarks for the deterministic ZapTrace design flow.

Each stage of intent -> design -> placement -> routing -> ERC/DRC -> export is
measured on the committed ESP32 example design and on a synthetic multi-channel
design that exercises scaling behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_codspeed import BenchmarkFixture

from zaptrace.algo.placer import place_components
from zaptrace.algo.router import route_design_smart, route_nets
from zaptrace.core.parser import dump_str, parse_str
from zaptrace.ee.classifier import classify_design
from zaptrace.ee.drc.engine import DRCEngine
from zaptrace.erc.runner import ERCRunner
from zaptrace.export.bom import generate_bom_csv, generate_bom_json
from zaptrace.export.kicad import export_kicad
from zaptrace.synthesis.engine import synthesize

DESIGNS = ("example", "scaled")


@pytest.mark.parametrize("name", DESIGNS)
def test_parse_design_yaml(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    source = request.getfixturevalue(f"{name}_yaml")
    benchmark(parse_str, source)


@pytest.mark.parametrize("name", DESIGNS)
def test_dump_design_yaml(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design = request.getfixturevalue(f"{name}_routed")
    benchmark(dump_str, design)


def test_synthesize_from_intent(benchmark: BenchmarkFixture) -> None:
    benchmark(synthesize, "ESP32 I2C sensor board with BME280")


@pytest.mark.parametrize("name", DESIGNS)
def test_classify_nets(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design = request.getfixturevalue(f"{name}_design")
    benchmark(classify_design, design)


@pytest.mark.parametrize("name", DESIGNS)
def test_place_components(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design = request.getfixturevalue(f"{name}_design")
    benchmark(place_components, design)


@pytest.mark.parametrize("name", DESIGNS)
def test_route_nets_manhattan(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design, positions = request.getfixturevalue(f"{name}_placed")
    benchmark(route_nets, design, positions)


@pytest.mark.parametrize("name", DESIGNS)
def test_route_design_smart(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design, positions = request.getfixturevalue(f"{name}_placed")
    benchmark(route_design_smart, design, positions)


@pytest.mark.parametrize("name", DESIGNS)
def test_erc_run(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design = request.getfixturevalue(f"{name}_design")
    benchmark(ERCRunner().run, design)


@pytest.mark.parametrize("name", DESIGNS)
def test_drc_run(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design = request.getfixturevalue(f"{name}_routed")
    benchmark(DRCEngine().run, design)


@pytest.mark.parametrize("name", DESIGNS)
def test_bom_export(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design = request.getfixturevalue(f"{name}_design")

    def export_bom() -> tuple[str, str]:
        return generate_bom_csv(design), generate_bom_json(design)

    benchmark(export_bom)


@pytest.mark.parametrize("name", DESIGNS)
def test_kicad_export(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, tmp_path: Path, name: str) -> None:
    design = request.getfixturevalue(f"{name}_routed")
    benchmark(export_kicad, design, tmp_path)
