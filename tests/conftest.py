"""Shared test fixtures for ZapTrace tests."""

from __future__ import annotations

import hashlib
import shutil
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


@pytest.fixture(scope="session", autouse=True)
def _stage_native_reference_source_for_tests() -> None:
    """Provide a pinned, local-only KiCad input without overwriting existing source data."""
    root = Path(__file__).resolve().parents[1]
    fixture = root / "tests/fixtures/native_review_reference"
    destination = root / "build/source-reference-readonly"
    manifest = fixture / "SHA256SUMS"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        candidate = fixture / relative
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
            pytest.fail(f"Pinned native source fixture is corrupt: {relative}")

    if not destination.exists() and not destination.is_symlink():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(fixture, destination)
    elif destination.is_symlink() or not destination.is_dir():
        pytest.fail("Native source directory is not a regular folder")

    # Do not overwrite someone else's source checkout. Its identity must match
    # the pinned fixture when it is used for source-bound acceptance tests.
    for name in (
        "issue91-design.yaml",
        "ESP32_actual_copper_review.kicad_pcb",
        "ESP32_I2C_Sensor_Board.kicad_sch",
    ):
        actual = destination / name
        if (
            not actual.is_file()
            or hashlib.sha256(actual.read_bytes()).digest() != hashlib.sha256((fixture / name).read_bytes()).digest()
        ):
            pytest.fail(f"Existing native source differs from pinned test fixture: {name}")
