from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable

from zaptrace.core.models import Component, Design, Net, NetType, Pin
from zaptrace.erc.graph import ElectricalGraph
from zaptrace.erc.models import ERCSeverity, ERCViolation

INVALID_NET_NAME_RE = re.compile(r"[^a-zA-Z0-9_+\-\.]")

# Component-type keywords used to tell active ICs (which need decoupling and
# carry power pins) apart from passives and connectors. IC detection is
# structural — a power pin plus "not an obvious passive/connector" — rather than
# a hardcoded part-number whitelist, so it generalises to any IC in the library.
_PASSIVE_TYPE_KEYWORDS = (
    "res",
    "cap",
    "ind",
    "ferrite",
    "bead",
    "led",
    "diode",
    "zener",
    "tvs",
    "crystal",
    "xtal",
    "resonator",
    "oscillator",
    "fuse",
    "jumper",
    "testpoint",
    "antenna",
    "switch",
    "button",
    "relay",
)
_CONNECTOR_TYPE_KEYWORDS = ("conn", "header", "usb", "jack", "socket", "terminal", "receptacle")
_CAP_TYPES = {"CAP", "CAPACITOR", "C"}
_DECOUPLE_CAP_VALUES = {"100nf", "0.1uf", "10nf", "1uf", "4.7uf", "10uf", "22uf"}


def _has_power_pin(comp: Component) -> bool:
    return any(pin.type.value == "power" for pin in comp.pins.values())


def _is_ic(comp: Component) -> bool:
    """Heuristically decide whether a component is an active IC.

    An IC is a component that carries at least one power pin and whose type is
    not an obvious passive or connector. This replaces the previous hardcoded
    part-number whitelist so the rule covers any IC in the library.
    """
    if not _has_power_pin(comp):
        return False
    type_lower = comp.type.lower()
    return not any(kw in type_lower for kw in _PASSIVE_TYPE_KEYWORDS + _CONNECTOR_TYPE_KEYWORDS)


def _component_net_ids(design: Design, component_ref: str) -> set[str]:
    """Net ids that *component_ref* is wired to via net nodes (canonical connectivity)."""
    return {net.id for net in design.nets.values() if any(node.component_ref == component_ref for node in net.nodes)}


def _net_owns_decoupling(design: Design, power_net_id: str, ground_net_ids: set[str]) -> bool:
    """Return True if a capacitor bridges *power_net_id* to a ground net."""
    for comp in design.get_components_on_net(power_net_id):
        if comp.type.upper() not in _CAP_TYPES:
            continue
        other_nets = _component_net_ids(design, comp.ref)
        other_nets.discard(power_net_id)
        if other_nets & ground_net_ids:
            return True
    return False


def rule_erc001(design: Design) -> list[ERCViolation]:
    """Detect power pins with no net assignment."""
    violations: list[ERCViolation] = []
    for comp in design.components.values():
        for pin_name, pin in comp.pins.items():
            if pin.type.value == "power" and pin.net is None:
                net = design.get_net_for_pin(comp.ref, pin_name)
                if net is None:
                    violations.append(
                        ERCViolation(
                            rule_id="ERC001",
                            severity=ERCSeverity.ERROR,
                            message=f"{comp.ref}.{pin_name} (power pin) is not connected to any net",
                            component_refs=[comp.ref],
                            patch_suggestion=f"Connect {comp.ref}.{pin_name} to an appropriate power net",
                        )
                    )
    return violations


def rule_erc002(design: Design) -> list[ERCViolation]:
    """Detect floating input pins with no net."""
    violations: list[ERCViolation] = []
    for comp in design.components.values():
        for pin_name, pin in comp.pins.items():
            if pin.type.value == "input" and pin.net is None:
                net = design.get_net_for_pin(comp.ref, pin_name)
                if net is None:
                    violations.append(
                        ERCViolation(
                            rule_id="ERC002",
                            severity=ERCSeverity.WARNING,
                            message=f"{comp.ref}.{pin_name} (input pin) is not connected to any net",
                            component_refs=[comp.ref],
                            patch_suggestion=f"Connect {comp.ref}.{pin_name} or add a pull-up/pull-down resistor",
                        )
                    )
    return violations


def _component_power_net_state(design: Design, comp: Component) -> tuple[set[str], bool]:
    connected_power_nets: set[str] = set()
    has_unconnected_power_pin = False
    for pin_name, pin in comp.pins.items():
        if pin.type.value != "power":
            continue
        net = design.get_net_for_pin(comp.ref, pin_name)
        if net is None:
            has_unconnected_power_pin = True
        elif net.type == NetType.POWER:
            connected_power_nets.add(net.id)
    return connected_power_nets, has_unconnected_power_pin


def _erc003_violation(
    design: Design,
    comp: Component,
    connected_power_nets: set[str],
    has_unconnected_power_pin: bool,
    ground_net_ids: set[str],
    lenient_has_cap: bool,
) -> ERCViolation | None:
    if connected_power_nets:
        missing = sorted(
            net_id for net_id in connected_power_nets if not _net_owns_decoupling(design, net_id, ground_net_ids)
        )
        if not missing:
            return None
        net_names = [design.nets[net_id].name for net_id in missing]
        return ERCViolation(
            rule_id="ERC003",
            severity=ERCSeverity.WARNING,
            message=(f"{comp.ref} ({comp.type}) power net(s) {net_names} have no decoupling capacitor to ground"),
            component_refs=[comp.ref],
            net_refs=missing,
            patch_suggestion="Add a 100nF ceramic capacitor between each power pin and GND",
        )
    if not has_unconnected_power_pin or lenient_has_cap:
        return None
    return ERCViolation(
        rule_id="ERC003",
        severity=ERCSeverity.WARNING,
        message=f"{comp.ref} ({comp.type}) may be missing a decoupling capacitor",
        component_refs=[comp.ref],
        patch_suggestion="Add a 100nF ceramic capacitor near each power pin",
    )


def rule_erc003(design: Design) -> list[ERCViolation]:
    """Check ICs on power nets have a decoupling capacitor.

    For each IC power pin wired to a POWER net, require a capacitor bridging that
    net to ground (net-ownership check) rather than just *any* 100nF capacitor
    somewhere in the design. When an IC's power pins are not yet wired into the
    netlist, fall back to a lenient design-wide check for at least one
    decoupling-value capacitor so under-specified designs still get the hint.
    """
    ground_net_ids = {net_id for net_id, net in design.nets.items() if net.type == NetType.GROUND}
    lenient_has_cap = any(
        (comp.value or "").lower() in _DECOUPLE_CAP_VALUES and comp.type.upper() in _CAP_TYPES
        for comp in design.components.values()
    )
    violations: list[ERCViolation] = []
    for comp in filter(_is_ic, design.components.values()):
        connected_power_nets, has_unconnected_power_pin = _component_power_net_state(design, comp)
        violation = _erc003_violation(
            design,
            comp,
            connected_power_nets,
            has_unconnected_power_pin,
            ground_net_ids,
            lenient_has_cap,
        )
        if violation is not None:
            violations.append(violation)
    return violations


def rule_erc004(design: Design) -> list[ERCViolation]:
    """Detect duplicate net names."""
    violations: list[ERCViolation] = []
    name_counts = Counter(n.name for n in design.nets.values())
    for name, count in name_counts.items():
        if count > 1:
            nets = [n.id for n in design.nets.values() if n.name == name]
            violations.append(
                ERCViolation(
                    rule_id="ERC004",
                    severity=ERCSeverity.ERROR,
                    message=f"Net name '{name}' is used {count} times (IDs: {nets})",
                    net_refs=nets,
                    patch_suggestion="Rename duplicate nets with unique names",
                )
            )
    return violations


def rule_erc005(design: Design) -> list[ERCViolation]:
    """Check I2C nets for pull-up resistors connected to a power rail."""
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    pullup_values = {"4.7k", "10k", "2.2k", "1k"}
    for net in design.nets.values():
        if net.name in ("I2C_SDA", "I2C_SCL") or "i2c" in net.name.lower():
            has_pullup = graph.has_resistor_to_power(net.id, pullup_values)
            if not has_pullup:
                violations.append(
                    ERCViolation(
                        rule_id="ERC005",
                        severity=ERCSeverity.WARNING,
                        message=f"I2C net '{net.name}' has no pull-up resistor tied to a power rail",
                        net_refs=[net.id],
                        patch_suggestion="Add 4.7k-10k pull-up resistors from SDA/SCL to the I2C voltage rail",
                    )
                )
    return violations


def rule_erc006(design: Design) -> list[ERCViolation]:
    """Detect SPI MOSI-MOSI connection (should be MOSI-MISO)."""
    violations: list[ERCViolation] = []
    for net in design.nets.values():
        if "mosi" in net.name.lower():
            pins_on_net = [(n.component_ref, n.pin_name) for n in net.nodes]
            mosi_count = sum(1 for _, p in pins_on_net if "mosi" in p.lower())
            miso_count = sum(1 for _, p in pins_on_net if "miso" in p.lower())
            if mosi_count > 1 and miso_count == 0:
                violations.append(
                    ERCViolation(
                        rule_id="ERC006",
                        severity=ERCSeverity.ERROR,
                        message=f"MOSI connected to MOSI (should connect to MISO) on net '{net.name}'",
                        net_refs=[net.id],
                        patch_suggestion="Verify SPI wiring: master MOSI -> slave MOSI, master MISO <- slave MISO",
                    )
                )
    return violations


def rule_erc007(design: Design) -> list[ERCViolation]:
    """Check power nets have at least one driving source.

    A power net is driven if it has an output pin, a regulator/power-source
    component, or an input connector on it — the same sources ERC027 recognizes,
    so a rail fed directly by a DC connector is not falsely flagged. Power-sink-
    only nets (e.g. an MCU VCC with nothing feeding it) are reported.
    """
    violations: list[ERCViolation] = []
    for net in design.nets.values():
        if net.type != NetType.POWER:
            continue
        if not _power_net_has_source(design, net.id):
            violations.append(
                ERCViolation(
                    rule_id="ERC007",
                    severity=ERCSeverity.WARNING,
                    message=f"Power net '{net.name}' has no driving source (output pin)",
                    net_refs=[net.id],
                    patch_suggestion=f"Connect a regulator or power source to {net.name}",
                )
            )
    return violations


_RES_TYPES = {"RES", "R", "RESISTOR"}


def rule_erc008(design: Design) -> list[ERCViolation]:
    """Detect LEDs on power nets with no series resistor.

    A series resistor is only counted if a resistor is *directly connected* to
    the LED (shares one of the LED's nets) -- the previous global check passed
    whenever any resistor existed anywhere in the design (e.g. an unrelated I2C
    pull-up), masking real missing-current-limit faults. (graph/pin
    connectivity, not global heuristics.)
    """
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    for comp in design.components.values():
        if comp.type not in ("LED", "LED-0603", "LED-0805", "LED-0402"):
            continue
        anode_pin = comp.pins.get("ANODE")
        if not (anode_pin and anode_pin.net):
            continue
        node_net = design.get_net_for_pin(comp.ref, "ANODE")
        if not (node_net and node_net.type in (NetType.POWER,)):
            continue
        led_net_ids = graph.nets_for_component(comp.ref) | graph.nets_for_component(comp.id)
        has_series_r = any(
            (other := design.get_component(ep.component_ref)) is not None
            and other.ref not in (comp.ref, comp.id)
            and other.type.upper() in _RES_TYPES
            for net_id in led_net_ids
            for ep in graph.endpoints(net_id)
        )
        if not has_series_r:
            violations.append(
                ERCViolation(
                    rule_id="ERC008",
                    severity=ERCSeverity.ERROR,
                    message=f"{comp.ref} LED anode on power net without series resistor",
                    component_refs=[comp.ref],
                    patch_suggestion="Add a current-limiting resistor (220-470 ohms) in series with the LED",
                )
            )
    return violations


def rule_erc009(design: Design) -> list[ERCViolation]:
    """Detect UART TX-TX connection (should be TX-RX)."""
    violations: list[ERCViolation] = []
    for net in design.nets.values():
        if "uart" in net.name.lower() or "tx" in net.name.lower():
            pins_on_net = [(n.component_ref, n.pin_name) for n in net.nodes]
            tx_count = sum(1 for _, p in pins_on_net if p.upper() in ("TX", "TXD", "TX1", "TX0"))
            rx_count = sum(1 for _, p in pins_on_net if p.upper() in ("RX", "RXD", "RX1", "RX0"))
            if tx_count >= 2 and rx_count == 0:
                violations.append(
                    ERCViolation(
                        rule_id="ERC009",
                        severity=ERCSeverity.ERROR,
                        message=f"TX connected to TX on net '{net.name}' (should connect TX to RX)",
                        net_refs=[net.id],
                        patch_suggestion="Connect UART TX to RX, not TX to TX",
                    )
                )
    return violations


def _is_crystal_component(comp: Component) -> bool:
    crystal_keywords = ("xtal", "crystal", "32khz", "32.768khz")
    type_lower = comp.type.lower()
    return any(keyword in type_lower for keyword in crystal_keywords)


def _connected_capacitor_count(design: Design, comp: Component) -> int:
    count = 0
    for net in design.nets.values():
        if not any(node.component_ref == comp.ref for node in net.nodes):
            continue
        for node in net.nodes:
            if node.component_ref == comp.ref:
                continue
            other = design.get_component(node.component_ref)
            if other is not None and other.type.lower() in ("cap", "capacitor"):
                count += 1
    return count


def _erc010_violation(design: Design, comp: Component) -> ERCViolation | None:
    if not _is_crystal_component(comp) or _connected_capacitor_count(design, comp) >= 2:
        return None
    return ERCViolation(
        rule_id="ERC010",
        severity=ERCSeverity.WARNING,
        message=f"{comp.ref} ({comp.type}) may be missing load capacitors",
        component_refs=[comp.ref],
        patch_suggestion="Add 12-22pF load capacitors between crystal pins and ground",
    )


def rule_erc010(design: Design) -> list[ERCViolation]:
    """Check crystal components have load capacitors."""
    return [
        violation for comp in design.components.values() if (violation := _erc010_violation(design, comp)) is not None
    ]


_ESD_TYPES = {"ESD", "TVS", "ESD_PROTECTION"}


def _is_esd(comp: Component) -> bool:
    type_upper = comp.type.upper()
    return type_upper in _ESD_TYPES or "USBLC" in type_upper or "ESD" in type_upper or "TVS" in type_upper


def rule_erc011(design: Design) -> list[ERCViolation]:
    """Check USB connectors for ESD protection on their own lines (info-level).

    The ESD/TVS device must share a net with the USB connector to count -- the
    previous check passed if any ESD part existed anywhere in the design, even
    one protecting an unrelated net. (graph/pin connectivity, not global
    heuristics.)
    """
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    for comp in design.components.values():
        # Match USB connectors/devices, but not the ESD parts themselves (e.g. a
        # USBLC6 has "usb" in its type yet *is* the protection).
        if "usb" not in comp.type.lower() or _is_esd(comp):
            continue
        usb_net_ids = graph.nets_for_component(comp.ref) | graph.nets_for_component(comp.id)
        has_esd = any(
            (other := design.get_component(ep.component_ref)) is not None
            and other.ref not in (comp.ref, comp.id)
            and _is_esd(other)
            for net_id in usb_net_ids
            for ep in graph.endpoints(net_id)
        )
        if not has_esd:
            violations.append(
                ERCViolation(
                    rule_id="ERC011",
                    severity=ERCSeverity.INFO,
                    message=f"{comp.ref} ({comp.type}) has no ESD protection on its lines",
                    component_refs=[comp.ref],
                    patch_suggestion="Add ESD protection diodes (e.g., USBLC6-2) on D+/D- lines",
                )
            )
    return violations


def rule_erc012(design: Design) -> list[ERCViolation]:
    """Detect nets with only one connected pin."""
    violations: list[ERCViolation] = []
    for net in design.nets.values():
        if len(net.nodes) < 2:
            violations.append(
                ERCViolation(
                    rule_id="ERC012",
                    severity=ERCSeverity.WARNING,
                    message=f"Net '{net.name}' has only {len(net.nodes)} connected pin(s)",
                    net_refs=[net.id],
                    patch_suggestion=f"Connect more components to '{net.name}' or remove unused net",
                )
            )
    return violations


def rule_erc013(design: Design) -> list[ERCViolation]:
    """Hint at polarized component polarity concerns."""
    violations: list[ERCViolation] = []
    for comp in design.components.values():
        if comp.type in ("CAP-ELEC", "cap-electrolytic-5mm") or "electrolytic" in comp.type.lower():
            violations.append(
                ERCViolation(
                    rule_id="ERC013",
                    severity=ERCSeverity.WARNING,
                    message=f"{comp.ref} is a polarized capacitor — verify correct polarity",
                    component_refs=[comp.ref],
                    patch_suggestion="Ensure positive pin connects to higher potential and negative to GND",
                )
            )
    return violations


def _parse_supply_voltage(raw: str) -> float | None:
    """Parse a declared supply voltage string to volts.

    Handles ``"3.3"``, ``"5"``, ``"5.0"``, ``"3V3"``, ``"5V"`` and ``"3.3V"``;
    returns ``None`` for blank/unparseable values so they never trigger a
    mismatch.
    """
    if not raw:
        return None
    # "3V3" style: a 'v' between digits is the decimal separator.
    s = re.sub(r"(?<=\d)[vV](?=\d)", ".", raw.strip())
    # Strip a trailing unit suffix ("5V" -> "5").
    s = re.sub(r"[vV]\s*$", "", s).strip()
    try:
        return round(float(s), 3)
    except ValueError:
        return None


def rule_erc014(design: Design) -> list[ERCViolation]:
    """Detect components declaring different supply voltages on the same net.

    Generalised from a hardcoded 3.3 V vs 5 V check to any two distinct declared
    supply voltages (1.8/3.3, 3.3/5, 5/12, …), so cross-domain shorts are caught
    for every rail — not just the one hardcoded pair. (voltage-domain.)
    """
    violations: list[ERCViolation] = []
    for net in design.nets.values():
        if net.type != NetType.POWER:
            continue
        voltages: dict[float, set[str]] = {}
        for node in net.nodes:
            comp = design.get_component(node.component_ref)
            if comp is None:
                continue
            volts = _parse_supply_voltage(comp.voltage_supply)
            if volts is not None:
                voltages.setdefault(volts, set()).add(comp.ref)
        if len(voltages) >= 2:
            listed = ", ".join(f"{v:g}V" for v in sorted(voltages))
            violations.append(
                ERCViolation(
                    rule_id="ERC014",
                    severity=ERCSeverity.ERROR,
                    message=f"Net '{net.name}' connects components of different supply voltages ({listed}) — voltage mismatch",  # noqa: E501
                    net_refs=[net.id],
                    component_refs=sorted({ref for refs in voltages.values() for ref in refs}),
                    patch_suggestion="Use a level shifter or separate power nets for each voltage domain",
                )
            )
    return violations


def rule_erc015(design: Design) -> list[ERCViolation]:
    """Detect multiple GND nets not joined."""
    violations: list[ERCViolation] = []
    gnd_nets = [n for n in design.nets.values() if n.type == NetType.GROUND]
    if len(gnd_nets) > 1:
        names = [n.name for n in gnd_nets]
        violations.append(
            ERCViolation(
                rule_id="ERC015",
                severity=ERCSeverity.ERROR,
                message=f"Multiple ground nets found: {names}. All grounds must be connected.",
                net_refs=[n.id for n in gnd_nets],
                patch_suggestion="Join all ground nets into a single GND net or use a 0-ohm jumper",
            )
        )
    return violations


_RESET_PIN_NAMES = {"NRST", "RESET", "RST", "nRESET", "RSTB", "RUN"}


def _reset_pin_violation(
    design: Design,
    graph: ElectricalGraph,
    comp: Component,
    pin_name: str,
    pin: Pin,
) -> ERCViolation | None:
    if pin_name not in _RESET_PIN_NAMES or not pin.net:
        return None
    net = design.nets.get(pin.net) or next((item for item in design.nets.values() if item.name == pin.net), None)
    if net is None or net.type == NetType.POWER or graph.has_resistor_to_power(net.id):
        return None
    return ERCViolation(
        rule_id="ERC016",
        severity=ERCSeverity.INFO,
        message=f"{comp.ref}.{pin_name} reset pin is not held high (no pull-up or rail tie)",
        component_refs=[comp.ref],
        patch_suggestion=f"Add a 10k pull-up resistor from {pin_name} to VCC",
    )


def rule_erc016(design: Design) -> list[ERCViolation]:
    """Check reset pins are held high — tied to a power rail or pulled up to one.

    A reset pin is satisfied if its net *is* a power rail (tied high directly)
    or a resistor on that net bridges to a power/ground rail (pull-up). The
    previous check counted any resistor sharing the net regardless of where it
    went, and missed direct-to-rail resets and "R"/"Resistor"-typed parts.
    (graph/pin connectivity, not loose heuristics.)
    """
    graph = ElectricalGraph.from_design(design)
    violations: list[ERCViolation] = []
    for comp in design.components.values():
        for pin_name, pin in comp.pins.items():
            violation = _reset_pin_violation(design, graph, comp, pin_name, pin)
            if violation is not None:
                violations.append(violation)
    return violations


def rule_erc017(design: Design) -> list[ERCViolation]:
    """Detect duplicate component references."""
    violations: list[ERCViolation] = []
    ref_counts = Counter(c.ref for c in design.components.values())
    for ref, count in ref_counts.items():
        if count > 1:
            ids = [c.id for c in design.components.values() if c.ref == ref]
            violations.append(
                ERCViolation(
                    rule_id="ERC017",
                    severity=ERCSeverity.ERROR,
                    message=f"Reference '{ref}' is used {count} times (IDs: {ids})",
                    component_refs=ids,
                    patch_suggestion=f"Rename duplicate references to unique values (e.g., {ref}_A, {ref}_B)",
                )
            )
    return violations


def rule_erc018(design: Design) -> list[ERCViolation]:
    """Check for test points on debug/protocol nets."""
    violations: list[ERCViolation] = []
    protocol_keywords = {"uart", "i2c", "swd", "spi"}
    for net in design.nets.values():
        if any(kw in net.name.lower() for kw in protocol_keywords):
            has_test_point = any(
                (candidate := design.get_component(n.component_ref)) is not None and "tp" in candidate.ref.lower()
                for n in net.nodes
            )
            if not has_test_point:
                violations.append(
                    ERCViolation(
                        rule_id="ERC018",
                        severity=ERCSeverity.INFO,
                        message=f"Net '{net.name}' ({net.type.value}) has no test point",
                        net_refs=[net.id],
                        patch_suggestion=f"Add a test point (TP) on {net.name} for debugging",
                    )
                )
    return violations


def rule_erc019(design: Design) -> list[ERCViolation]:
    """Check for illegal characters in net names."""
    violations: list[ERCViolation] = []
    for net in design.nets.values():
        if INVALID_NET_NAME_RE.search(net.name):
            violations.append(
                ERCViolation(
                    rule_id="ERC019",
                    severity=ERCSeverity.INFO,
                    message=f"Net name '{net.name}' contains illegal characters",
                    net_refs=[net.id],
                    patch_suggestion="Use only letters, digits, underscores, and hyphens in net names",
                )
            )
    return violations


def rule_erc020(design: Design) -> list[ERCViolation]:
    """Detect components with no footprint."""
    violations: list[ERCViolation] = []
    for comp in design.components.values():
        if not comp.footprint:
            violations.append(
                ERCViolation(
                    rule_id="ERC020",
                    severity=ERCSeverity.WARNING,
                    message=f"{comp.ref} ({comp.type}) has no footprint assigned",
                    component_refs=[comp.ref],
                    patch_suggestion=f"Assign a footprint to {comp.ref}",
                )
            )
    return violations


_USBC_TYPE_KEYWORDS = ("usb-c", "usbc", "usb_c", "type-c", "typec", "usb_type_c")
_USBC_CC_RD_VALUES = {"5.1k", "5k1", "5.1K", "5K1"}
# Underscore is a word char, so \b does not fire in names like "SPI_CS";
# use explicit non-alphanumeric boundaries instead.
_CS_NET_RE = re.compile(r"(?<![a-z0-9])(?:cs|ss|nss|csb|ssel|ncs)\d*(?![a-z0-9])", re.IGNORECASE)
_CS_PULLUP_VALUES = {"10k", "4.7k", "47k", "22k", "100k", "1k"}


def rule_erc021(design: Design) -> list[ERCViolation]:
    """Check USB-C connectors have CC pin termination resistors.

    A USB-C sink (UFP) needs an Rd (5.1k) from each CC pin to GND, or it will
    never be detected by the host. Detection is structural: a USB-C component
    type plus CC/CC1/CC2 pins, then a CC-to-rail termination resistor.
    """
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    for comp in design.components.values():
        type_lower = comp.type.lower()
        if not any(kw in type_lower for kw in _USBC_TYPE_KEYWORDS):
            continue
        for pin_name in comp.pins:
            if pin_name.upper() not in ("CC", "CC1", "CC2"):
                continue
            net = design.get_net_for_pin(comp.ref, pin_name)
            if net is None:
                continue
            if not graph.has_resistor_to_power(net.id, _USBC_CC_RD_VALUES):
                violations.append(
                    ERCViolation(
                        rule_id="ERC021",
                        severity=ERCSeverity.WARNING,
                        message=f"{comp.ref}.{pin_name} (USB-C CC) has no termination resistor",
                        component_refs=[comp.ref],
                        net_refs=[net.id],
                        patch_suggestion="Add a 5.1k resistor from each CC pin to GND (sink/UFP), or Rp for a source",
                    )
                )
    return violations


def rule_erc022(design: Design) -> list[ERCViolation]:
    """Check SPI chip-select nets have an idle pull-up resistor.

    Without a pull-up, a peripheral's CS can float (and the device be spuriously
    selected) while the MCU is in reset or its GPIOs are high-impedance.
    """
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    for net in design.nets.values():
        if net.type in (NetType.POWER, NetType.GROUND):
            continue
        if not _CS_NET_RE.search(net.name):
            continue
        if not graph.has_resistor_to_power(net.id, _CS_PULLUP_VALUES):
            violations.append(
                ERCViolation(
                    rule_id="ERC022",
                    severity=ERCSeverity.INFO,
                    message=f"SPI chip-select net '{net.name}' has no idle pull-up resistor",
                    net_refs=[net.id],
                    patch_suggestion="Add a 10k-100k pull-up from the CS net to its logic rail",
                )
            )
    return violations


def _pin_net(design: Design, comp: Component, pin_name: str, pin: Pin) -> Net | None:
    if pin.net:
        resolved = design.nets.get(pin.net) or next(
            (net for net in design.nets.values() if net.name == pin.net),
            None,
        )
        if resolved is not None:
            return resolved
    return design.get_net_for_pin(comp.ref, pin_name)


def _erc023_violation(
    design: Design,
    graph: ElectricalGraph,
    comp: Component,
    pin_name: str,
    pin: Pin,
) -> ERCViolation | None:
    if pin.type.value != "no_connect":
        return None
    net = _pin_net(design, comp, pin_name, pin)
    if net is None:
        return None
    others = [
        endpoint
        for endpoint in graph.endpoints(net.id)
        if not (endpoint.component_ref in (comp.ref, comp.id) and endpoint.pin_name == pin_name)
    ]
    if not others:
        return None
    other_refs = sorted({endpoint.component_ref for endpoint in others})
    return ERCViolation(
        rule_id="ERC023",
        severity=ERCSeverity.WARNING,
        message=f"{comp.ref}.{pin_name} is a no-connect pin but is wired to {', '.join(other_refs)}",
        component_refs=[comp.ref],
        net_refs=[net.id],
        patch_suggestion=f"Leave {comp.ref}.{pin_name} unconnected unless the datasheet says otherwise",
    )


def rule_erc023(design: Design) -> list[ERCViolation]:
    """Flag no-connect (NC) pins that are wired to other pins.

    A pin the part marks 'no connect' / 'do not connect' must be left floating;
    wiring it to a net shared with other pins can violate the datasheet and, for
    internally-used NC pins, damage the part. (no-connect intent.)
    """
    graph = ElectricalGraph.from_design(design)
    violations: list[ERCViolation] = []
    for comp in design.components.values():
        for pin_name, pin in comp.pins.items():
            violation = _erc023_violation(design, graph, comp, pin_name, pin)
            if violation is not None:
                violations.append(violation)
    return violations


# RS485 transceiver keywords


# RS485 transceiver keywords and DE/RE pin patterns.
_RS485_TYPE_KEYWORDS = ("rs485", "rs-485", "sp3485", "max485", "sn75176", "lt1785", "max3485")
_RS485_DE_RE_RE = re.compile(r"^(?:de|re|oe|nre|de_re|driver_enable|receiver_enable)$", re.IGNORECASE)
_RS485_PULL_VALUES = {"1k", "4.7k", "10k", "22k", "47k", "100k"}


def _is_rs485_component(comp: Component) -> bool:
    type_lower = comp.type.lower()
    return any(keyword in type_lower for keyword in _RS485_TYPE_KEYWORDS)


def _erc024_violation(
    design: Design,
    graph: ElectricalGraph,
    comp: Component,
    pin_name: str,
) -> ERCViolation | None:
    net = design.get_net_for_pin(comp.ref, pin_name)
    if net is None:
        return ERCViolation(
            rule_id="ERC024",
            severity=ERCSeverity.ERROR,
            message=f"{comp.ref}.{pin_name} (RS485 direction control) is unconnected and will float",
            component_refs=[comp.ref],
            patch_suggestion=f"Pull {comp.ref}.{pin_name} to a defined level via a 10k resistor",
        )
    if graph.is_power_net(net.id) or graph.has_resistor_to_power(net.id, _RS485_PULL_VALUES):
        return None
    return ERCViolation(
        rule_id="ERC024",
        severity=ERCSeverity.WARNING,
        message=(
            f"{comp.ref}.{pin_name} (RS485 direction control) has no pull resistor; direction is undefined at power-up"
        ),
        component_refs=[comp.ref],
        net_refs=[net.id],
        patch_suggestion=f"Add a 10k pull-up or pull-down to fix the idle bus direction for {pin_name}",
    )


def rule_erc024(design: Design) -> list[ERCViolation]:
    """Check RS485 transceivers have DE/RE direction control in a defined state.

    A floating DE pin enables the driver at power-up and will assert RS485 bus
    dominance even when idle. A floating RE pin (active-low) disables the receiver
    unintentionally. Both must be pulled to a defined level.
    """
    graph = ElectricalGraph.from_design(design)
    violations: list[ERCViolation] = []
    for comp in filter(_is_rs485_component, design.components.values()):
        for pin_name in filter(_RS485_DE_RE_RE.match, comp.pins):
            violation = _erc024_violation(design, graph, comp, pin_name)
            if violation is not None:
                violations.append(violation)
    return violations


_SPI_PERIPHERAL_KEYWORDS = (
    "adc",
    "dac",
    "flash",
    "eeprom",
    "sram",
    "spi",
    "accel",
    "gyro",
    "baro",
    "temp",
    "sensor",
    "display",
    "lcd",
    "oled",
    "eth",
    "enc28",
    "w5500",
    "mcp",
)


def rule_erc025(design: Design) -> list[ERCViolation]:
    """Flag SPI chip-select nets shared by more than one peripheral.

    Every SPI slave must have its own dedicated chip-select net; sharing a CS
    between two peripherals selects them simultaneously and corrupts transfers.
    (SPI CS uniqueness.)
    """
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    for net in design.nets.values():
        if net.type in (NetType.POWER, NetType.GROUND):
            continue
        if not _CS_NET_RE.search(net.name):
            continue
        endpoints = graph.endpoints(net.id)
        peripheral_refs: list[str] = []
        for ep in endpoints:
            comp = design.get_component(ep.component_ref)
            if comp is None:
                continue
            type_lower = comp.type.lower()
            if any(kw in type_lower for kw in _PASSIVE_TYPE_KEYWORDS):
                continue
            peripheral_refs.append(comp.ref)
        if len(peripheral_refs) > 2:
            violations.append(
                ERCViolation(
                    rule_id="ERC025",
                    severity=ERCSeverity.ERROR,
                    message=(
                        f"SPI chip-select net '{net.name}' connects to {len(peripheral_refs)} non-passive "
                        f"components ({', '.join(peripheral_refs)}); each SPI slave needs its own CS net"
                    ),
                    net_refs=[net.id],
                    component_refs=peripheral_refs,
                    patch_suggestion="Route separate CS nets — one per SPI peripheral — from the MCU",
                )
            )
    return violations


_LIPO_BATT_KEYWORDS = ("battery", "batt", "lipo", "li-ion", "liion", "cell")
_LIPO_PROT_KEYWORDS = ("dw01", "bq2", "ap9101", "s8261", "mcp73", "tc4056", "ip5306", "lp2771", "protection")


def rule_erc026(design: Design) -> list[ERCViolation]:
    """Check Li-ion/LiPo batteries have an overdischarge/overcurrent protection IC.

    An unprotected LiPo can be discharged below 2.5 V, causing permanent damage
    or thermal runaway. A dedicated protection IC (or a charger IC with built-in
    protection, e.g. BQ24xxx) must be present on the same design.
    (charger/battery protection.)
    """
    violations: list[ERCViolation] = []
    battery_refs: list[str] = []
    for comp in design.components.values():
        type_lower = comp.type.lower()
        if any(kw in type_lower for kw in _LIPO_BATT_KEYWORDS):
            battery_refs.append(comp.ref)
    if not battery_refs:
        return violations
    has_protection = any(
        any(kw in comp.type.lower() for kw in _LIPO_PROT_KEYWORDS) for comp in design.components.values()
    )
    if not has_protection:
        violations.append(
            ERCViolation(
                rule_id="ERC026",
                severity=ERCSeverity.WARNING,
                message=(
                    f"Li-ion/LiPo battery ({', '.join(battery_refs)}) detected but no protection IC found; "
                    "overdischarge or overcurrent can permanently damage the cell"
                ),
                component_refs=battery_refs,
                patch_suggestion=(
                    "Add a protection IC (e.g. DW01A + FS8205A) or a charger with built-in protection "
                    "(e.g. BQ24xxx, MCP73xxx)"
                ),
            )
        )
    return violations


# ---------------------------------------------------------------------------
# ERC027: Power-tree completeness — every power net must have a driving source
# ---------------------------------------------------------------------------

_REGULATOR_TYPE_KEYWORDS = (
    "regulator",
    "ldo",
    "buck",
    "boost",
    "buck-boost",
    "dc-dc",
    "dcdc",
    "tlv",
    "tps",
    "max",
    "lt",
    "adp",
    "mic",
    "mcp",
)

# Magnetics that pass a switching-regulator output to its filter cap / load.
_INDUCTOR_KEYWORDS = ("inductor", "choke", "ferrite")


def _is_power_source_component(comp: Component, pin_name: str) -> bool:
    """True if *comp* can drive a power net through *pin_name*.

    A driver is an explicit output pin, a regulator/power-source component, or an
    input connector — the same notions ERC007 and ERC027 share.
    """
    pin = comp.pins.get(pin_name)
    if pin is not None and pin.type.value == "output":
        return True
    type_lower = comp.type.lower()
    if any(kw in type_lower for kw in _REGULATOR_TYPE_KEYWORDS):
        return True
    return any(kw in type_lower for kw in _CONNECTOR_TYPE_KEYWORDS)


def _component_type_contains(comp: Component, keywords: tuple[str, ...]) -> bool:
    """Whether a component type contains one of the normalized keywords."""
    type_lower = comp.type.lower()
    return any(keyword in type_lower for keyword in keywords)


def _net_has_direct_power_source(design: Design, net: Net) -> bool:
    """Whether a net directly contains an output, regulator, or connector."""
    return any(
        component is not None and _is_power_source_component(component, node.pin_name)
        for node in net.nodes
        if (component := design.get_component(node.component_ref)) is not None
    )


def _net_contains_component_reference(net: Net, component_ref: str) -> bool:
    """Whether a net contains the exact serialized component reference."""
    return any(node.component_ref == component_ref for node in net.nodes)


def _net_has_regulator_component(design: Design, net: Net) -> bool:
    """Whether a net contains a component classified as a regulator."""
    return any(
        component is not None and _component_type_contains(component, _REGULATOR_TYPE_KEYWORDS)
        for node in net.nodes
        if (component := design.get_component(node.component_ref)) is not None
    )


def _inductor_connects_to_regulator(design: Design, source_net_id: str, component_ref: str) -> bool:
    """Whether an inductor reference reaches a regulator on another net."""
    return any(
        other.id != source_net_id
        and _net_contains_component_reference(other, component_ref)
        and _net_has_regulator_component(design, other)
        for other in design.nets.values()
    )


def _power_net_has_source(design: Design, net_id: str) -> bool:
    """Whether a power net is driven directly or through regulator magnetics."""
    net = design.nets.get(net_id)
    if net is None:
        return False
    if _net_has_direct_power_source(design, net):
        return True
    return any(
        component is not None
        and _component_type_contains(component, _INDUCTOR_KEYWORDS)
        and _inductor_connects_to_regulator(design, net_id, node.component_ref)
        for node in net.nodes
        if (component := design.get_component(node.component_ref)) is not None
    )


def rule_erc027(design: Design) -> list[ERCViolation]:
    """Check power-tree completeness: every power net needs a source.

    A power net is considered "fed" if:
    - It has at least one output pin (regulator or power-source output), OR
    - It is connected to an input connector/power-source component, OR
    - It is a ground net.

    Power nets with no identified source are flagged; they cannot supply
    current. (power-tree completeness.)
    """
    violations: list[ERCViolation] = []

    for net in design.nets.values():
        if net.type == NetType.GROUND:
            continue
        if net.type != NetType.POWER:
            continue

        if not _power_net_has_source(design, net.id):
            violations.append(
                ERCViolation(
                    rule_id="ERC027",
                    severity=ERCSeverity.WARNING,
                    message=f"Power net '{net.name}' has no identified driving source (no regulator, output pin, or connector on this net)",  # noqa: E501
                    net_refs=[net.id],
                    patch_suggestion=(
                        f"Verify that '{net.name}' is fed by a regulator, power-source output, or external connector"
                    ),
                )
            )
    return violations


# ---------------------------------------------------------------------------
# ERC028: Regulator headroom and current budget
# ---------------------------------------------------------------------------

# Common regulator output current keywords for value strings (amps).
_CURRENT_A_PATTERN = re.compile(r"(\d{1,12}(?:\.\d{1,12})?)\s{0,32}A", re.IGNORECASE)
_CURRENT_MA_PATTERN = re.compile(r"(\d{1,12}(?:\.\d{1,12})?)\s{0,32}ma", re.IGNORECASE)


def _parse_current(raw: str) -> float | None:
    """Parse a current value string to amperes."""
    if not raw:
        return None
    m = _CURRENT_A_PATTERN.search(raw)
    if m:
        return float(m.group(1))
    m = _CURRENT_MA_PATTERN.search(raw)
    if m:
        return float(m.group(1)) / 1000.0
    # Bare number with no unit — assume mA if > 1, else A.
    try:
        v = float(raw)
        return v / 1000.0 if v > 10 else v
    except ValueError:
        return None


def _regulator_kind(comp: Component) -> str | None:
    type_lower = comp.type.lower()
    if "buck" in type_lower:
        return "buck"
    if "boost" in type_lower:
        return "boost"
    if "ldo" in type_lower or "linear" in type_lower:
        return "linear"
    return None


def _regulator_net_ids(comp: Component) -> tuple[set[str], set[str]]:
    output_nets = {pin.net for pin in comp.pins.values() if pin.type.value == "output" and pin.net is not None}
    input_nets = {pin.net for pin in comp.pins.values() if pin.type.value == "power" and pin.net is not None}
    return output_nets, input_nets


def _erc028_headroom_violations(
    design: Design,
    comp: Component,
    kind: str,
    output_nets: set[str],
    input_nets: set[str],
) -> list[ERCViolation]:
    if kind != "buck" or not input_nets or not output_nets or not comp.voltage_supply:
        return []
    vin = _parse_supply_voltage(comp.voltage_supply)
    if vin is None or vin > 0.5:
        return []
    return [
        ERCViolation(
            rule_id="ERC028",
            severity=ERCSeverity.WARNING,
            message=f"{comp.ref} buck regulator input ({vin:g}V) may be too low to regulate",
            component_refs=[comp.ref],
            patch_suggestion=f"Verify {comp.ref} input voltage is above its minimum operating voltage",
        )
        for net_id in output_nets
        if design.nets.get(net_id) is not None
    ]


def _estimated_load_current(design: Design, regulator_ref: str, output_nets: set[str]) -> float:
    total = 0.0
    for net_id in output_nets:
        net = design.nets.get(net_id)
        if net is None:
            continue
        for node in net.nodes:
            load_comp = design.get_component(node.component_ref)
            if load_comp is None or load_comp.ref == regulator_ref:
                continue
            load_value = _parse_current(load_comp.value or "")
            if load_value is not None:
                total += load_value
    return total


def _erc028_current_budget_violation(
    design: Design,
    comp: Component,
    output_nets: set[str],
) -> ERCViolation | None:
    max_current_a = comp.current_rating
    if max_current_a is None or max_current_a <= 0:
        return None
    load_current_a = _estimated_load_current(design, comp.ref, output_nets)
    if load_current_a <= max_current_a * 1.1:
        return None
    return ERCViolation(
        rule_id="ERC028",
        severity=ERCSeverity.WARNING,
        message=(
            f"{comp.ref} regulator rated for {max_current_a:g}A but loads on its output "
            f"net total ~{load_current_a:g}A — current budget exceeded"
        ),
        component_refs=[comp.ref],
        net_refs=list(output_nets),
        patch_suggestion=f"Choose a regulator rated for at least {load_current_a:g}A, or reduce load",
    )


def rule_erc028(design: Design) -> list[ERCViolation]:
    """Check regulator headroom and current budget.

    For components whose type contains regulator keywords, verify regulator
    input headroom and output current budget without hiding either result.
    """
    violations: list[ERCViolation] = []
    for comp in design.components.values():
        kind = _regulator_kind(comp)
        if kind is None:
            continue
        output_nets, input_nets = _regulator_net_ids(comp)
        violations.extend(_erc028_headroom_violations(design, comp, kind, output_nets, input_nets))
        current_violation = _erc028_current_budget_violation(design, comp, output_nets)
        if current_violation is not None:
            violations.append(current_violation)
    return violations


# ---------------------------------------------------------------------------
# ERC029: DNP/variant-aware ERC
# ---------------------------------------------------------------------------


def _net_components_of_types(design: Design, net: Net, component_types: set[str]) -> list[Component]:
    components: list[Component] = []
    for node in net.nodes:
        comp = design.get_component(node.component_ref)
        if comp is not None and comp.type.upper() in component_types:
            components.append(comp)
    return components


def _erc029_power_violation(design: Design, net: Net) -> ERCViolation | None:
    if net.type != NetType.POWER:
        return None
    caps_on_net = _net_components_of_types(design, net, _CAP_TYPES)
    if not caps_on_net or not all(comp.dnp for comp in caps_on_net):
        return None
    return ERCViolation(
        rule_id="ERC029",
        severity=ERCSeverity.WARNING,
        message=(
            f"All decoupling capacitors on power net '{net.name}' are DNP — no decoupling in the populated variant"
        ),
        net_refs=[net.id],
        component_refs=[comp.ref for comp in caps_on_net],
        patch_suggestion="Review DNP assignments: at least one decoupling cap per power rail must be populated",
    )


def _is_i2c_net(net: Net) -> bool:
    return "i2c" in net.name.lower() or net.name in ("I2C_SDA", "I2C_SCL")


def _erc029_i2c_violation(design: Design, net: Net) -> ERCViolation | None:
    if not _is_i2c_net(net):
        return None
    pullups_on_net = _net_components_of_types(design, net, _RES_TYPES)
    if not pullups_on_net or not all(comp.dnp for comp in pullups_on_net):
        return None
    return ERCViolation(
        rule_id="ERC029",
        severity=ERCSeverity.ERROR,
        message=f"I2C net '{net.name}' has all pull-up resistors DNP — bus will not work",
        net_refs=[net.id],
        component_refs=[comp.ref for comp in pullups_on_net],
        patch_suggestion="Ensure at least one pull-up resistor per I2C line is populated in all variants",
    )


def rule_erc029(design: Design) -> list[ERCViolation]:
    """Check critical power and I2C support components are populated."""
    if not any(comp.dnp for comp in design.components.values()):
        return []
    violations: list[ERCViolation] = []
    for net in design.nets.values():
        power_violation = _erc029_power_violation(design, net)
        if power_violation is not None:
            violations.append(power_violation)
        i2c_violation = _erc029_i2c_violation(design, net)
        if i2c_violation is not None:
            violations.append(i2c_violation)
    return violations


# Backward-compatible module attributes for callers that imported the historic
# mixed-case rule names. Canonical code and discovery use PEP 8-compliant names.
RuleFunction = Callable[[Design], list[ERCViolation]]
_LEGACY_RULE_FUNCTIONS: dict[str, RuleFunction] = {
    "rule_ERC001": rule_erc001,
    "rule_ERC002": rule_erc002,
    "rule_ERC003": rule_erc003,
    "rule_ERC004": rule_erc004,
    "rule_ERC005": rule_erc005,
    "rule_ERC006": rule_erc006,
    "rule_ERC007": rule_erc007,
    "rule_ERC008": rule_erc008,
    "rule_ERC009": rule_erc009,
    "rule_ERC010": rule_erc010,
    "rule_ERC011": rule_erc011,
    "rule_ERC012": rule_erc012,
    "rule_ERC013": rule_erc013,
    "rule_ERC014": rule_erc014,
    "rule_ERC015": rule_erc015,
    "rule_ERC016": rule_erc016,
    "rule_ERC017": rule_erc017,
    "rule_ERC018": rule_erc018,
    "rule_ERC019": rule_erc019,
    "rule_ERC020": rule_erc020,
    "rule_ERC021": rule_erc021,
    "rule_ERC022": rule_erc022,
    "rule_ERC023": rule_erc023,
    "rule_ERC024": rule_erc024,
    "rule_ERC025": rule_erc025,
    "rule_ERC026": rule_erc026,
    "rule_ERC027": rule_erc027,
    "rule_ERC028": rule_erc028,
    "rule_ERC029": rule_erc029,
}


def __getattr__(name: str) -> RuleFunction:
    try:
        return _LEGACY_RULE_FUNCTIONS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LEGACY_RULE_FUNCTIONS.keys())
