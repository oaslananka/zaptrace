"""Tests for benchmark corpus schema and utilities."""

from __future__ import annotations

import pytest

from zaptrace.benchmark.corpus import (
    BUILTIN_BENCHMARKS,
    BenchmarkResult,
    BenchmarkRunResult,
    get_benchmark,
    list_benchmarks,
)


def test_builtin_benchmarks_non_empty() -> None:
    assert len(BUILTIN_BENCHMARKS) >= 5


def test_get_benchmark_by_id() -> None:
    entry = get_benchmark("BM-001")
    assert entry.entry_id == "BM-001"
    assert entry.title
    assert len(entry.criteria) >= 3


def test_get_unknown_benchmark_raises() -> None:
    with pytest.raises(ValueError, match="No benchmark"):
        get_benchmark("BM-999")


def test_list_benchmarks_all() -> None:
    all_entries = list_benchmarks()
    assert len(all_entries) == len(BUILTIN_BENCHMARKS)


def test_list_benchmarks_by_category() -> None:
    erc_entries = list_benchmarks(category="erc")
    assert all(e.category == "erc" for e in erc_entries)
    assert len(erc_entries) >= 1


def test_list_benchmarks_by_tag() -> None:
    ble_entries = list_benchmarks(tags=["ble"])
    assert len(ble_entries) >= 1
    assert all("ble" in e.tags for e in ble_entries)


def test_benchmark_entry_serializable() -> None:
    entry = get_benchmark("BM-001")
    d = entry.to_dict()
    assert "entry_id" in d
    assert "criteria" in d
    assert "intent" in d


class TestBenchmarkRunResult:
    def test_all_passed_when_all_true(self) -> None:
        run = BenchmarkRunResult(
            entry_id="BM-001",
            results=[
                BenchmarkResult("has_mcu", True, 1.0),
                BenchmarkResult("has_led", True, 1.0),
            ],
        )
        assert run.all_passed

    def test_all_passed_false_when_any_fail(self) -> None:
        run = BenchmarkRunResult(
            entry_id="BM-001",
            results=[
                BenchmarkResult("has_mcu", True, 1.0),
                BenchmarkResult("erc_clean", False, 0.0, "3 ERC errors"),
            ],
        )
        assert not run.all_passed

    def test_weighted_score_is_mean(self) -> None:
        run = BenchmarkRunResult(
            entry_id="BM-001",
            results=[
                BenchmarkResult("a", True, 1.0),
                BenchmarkResult("b", False, 0.0),
            ],
        )
        assert run.weighted_score == pytest.approx(0.5)

    def test_empty_result_score_is_zero(self) -> None:
        run = BenchmarkRunResult(entry_id="X")
        assert run.weighted_score == 0.0
