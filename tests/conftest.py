"""Shared test fixtures for ZapTrace tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from zaptrace.core.models import (
    BoardConfig,
    Component,
    Design,
    DesignMeta,
    Net,
    NetNode,
)

pytest_plugins = ("tests.lane_policy",)

MINIMAL_YAML = """\
meta:
  name: MinimalTest
  author: test
components:
  r1:
    ref: R1
    type: resistor
    value: 10k
    footprint: "0805"
  c1:
    ref: C1
    type: capacitor
    value: 100n
    footprint: "0603"
nets:
  vcc:
    name: VCC
    nodes:
      - R1.p1
      - C1.p1
  gnd:
    name: GND
    nodes:
      - R1.p2
      - C1.p2
board:
  width_mm: 50.0
  height_mm: 40.0
  layers: 2
"""


@pytest.fixture
def sample_design() -> Design:
    """Create a minimal sample design for testing."""
    return Design(
        meta=DesignMeta(name="SampleDesign", author="tester"),
        components={
            "r1": Component(id="r1", ref="R1", type="resistor", value="10k", footprint="0805"),
            "c1": Component(id="c1", ref="C1", type="capacitor", value="100n", footprint="0603"),
            "u1": Component(id="u1", ref="U1", type="mcu", footprint="QFP-44"),
        },
        nets={
            "vcc": Net(
                id="vcc",
                name="VCC",
                nodes=[NetNode(component_ref="R1", pin_name="p1"), NetNode(component_ref="C1", pin_name="p1")],
            ),
            "gnd": Net(
                id="gnd",
                name="GND",
                nodes=[NetNode(component_ref="R1", pin_name="p2"), NetNode(component_ref="C1", pin_name="p2")],
            ),
        },
        board=BoardConfig(width_mm=50.0, height_mm=40.0, layers=2),
    )


@pytest.fixture
def sample_design_path(tmp_path: Path) -> Path:
    """Write MINIMAL_YAML to a temp file and return the path."""
    path = tmp_path / "sample.yaml"
    path.write_text(MINIMAL_YAML, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _enable_local_api_capability_headers_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run API tests in the explicitly opted-in loopback development mode."""
    monkeypatch.setenv("ZAPTRACE_API_ALLOW_LOCAL_CAPABILITY_HEADERS", "1")


@pytest.fixture(autouse=True)
def _reset_api_rate_limiter_between_tests() -> None:
    """Keep process-global API rate-limit state isolated between tests."""
    from zaptrace.api import server as api_server

    api_server.app.state.rate_limit_backend.reset()
    yield
    api_server.app.state.rate_limit_backend.reset()
