"""Tests for ERC rules and runner."""

from __future__ import annotations

from zaptrace.core.models import (
    Component,
    Design,
    DesignMeta,
    Net,
    NetNode,
    NetType,
    Pin,
)
from zaptrace.erc import rules
from zaptrace.erc.models import ERCSeverity
from zaptrace.erc.runner import ERCRunner


def _empty_design() -> Design:
    return Design(meta=DesignMeta(name="test"))


def _design_with(comps: list[Component] | None = None, nets: list[Net] | None = None) -> Design:
    d = _empty_design()
    if comps:
        for c in comps:
            d.components[c.id] = c
    if nets:
        for n in nets:
            d.nets[n.id] = n
    return d


class TestRules:
    def test_erc001_no_power(self) -> None:
        """ERC001: no power pins on any component."""
        d = _design_with(
            comps=[
                Component(
                    id="u1",
                    ref="U1",
                    type="mcu",
                    pins={
                        "VCC": Pin(name="VCC", type="power"),
                    },
                ),
            ],
        )
        violations = rules.rule_ERC001(d)
        assert len(violations) >= 1
        assert violations[0].rule_id == "ERC001"

    def test_erc001_with_power_net_ok(self) -> None:
        """ERC001: power pin connected to power net — no violation."""
        d = _design_with(
            comps=[
                Component(
                    id="u1",
                    ref="U1",
                    type="mcu",
                    pins={
                        "VCC": Pin(name="VCC", type="power", net="VCC"),
                    },
                ),
            ],
            nets=[
                Net(id="n1", name="VCC", type=NetType.POWER),
            ],
        )
        violations = rules.rule_ERC001(d)
        # VCC pin is connected to VCC net — no violation
        [v for v in violations if v.severity == ERCSeverity.ERROR]
        assert sum(1 for v in violations if v.rule_id == "ERC001") == 0

    def test_erc002_unconnected_input(self) -> None:
        d = _design_with(
            comps=[
                Component(
                    id="u1",
                    ref="U1",
                    type="mcu",
                    pins={
                        "EN": Pin(name="EN", type="input"),
                    },
                ),
            ],
        )
        violations = rules.rule_ERC002(d)
        assert any(v.rule_id == "ERC002" for v in violations)

    def test_erc003_decap_ok(self) -> None:
        """ERC003: IC on power net with decoupling cap — no violation."""
        d = _design_with(
            comps=[
                Component(
                    id="u1",
                    ref="U1",
                    type="ESP32-WROOM-32",
                    pins={
                        "VCC": Pin(name="VCC", type="power", net="VCC"),
                    },
                ),
                Component(id="c1", ref="C1", type="CAP", value="100nF"),
            ],
            nets=[Net(id="n1", name="VCC", type=NetType.POWER)],
        )
        violations = rules.rule_ERC003(d)
        assert sum(1 for v in violations if v.rule_id == "ERC003") == 0

    def test_erc003_missing_decap(self) -> None:
        """ERC003: IC on power net missing decoupling cap."""
        d = _design_with(
            comps=[
                Component(
                    id="u1",
                    ref="U1",
                    type="ESP32-WROOM-32",
                    pins={
                        "VCC": Pin(name="VCC", type="power", net="VCC"),
                    },
                ),
            ],
            nets=[Net(id="n1", name="VCC", type=NetType.POWER)],
        )
        violations = rules.rule_ERC003(d)
        assert any(v.rule_id == "ERC003" for v in violations)

    def test_erc003_generalized_ic_detection(self) -> None:
        """ERC003: an IC outside the old whitelist is still checked (structural detection)."""
        d = _design_with(
            comps=[
                Component(
                    id="u1",
                    ref="U1",
                    type="AP2112K-3.3",  # a real LDO, never in the old hardcoded whitelist
                    pins={"VIN": Pin(name="VIN", type="power")},
                ),
            ],
        )
        violations = rules.rule_ERC003(d)
        assert any(v.rule_id == "ERC003" for v in violations)

    def test_erc003_passive_is_not_treated_as_ic(self) -> None:
        """ERC003: a passive (no power pin) is never flagged as needing decoupling."""
        d = _design_with(
            comps=[
                Component(
                    id="r1",
                    ref="R1",
                    type="resistor",
                    pins={"p1": Pin(name="p1", type="passive"), "p2": Pin(name="p2", type="passive")},
                ),
            ],
        )
        assert sum(1 for v in rules.rule_ERC003(d) if v.rule_id == "ERC003") == 0

    def test_erc003_net_ownership_requires_cap_to_ground(self) -> None:
        """ERC003: a wired power net needs a capacitor bridging it to ground."""
        u1 = Component(id="u1", ref="U1", type="some-mcu", pins={"VCC": Pin(name="VCC", type="power")})
        cap = Component(
            id="c1",
            ref="C1",
            type="CAP",
            value="100nF",
            pins={"p1": Pin(name="p1", type="passive"), "p2": Pin(name="p2", type="passive")},
        )
        vcc = Net(
            id="vcc",
            name="VCC",
            type=NetType.POWER,
            nodes=[NetNode(component_ref="U1", pin_name="VCC"), NetNode(component_ref="C1", pin_name="p1")],
        )
        # Cap bridges VCC <-> GND: decoupling is owned, no violation.
        gnd = Net(id="gnd", name="GND", type=NetType.GROUND, nodes=[NetNode(component_ref="C1", pin_name="p2")])
        d_ok = _design_with(comps=[u1, cap], nets=[vcc, gnd])
        assert sum(1 for v in rules.rule_ERC003(d_ok) if v.rule_id == "ERC003") == 0
        # Same cap with no ground connection: it no longer counts as decoupling.
        gnd_empty = Net(id="gnd", name="GND", type=NetType.GROUND, nodes=[])
        d_bad = _design_with(comps=[u1, cap], nets=[vcc, gnd_empty])
        assert any(v.rule_id == "ERC003" for v in rules.rule_ERC003(d_bad))

    def test_erc004_duplicate_net_names(self) -> None:
        """ERC004: duplicate net names detected."""
        d = _design_with(
            nets=[
                Net(id="n1", name="DUPE"),
                Net(id="n2", name="DUPE"),
            ],
        )
        violations = rules.rule_ERC004(d)
        assert any(v.rule_id == "ERC004" for v in violations)

    def test_erc005_i2c_pullup_missing(self) -> None:
        """ERC005: I2C net with no pull-up resistor."""
        d = _design_with(
            nets=[Net(id="n1", name="I2C_SDA", nodes=[NetNode(component_ref="U1", pin_name="SDA")])],
        )
        violations = rules.rule_ERC005(d)
        assert any(v.rule_id == "ERC005" for v in violations)

    def test_erc006_mosi_mosi_connection(self) -> None:
        """ERC006: SPI MOSI connected to MOSI (should be MOSI-MISO)."""
        d = _design_with(
            nets=[
                Net(
                    id="n1",
                    name="SPI_MOSI",
                    nodes=[
                        NetNode(component_ref="U1", pin_name="MOSI"),
                        NetNode(component_ref="U2", pin_name="MOSI"),
                    ],
                )
            ],
        )
        violations = rules.rule_ERC006(d)
        assert any(v.rule_id == "ERC006" for v in violations)

    def test_erc007_power_net_no_driver(self) -> None:
        """ERC007: power net with no driving output pin."""
        d = _design_with(
            comps=[
                Component(
                    id="u1",
                    ref="U1",
                    type="mcu",
                    pins={
                        "VCC": Pin(name="VCC", type="power", net="VCC"),
                    },
                )
            ],
            nets=[
                Net(
                    id="n1",
                    name="VCC",
                    type=NetType.POWER,
                    nodes=[
                        NetNode(component_ref="U1", pin_name="VCC"),
                    ],
                )
            ],
        )
        violations = rules.rule_ERC007(d)
        assert any(v.rule_id == "ERC007" for v in violations)

    def test_erc007_usb_c_input_counts_as_power_source(self) -> None:
        d = _design_with(
            comps=[
                Component(
                    id="j1",
                    ref="J1",
                    type="USB-C-16P",
                    pins={"VBUS": Pin(name="VBUS", type="power", net="VBUS")},
                )
            ],
            nets=[
                Net(id="vbus", name="VBUS", type=NetType.POWER, nodes=[NetNode(component_ref="J1", pin_name="VBUS")])
            ],
        )

        assert rules.rule_ERC007(d) == []

    def test_erc009_tx_tx_connection(self) -> None:
        """ERC009: UART TX connected to TX (should be TX-RX)."""
        d = _design_with(
            nets=[
                Net(
                    id="n1",
                    name="UART_TX",
                    nodes=[
                        NetNode(component_ref="U1", pin_name="TX"),
                        NetNode(component_ref="U2", pin_name="TX"),
                    ],
                )
            ],
        )
        violations = rules.rule_ERC009(d)
        assert any(v.rule_id == "ERC009" for v in violations)

    def test_erc011_usb_no_esd(self) -> None:
        """ERC011: USB component with no ESD protection."""
        d = _design_with(
            comps=[Component(id="j1", ref="J1", type="usb-c")],
        )
        violations = rules.rule_ERC011(d)
        assert any(v.rule_id == "ERC011" for v in violations)

    def test_erc012_single_node_net(self) -> None:
        """ERC012: nets with fewer than 2 connected pins."""
        d = _design_with(
            nets=[Net(id="n1", name="SOLO", nodes=[NetNode(component_ref="U1", pin_name="pin1")])],
        )
        violations = rules.rule_ERC012(d)
        assert any(v.rule_id == "ERC012" for v in violations)

    def test_erc014_detects_voltage_mismatch_by_component_ref(self) -> None:
        d = _design_with(
            comps=[
                Component(id="u1", ref="U1", type="mcu", voltage_supply="3.3"),
                Component(id="u2", ref="U2", type="mcu", voltage_supply="5.0"),
            ],
            nets=[
                Net(
                    id="vcc",
                    name="VCC",
                    type=NetType.POWER,
                    nodes=[
                        NetNode(component_ref="U1", pin_name="VCC"),
                        NetNode(component_ref="U2", pin_name="VCC"),
                    ],
                )
            ],
        )
        assert any(v.rule_id == "ERC014" for v in rules.rule_ERC014(d))

    def test_erc016_reset_no_pullup(self) -> None:
        """ERC016: reset pin with no external pull-up."""
        d = _design_with(
            comps=[
                Component(
                    id="u1",
                    ref="U1",
                    type="mcu",
                    pins={
                        "NRST": Pin(name="NRST", type="input", net="RST"),
                    },
                )
            ],
            nets=[Net(id="n1", name="RST", nodes=[NetNode(component_ref="U1", pin_name="NRST")])],
        )
        violations = rules.rule_ERC016(d)
        assert any(v.rule_id == "ERC016" for v in violations)


class TestDeeperRules:
    def test_erc021_usbc_cc_missing_termination(self) -> None:
        d = _design_with(
            comps=[
                Component(id="j1", ref="J1", type="usb-c-receptacle", pins={"CC1": Pin(name="CC1", type="passive")}),
            ],
            nets=[Net(id="cc", name="CC1", nodes=[NetNode(component_ref="J1", pin_name="CC1")])],
        )
        assert any(v.rule_id == "ERC021" for v in rules.rule_ERC021(d))

    def test_erc021_usbc_cc_with_rd_ok(self) -> None:
        d = _design_with(
            comps=[
                Component(id="j1", ref="J1", type="usb-c-receptacle", pins={"CC1": Pin(name="CC1", type="passive")}),
                Component(
                    id="r1",
                    ref="R1",
                    type="RES",
                    value="5.1k",
                    pins={"P1": Pin(name="P1", type="passive"), "P2": Pin(name="P2", type="passive")},
                ),
            ],
            nets=[
                Net(
                    id="cc",
                    name="CC1",
                    nodes=[NetNode(component_ref="J1", pin_name="CC1"), NetNode(component_ref="R1", pin_name="P1")],
                ),
                Net(
                    id="gnd",
                    name="GND",
                    type=NetType.GROUND,
                    nodes=[NetNode(component_ref="R1", pin_name="P2")],
                ),
            ],
        )
        assert not [v for v in rules.rule_ERC021(d) if v.rule_id == "ERC021"]

    def test_erc022_spi_cs_missing_pullup(self) -> None:
        d = _design_with(
            nets=[Net(id="cs", name="SPI_CS", nodes=[NetNode(component_ref="U1", pin_name="CS")])],
        )
        assert any(v.rule_id == "ERC022" for v in rules.rule_ERC022(d))

    def test_erc022_spi_cs_with_pullup_ok(self) -> None:
        d = _design_with(
            comps=[
                Component(
                    id="r1",
                    ref="R1",
                    type="RES",
                    value="10k",
                    pins={"P1": Pin(name="P1", type="passive"), "P2": Pin(name="P2", type="passive")},
                ),
            ],
            nets=[
                Net(
                    id="cs",
                    name="SPI_CS",
                    nodes=[NetNode(component_ref="U1", pin_name="CS"), NetNode(component_ref="R1", pin_name="P1")],
                ),
                Net(
                    id="vcc",
                    name="VCC",
                    type=NetType.POWER,
                    nodes=[NetNode(component_ref="R1", pin_name="P2")],
                ),
            ],
        )
        assert not [v for v in rules.rule_ERC022(d) if v.rule_id == "ERC022"]


class TestERC014VoltageDomain:
    """ERC014 must catch any two distinct supply voltages on a power net, not just 3.3/5."""

    def _power_net(self, *voltages: str) -> Design:
        comps = []
        nodes = []
        for i, v in enumerate(voltages):
            ref = f"U{i + 1}"
            comps.append(Component(id=ref.lower(), ref=ref, type="ic", voltage_supply=v))
            nodes.append(NetNode(component_ref=ref, pin_name="VCC"))
        net = Net(id="P", name="VRAIL", type=NetType.POWER, nodes=nodes)
        return _design_with(comps=comps, nets=[net])

    def test_classic_3v3_5v_mismatch(self) -> None:
        assert any(v.rule_id == "ERC014" for v in rules.rule_ERC014(self._power_net("3.3", "5.0")))

    def test_non_hardcoded_pair_is_caught(self) -> None:
        # 1.8 V vs 3.3 V — the old hardcoded check missed this entirely.
        assert any(v.rule_id == "ERC014" for v in rules.rule_ERC014(self._power_net("1.8", "3.3")))

    def test_same_voltage_different_spelling_is_clean(self) -> None:
        # "5" and "5.0" are the same domain — not a mismatch.
        assert not any(v.rule_id == "ERC014" for v in rules.rule_ERC014(self._power_net("5", "5.0")))

    def test_v_notation_is_parsed(self) -> None:
        # "3V3" and "5V" parse to 3.3 and 5.0 → mismatch.
        assert any(v.rule_id == "ERC014" for v in rules.rule_ERC014(self._power_net("3V3", "5V")))

    def test_single_domain_is_clean(self) -> None:
        assert not any(v.rule_id == "ERC014" for v in rules.rule_ERC014(self._power_net("3.3", "3.3")))

    def test_unparseable_voltage_ignored(self) -> None:
        # A blank/garbage voltage_supply must not register as a domain.
        assert not any(v.rule_id == "ERC014" for v in rules.rule_ERC014(self._power_net("3.3", "")))
        # A non-empty but unparseable value is also ignored (not a second domain).
        assert not any(v.rule_id == "ERC014" for v in rules.rule_ERC014(self._power_net("3.3", "n/a")))

    def test_missing_component_reference_is_skipped(self) -> None:
        # A net node pointing at a non-existent component must not crash the rule.
        design = self._power_net("3.3")
        design.nets["P"].nodes.append(NetNode(component_ref="GHOST", pin_name="VCC"))
        assert not any(v.rule_id == "ERC014" for v in rules.rule_ERC014(design))

    def test_voltage_parser_values(self) -> None:
        parse = rules._parse_supply_voltage
        assert parse("3.3") == 3.3
        assert parse("5") == parse("5.0") == 5.0
        assert parse("3V3") == 3.3
        assert parse("5V") == 5.0
        assert parse("") is None
        assert parse("garbage") is None


class TestERC023NoConnect:
    """ERC023: a no-connect pin must be left floating, not wired to other pins."""

    def _design(self, *, wire_nc: bool) -> Design:
        mcu = Component(
            id="u1",
            ref="U1",
            type="ic",
            pins={
                "NC": Pin(name="NC", type="no_connect", net="SIG" if wire_nc else None),
                "OUT": Pin(name="OUT", type="output", net="SIG2"),
            },
        )
        comps = [mcu]
        nets = []
        if wire_nc:
            other = Component(id="u2", ref="U2", type="ic", pins={"IN": Pin(name="IN", type="input", net="SIG")})
            comps.append(other)
            nets.append(
                Net(
                    id="SIG",
                    name="SIG",
                    type=NetType.SIGNAL,
                    nodes=[
                        NetNode(component_ref="U1", pin_name="NC"),
                        NetNode(component_ref="U2", pin_name="IN"),
                    ],
                )
            )
        return _design_with(comps=comps, nets=nets)

    def test_wired_nc_pin_flags(self) -> None:
        result = ERCRunner().run(self._design(wire_nc=True))
        nc_violations = [v for v in result.violations if v.rule_id == "ERC023"]
        assert nc_violations
        assert "U2" in nc_violations[0].message

    def test_floating_nc_pin_passes(self) -> None:
        result = ERCRunner().run(self._design(wire_nc=False))
        assert not any(v.rule_id == "ERC023" for v in result.violations)

    def test_nc_pin_alone_on_net_passes(self) -> None:
        # An NC pin that is the only node on its net is not "wired to" anything.
        mcu = Component(id="u1", ref="U1", type="ic", pins={"NC": Pin(name="NC", type="no_connect", net="NC_NET")})
        net = Net(id="NC_NET", name="NC_NET", type=NetType.SIGNAL, nodes=[NetNode(component_ref="U1", pin_name="NC")])
        result = ERCRunner().run(_design_with(comps=[mcu], nets=[net]))
        assert not any(v.rule_id == "ERC023" for v in result.violations)


class TestERC016ResetHeldHigh:
    """ERC016: a reset pin must be tied to a power rail or pulled up to one."""

    def _design(self, reset_net_type: NetType, *, pullup_to: str | None, r_type: str = "RES") -> Design:
        mcu = Component(id="u1", ref="U1", type="mcu", pins={"NRST": Pin(name="NRST", type="input", net="RST")})
        rst = Net(id="RST", name="RST", type=reset_net_type, nodes=[NetNode(component_ref="U1", pin_name="NRST")])
        vcc = Net(id="VCC", name="VCC", type=NetType.POWER, nodes=[])
        comps = [mcu]
        nets = [rst, vcc]
        if pullup_to is not None:
            res = Component(
                id="r1",
                ref="R1",
                type=r_type,
                value="10k",
                pins={
                    "P1": Pin(name="P1", type="passive", net="RST"),
                    "P2": Pin(name="P2", type="passive", net=pullup_to),
                },
            )
            comps.append(res)
            rst.nodes.append(NetNode(component_ref="R1", pin_name="P1"))
            vcc.nodes.append(NetNode(component_ref="R1", pin_name="P2"))
        return _design_with(comps=comps, nets=nets)

    def test_no_pullup_flags(self) -> None:
        result = ERCRunner().run(self._design(NetType.SIGNAL, pullup_to=None))
        assert any(v.rule_id == "ERC016" for v in result.violations)

    def test_pullup_to_rail_passes(self) -> None:
        result = ERCRunner().run(self._design(NetType.SIGNAL, pullup_to="VCC"))
        assert not any(v.rule_id == "ERC016" for v in result.violations)

    def test_pullup_resistor_typed_r_passes(self) -> None:
        # "R"-typed resistor must count (the old check matched only exact "RES").
        result = ERCRunner().run(self._design(NetType.SIGNAL, pullup_to="VCC", r_type="R"))
        assert not any(v.rule_id == "ERC016" for v in result.violations)

    def test_reset_tied_directly_to_power_passes(self) -> None:
        # Reset held high directly on a power rail needs no pull-up resistor.
        result = ERCRunner().run(self._design(NetType.POWER, pullup_to=None))
        assert not any(v.rule_id == "ERC016" for v in result.violations)


class TestERC008SeriesResistor:
    """ERC008 must count only a resistor *connected to* the LED, not any resistor."""

    def _led_on_power(self, *extra: Component, extra_nets: list[Net] | None = None) -> Design:
        led = Component(
            id="d1",
            ref="D1",
            type="LED",
            pins={
                "ANODE": Pin(name="ANODE", type="passive", net="VCC"),
                "CATHODE": Pin(name="CATHODE", type="passive", net="GND"),
            },
        )
        vcc = Net(
            id="VCC",
            name="VCC",
            type=NetType.POWER,
            nodes=[NetNode(component_ref="D1", pin_name="ANODE")],
        )
        gnd = Net(
            id="GND",
            name="GND",
            type=NetType.GROUND,
            nodes=[NetNode(component_ref="D1", pin_name="CATHODE")],
        )
        return _design_with(comps=[led, *extra], nets=[vcc, gnd, *(extra_nets or [])])

    def test_no_resistor_flags_violation(self) -> None:
        result = ERCRunner().run(self._led_on_power())
        assert any(v.rule_id == "ERC008" for v in result.violations)

    def test_connected_series_resistor_passes(self) -> None:
        series_r = Component(
            id="r1",
            ref="R1",
            type="RES",
            value="330",
            pins={
                "P1": Pin(name="P1", type="passive", net="VCC"),
                "P2": Pin(name="P2", type="passive", net="GND"),
            },
        )
        design = self._led_on_power(series_r)
        # R1 shares the LED's VCC net → counts as a series resistor.
        design.nets["VCC"].nodes.append(NetNode(component_ref="R1", pin_name="P1"))
        result = ERCRunner().run(design)
        assert not any(v.rule_id == "ERC008" for v in result.violations)

    def test_unrelated_resistor_still_flags(self) -> None:
        # A resistor that does NOT touch the LED (e.g. an I2C pull-up) must not
        # suppress the missing-series-resistor violation. This is the regression
        # the old global "any resistor exists" heuristic got wrong.
        pull_up = Component(
            id="r2",
            ref="R2",
            type="RES",
            value="10k",
            pins={
                "P1": Pin(name="P1", type="passive", net="SDA"),
                "P2": Pin(name="P2", type="passive", net="SCL"),
            },
        )
        sda = Net(id="SDA", name="I2C_SDA", type=NetType.SIGNAL, nodes=[NetNode(component_ref="R2", pin_name="P1")])
        scl = Net(id="SCL", name="I2C_SCL", type=NetType.SIGNAL, nodes=[NetNode(component_ref="R2", pin_name="P2")])
        result = ERCRunner().run(self._led_on_power(pull_up, extra_nets=[sda, scl]))
        assert any(v.rule_id == "ERC008" for v in result.violations)


class TestERC011USBESD:
    """ERC011 must count only ESD parts connected to the USB device's own lines."""

    def _usb(self, *extra: Component, extra_nets: list[Net] | None = None) -> Design:
        usb = Component(
            id="j1",
            ref="J1",
            type="USB-C",
            pins={
                "DP": Pin(name="DP", type="bidirectional", net="USB_DP"),
                "DM": Pin(name="DM", type="bidirectional", net="USB_DM"),
            },
        )
        dp = Net(id="USB_DP", name="USB_DP", type=NetType.SIGNAL, nodes=[NetNode(component_ref="J1", pin_name="DP")])
        dm = Net(id="USB_DM", name="USB_DM", type=NetType.SIGNAL, nodes=[NetNode(component_ref="J1", pin_name="DM")])
        return _design_with(comps=[usb, *extra], nets=[dp, dm, *(extra_nets or [])])

    def test_no_esd_flags(self) -> None:
        result = ERCRunner().run(self._usb())
        assert any(v.rule_id == "ERC011" for v in result.violations)

    def test_connected_esd_passes(self) -> None:
        esd = Component(
            id="u9",
            ref="U9",
            type="USBLC6-2SC6",
            pins={
                "I1": Pin(name="I1", type="bidirectional", net="USB_DP"),
                "I2": Pin(name="I2", type="bidirectional", net="USB_DM"),
            },
        )
        design = self._usb(esd)
        design.nets["USB_DP"].nodes.append(NetNode(component_ref="U9", pin_name="I1"))
        design.nets["USB_DM"].nodes.append(NetNode(component_ref="U9", pin_name="I2"))
        result = ERCRunner().run(design)
        assert not any(v.rule_id == "ERC011" for v in result.violations)

    def test_unrelated_esd_still_flags(self) -> None:
        tvs = Component(id="u8", ref="U8", type="TVS", pins={"P1": Pin(name="P1", type="passive", net="OTHER")})
        other = Net(id="OTHER", name="OTHER", type=NetType.SIGNAL, nodes=[NetNode(component_ref="U8", pin_name="P1")])
        result = ERCRunner().run(self._usb(tvs, extra_nets=[other]))
        assert any(v.rule_id == "ERC011" for v in result.violations)


class TestERCRunner:
    def test_empty_design(self) -> None:
        runner = ERCRunner()
        result = runner.run(_empty_design())
        assert result.passed
        assert result.total_errors == 0
        assert result.design_name == "test"

    def test_all_rules_executed(self) -> None:
        runner = ERCRunner()
        assert hasattr(runner, "run")

    def test_rules_listed(self) -> None:
        import inspect

        import zaptrace.erc.rules as erc_rules

        rule_fns = [
            obj for name, obj in inspect.getmembers(erc_rules, inspect.isfunction) if name.startswith("rule_erc")
        ]
        assert len(rule_fns) == 29

    def test_legacy_rule_names_remain_available(self) -> None:
        import zaptrace.erc.rules as erc_rules

        for index in range(1, 30):
            canonical = getattr(erc_rules, f"rule_erc{index:03d}")
            legacy = getattr(erc_rules, f"rule_ERC{index:03d}")
            assert legacy is canonical


class TestERCCoverageReporting:
    """ERC must report what it checked and its known gaps, not a bare pass/fail."""

    def test_checks_run_recorded_for_every_rule(self) -> None:
        from zaptrace.erc.runner import _ALL_RULES

        result = ERCRunner().run(_empty_design())
        # One ERCCheck per registered rule, in registry order, with stable ids.
        assert len(result.checks_run) == len(_ALL_RULES)
        assert [c.rule_id for c in result.checks_run] == [spec.rule_id for spec in _ALL_RULES]
        assert all(c.title and c.category for c in result.checks_run)

    def test_categories_covered_are_distinct_and_nonempty(self) -> None:
        result = ERCRunner().run(_empty_design())
        cats = result.categories_covered
        assert cats  # at least one category
        assert len(cats) == len(set(cats))  # de-duplicated
        assert "connectivity" in cats
        assert "power" in cats

    def test_coverage_summary_states_scope_and_gaps(self) -> None:
        result = ERCRunner().run(_empty_design())
        summary = result.coverage_summary()
        assert f"{len(result.checks_run)} check(s) run" in summary
        assert "coverage gap(s) noted" in summary

    def test_coverage_gaps_are_reported(self) -> None:
        result = ERCRunner().run(_empty_design())
        assert result.coverage_gaps  # honest limitations are always surfaced
        assert any("Decoupling" in gap for gap in result.coverage_gaps)

    def test_violation_count_matches_recorded_checks(self) -> None:
        # A design that trips ERC020 (missing footprint) must show that count
        # against the ERC020 check entry, proving checks_run reflects findings.
        d = _design_with(
            comps=[Component(id="u1", ref="U1", type="ic", footprint="", pins={"1": Pin(name="1", type="input")})]
        )
        result = ERCRunner().run(d)
        erc020 = next(c for c in result.checks_run if c.rule_id == "ERC020")
        assert erc020.violation_count >= 1

    def test_internal_rule_error_still_records_check(self, monkeypatch) -> None:
        # If a rule raises, the runner must surface an ERC_INTERNAL error AND
        # still record that the check was attempted (no silent gap in coverage).
        import zaptrace.erc.runner as runner_mod

        def boom(_design: Design) -> list:
            raise RuntimeError("synthetic rule failure")

        original = runner_mod._ALL_RULES[0]
        patched = runner_mod.RuleSpec(original.rule_id, original.title, original.category, boom)
        monkeypatch.setattr(runner_mod, "_ALL_RULES", [patched, *runner_mod._ALL_RULES[1:]])

        result = ERCRunner().run(_empty_design())
        assert any(v.rule_id == "ERC_INTERNAL" for v in result.violations)
        assert len(result.checks_run) == len(runner_mod._ALL_RULES)
        assert result.checks_run[0].violation_count == 1


class TestERC024Rs485Direction:
    """ERC024: RS485 DE/RE direction control must be in a defined state."""

    def _rs485_design(self, *, de_connected: bool, de_pulled: bool) -> Design:
        ic = Component(
            id="u1",
            ref="U1",
            type="rs485-transceiver",
            pins={
                "DE": Pin(name="DE", type="input", net="DE_NET" if de_connected else None),
                "A": Pin(name="A", type="passive"),
                "B": Pin(name="B", type="passive"),
            },
        )
        comps = [ic]
        nets = []
        if de_connected:
            nodes = [NetNode(component_ref="U1", pin_name="DE")]
            if de_pulled:
                r = Component(
                    id="r1",
                    ref="R1",
                    type="RES",
                    value="10k",
                    pins={"1": Pin(name="1", type="passive"), "2": Pin(name="2", type="passive")},
                )
                comps.append(r)
                nodes.append(NetNode(component_ref="R1", pin_name="1"))
                nets.append(
                    Net(
                        id="VCC",
                        name="VCC",
                        type=NetType.POWER,
                        nodes=[NetNode(component_ref="R1", pin_name="2")],
                    )
                )
            nets.append(Net(id="DE_NET", name="DE_NET", nodes=nodes))
        return _design_with(comps=comps, nets=nets)

    def test_floating_de_pin_errors(self) -> None:
        d = self._rs485_design(de_connected=False, de_pulled=False)
        violations = rules.rule_ERC024(d)
        assert any(v.rule_id == "ERC024" and v.severity == ERCSeverity.ERROR for v in violations)

    def test_de_without_pull_warns(self) -> None:
        d = self._rs485_design(de_connected=True, de_pulled=False)
        violations = rules.rule_ERC024(d)
        assert any(v.rule_id == "ERC024" and v.severity == ERCSeverity.WARNING for v in violations)

    def test_de_with_pull_passes(self) -> None:
        d = self._rs485_design(de_connected=True, de_pulled=True)
        assert not rules.rule_ERC024(d)

    def test_non_rs485_ic_skipped(self) -> None:
        ic = Component(
            id="u1",
            ref="U1",
            type="mcu",
            pins={"DE": Pin(name="DE", type="input")},
        )
        d = _design_with(comps=[ic])
        assert not rules.rule_ERC024(d)


class TestERC025SpiCsUniqueness:
    """ERC025: a SPI chip-select net must not be shared between multiple peripherals."""

    def _shared_cs_design(self) -> Design:
        mcu = Component(id="u1", ref="U1", type="mcu", pins={"CS": Pin(name="CS", type="output")})
        adc = Component(id="u2", ref="U2", type="adc", pins={"CS": Pin(name="CS", type="input")})
        flash = Component(id="u3", ref="U3", type="flash", pins={"CS": Pin(name="CS", type="input")})
        cs_net = Net(
            id="SPI_CS",
            name="SPI_CS",
            nodes=[
                NetNode(component_ref="U1", pin_name="CS"),
                NetNode(component_ref="U2", pin_name="CS"),
                NetNode(component_ref="U3", pin_name="CS"),
            ],
        )
        return _design_with(comps=[mcu, adc, flash], nets=[cs_net])

    def _unique_cs_design(self) -> Design:
        mcu = Component(id="u1", ref="U1", type="mcu", pins={"CS": Pin(name="CS", type="output")})
        adc = Component(id="u2", ref="U2", type="adc", pins={"CS": Pin(name="CS", type="input")})
        cs_net = Net(
            id="SPI_CS",
            name="SPI_CS",
            nodes=[
                NetNode(component_ref="U1", pin_name="CS"),
                NetNode(component_ref="U2", pin_name="CS"),
            ],
        )
        return _design_with(comps=[mcu, adc], nets=[cs_net])

    def test_shared_cs_errors(self) -> None:
        violations = rules.rule_ERC025(self._shared_cs_design())
        assert any(v.rule_id == "ERC025" for v in violations)

    def test_unique_cs_passes(self) -> None:
        assert not rules.rule_ERC025(self._unique_cs_design())


class TestERC026LipoProtection:
    """ERC026: Li-ion/LiPo battery must have a protection IC."""

    def _lipo_design(self, *, with_protection: bool) -> Design:
        batt = Component(id="bt1", ref="BT1", type="lipo-cell", pins={"P": Pin(name="P", type="power")})
        comps = [batt]
        if with_protection:
            prot = Component(id="u1", ref="U1", type="dw01a-protection", pins={})
            comps.append(prot)
        return _design_with(comps=comps)

    def test_unprotected_lipo_warns(self) -> None:
        violations = rules.rule_ERC026(self._lipo_design(with_protection=False))
        assert any(v.rule_id == "ERC026" for v in violations)

    def test_protected_lipo_passes(self) -> None:
        assert not rules.rule_ERC026(self._lipo_design(with_protection=True))

    def test_no_battery_passes(self) -> None:
        assert not rules.rule_ERC026(_empty_design())


class TestWaiverSupport:
    """ERCViolation waiver_reason suppresses violations from totals."""

    def test_waived_violation_not_counted_in_errors(self) -> None:
        from zaptrace.erc.models import ERCResult, ERCSeverity, ERCViolation

        v_waived = ERCViolation(
            rule_id="ERC002",
            severity=ERCSeverity.ERROR,
            message="waived error",
            waiver_reason="Engineering deviation approved by review board",
        )
        result = ERCResult.from_violations([v_waived], design_name="test")
        assert result.total_errors == 0
        assert result.total_waivers == 1
        assert result.passed  # waived errors do not block the pass gate

    def test_active_error_still_fails(self) -> None:
        from zaptrace.erc.models import ERCResult, ERCSeverity, ERCViolation

        v_active = ERCViolation(rule_id="ERC001", severity=ERCSeverity.ERROR, message="active error")
        v_waived = ERCViolation(
            rule_id="ERC002",
            severity=ERCSeverity.ERROR,
            message="waived error",
            waiver_reason="Engineering deviation approved by review board",
        )
        result = ERCResult.from_violations([v_active, v_waived], design_name="test")
        assert result.total_errors == 1
        assert result.total_waivers == 1
        assert not result.passed  # one active error remains

    def test_is_waived_property(self) -> None:
        from zaptrace.erc.models import ERCSeverity, ERCViolation

        v = ERCViolation(rule_id="ERC001", severity=ERCSeverity.ERROR, message="x")
        assert not v.is_waived
        v2 = ERCViolation(rule_id="ERC001", severity=ERCSeverity.ERROR, message="x", waiver_reason="approved")
        assert v2.is_waived

    def test_coverage_summary_includes_waivers(self) -> None:
        from zaptrace.erc.models import ERCResult, ERCSeverity, ERCViolation

        v = ERCViolation(
            rule_id="ERC001",
            severity=ERCSeverity.WARNING,
            message="w",
            waiver_reason="ok",
        )
        result = ERCResult.from_violations([v], design_name="test")
        assert "waived" in result.coverage_summary()

    def test_active_and_waived_accessors(self) -> None:
        from zaptrace.erc.models import ERCResult, ERCSeverity, ERCViolation

        v_active = ERCViolation(rule_id="ERC001", severity=ERCSeverity.ERROR, message="x")
        v_waived = ERCViolation(rule_id="ERC002", severity=ERCSeverity.ERROR, message="y", waiver_reason="approved")
        result = ERCResult.from_violations([v_active, v_waived], design_name="test")
        assert result.active_violations == [v_active]
        assert result.waived_violations == [v_waived]


class TestERC027:
    """Power-tree completeness check."""

    def test_power_net_with_source_ok(self) -> None:
        d = _design_with(
            comps=[
                Component(
                    id="u1",
                    ref="U1",
                    type="regulator",
                    value="",
                    pins={
                        "VOUT": Pin(name="VOUT", type="power", net="3V3"),
                        "VIN": Pin(name="VIN", type="power", net="VIN"),
                    },
                ),
            ],
            nets=[
                Net(id="3V3", name="+3V3", type=NetType.POWER, nodes=[NetNode(component_ref="U1", pin_name="VOUT")]),
                Net(id="VIN", name="VIN", type=NetType.POWER, nodes=[NetNode(component_ref="U1", pin_name="VIN")]),
            ],
        )
        vs = rules.rule_ERC027(d)
        assert len(vs) == 0

    def test_usb_c_input_counts_as_power_tree_source(self) -> None:
        d = _design_with(
            comps=[
                Component(
                    id="j1",
                    ref="J1",
                    type="USB-C-16P",
                    pins={"VBUS": Pin(name="VBUS", type="power", net="VBUS")},
                )
            ],
            nets=[
                Net(id="vbus", name="VBUS", type=NetType.POWER, nodes=[NetNode(component_ref="J1", pin_name="VBUS")])
            ],
        )

        assert rules.rule_ERC027(d) == []

    def test_orphan_power_net_detected(self) -> None:
        d = _design_with(
            comps=[
                Component(
                    id="r1",
                    ref="R1",
                    type="resistor",
                    value="10k",
                    pins={"1": Pin(name="1", type="passive", net="SIGNAL")},
                ),
            ],
            nets=[
                Net(id="3V3", name="+3V3", type=NetType.POWER, nodes=[NetNode(component_ref="R1", pin_name="1")]),
            ],
        )
        vs = rules.rule_ERC027(d)
        assert len(vs) == 1
        assert vs[0].rule_id == "ERC027"
        assert "+3V3" in vs[0].message


class TestERC028:
    """Regulator headroom and current budget."""

    def test_no_regulator_no_violation(self) -> None:
        d = _design_with(
            comps=[Component(id="r1", ref="R1", type="resistor", value="10k")],
        )
        vs = rules.rule_ERC028(d)
        assert len(vs) == 0

    def test_regulator_current_overage(self) -> None:
        d = _design_with(
            comps=[
                Component(
                    id="u1",
                    ref="U1",
                    type="buck",
                    value="",
                    current_rating=0.5,
                    pins={
                        "VOUT": Pin(name="VOUT", type="output", net="3V3"),
                        "VIN": Pin(name="VIN", type="power", net="VIN"),
                    },
                ),
                Component(
                    id="r1",
                    ref="R1",
                    type="resistor",
                    value="1A",
                    pins={"1": Pin(name="1", type="passive", net="3V3")},
                ),
            ],
            nets=[
                Net(
                    id="3V3",
                    name="+3V3",
                    type=NetType.POWER,
                    nodes=[NetNode(component_ref="U1", pin_name="VOUT"), NetNode(component_ref="R1", pin_name="1")],
                ),
                Net(id="VIN", name="VIN", type=NetType.POWER),
            ],
        )
        vs = rules.rule_ERC028(d)
        assert len(vs) >= 1
        assert any("current budget" in v.message.lower() for v in vs)


class TestERC029:
    """DNP/variant-aware ERC."""

    def test_no_dnp_no_violation(self) -> None:
        d = _design_with(
            comps=[Component(id="c1", ref="C1", type="cap", value="100nF")],
        )
        vs = rules.rule_ERC029(d)
        assert len(vs) == 0

    def test_all_decoupling_dnp_warns(self) -> None:
        d = _design_with(
            comps=[
                Component(
                    id="c1",
                    ref="C1",
                    type="cap",
                    value="100nF",
                    dnp=True,
                    pins={"1": Pin(name="1", type="passive", net="3V3"), "2": Pin(name="2", type="passive", net="GND")},
                ),
                Component(
                    id="c2",
                    ref="C2",
                    type="cap",
                    value="100nF",
                    dnp=True,
                    pins={"1": Pin(name="1", type="passive", net="3V3"), "2": Pin(name="2", type="passive", net="GND")},
                ),
            ],
            nets=[
                Net(
                    id="3V3",
                    name="+3V3",
                    type=NetType.POWER,
                    nodes=[NetNode(component_ref="C1", pin_name="1"), NetNode(component_ref="C2", pin_name="1")],
                ),
                Net(id="GND", name="GND", type=NetType.GROUND),
            ],
        )
        vs = rules.rule_ERC029(d)
        assert len(vs) == 1
        assert vs[0].rule_id == "ERC029"
        assert "DNP" in vs[0].message

    def test_some_caps_populated_no_warning(self) -> None:
        d = _design_with(
            comps=[
                Component(
                    id="c1",
                    ref="C1",
                    type="cap",
                    value="100nF",
                    dnp=True,
                    pins={"1": Pin(name="1", type="passive", net="3V3")},
                ),
                Component(
                    id="c2",
                    ref="C2",
                    type="cap",
                    value="100nF",
                    dnp=False,
                    pins={"1": Pin(name="1", type="passive", net="3V3")},
                ),
            ],
            nets=[
                Net(
                    id="3V3",
                    name="+3V3",
                    type=NetType.POWER,
                    nodes=[NetNode(component_ref="C1", pin_name="1"), NetNode(component_ref="C2", pin_name="1")],
                ),
            ],
        )
        vs = rules.rule_ERC029(d)
        assert len(vs) == 0


def test_erc_current_parser_accepts_ma_case_variants() -> None:
    assert rules._parse_current("250mA") == 0.25
    assert rules._parse_current("250ma") == 0.25
