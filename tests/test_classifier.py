"""Tests for the netlist classifier."""

from __future__ import annotations

from zaptrace.core.models import (
    Component,
    Design,
    DesignMeta,
    Net,
    NetClass,
    NetNode,
    Pin,
    PinType,
)
from zaptrace.ee.classifier import (
    classify_design,
    get_net_class,
    summarize_classification,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _design(nets: dict[str, Net], comps: dict[str, Component] | None = None) -> Design:
    return Design(
        meta=DesignMeta(name="test"),
        components=comps or {},
        nets=nets,
    )


def _net(name: str, *nodes: NetNode) -> Net:
    return Net(id=name.lower().replace(" ", "_"), name=name, nodes=list(nodes))


def _node(ref: str, pin: str) -> NetNode:
    return NetNode(component_ref=ref, pin_name=pin)


def _comp(ref: str, type_: str = "resistor", pins: dict[str, Pin] | None = None) -> Component:
    return Component(id=ref.lower(), ref=ref, type=type_, pins=pins or {})


def _pin(name: str, type_: PinType = PinType.PASSIVE) -> Pin:
    return Pin(name=name, type=type_)


# ---------------------------------------------------------------------------
# Name-based classification
# ---------------------------------------------------------------------------


class TestNameBased:
    def test_ground_vcc(self) -> None:
        d = _design({"gnd": _net("GND"), "vcc": _net("VCC")})
        classify_design(d)
        assert d.net_classes["gnd"] == NetClass.GROUND
        assert d.net_classes["vcc"] == NetClass.POWER_MED

    def test_power_by_voltage(self) -> None:
        d = _design({"v3": _net("3V3"), "v5": _net("5V"), "v12": _net("12V")})
        classify_design(d)
        assert d.net_classes["v3"] == NetClass.POWER_MED
        assert d.net_classes["v5"] == NetClass.POWER_MED
        assert d.net_classes["v12"] == NetClass.POWER_HIGH

    def test_ground_variants(self) -> None:
        d = _design(
            {
                "agnd": _net("AGND"),
                "dgnd": _net("DGND"),
                "pgnd": _net("PGND"),
                "vss": _net("VSS"),
            }
        )
        classify_design(d)
        for k in ("agnd", "dgnd", "pgnd", "vss"):
            assert d.net_classes[k] == NetClass.GROUND, f"{k} should be GROUND"

    def test_differential_usb(self) -> None:
        d = _design(
            {
                "usb_dp": _net("USB_DP"),
                "usb_dm": _net("USB_DM"),
            }
        )
        classify_design(d)
        assert d.net_classes["usb_dp"] == NetClass.DIFFERENTIAL
        assert d.net_classes["usb_dm"] == NetClass.DIFFERENTIAL

    def test_i2c(self) -> None:
        d = _design({"sda": _net("SDA"), "scl": _net("SCL")})
        classify_design(d)
        assert d.net_classes["sda"] == NetClass.SIGNAL_LOW
        assert d.net_classes["scl"] == NetClass.SIGNAL_LOW

    def test_spi(self) -> None:
        d = _design(
            {
                "mosi": _net("MOSI"),
                "miso": _net("MISO"),
                "sck": _net("SCK"),
            }
        )
        classify_design(d)
        for k in ("mosi", "miso", "sck"):
            assert d.net_classes[k] == NetClass.SIGNAL_LOW

    def test_uart(self) -> None:
        d = _design({"tx": _net("TX"), "rx": _net("RX")})
        classify_design(d)
        assert d.net_classes["tx"] == NetClass.SIGNAL_LOW
        assert d.net_classes["rx"] == NetClass.SIGNAL_LOW

    def test_analog(self) -> None:
        d = _design(
            {
                "adc1": _net("ADC1"),
                "vref": _net("VREF"),
            }
        )
        classify_design(d)
        assert d.net_classes["adc1"] == NetClass.SIGNAL_ANALOG
        assert d.net_classes["vref"] == NetClass.POWER_LOW

    def test_rf(self) -> None:
        d = _design({"ant": _net("ANT")})
        classify_design(d)
        assert d.net_classes["ant"] == NetClass.RF

    def test_high_speed_ethernet(self) -> None:
        d = _design(
            {
                "eth_tx": _net("ETH_TX"),
                "rmii_ref": _net("RMII_REF_CLK"),
            }
        )
        classify_design(d)
        assert d.net_classes["eth_tx"] == NetClass.SIGNAL_HIGH
        assert d.net_classes["rmii_ref"] == NetClass.SIGNAL_HIGH

    def test_clock(self) -> None:
        d = _design({"clk": _net("CLK"), "sys_clk": _net("SYS_CLK")})
        classify_design(d)
        assert d.net_classes["clk"] == NetClass.SIGNAL_HIGH
        assert d.net_classes["sys_clk"] == NetClass.SIGNAL_HIGH

    def test_battery(self) -> None:
        d = _design({"vbat": _net("VBAT")})
        classify_design(d)
        assert d.net_classes["vbat"] == NetClass.POWER_MED

    def test_unknown_signal(self) -> None:
        d = _design({"gpio1": _net("GPIO1"), "btn": _net("BUTTON")})
        classify_design(d)
        assert d.net_classes["gpio1"] == NetClass.SIGNAL_LOW
        assert d.net_classes["btn"] == NetClass.SIGNAL_LOW


# ---------------------------------------------------------------------------
# Pin-type fallback
# ---------------------------------------------------------------------------


class TestPinTypeFallback:
    def test_power_pin_on_net(self) -> None:
        comp = _comp("U1", "regulator", pins={"out": _pin("OUT", PinType.POWER)})
        d = _design(
            {"vout": _net("VOUT", _node("U1", "out"))},
            comps={"u1": comp},
        )
        classify_design(d)
        assert d.net_classes["vout"] == NetClass.POWER_MED

    def test_usb_connector_component(self) -> None:
        comp = _comp(
            "J1",
            "usb-c",
            pins={
                "dp": _pin("DP", PinType.PASSIVE),
                "dm": _pin("DM", PinType.PASSIVE),
            },
        )
        d = _design(
            {"usb_dp": _net("USB_DP", _node("J1", "dp"))},
            comps={"j1": comp},
        )
        classify_design(d)
        assert d.net_classes["usb_dp"] == NetClass.DIFFERENTIAL

    def test_antenna_component(self) -> None:
        comp = _comp("ANT1", "antenna")
        d = _design(
            {"rf_in": _net("RF_IN", _node("ANT1", "p1"))},
            comps={"ant1": comp},
        )
        classify_design(d)
        assert d.net_classes["rf_in"] == NetClass.RF

    def test_adc_component(self) -> None:
        comp = _comp("U1", "adc", pins={"in": _pin("IN", PinType.INPUT)})
        d = _design(
            {"sensor": _net("SENSOR_OUT", _node("U1", "in"))},
            comps={"u1": comp},
        )
        classify_design(d)
        assert d.net_classes["sensor"] == NetClass.SIGNAL_ANALOG  # by component type

    def test_empty_net_no_nodes(self) -> None:
        d = _design({"floating": _net("FLOATING")})
        classify_design(d)
        assert d.net_classes["floating"] == NetClass.SIGNAL_LOW


# ---------------------------------------------------------------------------
# Preserve manual classification
# ---------------------------------------------------------------------------


class TestPreserveManual:
    def test_existing_classification_not_overwritten(self) -> None:
        d = _design({"vcc": _net("VCC"), "gnd": _net("GND")})
        d.net_classes = {"vcc": NetClass.POWER_HIGH}  # manual override
        classify_design(d)
        assert d.net_classes["vcc"] == NetClass.POWER_HIGH  # preserved
        assert d.net_classes["gnd"] == NetClass.GROUND  # auto-classified


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_get_net_class(self) -> None:
        d = _design({"gnd": _net("GND")})
        assert get_net_class(d, "gnd") == NetClass.GROUND

    def test_get_net_class_missing(self) -> None:
        d = _design({"n1": _net("N1")})
        assert get_net_class(d, "n1") == NetClass.SIGNAL_LOW

    def test_get_net_class_runs_classify(self) -> None:
        d = _design({"vcc": _net("VCC")})
        assert d.net_classes is None
        _ = get_net_class(d, "vcc")
        assert d.net_classes is not None

    def test_summarize(self) -> None:
        d = _design(
            {
                "vcc": _net("VCC"),
                "gnd": _net("GND"),
            }
        )
        summary = summarize_classification(d)
        assert "ground" in summary
        assert "power_med" in summary
        assert "GND" in summary["ground"]
        assert "VCC" in summary["power_med"]


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


class TestIdempotence:
    def test_classify_twice_same(self) -> None:
        d = _design({"gnd": _net("GND"), "vcc": _net("VCC")})
        classify_design(d)
        first = dict(d.net_classes or {})
        classify_design(d)
        assert dict(d.net_classes or {}) == first
