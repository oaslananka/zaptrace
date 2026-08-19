"""Focused regression tests for normalized DFM via validation."""

from __future__ import annotations

from zaptrace.core.models import TraceSegment
from zaptrace.fab.dfm import (
    _legacy_via_measurements,
    _trace_via_measurements,
    _via_dimension_violations,
)


def test_via_dimension_violations_preserve_rule_order_and_messages() -> None:
    violations = _via_dimension_violations(
        diameter=0.25,
        hole=1.25,
        location="GND via#4",
        min_diameter=0.30,
        min_hole=0.15,
        max_hole=1.00,
    )

    assert [(item.rule_id, item.severity) for item in violations] == [
        ("via-diameter-min", "warning"),
        ("via-hole-max", "warning"),
    ]
    assert violations[0].message == "Via diameter 0.250mm below minimum 0.300mm"
    assert violations[0].actual == "0.250mm"
    assert violations[0].expected == ">= 0.300mm"
    assert violations[1].message == "Via hole 1.250mm exceeds maximum 1.000mm"
    assert violations[1].location == "GND via#4"
    assert violations[1].expected == "<= 1.000mm"


def test_via_dimension_violations_report_minimum_hole_as_error() -> None:
    violations = _via_dimension_violations(
        diameter=0.50,
        hole=0.10,
        location="SIG seg#2",
        min_diameter=0.30,
        min_hole=0.15,
        max_hole=1.00,
    )

    assert len(violations) == 1
    assert violations[0].rule_id == "via-hole-min"
    assert violations[0].severity == "error"
    assert violations[0].message == "Via hole 0.100mm below minimum 0.150mm"
    assert violations[0].location == "SIG seg#2"


def test_legacy_via_measurements_preserve_index_and_optional_net_id() -> None:
    assert _legacy_via_measurements(
        [
            (1.0, 2.0, 0.45, 0.20, "VCC"),
            (3.0, 4.0, 0.50, 0.25),
            (9.0, 9.0, 0.20),
        ]
    ) == [
        (0.45, 0.20, "VCC via#0"),
        (0.50, 0.25, "? via#1"),
    ]


def test_trace_via_measurements_include_only_via_segments() -> None:
    traces = [
        TraceSegment(layer="F.Cu", start=(0, 0), end=(1, 0), net_id="N1", via=False),
        TraceSegment(
            layer="F.Cu",
            start=(1, 0),
            end=(2, 0),
            net_id="N2",
            via=True,
            via_diameter=0.40,
            via_hole=0.18,
        ),
        TraceSegment(
            layer="B.Cu",
            start=(2, 0),
            end=(3, 0),
            net_id="",
            via=True,
            via_diameter=0.55,
            via_hole=0.22,
        ),
    ]

    assert _trace_via_measurements(traces) == [
        (0.40, 0.18, "N2 seg#1"),
        (0.55, 0.22, " seg#2"),
    ]
