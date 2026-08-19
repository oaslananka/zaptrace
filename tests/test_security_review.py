"""Tests for hardware security review."""

from __future__ import annotations

from zaptrace.analysis.security_review import hardware_security_policies, security_review
from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode


def _topics(design: Design) -> dict[str, str]:
    return {f.topic: f.severity for f in security_review(design)}


def test_exposed_debug_is_flagged_warning() -> None:
    d = Design(meta=DesignMeta(name="dbg"))
    d.components["u1"] = Component(id="u1", ref="U1", type="esp32")
    d.nets["swd"] = Net(id="swd", name="SWDIO", nodes=[NetNode(component_ref="U1", pin_name="SWDIO")])
    topics = _topics(d)
    assert topics.get("debug-exposure") == "warning"


def test_no_debug_no_exposure_finding() -> None:
    d = Design(meta=DesignMeta(name="nodbg"))
    d.components["u1"] = Component(id="u1", ref="U1", type="esp32")
    assert "debug-exposure" not in _topics(d)


def test_secure_element_present() -> None:
    d = Design(meta=DesignMeta(name="se"))
    d.components["u2"] = Component(id="u2", ref="U2", type="atecc608b")
    findings = {f.topic: f for f in security_review(d)}
    assert "use it for key storage" in findings["secure-element"].recommendation.lower()


def test_no_secure_element_recommends_one() -> None:
    d = Design(meta=DesignMeta(name="nose"))
    d.components["u1"] = Component(id="u1", ref="U1", type="stm32")
    findings = {f.topic: f for f in security_review(d)}
    assert "no secure element" in findings["secure-element"].detail.lower()


def test_mcu_gets_secure_boot_reminder() -> None:
    d = Design(meta=DesignMeta(name="mcu"))
    d.components["u1"] = Component(id="u1", ref="U1", type="rp2040")
    assert "secure-boot" in _topics(d)


def test_findings_serializable() -> None:
    d = Design(meta=DesignMeta(name="x"))
    d.components["u1"] = Component(id="u1", ref="U1", type="mcu")
    data = security_review(d)[0].to_dict()
    assert set(data) == {"topic", "severity", "detail", "recommendation"}


def test_wireless_triggers_attack_surface_warning() -> None:
    d = Design(meta=DesignMeta(name="ble"))
    d.components["u1"] = Component(id="u1", ref="U1", type="nrf52840")
    topics = _topics(d)
    assert "wireless-attack-surface" in topics
    assert topics["wireless-attack-surface"] == "warning"


def test_jtag_pins_trigger_lockout_warning() -> None:
    d = Design(meta=DesignMeta(name="jtag"))
    d.components["u1"] = Component(id="u1", ref="U1", type="stm32")
    d.nets["tck"] = Net(id="tck", name="TCK", nodes=[NetNode(component_ref="U1", pin_name="TCK")])
    topics = _topics(d)
    assert "jtag-lockout" in topics


class TestHardwareSecurityPolicies:
    def test_returns_list(self) -> None:
        policies = hardware_security_policies()
        assert isinstance(policies, list)
        assert len(policies) >= 5

    def test_each_policy_has_required_fields(self) -> None:
        for p in hardware_security_policies():
            assert "policy" in p
            assert "standard" in p
            assert "action" in p
            assert "severity" in p

    def test_debug_disable_is_critical(self) -> None:
        policies = {p["policy"]: p for p in hardware_security_policies()}
        assert policies["debug-disable"]["severity"] == "critical"

    def test_secure_boot_is_present(self) -> None:
        policies = {p["policy"] for p in hardware_security_policies()}
        assert "secure-boot" in policies
