"""Tests for the synthesis benchmark harness."""

from __future__ import annotations

from functools import cache

from zaptrace.synthesis.benchmark import BenchmarkCase, run_benchmark

_DIMENSIONS = {"functional_core", "composition", "electrical", "manufacturability"}


@cache
def _default_benchmark_report():
    """Run the expensive default synthesis corpus once per pytest process."""
    return run_benchmark()


class TestBenchmark:
    def test_default_corpus_runs_and_aggregates(self) -> None:
        report = _default_benchmark_report()
        assert len(report.cases) >= 5
        assert 0 <= report.mean_score <= 100
        assert set(report.dimension_pass_rate) == _DIMENSIONS

    def test_functional_core_is_reliably_placed(self) -> None:
        # Every corpus board names an MCU family with a library part.
        report = _default_benchmark_report()
        assert report.dimension_pass_rate["functional_core"] == 1.0

    def test_identifies_weakest_dimension_and_worst_case(self) -> None:
        report = _default_benchmark_report()
        assert report.weakest_dimension in _DIMENSIONS
        assert report.worst_case in {c.name for c in report.cases}
        # the worst case has the lowest score
        assert report.cases  # non-empty
        assert min(c.score for c in report.cases) == next(c.score for c in report.cases if c.name == report.worst_case)

    def test_custom_corpus(self) -> None:
        report = run_benchmark((BenchmarkCase("one", "ESP32-C3 3.3V board, I2C sensor"),))
        assert len(report.cases) == 1
        assert report.cases[0].name == "one"

    def test_empty_corpus_is_safe(self) -> None:
        report = run_benchmark(())
        assert report.cases == []
        assert report.mean_score == 0.0

    def test_to_dict_shape(self) -> None:
        data = run_benchmark((BenchmarkCase("one", "ESP32-C3 3.3V board, I2C sensor"),)).to_dict()
        assert set(data) == {
            "case_count",
            "mean_score",
            "dimension_pass_rate",
            "weakest_dimension",
            "worst_case",
            "cases",
        }
        assert data["case_count"] == 1
