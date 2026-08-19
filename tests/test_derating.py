from __future__ import annotations

from zaptrace.analysis.derating import DeratingPolicy, DeratingStatus, evaluate_component_derating
from zaptrace.core.models import Component, Design, DesignMeta


def _design() -> Design:
    return Design(
        meta=DesignMeta(name="derating"),
        components={
            "c1": Component(
                id="c1",
                ref="C1",
                type="capacitor",
                voltage_rating=10.0,
                voltage_supply="3.3V",
                properties={"rated_power_w": 0.25, "power_w": 0.05},
            ),
            "u1": Component(
                id="u1",
                ref="U1",
                type="regulator",
                voltage_rating=6.0,
                current_rating=0.5,
                properties={"operating_voltage_v": 5.5, "operating_current_a": 0.45},
            ),
        },
    )


def test_derating_policy_flags_voltage_and_current_overuse() -> None:
    report = evaluate_component_derating(_design())
    failed = [finding for finding in report.findings if finding.status == DeratingStatus.FAIL]

    assert report.blocked is True
    assert {finding.metric for finding in failed} == {"voltage", "current"}
    assert all(finding.component_ref == "U1" for finding in failed)


def test_derating_policy_is_configurable() -> None:
    report = evaluate_component_derating(
        _design(),
        DeratingPolicy(voltage_utilization_max=1.0, current_utilization_max=1.0, power_utilization_max=1.0),
    )

    assert report.blocked is False
    assert all(finding.status == DeratingStatus.PASS for finding in report.findings)


def test_derating_policy_can_require_operating_values() -> None:
    design = Design(
        meta=DesignMeta(name="missing-used"),
        components={"r1": Component(id="r1", ref="R1", type="resistor", voltage_rating=50.0)},
    )

    report = evaluate_component_derating(design, DeratingPolicy(require_operating_values=True))

    assert report.blocked is False
    assert report.findings[0].status == DeratingStatus.WARNING
    assert report.findings[0].metric == "voltage"


def test_derating_report_is_machine_readable() -> None:
    payload = evaluate_component_derating(_design()).model_dump(mode="json")

    assert payload["schema_version"] == "1.0"
    assert payload["policy"]["voltage_utilization_max"] == 0.8
    assert payload["finding_count"] >= 1
