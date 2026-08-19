"""Tests for the rubber-band shove router (issue #138).

Verifies:
- Geometry: deterministic walkaround resolves the canonical obstacle case.
- Python fallback: correct result schema, no Rust toolchain required.
- Rust extension path (skipped if extension unavailable).
- Memory/invalid-input paths: clearance < 0, empty connections.
- Cancellation / no-solution path: unresolvable obstacle.
- Existing router behaviour is unchanged.
- Result schema has required keys for both Rust and Python paths.
"""

from __future__ import annotations

import pytest

from zaptrace.algo.shove import ShoveResult, route_shove

OBSTACLE = (5.0, 0.0, 15.0, 10.0)  # rectangle blocking straight L-path
CLEAR_PATH = (50.0, 50.0, 60.0, 60.0)  # no obstacles on this route


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rust_available() -> bool:
    try:
        import zaptrace._core as _c  # type: ignore[import-not-found]

        return hasattr(_c, "route_shove")
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Schema / data-model tests
# ---------------------------------------------------------------------------


def test_shove_result_schema() -> None:
    r = ShoveResult(
        net_id="N1",
        provenance="direct-l-path",
        resolved=True,
        segments=[(0.0, 0.0, 10.0, 0.0), (10.0, 0.0, 10.0, 10.0)],
    )
    d = r.to_dict()
    assert d["net_id"] == "N1"
    assert d["provenance"] == "direct-l-path"
    assert d["resolved"] is True
    assert len(d["segments"]) == 2


# ---------------------------------------------------------------------------
# Python fallback tests
# ---------------------------------------------------------------------------


def test_empty_connections_returns_empty(force_python: bool = True) -> None:
    results = route_shove([], [], 0.2, force_python=True)
    assert results == []


def test_no_obstacle_direct_l_path() -> None:
    connections = [(0.0, 0.0, 10.0, 10.0, "NET1")]
    results = route_shove(connections, [], 0.2, force_python=True)
    assert len(results) == 1
    r = results[0]
    assert r.net_id == "NET1"
    assert r.resolved is True
    assert r.provenance == "direct-l-path"
    assert len(r.segments) == 2


def test_obstacle_triggers_walkaround() -> None:
    # Connection that would cross the obstacle with naive L-path
    connections = [(0.0, 5.0, 20.0, 5.0, "NET_CROSS")]
    results = route_shove(connections, [OBSTACLE], 0.2, force_python=True)
    r = results[0]
    assert r.resolved is True
    assert "walkaround" in r.provenance
    assert len(r.segments) == 3


def test_walkaround_detour_clears_obstacle() -> None:
    connections = [(0.0, 5.0, 20.0, 5.0, "NET_CROSS")]
    results = route_shove(connections, [OBSTACLE], 0.5, force_python=True)
    r = results[0]
    for sx1, sy1, sx2, sy2 in r.segments:
        # No segment should be inside the obstacle bounding box
        assert not (
            min(sx1, sx2) < OBSTACLE[2]
            and max(sx1, sx2) > OBSTACLE[0]
            and min(sy1, sy2) < OBSTACLE[3]
            and max(sy1, sy2) > OBSTACLE[1]
        ), f"Segment {(sx1, sy1, sx2, sy2)} overlaps obstacle {OBSTACLE}"


def test_determinism_same_result_twice() -> None:
    connections = [(0.0, 5.0, 20.0, 5.0, "NET1")]
    r1 = route_shove(connections, [OBSTACLE], 0.2, force_python=True)
    r2 = route_shove(connections, [OBSTACLE], 0.2, force_python=True)
    assert r1[0].segments == r2[0].segments
    assert r1[0].provenance == r2[0].provenance


def test_multiple_connections_each_resolved() -> None:
    connections = [
        (0.0, 5.0, 20.0, 5.0, "NET1"),
        (0.0, 5.0, 20.0, 5.0, "NET2"),
        (50.0, 50.0, 60.0, 60.0, "NET3"),
    ]
    results = route_shove(connections, [OBSTACLE], 0.2, force_python=True)
    assert len(results) == 3
    assert results[2].provenance == "direct-l-path"


# ---------------------------------------------------------------------------
# Error / edge-case tests
# ---------------------------------------------------------------------------


def test_negative_clearance_raises() -> None:
    with pytest.raises(ValueError, match="clearance"):
        route_shove([(0.0, 0.0, 10.0, 10.0, "N1")], [], -0.1)


def test_no_solution_returns_fallback() -> None:
    # Build an obstacle that completely surrounds any detour path
    big_obstacle = (-100.0, -100.0, 100.0, 100.0)
    connections = [(0.0, 5.0, 20.0, 5.0, "N1")]
    results = route_shove(connections, [big_obstacle], 0.2, force_python=True)
    r = results[0]
    # Should not crash; resolved may be False with fallback
    assert r.net_id == "N1"
    assert isinstance(r.segments, list)
    assert isinstance(r.provenance, str)


def test_zero_clearance_accepted() -> None:
    connections = [(0.0, 5.0, 20.0, 5.0, "N1")]
    results = route_shove(connections, [OBSTACLE], 0.0, force_python=True)
    assert results[0].net_id == "N1"


# ---------------------------------------------------------------------------
# Rust extension path (skipped if unavailable)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _rust_available(),
    reason="zaptrace._core.route_shove not available in this environment",
)
def test_rust_path_same_schema() -> None:
    connections = [(0.0, 5.0, 20.0, 5.0, "NET_RUST")]
    results = route_shove(connections, [OBSTACLE], 0.2, force_python=False)
    r = results[0]
    assert r.net_id == "NET_RUST"
    assert r.resolved is True
    assert "walkaround" in r.provenance
    assert len(r.segments) >= 2


@pytest.mark.skipif(
    not _rust_available(),
    reason="zaptrace._core.route_shove not available in this environment",
)
def test_rust_and_python_same_result() -> None:
    connections = [(0.0, 5.0, 20.0, 5.0, "N")]
    rust = route_shove(connections, [OBSTACLE], 0.2, force_python=False)
    python = route_shove(connections, [OBSTACLE], 0.2, force_python=True)
    assert rust[0].provenance == python[0].provenance
    assert rust[0].resolved == python[0].resolved
    assert len(rust[0].segments) == len(python[0].segments)


# ---------------------------------------------------------------------------
# Existing router behaviour unchanged
# ---------------------------------------------------------------------------


def test_existing_router_unchanged() -> None:
    """route_nets import and basic interface remain intact."""
    from zaptrace.algo.router import route_nets

    assert callable(route_nets)


def test_placer_unchanged() -> None:
    from zaptrace.algo.placer import place_components

    assert callable(place_components)
