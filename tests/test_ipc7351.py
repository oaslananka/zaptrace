from __future__ import annotations

import json
from pathlib import Path

import pytest

from zaptrace.ee.footprint_proof import validate_footprint_proof
from zaptrace.ee.ipc7351 import Ipc7351DensityLevel, calculate_ipc7351_chip, supported_ipc7351_chip_packages


def test_supported_ipc7351_chip_packages_contains_0603() -> None:
    assert supported_ipc7351_chip_packages() == ["0603"]


def test_calculate_ipc7351_0603_emits_footprint_and_proof() -> None:
    result = calculate_ipc7351_chip("0603")

    assert result.coverage == "skeleton-passive-chip-only"
    assert result.fixture.package_code == "0603"
    assert len(result.footprint.pads) == 2
    assert result.proof.package_id == "0603"
    assert result.proof.pad_count == 2
    assert result.proof.pin_count == 2
    assert result.proof.source.generator == "zaptrace.ee.ipc7351.calculate_ipc7351_chip"
    assert result.proof.pin1.present is True
    assert validate_footprint_proof(result.proof).blocked is False


def test_ipc7351_density_changes_pad_size() -> None:
    least = calculate_ipc7351_chip("0603", density=Ipc7351DensityLevel.LEAST)
    most = calculate_ipc7351_chip("0603", density=Ipc7351DensityLevel.MOST)

    assert least.footprint.pads[0].size[0] < most.footprint.pads[0].size[0]
    assert least.density == Ipc7351DensityLevel.LEAST
    assert most.density == Ipc7351DensityLevel.MOST


def test_ipc7351_unknown_package_is_actionable() -> None:
    with pytest.raises(ValueError, match="supported: 0603"):
        calculate_ipc7351_chip("9999")


def test_ipc7351_sample_fixture_matches_schema() -> None:
    data = json.loads(Path("tests/fixtures/footprints/ipc7351_0603_result.json").read_text(encoding="utf-8"))

    assert data["standard_family"] == "IPC-7351-oriented"
    assert data["coverage"] == "skeleton-passive-chip-only"
    assert data["proof"]["package_id"] == "0603"
