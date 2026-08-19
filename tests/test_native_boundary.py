"""Mandatory boundary tests for the installed PyO3 extension."""

from __future__ import annotations

import importlib.util
import math
import os

import pytest


def _native_core():
    if importlib.util.find_spec("zaptrace._core") is None:
        if os.environ.get("ZAPTRACE_REQUIRE_NATIVE") == "1":
            pytest.fail(
                "ZAPTRACE_REQUIRE_NATIVE=1 but zaptrace._core is not installed",
                pytrace=False,
            )
        pytest.skip("Rust extension not installed in this source-only test environment")

    import zaptrace._core as core  # type: ignore[import-not-found]

    return core


def test_native_boundary_rejects_invalid_values_with_value_error() -> None:
    core = _native_core()

    cases = (
        (core.place_components, (1, math.nan, 80.0, [], 5.0), "width_mm must be finite"),
        (
            core.place_components,
            (2, 100.0, 80.0, [(0, 2)], 5.0),
            "connection index out of bounds",
        ),
        (core.route_mst, ([(0.0, math.inf)],), "point.y must be finite"),
        (core.route_shove, ([], [], math.nan), "clearance must be finite"),
    )

    for function, arguments, message in cases:
        with pytest.raises(ValueError, match=message):
            function(*arguments)


def test_native_boundary_enforces_component_resource_limit() -> None:
    core = _native_core()

    with pytest.raises(ValueError, match="components count 1001 exceeds supported maximum 1000"):
        core.place_components(1001, 100.0, 80.0, [], 5.0)


def test_native_boundary_remains_usable_after_rejected_calls() -> None:
    core = _native_core()

    with pytest.raises(ValueError, match="clearance must be non-negative"):
        core.route_shove([], [], -0.1)

    positions = core.place_components(2, 100.0, 80.0, [(0, 1)], 5.0)
    segments = core.route_mst([(0.0, 0.0), (1.0, 1.0)])

    assert len(positions) == 2
    assert len(segments) == 2


def test_native_boundary_rejects_oversized_sequences_before_extraction() -> None:
    core = _native_core()

    with pytest.raises(ValueError, match="mst_points count 2001 exceeds supported maximum 2000"):
        core.route_mst([object()] * 2001)

    with pytest.raises(
        ValueError,
        match="placement_connections count 10001 exceeds supported maximum 10000",
    ):
        core.place_components(1, 100.0, 80.0, [object()] * 10001, 5.0)

    with pytest.raises(
        ValueError,
        match="shove_connections count 10001 exceeds supported maximum 10000",
    ):
        core.route_shove([object()] * 10001, [], 0.2)

    with pytest.raises(
        ValueError,
        match="shove_obstacles count 2001 exceeds supported maximum 2000",
    ):
        core.route_shove([], [object()] * 2001, 0.2)


def test_native_boundary_rejects_extreme_finite_overflow() -> None:
    core = _native_core()

    with pytest.raises(ValueError, match="detour_y must be finite"):
        core.route_shove(
            [(0.0, 0.0, 30.0, 10.0, "N")],
            [(10.0, -1.0, 20.0, 1e308)],
            1e308,
        )
