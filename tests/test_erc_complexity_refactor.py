from __future__ import annotations

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode, NetType, Pin, PinType
from zaptrace.erc import rules
from zaptrace.erc.graph import ElectricalGraph
from zaptrace.erc.models import ERCSeverity


def _design(*components: Component, nets: list[Net] | None = None) -> Design:
    return Design(
        meta=DesignMeta(name="erc-complexity"),
        components={component.id: component for component in components},
        nets={net.id: net for net in nets or []},
    )


def test_erc003_helpers_preserve_connected_and_lenient_paths() -> None:
    controller = Component(
        id="u1",
        ref="U1",
        type="mcu",
        pins={
            "IN": Pin(name="IN", type=PinType.INPUT),
            "VCC": Pin(name="VCC", type=PinType.POWER, net="VCC"),
            "AUX": Pin(name="AUX", type=PinType.POWER, net="AUX"),
            "VDD": Pin(name="VDD", type=PinType.POWER),
        },
    )
    design = _design(
        controller,
        nets=[
            Net(
                id="VCC",
                name="VCC",
                type=NetType.POWER,
                nodes=[NetNode(component_ref="U1", pin_name="VCC")],
            ),
            Net(
                id="AUX",
                name="AUX",
                type=NetType.SIGNAL,
                nodes=[NetNode(component_ref="U1", pin_name="AUX")],
            ),
        ],
    )

    connected, unconnected = rules._component_power_net_state(design, controller)
    assert connected == {"VCC"}
    assert unconnected is True
    assert rules._erc003_violation(design, controller, set(), True, set(), True) is None
    assert rules._erc003_violation(design, controller, set(), False, set(), False) is None
    unconnected_violation = rules._erc003_violation(design, controller, set(), True, set(), False)
    assert unconnected_violation is not None
    assert unconnected_violation.rule_id == "ERC003"
    connected_violation = rules._erc003_violation(design, controller, {"VCC"}, False, set(), False)
    assert connected_violation is not None
    assert connected_violation.net_refs == ["VCC"]


def test_erc010_counts_only_connected_load_capacitors() -> None:
    crystal = Component(
        id="y1",
        ref="Y1",
        type="crystal",
        pins={
            "1": Pin(name="1", type=PinType.PASSIVE),
            "2": Pin(name="2", type=PinType.PASSIVE),
        },
    )
    cap1 = Component(id="c1", ref="C1", type="cap")
    cap2 = Component(id="c2", ref="C2", type="capacitor")
    unrelated = Component(id="r1", ref="R1", type="resistor")
    design = _design(
        crystal,
        cap1,
        cap2,
        unrelated,
        nets=[
            Net(
                id="XTAL1",
                name="XTAL1",
                nodes=[
                    NetNode(component_ref="Y1", pin_name="1"),
                    NetNode(component_ref="C1", pin_name="1"),
                    NetNode(component_ref="R1", pin_name="1"),
                ],
            ),
            Net(
                id="XTAL2",
                name="XTAL2",
                nodes=[NetNode(component_ref="Y1", pin_name="2"), NetNode(component_ref="C2", pin_name="1")],
            ),
            Net(id="UNRELATED", name="UNRELATED", nodes=[NetNode(component_ref="R1", pin_name="2")]),
        ],
    )

    assert rules._connected_capacitor_count(design, crystal) == 2
    assert rules.rule_erc010(design) == []
    assert rules._erc010_violation(design, unrelated) is None
    design.nets.pop("XTAL2")
    assert rules.rule_erc010(design)[0].rule_id == "ERC010"


def test_reset_and_no_connect_helpers_cover_resolution_edges() -> None:
    controller = Component(
        id="u1",
        ref="U1",
        type="mcu",
        pins={
            "GPIO": Pin(name="GPIO", type=PinType.INPUT),
            "NRST": Pin(name="NRST", type=PinType.INPUT, net="RST_BY_NAME"),
            "NC": Pin(name="NC", type=PinType.NO_CONNECT),
        },
    )
    other = Component(id="u2", ref="U2", type="sensor", pins={"IN": Pin(name="IN", type=PinType.INPUT)})
    rst = Net(id="rst-id", name="RST_BY_NAME", type=NetType.SIGNAL)
    nc = Net(
        id="NC_NET",
        name="NC_NET",
        nodes=[NetNode(component_ref="U1", pin_name="NC"), NetNode(component_ref="U2", pin_name="IN")],
    )
    design = _design(controller, other, nets=[rst, nc])
    graph = ElectricalGraph.from_design(design)

    assert rules._reset_pin_violation(design, graph, controller, "GPIO", controller.pins["GPIO"]) is None
    reset_violation = rules._reset_pin_violation(design, graph, controller, "NRST", controller.pins["NRST"])
    assert reset_violation is not None
    assert reset_violation.rule_id == "ERC016"
    assert rules._pin_net(design, controller, "NC", controller.pins["NC"]) == nc
    violation = rules._erc023_violation(design, graph, controller, "NC", controller.pins["NC"])
    assert violation is not None
    assert violation.component_refs == ["U1"]
    assert rules._erc023_violation(design, graph, controller, "GPIO", controller.pins["GPIO"]) is None


def test_erc024_accepts_direct_rail_and_reports_other_states() -> None:
    transceiver = Component(
        id="u1",
        ref="U1",
        type="rs485-transceiver",
        pins={"DE": Pin(name="DE", type=PinType.INPUT, net="VCC")},
    )
    rail = Net(
        id="VCC",
        name="VCC",
        type=NetType.POWER,
        nodes=[NetNode(component_ref="U1", pin_name="DE")],
    )
    design = _design(transceiver, nets=[rail])
    graph = ElectricalGraph.from_design(design)

    assert rules._is_rs485_component(transceiver) is True
    assert rules._erc024_violation(design, graph, transceiver, "DE") is None
    transceiver.pins["DE"].net = None
    design.nets.clear()
    floating = rules._erc024_violation(design, ElectricalGraph.from_design(design), transceiver, "DE")
    assert floating is not None
    assert floating.severity == ERCSeverity.ERROR


def test_erc028_helpers_cover_regulator_kinds_headroom_and_budget() -> None:
    regulator = Component(
        id="u1",
        ref="U1",
        type="buck regulator",
        voltage_supply="0.4V",
        current_rating=0.5,
        pins={
            "VIN": Pin(name="VIN", type=PinType.POWER, net="VIN"),
            "VOUT": Pin(name="VOUT", type=PinType.OUTPUT, net="VOUT"),
        },
    )
    load = Component(id="u2", ref="U2", type="load", value="1A")
    design = _design(
        regulator,
        load,
        nets=[
            Net(id="VIN", name="VIN", type=NetType.POWER),
            Net(
                id="VOUT",
                name="VOUT",
                type=NetType.POWER,
                nodes=[NetNode(component_ref="U1", pin_name="VOUT"), NetNode(component_ref="U2", pin_name="VCC")],
            ),
        ],
    )

    assert rules._regulator_kind(regulator) == "buck"
    assert rules._regulator_kind(Component(id="b", ref="B1", type="boost")) == "boost"
    assert rules._regulator_kind(Component(id="l", ref="L1", type="linear ldo")) == "linear"
    assert rules._regulator_kind(Component(id="r", ref="R1", type="resistor")) is None
    output_nets, input_nets = rules._regulator_net_ids(regulator)
    assert (output_nets, input_nets) == ({"VOUT"}, {"VIN"})
    assert rules._erc028_headroom_violations(design, regulator, "boost", output_nets, input_nets) == []
    regulator.voltage_supply = "3.3V"
    assert rules._erc028_headroom_violations(design, regulator, "buck", output_nets, input_nets) == []
    regulator.voltage_supply = "0.4V"
    assert rules._erc028_headroom_violations(design, regulator, "buck", output_nets, input_nets)[0].rule_id == "ERC028"
    assert rules._estimated_load_current(design, regulator.ref, {"missing", "VOUT"}) == 1.0
    budget_violation = rules._erc028_current_budget_violation(design, regulator, output_nets)
    assert budget_violation is not None
    assert budget_violation.rule_id == "ERC028"
    regulator.current_rating = 2.0
    assert rules._erc028_current_budget_violation(design, regulator, output_nets) is None
    regulator.current_rating = None
    assert rules._erc028_current_budget_violation(design, regulator, output_nets) is None


def test_erc029_helpers_cover_power_and_i2c_population_states() -> None:
    cap = Component(id="c1", ref="C1", type="cap", dnp=True)
    resistor = Component(id="r1", ref="R1", type="resistor", dnp=True)
    other = Component(id="u1", ref="U1", type="sensor", dnp=True)
    power = Net(
        id="VCC",
        name="VCC",
        type=NetType.POWER,
        nodes=[NetNode(component_ref="C1", pin_name="1"), NetNode(component_ref="missing", pin_name="1")],
    )
    i2c = Net(id="SDA", name="I2C_SDA", nodes=[NetNode(component_ref="R1", pin_name="1")])
    signal = Net(id="SIG", name="SIG", nodes=[NetNode(component_ref="U1", pin_name="1")])
    design = _design(cap, resistor, other, nets=[power, i2c, signal])

    assert rules._net_components_of_types(design, power, rules._CAP_TYPES) == [cap]
    assert rules._erc029_power_violation(design, signal) is None
    power_violation = rules._erc029_power_violation(design, power)
    assert power_violation is not None
    assert power_violation.severity == ERCSeverity.WARNING
    assert rules._erc029_i2c_violation(design, signal) is None
    i2c_violation = rules._erc029_i2c_violation(design, i2c)
    assert i2c_violation is not None
    assert i2c_violation.severity == ERCSeverity.ERROR
    resistor.dnp = False
    assert rules._erc029_i2c_violation(design, i2c) is None
    resistor.dnp = True
    assert {violation.severity for violation in rules.rule_erc029(design)} == {
        ERCSeverity.WARNING,
        ERCSeverity.ERROR,
    }


def test_current_parser_bounds_numeric_tokens_and_whitespace() -> None:
    assert rules._parse_current("123456789012.123456789012 A") == 123456789012.12346
    assert rules._parse_current("250" + " " * 32 + "mA") == 0.25
    assert rules._parse_current("9" * 100_000 + "x") is None
