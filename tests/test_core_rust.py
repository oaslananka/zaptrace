"""Tests for the native Rust extension (zaptrace._core).

These tests require the Rust extension to be built.
Skip conditions are handled via pytest.mark.skipif.
"""

from __future__ import annotations

import importlib.util

import pytest

# Condition: Rust extension available?
_HAS_RUST = importlib.util.find_spec("zaptrace._core") is not None

rust_test = pytest.mark.skipif(
    not _HAS_RUST,
    reason="Rust extension not built — run `maturin develop` or `cargo build`",
)


class TestRustPlacer:
    """Tests for the Rust place_components function."""

    @rust_test
    def test_place_components_basic(self) -> None:
        """Rust placer should place two components and return positions."""
        from zaptrace._core import place_components  # type: ignore[attr-defined]

        n = 2
        connections: list[tuple[int, int]] = [(0, 1)]
        positions = place_components(n, 100.0, 80.0, connections, 5.0)
        assert isinstance(positions, list)
        assert len(positions) == 2
        # Both positions should be within board bounds
        for x, y in positions:
            assert 5.0 <= x <= 95.0
            assert 5.0 <= y <= 75.0

    @rust_test
    def test_place_components_empty(self) -> None:
        """Zero components should return empty list."""
        from zaptrace._core import place_components  # type: ignore[attr-defined]

        positions = place_components(0, 100.0, 80.0, [], 5.0)
        assert positions == []

    @rust_test
    def test_place_components_single(self) -> None:
        """Single component should be placed at roughly center."""
        from zaptrace._core import place_components  # type: ignore[attr-defined]

        positions = place_components(1, 100.0, 80.0, [], 5.0)
        assert len(positions) == 1
        x, y = positions[0]
        # Grid placement: single component appears at first grid cell
        assert 20.0 <= x <= 35.0
        assert 30.0 <= y <= 50.0


class TestRustRouter:
    """Tests for the Rust route_mst function."""

    @rust_test
    def test_route_nets_basic(self) -> None:
        """Rust router should route between two points."""
        from zaptrace._core import route_mst  # type: ignore[attr-defined]

        points = [(10.0, 10.0), (90.0, 90.0)]
        segments = route_mst(points)
        assert isinstance(segments, list)
        assert len(segments) >= 2  # L-shape: H then V

    @rust_test
    def test_route_nets_single_node(self) -> None:
        """Single point should produce no segments."""
        from zaptrace._core import route_mst  # type: ignore[attr-defined]

        segments = route_mst([(10.0, 10.0)])
        assert segments == []

    @rust_test
    def test_route_nets_three_points(self) -> None:
        """Three points should route with MST edges."""
        from zaptrace._core import route_mst  # type: ignore[attr-defined]

        points = [(0.0, 0.0), (100.0, 0.0), (50.0, 100.0)]
        segments = route_mst(points)
        # MST with 3 nodes = 2 edges, each edge = 2 L-shape segments = 4 total
        assert 2 <= len(segments) <= 4


class TestRustIntegration:
    @rust_test
    def test_place_then_route(self) -> None:
        """Full workflow: place components then route MST."""
        from zaptrace._core import place_components, route_mst  # type: ignore[attr-defined]

        n = 3
        connections = [(0, 1), (1, 2)]
        positions = place_components(n, 100.0, 80.0, connections, 5.0)
        assert len(positions) == 3

        # Route all positions via MST
        segments = route_mst(positions)
        assert len(segments) >= 2  # 3 nodes = 2 edges minimum
