from __future__ import annotations

from zaptrace.analysis.sipi_risk import SipiRiskStatus, build_sipi_risk_report
from zaptrace.core.models import Component, Design, DesignMeta, Net, NetConstraints, NetNode, NetType


def test_sipi_risk_report_requires_review_for_unsupported_high_speed_net() -> None:
    design = Design(
        meta=DesignMeta(name="sipi"),
        nets={"usb": Net(id="usb", name="USB_DP", type=NetType.SIGNAL)},
    )

    report = build_sipi_risk_report(design)

    assert report.high_speed_net_count == 1
    assert report.unsupported_high_speed_count == 1
    assert report.human_review_required is True
    assert any(item.category == "high_speed_support" for item in report.findings)


def test_sipi_risk_report_covers_impedance_return_path_and_decoupling() -> None:
    design = Design(
        meta=DesignMeta(name="sipi"),
        components={"u1": Component(id="u1", ref="U1", type="mcu", value="MCU")},
        nets={
            "hs": Net(
                id="hs",
                name="HS_DATA",
                type=NetType.SIGNAL,
                constraints=NetConstraints(impedance_target=50.0),
            ),
            "vdd": Net(
                id="vdd",
                name="VDD_3V3",
                type=NetType.POWER,
                nodes=[NetNode(component_ref="U1", pin_name="VDD")],
            ),
        },
    )

    report = build_sipi_risk_report(design)
    categories = {finding.category for finding in report.findings}

    assert report.impedance_assumption_count == 1
    assert report.return_path_diagnostic_count == 1
    assert report.decoupling_issue_count == 1
    assert report.human_review_required is True
    assert {"return_path", "decoupling"} <= categories
    assert any(finding.status == SipiRiskStatus.HUMAN_REVIEW_REQUIRED for finding in report.findings)


def test_sipi_risk_report_passes_clean_basic_design() -> None:
    design = Design(
        meta=DesignMeta(name="sipi"),
        components={"c1": Component(id="c1", ref="C1", type="capacitor", value="100nF")},
        nets={
            "vdd": Net(
                id="vdd",
                name="VDD_3V3",
                type=NetType.POWER,
                nodes=[NetNode(component_ref="C1", pin_name="1")],
            )
        },
    )

    report = build_sipi_risk_report(design)

    assert report.blocked is False
    assert report.human_review_required is False
    assert report.decoupling_issue_count == 0
    assert report.high_speed_net_count == 0
