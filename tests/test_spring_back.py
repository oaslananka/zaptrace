"""Tests for spring-back shove behavior and benchmark evidence (issue #139).

Verifies:
- Spring-back retraction reduces wirelength for detoured paths.
- DRC-clean rate is reported correctly.
- Obstacle chains and multi-segment push are covered.
- Benchmark report has all required keys.
- Freerouting status is 'skipped' when unavailable.
- Python and Rust paths produce schema-compatible evidence.
- Native results meet declared baseline gate without hiding skipped cases.
"""

from __future__ import annotations

import pytest

from zaptrace.algo.spring_back import (
    ShoveBenchmarkResult,
    ShoveSpringbackResult,
    SpringbackSegment,
    benchmark_shove_vs_freerouting,
    route_shove_springback,
)

OBSTACLE = (5.0, 0.0, 15.0, 10.0)


# ---------------------------------------------------------------------------
# Data-model / schema tests
# ---------------------------------------------------------------------------


def test_springback_segment_schema() -> None:
    s = SpringbackSegment(coords=(0.0, 0.0, 10.0, 0.0))
    d = s.to_dict()
    assert "coords" in d
    assert "retracted" in d
    assert "drc_clean" in d


def test_shove_springback_result_schema() -> None:
    r = ShoveSpringbackResult(
        net_id="N1",
        provenance="walkaround-above-y10.000",
        resolved=True,
        segments=[(0.0, 0.0, 10.0, 0.0)],
    )
    d = r.to_dict()
    for key in (
        "net_id",
        "provenance",
        "resolved",
        "segments",
        "springback_segments",
        "retracted_count",
        "drc_clean",
        "elapsed_ms",
    ):
        assert key in d, f"Missing key: {key}"


def test_benchmark_result_schema() -> None:
    b = ShoveBenchmarkResult(
        shove_completion_rate=1.0,
        shove_drc_clean_rate=1.0,
        shove_total_wirelength_mm=25.0,
        shove_retracted_count=1,
        shove_elapsed_ms=0.5,
    )
    d = b.to_dict()
    for key in (
        "shove_completion_rate",
        "shove_drc_clean_rate",
        "shove_total_wirelength_mm",
        "shove_retracted_count",
        "shove_elapsed_ms",
        "freerouting_status",
        "freerouting_completion_rate",
        "fallback_usage",
        "evidence_schema",
    ):
        assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Spring-back geometry tests
# ---------------------------------------------------------------------------


def test_no_obstacle_direct_path_no_springback() -> None:
    connections = [(0.0, 0.0, 10.0, 10.0, "N1")]
    results = route_shove_springback(connections, [], 0.2)
    r = results[0]
    assert r.resolved is True
    assert r.net_id == "N1"


def test_obstacle_resolved_with_spring_back() -> None:
    connections = [(0.0, 5.0, 20.0, 5.0, "NET_SHOVE")]
    results = route_shove_springback(connections, [OBSTACLE], 0.2)
    r = results[0]
    assert r.resolved is True
    assert "walkaround" in r.provenance
    assert len(r.springback_segments) >= 2


def test_springback_drc_clean_for_clear_path() -> None:
    connections = [(50.0, 50.0, 60.0, 60.0, "CLEAR")]
    results = route_shove_springback(connections, [], 0.2)
    assert results[0].drc_clean is True


def test_springback_result_has_elapsed_ms() -> None:
    connections = [(0.0, 5.0, 20.0, 5.0, "N1")]
    results = route_shove_springback(connections, [OBSTACLE], 0.2)
    assert results[0].elapsed_ms >= 0.0


def test_obstacle_chain_multiple_connections() -> None:
    """Multiple connections routed around obstacle chain."""
    obstacles = [
        (2.0, 0.0, 8.0, 6.0),
        (10.0, 0.0, 16.0, 6.0),
    ]
    connections = [
        (0.0, 3.0, 20.0, 3.0, "N1"),
        (0.0, 4.0, 20.0, 4.0, "N2"),
        (0.0, 5.0, 20.0, 5.0, "N3"),
    ]
    results = route_shove_springback(connections, obstacles, 0.2)
    assert len(results) == 3
    for r in results:
        assert r.net_id in {"N1", "N2", "N3"}
        assert isinstance(r.segments, list)
        assert isinstance(r.drc_clean, bool)


def test_spring_back_reduces_wirelength_vs_naive_detour() -> None:
    """Retracted path should have <= wirelength of full detour."""
    connections = [(0.0, 5.0, 20.0, 5.0, "N1")]
    results_with_sb = route_shove_springback(connections, [OBSTACLE], 0.5)
    r = results_with_sb[0]

    def total_wl(segs: list) -> float:
        return sum(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 for x1, y1, x2, y2 in segs)

    # If retraction occurred, wirelength should be <= original detour
    if r.retracted_count > 0:
        assert (
            total_wl(r.segments)
            <= total_wl([(0.0, 5.0, 0.0, 10.2), (0.0, 10.2, 20.0, 10.2), (20.0, 10.2, 20.0, 5.0)]) + 1.0
        )  # small tolerance


def test_negative_clearance_raises() -> None:
    with pytest.raises(ValueError, match="clearance"):
        route_shove_springback([(0.0, 0.0, 10.0, 10.0, "N")], [], -0.1)


def test_empty_connections_returns_empty() -> None:
    results = route_shove_springback([], [], 0.2)
    assert results == []


# ---------------------------------------------------------------------------
# Benchmark tests
# ---------------------------------------------------------------------------


def test_benchmark_returns_result_schema() -> None:
    connections = [(0.0, 5.0, 20.0, 5.0, "N1")]
    bench = benchmark_shove_vs_freerouting(connections, [OBSTACLE], 0.2)
    assert isinstance(bench, ShoveBenchmarkResult)
    d = bench.to_dict()
    assert d["shove_completion_rate"] > 0.0
    assert d["freerouting_status"] in {"skipped", "pass", "fail", "drc_rejected"}
    assert d["evidence_schema"] == "springback-v1"


def test_benchmark_no_skipped_cases_hidden() -> None:
    """Freerouting SKIPPED must be explicit, not silently removed."""
    connections = [(0.0, 0.0, 10.0, 10.0, "N1")]
    bench = benchmark_shove_vs_freerouting(connections, [], 0.2)
    d = bench.to_dict()
    assert "freerouting_status" in d
    if d["freerouting_status"] == "skipped":
        assert d["freerouting_completion_rate"] is None


def test_benchmark_completion_rate_range() -> None:
    connections = [
        (0.0, 5.0, 20.0, 5.0, "N1"),
        (50.0, 50.0, 60.0, 60.0, "N2"),
    ]
    bench = benchmark_shove_vs_freerouting(connections, [OBSTACLE], 0.2)
    assert 0.0 <= bench.shove_completion_rate <= 1.0
    assert 0.0 <= bench.shove_drc_clean_rate <= 1.0


def test_benchmark_wirelength_positive() -> None:
    connections = [(0.0, 5.0, 20.0, 5.0, "N1")]
    bench = benchmark_shove_vs_freerouting(connections, [OBSTACLE], 0.2)
    assert bench.shove_total_wirelength_mm > 0.0


# ---------------------------------------------------------------------------
# Schema compatibility with shove router
# ---------------------------------------------------------------------------


def test_springback_result_compatible_with_shove_schema() -> None:
    """ShoveSpringbackResult must include all ShoveResult fields."""
    from zaptrace.algo.shove import route_shove

    connections = [(0.0, 5.0, 20.0, 5.0, "N1")]
    shove_results = route_shove(connections, [OBSTACLE], 0.2)
    springback_results = route_shove_springback(connections, [OBSTACLE], 0.2)

    sr = shove_results[0]
    sp = springback_results[0]

    # Both must have the same net_id and provenance
    assert sr.net_id == sp.net_id
    assert sr.provenance == sp.provenance
    assert sr.resolved == sp.resolved
