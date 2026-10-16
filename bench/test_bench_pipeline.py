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
    design = benchmark(parse_str, source)
    assert design.components


@pytest.mark.parametrize("name", DESIGNS)
def test_dump_design_yaml(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design = request.getfixturevalue(f"{name}_routed")
    text = benchmark(dump_str, design)
    assert text


def test_synthesize_from_intent(benchmark: BenchmarkFixture) -> None:
    design = benchmark(synthesize, "ESP32 I2C sensor board with BME280")
    assert design.components


@pytest.mark.parametrize("name", DESIGNS)
def test_classify_nets(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design = request.getfixturevalue(f"{name}_design")
    benchmark(classify_design, design)
    assert design.nets


@pytest.mark.parametrize("name", DESIGNS)
def test_place_components(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design = request.getfixturevalue(f"{name}_design")
    positions = benchmark(place_components, design)
    assert len(positions) == len(design.components)


@pytest.mark.parametrize("name", DESIGNS)
def test_route_nets_manhattan(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design, positions = request.getfixturevalue(f"{name}_placed")
    result = benchmark(route_nets, design, positions)
    assert result.total_nets > 0


@pytest.mark.parametrize("name", DESIGNS)
def test_route_design_smart(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design, positions = request.getfixturevalue(f"{name}_placed")
    _, route_result, _ = benchmark(route_design_smart, design, positions)
    assert route_result.traces


@pytest.mark.parametrize("name", DESIGNS)
def test_erc_run(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design = request.getfixturevalue(f"{name}_design")
    result = benchmark(ERCRunner().run, design)
    assert result.checks_run


@pytest.mark.parametrize("name", DESIGNS)
def test_drc_run(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design = request.getfixturevalue(f"{name}_routed")
    result = benchmark(DRCEngine().run, design)
    assert result.design_name == design.meta.name


@pytest.mark.parametrize("name", DESIGNS)
def test_bom_export(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, name: str) -> None:
    design = request.getfixturevalue(f"{name}_design")

    def export_bom() -> tuple[str, str]:
        return generate_bom_csv(design), generate_bom_json(design)

    csv_text, json_text = benchmark(export_bom)
    assert csv_text and json_text


@pytest.mark.parametrize("name", DESIGNS)
def test_kicad_export(benchmark: BenchmarkFixture, request: pytest.FixtureRequest, tmp_path: Path, name: str) -> None:
    design = request.getfixturevalue(f"{name}_routed")
    files = benchmark(export_kicad, design, tmp_path)
    assert files
