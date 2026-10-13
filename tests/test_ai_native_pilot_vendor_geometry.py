"""Source-checked physical geometry cannot be silently replaced."""

from pathlib import Path

import pytest

from scripts.ai_native_candidate_pilot import write_local_candidate
from scripts.ai_native_pilot_placement_geometry import require_pinned_physical_packages
from zaptrace.core.models import Design

INTENT = "USB-C powered STM32 MCU board, 3.3V rail at 100 mA, I2C temperature sensor"


def test_exact_stm32_footprint_verified(tmp_path: Path) -> None:
    p = tmp_path / "candidate"
    write_local_candidate(INTENT, p)
    design = Design.model_validate_json((p / "design.json").read_bytes())
    evidence = require_pinned_physical_packages(design)
    assert set(evidence) == {"U2", "U3"}
    assert design.components["U2"].footprint_def is not None
    assert len(design.components["U2"].footprint_def.pads) == 48
    assert design.components["U3"].footprint_def is not None
    assert len(design.components["U3"].footprint_def.pads) == 9


def test_wrong_source_part_rejected(tmp_path: Path) -> None:
    p = tmp_path / "candidate"
    write_local_candidate(INTENT, p)
    design = Design.model_validate_json((p / "design.json").read_bytes())
    design.components["U2"].mpn = "unverified-mcu"
    with pytest.raises(ValueError, match="Physical source part"):
        require_pinned_physical_packages(design)
