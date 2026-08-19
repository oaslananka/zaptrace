from __future__ import annotations

import json
from pathlib import Path

from zaptrace.analysis.diffpair import DiffPairCheckStatus, build_diffpair_length_report, write_diffpair_length_report
from zaptrace.core.models import (
    Design,
    DesignMeta,
    Net,
    NetConstraints,
    NetType,
    RouteResult,
    RoutingIntent,
    TraceSegment,
)


def _design_with_lengths(dp_len: float = 10.0, dn_len: float = 10.1, *, routed: bool = True) -> Design:
    design = Design(
        meta=DesignMeta(name="diffpair-length"),
        nets={
            "dp": Net(
                id="dp",
                name="USB_DP",
                type=NetType.DIFFERENTIAL,
                constraints=NetConstraints(length_match_group="usb2", diff_pair_partner="dn"),
            ),
            "dn": Net(
                id="dn",
                name="USB_DN",
                type=NetType.DIFFERENTIAL,
                constraints=NetConstraints(length_match_group="usb2", diff_pair_partner="dp"),
            ),
        },
    )
    design.constraints.routing.append(
        RoutingIntent(net="USB_D*", differential_pair=True, impedance_ohm=90, length_match_mm=0.15)
    )
    if routed:
        design.routing = RouteResult(
            traces=[
                TraceSegment(layer="F.Cu", start=(0, 0), end=(dp_len, 0), net_id="dp"),
                TraceSegment(layer="F.Cu", start=(0, 1), end=(dn_len, 1), net_id="dn"),
            ]
        )
    return design


def test_diffpair_length_report_passes_within_tolerance() -> None:
    report = build_diffpair_length_report(_design_with_lengths(10.0, 10.1))
    entry = report.entries[0]

    assert report.blocked is False
    assert entry.status == DiffPairCheckStatus.PASS
    assert entry.delta_mm == 0.1
    assert entry.tolerance_mm == 0.15
    assert entry.supported_profile is True


def test_diffpair_length_report_blocks_supported_violation() -> None:
    report = build_diffpair_length_report(_design_with_lengths(10.0, 10.4))
    entry = report.entries[0]

    assert report.blocked is True
    assert report.violation_count == 1
    assert entry.status == DiffPairCheckStatus.FAIL
    assert entry.blocking is True
    assert entry.delta_mm == 0.4


def test_diffpair_length_report_blocks_missing_route_evidence() -> None:
    report = build_diffpair_length_report(_design_with_lengths(routed=False))
    entry = report.entries[0]

    assert report.blocked is True
    assert report.missing_route_count == 1
    assert entry.status == DiffPairCheckStatus.MISSING_ROUTE
    assert set(entry.net_ids) == {"dp", "dn"}


def test_write_diffpair_length_report(tmp_path: Path) -> None:
    report = build_diffpair_length_report(_design_with_lengths())
    out = write_diffpair_length_report(report, tmp_path / "diffpair-length.json")
    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.0"
    assert data["pair_count"] == 1
    assert data["entries"][0]["group_name"] == "usb2"
