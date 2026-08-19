"""Tests for the board completeness scorecard."""

from __future__ import annotations

from zaptrace.synthesis.repair import synthesize_and_repair
from zaptrace.synthesis.scorecard import _grade, _status, score_board


def _score(intent: str):
    out = synthesize_and_repair(intent)
    return score_board(out["design"], out["plan"], out["repair"], out["footprints"])


class TestHelpers:
    def test_status_thresholds(self) -> None:
        assert _status(1.0) == "pass"
        assert _status(0.0) == "fail"
        assert _status(0.5) == "partial"

    def test_grade_bands(self) -> None:
        assert _grade(95) == "A"
        assert _grade(80) == "B"
        assert _grade(65) == "C"
        assert _grade(45) == "D"
        assert _grade(10) == "F"


class TestScoring:
    def test_full_mcu_sensor_board_scores_well(self) -> None:
        card = _score("ESP32-C3 USB-C 3.3V board, I2C temperature sensor")
        assert card.score >= 75
        names = {d.name for d in card.dimensions}
        assert names == {"functional_core", "composition", "electrical", "manufacturability"}
        core = next(d for d in card.dimensions if d.name == "functional_core")
        assert core.status == "pass"

    def test_missing_mcu_part_fails_functional_core(self) -> None:
        card = _score("SAMD21 3.3V board, I2C sensor")
        core = next(d for d in card.dimensions if d.name == "functional_core")
        assert core.status == "fail"
        assert core.score == 0.0
        # a failed core drags the overall score down — it cannot be a complete board
        assert card.score < 75

    def test_board_without_mcu_marks_core_na(self) -> None:
        card = _score("USB-C 3.3V board, I2C sensor")  # no MCU family in intent
        core = next(d for d in card.dimensions if d.name == "functional_core")
        assert core.status == "n/a"
        assert core.score == 1.0

    def test_advisory_only_board_passes_electrical(self) -> None:
        # A board whose only remaining ERC items are info-level DfT suggestions
        # (test points, idle pull-ups) is electrically sound and should pass.
        card = _score("nRF52 3.3V board, I2C temperature and pressure sensors")
        electrical = next(d for d in card.dimensions if d.name == "electrical")
        assert electrical.status == "pass"

    def test_unrealized_block_lowers_composition(self) -> None:
        # A 5V rail on a battery board needs a boost stage, which has no block yet.
        card = _score("ESP32-C3 battery board, single Li-ion cell, 5V rail")
        comp = next(d for d in card.dimensions if d.name == "composition")
        assert comp.score < 1.0


class TestSerialization:
    def test_to_dict_shape(self) -> None:
        data = _score("ESP32-C3 3.3V board, I2C sensor").to_dict()
        assert set(data) == {"score", "grade", "dimensions"}
        assert isinstance(data["score"], int)
        assert all({"name", "score", "status", "detail"} == set(d) for d in data["dimensions"])
