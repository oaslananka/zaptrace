"""Synthesis benchmark — the engine's completeness across many board types.

The scorecard measures one board; this measures the *engine*, by synthesizing a
fixed corpus of representative intents and aggregating their scores. It turns
"85/100 on a datalogger" into "here is mean completeness, which dimension is
weakest across board types, and which boards score worst" — a quantitative,
regression-catching answer to "how finished is synthesis?" and the first slice
of a release-blocking quality gate.

Deterministic: a fixed corpus, deterministic synthesis, so the report is stable
and a drop in any number is a real regression.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

_DIMENSIONS = ("functional_core", "composition", "electrical", "manufacturability")


@dataclass(frozen=True)
class BenchmarkCase:
    """One named intent in the corpus."""

    name: str
    intent: str


# Representative board types the composition synthesizer should handle.
_DEFAULT_CORPUS: tuple[BenchmarkCase, ...] = (
    BenchmarkCase("esp32_i2c_sensor", "ESP32-C3 USB-C 3.3V board, I2C temperature sensor"),
    BenchmarkCase("esp32_datalogger", "ESP32-C3 USB-C 3.3V datalogger, I2C temperature sensor, SPI flash"),
    BenchmarkCase("stm32_rs485_node", "STM32 3.3V board, RS485 modbus node"),
    BenchmarkCase("rp2040_can_node", "RP2040 3.3V board, CAN bus node"),
    BenchmarkCase("nrf52_multisensor", "nRF52 3.3V board, I2C temperature and pressure sensors"),
    BenchmarkCase("esp32_ethernet", "ESP32 3.3V board, I2C sensor, ethernet"),
)


@dataclass
class CaseResult:
    """The score of one benchmark case."""

    name: str
    intent: str
    score: int
    grade: str
    dimension_status: dict[str, str] = field(default_factory=dict)
    review_items: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "intent": self.intent,
            "score": self.score,
            "grade": self.grade,
            "dimension_status": self.dimension_status,
            "review_items": self.review_items,
        }


@dataclass
class BenchmarkReport:
    """Aggregate engine quality across the corpus."""

    cases: list[CaseResult] = field(default_factory=list)
    mean_score: float = 0.0
    dimension_pass_rate: dict[str, float] = field(default_factory=dict)
    weakest_dimension: str = ""
    worst_case: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_count": len(self.cases),
            "mean_score": round(self.mean_score, 1),
            "dimension_pass_rate": {k: round(v, 3) for k, v in self.dimension_pass_rate.items()},
            "weakest_dimension": self.weakest_dimension,
            "worst_case": self.worst_case,
            "cases": [c.to_dict() for c in self.cases],
        }


def _score_case(case: BenchmarkCase) -> CaseResult:
    from zaptrace.analysis.dc_bias import resolve_dc_bias
    from zaptrace.synthesis.fab import _review_checklist
    from zaptrace.synthesis.repair import synthesize_and_repair
    from zaptrace.synthesis.scorecard import score_board

    out = synthesize_and_repair(case.intent)
    bias = resolve_dc_bias(out["design"])
    card = score_board(out["design"], out["plan"], out["repair"], out["footprints"], bias)
    # The benchmark scores synthesis only (no place/route), so DRC errors are 0 here.
    review = _review_checklist(
        out["repair"], out["footprints"], bias, [b.block_id for b in out["plan"].unrealized_blocks], 0
    )
    return CaseResult(
        name=case.name,
        intent=case.intent,
        score=card.score,
        grade=card.grade,
        dimension_status={d.name: d.status for d in card.dimensions},
        review_items=len(review),
    )


@lru_cache(maxsize=16)
def _run_benchmark_cached(cases: tuple[BenchmarkCase, ...]) -> BenchmarkReport:
    results = [_score_case(case) for case in cases]
    if not results:
        return BenchmarkReport()

    mean = sum(r.score for r in results) / len(results)
    pass_rate: dict[str, float] = {}
    for dim in _DIMENSIONS:
        passing = sum(1 for r in results if r.dimension_status.get(dim) == "pass")
        pass_rate[dim] = passing / len(results)
    weakest = min(pass_rate, key=lambda d: pass_rate[d])
    worst = min(results, key=lambda r: r.score)
    return BenchmarkReport(
        cases=results,
        mean_score=mean,
        dimension_pass_rate=pass_rate,
        weakest_dimension=weakest,
        worst_case=worst.name,
    )


def run_benchmark(corpus: tuple[BenchmarkCase, ...] | None = None) -> BenchmarkReport:
    """Synthesize every corpus case and aggregate completeness across the engine.

    Results are cached per immutable corpus because the default benchmark is
    intentionally deterministic and expensive. A deep copy is returned so callers
    cannot mutate cached evidence shared by later tests or CI checks.
    """
    cases = corpus if corpus is not None else _DEFAULT_CORPUS
    return copy.deepcopy(_run_benchmark_cached(cases))
