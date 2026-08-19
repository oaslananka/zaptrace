"""Peripheral synthesis: place real sensors and hang them on the MCU's bus.

Functional-core synthesis (:mod:`zaptrace.synthesis.mcu`) gives the board a brain
and an I2C bus, but nothing to talk to. This adds the peripherals the intent asks
for: it picks a real sensor part for the requested measurement, places it, ties
its power pins to the rail, and drops it onto the existing I2C bus (the same SDA/
SCL nets the MCU and pull-ups are on). The result fulfils the intent — an "I2C
temperature sensor board" gets an actual temperature sensor, not an empty bus.

Deterministic: sensor selection is keyword-driven with a fixed rule order, and
parts mount in that order. Honest: a measurement with no library part, or an
intent with no I2C bus to hang a sensor on, is reported, never faked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from zaptrace.core.models import Component, Net, NetNode, Pin, PinType
from zaptrace.library.loader import LibraryLoader

if TYPE_CHECKING:
    from zaptrace.core.models import Design
    from zaptrace.synthesis.requirements import Requirements

# Keyword sets -> the I2C sensor part to place, in priority order. First rule a
# token hits wins for that measurement; several rules can match one intent.
_SENSOR_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("humidity", "climate", "rht"), "sht31-dis", "temperature/humidity"),
    (("temperature", "temp ", "thermo"), "sht31-dis", "temperature/humidity"),
    (("pressure", "barometer", "altitude", "baro"), "bmp390", "pressure/altitude"),
    (("accelerom", "imu", "motion", "accel", "tilt", "vibration"), "lis3dh", "accelerometer"),
    (("adc", "analog input", "analog-to-digital"), "ads1115", "ADC"),
    (("air quality", "gas", "voc", "co2"), "bme688", "air-quality/gas"),
]
# A bare "sensor" mention with an I2C bus but no specific measurement.
_DEFAULT_I2C_SENSOR = ("bme280", "environmental")

# Keyword sets -> the SPI peripheral to place. Requires an SPI bus to hang on.
_STORAGE_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("flash", "nor flash", "storage", "spi memory", "datalog", "data log", "logger"), "w25q128jv", "SPI NOR flash"),
]

_SUPPLY_NAMES = {"VDD", "VCC", "VDDIO"}
_GROUND_NAMES = {"GND", "VSS"}
_I2C_DATA_NAMES = {"SDA", "SDI"}
_I2C_CLK_NAMES = {"SCL", "SCK"}
_I2C_ADDR_NAMES = {"ADDR", "SA0", "SDO"}  # address-select: tie to GND (default address)
_I2C_MODE_HIGH_NAMES = {"CSB", "CS"}  # tie high to select I2C mode on dual-mode parts
# Active-low reset inputs: tie high to the rail so the part runs (not held in reset).
_ACTIVE_LOW_RESET_NAMES = {"NRESET", "NRST", "RESET_N", "RST_N", "RESET#", "RST#"}
_SPI_CLK_NAMES = {"CLK", "SCK", "SCLK"}
_SPI_MOSI_NAMES = {"DI", "MOSI", "SI", "IO0"}
_SPI_MISO_NAMES = {"DO", "MISO", "SO", "IO1"}
_SPI_CS_NAMES = {"CS", "NCS", "SS"}
_SPI_HOLD_HIGH_NAMES = {"WP", "HOLD"}  # tie high for normal (non-quad) operation


@dataclass(frozen=True)
class PeripheralChoice:
    """A peripheral the planner decided to place, and why."""

    part_id: str
    function: str
    bus: str  # "i2c" | "spi"
    realized: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "function": self.function,
            "bus": self.bus,
            "realized": self.realized,
            "reason": self.reason,
        }


def plan_sensors(requirements: Requirements) -> list[PeripheralChoice]:
    """Pick the I2C sensors an intent calls for (deduplicated, deterministic).

    Returns an empty list when there is no I2C bus to hang a sensor on, so a
    sensor is never placed with nowhere to connect.
    """
    if "i2c" not in requirements.interfaces:
        return []
    text = requirements.raw_intent.lower()
    chosen: list[PeripheralChoice] = []
    seen: set[str] = set()
    for keywords, part_id, function in _SENSOR_RULES:
        if any(kw in text for kw in keywords) and part_id not in seen:
            seen.add(part_id)
            chosen.append(PeripheralChoice(part_id, function, "i2c", _part_exists(part_id)))
    if not chosen and "sensor" in text:
        part_id, function = _DEFAULT_I2C_SENSOR
        chosen.append(PeripheralChoice(part_id, function, "i2c", _part_exists(part_id)))
    return chosen


def plan_storage(requirements: Requirements) -> list[PeripheralChoice]:
    """Pick the SPI storage an intent calls for. Needs an SPI bus to hang on."""
    if "spi" not in requirements.interfaces:
        return []
    text = requirements.raw_intent.lower()
    chosen: list[PeripheralChoice] = []
    seen: set[str] = set()
    for keywords, part_id, function in _STORAGE_RULES:
        if any(kw in text for kw in keywords) and part_id not in seen:
            seen.add(part_id)
            chosen.append(PeripheralChoice(part_id, function, "spi", _part_exists(part_id)))
    return chosen


def _part_exists(part_id: str) -> bool:
    return part_id in LibraryLoader().load_all()


def _pin_type(raw: dict[str, str]) -> PinType:
    try:
        return PinType(raw.get("type", "bidirectional"))
    except ValueError:
        return PinType.BIDIRECTIONAL


def _next_ref(design: Design, prefix: str) -> str:
    idx = 1
    while f"{prefix}{idx}" in design.components:
        idx += 1
    return f"{prefix}{idx}"


def _connect(design: Design, net_name: str, ref: str, pin: str) -> None:
    if net_name not in design.nets:
        design.nets[net_name] = Net(id=net_name, name=net_name)
    design.nets[net_name].nodes.append(NetNode(component_ref=ref, pin_name=pin))


def _find_pin(spec_pins: dict[str, dict[str, str]], names: set[str]) -> str | None:
    for name in spec_pins:
        if name.upper() in names:
            return name
    return None


def _place_eth_crystal(design: Design, w5500_ref: str, spec_pins: dict[str, dict[str, str]], *, gnd_net: str) -> None:
    """Place the W5500's 25 MHz crystal with load caps across XTAL1/XTAL2."""
    xtal_in = _find_pin(spec_pins, {"XTAL1", "XI", "XIN"})
    xtal_out = _find_pin(spec_pins, {"XTAL2", "XO", "XOUT"})
    if xtal_in is None or xtal_out is None:
        return
    spec = LibraryLoader().get("crystal-25mhz")
    y_ref = _next_ref(design, "Y")
    design.components[y_ref] = Component(
        id=y_ref,
        ref=y_ref,
        type="crystal",
        value=spec.name,
        mpn=spec.mpn,
        footprint=spec.footprint,
        pins={name: Pin(name=name, type=_pin_type(raw)) for name, raw in spec.pins.items()},
        package_pin_map=dict(spec.package_pin_map),
    )
    for mcu_pin, xtal_pin, net in ((xtal_in, "XI", "ETH_XTAL_IN"), (xtal_out, "XO", "ETH_XTAL_OUT")):
        _connect(design, net, w5500_ref, mcu_pin)
        _connect(design, net, y_ref, xtal_pin)
        cap = _next_ref(design, "C")
        design.components[cap] = Component(id=cap, ref=cap, type="capacitor", value="18pF")
        _connect(design, net, cap, "1")
        _connect(design, gnd_net, cap, "2")


def _component_from_spec(ref: str, component_type: str, spec: Any) -> Component:
    return Component(
        id=ref,
        ref=ref,
        type=component_type,
        value=spec.name,
        mpn=spec.mpn,
        footprint=spec.footprint,
        pins={name: Pin(name=name, type=_pin_type(raw)) for name, raw in spec.pins.items()},
        package_pin_map=dict(spec.package_pin_map),
    )


def _wire_declared_pins(
    design: Design,
    ref: str,
    spec_pins: dict[str, dict[str, str]],
    pin_nets: tuple[tuple[str, str], ...],
) -> None:
    for pin, net in pin_nets:
        if pin in spec_pins:
            _connect(design, net, ref, pin)


def _wire_w5500_control(
    design: Design,
    ref: str,
    pins: dict[str, dict[str, str]],
    *,
    rail_net: str,
    gnd_net: str,
    spi_nets: tuple[str, str, str, str],
) -> None:
    for name, raw in pins.items():
        if raw.get("type") == "power":
            _connect(design, gnd_net if name.upper() in _GROUND_NAMES else rail_net, ref, name)
    _wire_declared_pins(
        design,
        ref,
        pins,
        tuple(zip(("SCLK", "MOSI", "MISO", "SCS"), spi_nets, strict=True)),
    )
    _wire_declared_pins(
        design,
        ref,
        pins,
        tuple((pin, rail_net) for pin in ("PMODE1", "PMODE2", "PMODE3", "RST")),
    )
    _wire_declared_pins(design, ref, pins, (("TEST", gnd_net),))


def _place_decoupling_capacitor(
    design: Design,
    *,
    rail_net: str,
    gnd_net: str,
    value: str = "100nF",
) -> str:
    ref = _next_ref(design, "C")
    design.components[ref] = Component(id=ref, ref=ref, type="capacitor", value=value)
    _connect(design, rail_net, ref, "1")
    _connect(design, gnd_net, ref, "2")
    return ref


def _place_ethernet_jack(
    design: Design,
    controller_ref: str,
    controller_pins: dict[str, dict[str, str]],
    jack_spec: Any,
    *,
    gnd_net: str,
) -> str:
    jack_ref = _next_ref(design, "J")
    design.components[jack_ref] = _component_from_spec(jack_ref, "connector", jack_spec)
    for controller_pin, jack_pin, net in (
        ("TXP", "TX_P", "ETH_TXP"),
        ("TXN", "TX_N", "ETH_TXN"),
        ("RXP", "RX_P", "ETH_RXP"),
        ("RXN", "RX_N", "ETH_RXN"),
    ):
        if controller_pin in controller_pins and jack_pin in jack_spec.pins:
            _connect(design, net, controller_ref, controller_pin)
            _connect(design, net, jack_ref, jack_pin)
    _wire_declared_pins(
        design,
        jack_ref,
        jack_spec.pins,
        (("GND", gnd_net), ("SHIELD", gnd_net)),
    )
    return jack_ref


def instantiate_ethernet(
    design: Design,
    *,
    rail_net: str,
    gnd_net: str = "GND",
    sclk_net: str = "ETH_SCLK",
    mosi_net: str = "ETH_MOSI",
    miso_net: str = "ETH_MISO",
    scs_net: str = "ETH_SCS",
) -> str | None:
    """Place a W5500 Ethernet controller and complete RJ45 front-end.

    The controller joins the MCU-mastered SPI bus, receives power, clock,
    reset, and mode straps, and connects its differential pairs to an RJ45
    jack with integrated magnetics. The returned reference identifies the
    W5500 component. Mode pins select all-capable auto-negotiation, reset is
    held high, and test mode is held low.
    """
    loader = LibraryLoader()
    controller_spec = loader.get("w5500")
    jack_spec = loader.get("rj45-8p")
    controller_ref = _next_ref(design, "U")
    design.components[controller_ref] = _component_from_spec(controller_ref, "ic", controller_spec)
    _wire_w5500_control(
        design,
        controller_ref,
        controller_spec.pins,
        rail_net=rail_net,
        gnd_net=gnd_net,
        spi_nets=(sclk_net, mosi_net, miso_net, scs_net),
    )
    _place_eth_crystal(design, controller_ref, controller_spec.pins, gnd_net=gnd_net)
    _place_decoupling_capacitor(design, rail_net=rail_net, gnd_net=gnd_net)
    _place_ethernet_jack(
        design,
        controller_ref,
        controller_spec.pins,
        jack_spec,
        gnd_net=gnd_net,
    )
    return controller_ref


def instantiate_sensor(
    design: Design,
    part_id: str,
    *,
    rail_net: str,
    gnd_net: str = "GND",
    sda_net: str = "SDA",
    scl_net: str = "SCL",
) -> str | None:
    """Place one I2C sensor and wire its power and bus pins. Returns its ref.

    Power pins tie to ``rail_net``/``gnd_net``; the data/clock pins (whatever the
    part names them — SDA/SDI, SCL/SCK) join the board's I2C bus nets; an address
    pin is tied to GND for the default address. A 100 nF bypass is added on the
    rail. Mode/chip-select pins are left for a human (part-specific).
    """
    spec = LibraryLoader().get(part_id)
    supply_pin = _find_pin(spec.pins, _SUPPLY_NAMES)
    ground_pin = _find_pin(spec.pins, _GROUND_NAMES)
    data_pin = _find_pin(spec.pins, _I2C_DATA_NAMES)
    clock_pin = _find_pin(spec.pins, _I2C_CLK_NAMES)
    if supply_pin is None or ground_pin is None or data_pin is None or clock_pin is None:
        return None  # not an I2C part we can wire confidently

    ref = _next_ref(design, "U")
    design.components[ref] = Component(
        id=ref,
        ref=ref,
        type="sensor",
        value=spec.name,
        mpn=spec.mpn,
        footprint=spec.footprint,
        pins={name: Pin(name=name, type=_pin_type(raw)) for name, raw in spec.pins.items()},
        package_pin_map=dict(spec.package_pin_map),
    )
    # Every power pin (VDD, VDDIO, ...) reaches the rail; grounds reach GND.
    for name, raw in spec.pins.items():
        if raw.get("type") != "power":
            continue
        _connect(design, gnd_net if name.upper() in _GROUND_NAMES else rail_net, ref, name)
    _connect(design, sda_net, ref, data_pin)
    _connect(design, scl_net, ref, clock_pin)
    addr_pin = _find_pin(spec.pins, _I2C_ADDR_NAMES)
    if addr_pin is not None:
        _connect(design, gnd_net, ref, addr_pin)  # default I2C address
    mode_pin = _find_pin(spec.pins, _I2C_MODE_HIGH_NAMES)
    if mode_pin is not None:
        _connect(design, rail_net, ref, mode_pin)  # CS/CSB high selects I2C mode
    reset_pin = _find_pin(spec.pins, _ACTIVE_LOW_RESET_NAMES)
    if reset_pin is not None:
        _connect(design, rail_net, ref, reset_pin)  # active-low reset held high
    properties = getattr(spec, "properties", {})
    for strap_pin in properties.get("ground_strap_pins", []):
        if strap_pin in spec.pins:
            _connect(design, gnd_net, ref, strap_pin)

    # 100 nF decoupling cap on the sensor's rail (footprint assigned by repair).
    cap_ref = _next_ref(design, "C")
    design.components[cap_ref] = Component(id=cap_ref, ref=cap_ref, type="capacitor", value="100nF")
    _connect(design, rail_net, cap_ref, "1")
    _connect(design, gnd_net, cap_ref, "2")
    return ref


def instantiate_spi_flash(
    design: Design,
    part_id: str,
    *,
    rail_net: str,
    gnd_net: str = "GND",
    sck_net: str = "SPI_SCK",
    mosi_net: str = "SPI_MOSI",
    miso_net: str = "SPI_MISO",
    cs_net: str = "SPI_CS",
) -> str | None:
    """Place one SPI flash and wire it to the MCU's SPI bus. Returns its ref.

    Clock/data/CS pins (named CLK/DI/DO/CS or SCK/MOSI/MISO/SS across parts) join
    the SPI bus nets the MCU mastered; write-protect and hold pins are tied high
    for normal operation; a 100 nF bypass is added on the rail.
    """
    spec = LibraryLoader().get(part_id)
    supply_pin = _find_pin(spec.pins, _SUPPLY_NAMES)
    ground_pin = _find_pin(spec.pins, _GROUND_NAMES)
    clk_pin = _find_pin(spec.pins, _SPI_CLK_NAMES)
    mosi_pin = _find_pin(spec.pins, _SPI_MOSI_NAMES)
    miso_pin = _find_pin(spec.pins, _SPI_MISO_NAMES)
    cs_pin = _find_pin(spec.pins, _SPI_CS_NAMES)
    if (
        supply_pin is None
        or ground_pin is None
        or clk_pin is None
        or mosi_pin is None
        or miso_pin is None
        or cs_pin is None
    ):
        return None  # not an SPI part we can wire confidently

    ref = _next_ref(design, "U")
    design.components[ref] = Component(
        id=ref,
        ref=ref,
        type="memory",
        value=spec.name,
        mpn=spec.mpn,
        footprint=spec.footprint,
        pins={name: Pin(name=name, type=_pin_type(raw)) for name, raw in spec.pins.items()},
        package_pin_map=dict(spec.package_pin_map),
    )
    _connect(design, rail_net, ref, supply_pin)
    _connect(design, gnd_net, ref, ground_pin)
    _connect(design, sck_net, ref, clk_pin)
    _connect(design, mosi_net, ref, mosi_pin)
    _connect(design, miso_net, ref, miso_pin)
    _connect(design, cs_net, ref, cs_pin)
    for name in spec.pins:
        if name.upper() in _SPI_HOLD_HIGH_NAMES:
            _connect(design, rail_net, ref, name)  # WP#/HOLD# tied high

    cap_ref = _next_ref(design, "C")
    design.components[cap_ref] = Component(id=cap_ref, ref=cap_ref, type="capacitor", value="100nF")
    _connect(design, rail_net, cap_ref, "1")
    _connect(design, gnd_net, cap_ref, "2")
    return ref
