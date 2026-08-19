from __future__ import annotations

from zaptrace.analysis.current_density import CurrentDensityStatus, build_current_density_report
from zaptrace.core.models import Design, DesignMeta, Net, NetConstraints, NetType, RouteResult, TraceSegment


def _design_with_trace(width: float | None = 0.2) -> Design:
    design = Design(
        meta=DesignMeta(name="current-density"),
        nets={
            "motor": Net(
                id="motor",
                name="MOTOR_12V",
                type=NetType.POWER,
                constraints=NetConstraints(is_high_current=True, min_trace_width_mm=0.8),
            )
        },
    )
    if width is not None:
        design.routing = RouteResult(
            traces=[TraceSegment(layer="F.Cu", start=(0, 0), end=(10, 0), width=width, net_id="motor")]
        )
    return design


def test_current_density_report_passes_wide_trace() -> None:
    report = build_current_density_report(_design_with_trace(width=1.0))
    entry = report.traces[0]

    assert report.high_current_net_count == 1
    assert report.blocked is False
    assert entry.status == CurrentDensityStatus.PASS
    assert entry.required_width_mm == 0.8
    assert entry.margin_mm == 0.2


def test_current_density_report_blocks_narrow_trace() -> None:
    report = build_current_density_report(_design_with_trace(width=0.2))
    entry = report.traces[0]

    assert report.blocked is True
    assert report.violation_count == 1
    assert entry.status == CurrentDensityStatus.FAIL
    assert entry.margin_mm == -0.6


def test_current_density_report_requires_review_for_missing_route() -> None:
    report = build_current_density_report(_design_with_trace(width=None))

    assert report.blocked is False
    assert report.human_review_required is True
    assert report.missing_route_count == 1
    assert report.missing_route_nets == ["motor"]


def test_current_density_report_uses_default_current_for_high_current_non_rail() -> None:
    design = Design(
        meta=DesignMeta(name="current-density-signal"),
        nets={
            "heater": Net(
                id="heater",
                name="HEATER_PWM",
                type=NetType.SIGNAL,
                constraints=NetConstraints(is_high_current=True),
            )
        },
        routing=RouteResult(traces=[TraceSegment(layer="F.Cu", start=(0, 0), end=(5, 0), width=2.0, net_id="heater")]),
    )

    report = build_current_density_report(design)

    assert report.traces[0].current_a == 1.0
    assert report.assumptions
