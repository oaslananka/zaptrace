from typing import Any

from zaptrace.core.models import Block, Component, Design, Net, NetNode
from zaptrace.synthesis.calculators import divider_for_output, i2c_pullup, led_series_resistor


def _ohms_to_str(ohms: float) -> str:
    """Format an ohm value as a human/EDA-friendly string (330, 4.7k, 1M)."""
    if ohms >= 1e6:
        return f"{ohms / 1e6:g}M"
    if ohms >= 1e3:
        return f"{ohms / 1e3:g}k"
    return f"{ohms:g}"


def _add_component(
    design: Design,
    ref_prefix: str,
    comp_type: str,
    value: str,
    dnp: bool = False,
    variants: dict[str, bool] | None = None,
    **kwargs: Any,
) -> str:
    """Helper to add a component with an auto-incrementing reference designator."""
    idx = 1
    while f"{ref_prefix}{idx}" in design.components:
        idx += 1

    ref = f"{ref_prefix}{idx}"
    comp = Component(id=ref, ref=ref, type=comp_type, value=value, dnp=dnp, variants=variants or {}, **kwargs)
    design.components[ref] = comp
    return ref


def _connect_pin(design: Design, net_name: str, comp_ref: str, pin_name: str) -> None:
    """Helper to connect a component pin to a net."""
    if net_name not in design.nets:
        design.nets[net_name] = Net(id=net_name, name=net_name)

    design.nets[net_name].nodes.append(NetNode(component_ref=comp_ref, pin_name=pin_name))


def instantiate_adxl355_decoupling(
    design: Design,
    block_id: str,
    vdd_analog_net: str = "VDDA",
    vdd_digital_net: str = "VDDD",
    gnd_net: str = "GND",
    dnp: bool = False,
    variants: dict[str, bool] | None = None,
) -> Block:
    """
    ADXL355 decoupling network (datasheet Fig. 59: 100nF + 1uF + 10uF per supply).
    """
    components = []

    # VDDA decoupling
    for val in ["100nF", "1uF", "10uF"]:
        c_ref = _add_component(design, "C", "capacitor", val, dnp=dnp, variants=variants)
        components.append(c_ref)
        _connect_pin(design, vdd_analog_net, c_ref, "1")
        _connect_pin(design, gnd_net, c_ref, "2")

    # VDDD decoupling
    for val in ["100nF", "1uF", "10uF"]:
        c_ref = _add_component(design, "C", "capacitor", val, dnp=dnp, variants=variants)
        components.append(c_ref)
        _connect_pin(design, vdd_digital_net, c_ref, "1")
        _connect_pin(design, gnd_net, c_ref, "2")

    block = Block(id=block_id, name="ADXL355_Decoupling", components=components)
    design.blocks.append(block)
    return block


def instantiate_sync_buck_tlv62569(
    design: Design,
    block_id: str,
    vin_net: str = "VIN",
    sw_net: str = "SW",
    vout_net: str = "VOUT",
    gnd_net: str = "GND",
    en_net: str = "EN",
    fb_net: str = "FB",
    inductor_val: str = "2.2uH",
    cin_val: str = "10uF",
    cout_val: str = "22uF",
    dnp: bool = False,
    variants: dict[str, bool] | None = None,
) -> Block:
    """
    Synchronous buck application circuit (e.g. TLV62569).
    Includes the IC, L, Cin, Cout.
    """
    components = []

    u_ref = _add_component(design, "U", "regulator", "TLV62569", dnp=dnp, variants=variants, mpn="TLV62569")
    components.append(u_ref)

    cin_ref = _add_component(design, "C", "capacitor", cin_val, dnp=dnp, variants=variants)
    components.append(cin_ref)

    cout_ref = _add_component(design, "C", "capacitor", cout_val, dnp=dnp, variants=variants)
    components.append(cout_ref)

    l_ref = _add_component(design, "L", "inductor", inductor_val, dnp=dnp, variants=variants)
    components.append(l_ref)

    # Connect U (TLV62569 SOT-23-5: 1=EN, 2=GND, 3=SW, 4=VIN, 5=FB)
    _connect_pin(design, en_net, u_ref, "1")
    _connect_pin(design, gnd_net, u_ref, "2")
    _connect_pin(design, sw_net, u_ref, "3")
    _connect_pin(design, vin_net, u_ref, "4")
    _connect_pin(design, fb_net, u_ref, "5")

    # Connect Cin
    _connect_pin(design, vin_net, cin_ref, "1")
    _connect_pin(design, gnd_net, cin_ref, "2")

    # Connect Cout
    _connect_pin(design, vout_net, cout_ref, "1")
    _connect_pin(design, gnd_net, cout_ref, "2")

    # Connect L
    _connect_pin(design, sw_net, l_ref, "1")
    _connect_pin(design, vout_net, l_ref, "2")

    block = Block(id=block_id, name="Sync_Buck_TLV62569", components=components)
    design.blocks.append(block)
    return block


def instantiate_usb_c_ufp_cc(
    design: Design,
    block_id: str,
    cc1_net: str = "CC1",
    cc2_net: str = "CC2",
    gnd_net: str = "GND",
    dnp: bool = False,
    variants: dict[str, bool] | None = None,
) -> Block:
    """
    USB-C UFP CC termination (2x 5.1kOhm to GND).
    """
    components = []

    r1_ref = _add_component(design, "R", "resistor", "5.1k", dnp=dnp, variants=variants)
    components.append(r1_ref)
    _connect_pin(design, cc1_net, r1_ref, "1")
    _connect_pin(design, gnd_net, r1_ref, "2")

    r2_ref = _add_component(design, "R", "resistor", "5.1k", dnp=dnp, variants=variants)
    components.append(r2_ref)
    _connect_pin(design, cc2_net, r2_ref, "1")
    _connect_pin(design, gnd_net, r2_ref, "2")

    block = Block(id=block_id, name="USB_C_UFP_CC", components=components)
    design.blocks.append(block)
    return block


def instantiate_rj45_bob_smith(
    design: Design,
    block_id: str,
    pair1_center_net: str = "CT1",
    pair2_center_net: str = "CT2",
    pair3_center_net: str = "CT3",
    pair4_center_net: str = "CT4",
    shield_net: str = "SHIELD",
    dnp: bool = False,
    variants: dict[str, bool] | None = None,
) -> Block:
    """
    RJ45 + Bob-Smith termination network.
    4x 75 Ohm resistors to a common point, then 1nF 2kV cap to chassis/shield.
    """
    components = []

    common_net = f"BS_COMMON_{block_id}"

    for net in [pair1_center_net, pair2_center_net, pair3_center_net, pair4_center_net]:
        r_ref = _add_component(design, "R", "resistor", "75", dnp=dnp, variants=variants)
        components.append(r_ref)
        _connect_pin(design, net, r_ref, "1")
        _connect_pin(design, common_net, r_ref, "2")

    c_ref = _add_component(design, "C", "capacitor", "1nF", dnp=dnp, variants=variants, voltage_rating=2000.0)
    components.append(c_ref)
    _connect_pin(design, common_net, c_ref, "1")
    _connect_pin(design, shield_net, c_ref, "2")

    block = Block(id=block_id, name="RJ45_BobSmith", components=components)
    design.blocks.append(block)
    return block


def instantiate_esp32_s3_strapping(
    design: Design,
    block_id: str,
    en_net: str = "EN",
    gpio0_net: str = "GPIO0",
    vdd_net: str = "3V3",
    gnd_net: str = "GND",
    dnp: bool = False,
    variants: dict[str, bool] | None = None,
) -> Block:
    """
    ESP32-S3 strapping + EN RC + bypass block.
    Includes:
    - EN pullup (10k) and capacitor (1uF or 0.1uF, typically 1uF) to GND.
    - GPIO0 pullup (10k) to VDD.
    - Main bypass capacitor (10uF).
    - Optional small bypass (0.1uF).
    """
    components = []

    # EN pullup
    r_en_ref = _add_component(design, "R", "resistor", "10k", dnp=dnp, variants=variants)
    components.append(r_en_ref)
    _connect_pin(design, vdd_net, r_en_ref, "1")
    _connect_pin(design, en_net, r_en_ref, "2")

    # EN capacitor
    c_en_ref = _add_component(design, "C", "capacitor", "1uF", dnp=dnp, variants=variants)
    components.append(c_en_ref)
    _connect_pin(design, en_net, c_en_ref, "1")
    _connect_pin(design, gnd_net, c_en_ref, "2")

    # GPIO0 pullup
    r_boot_ref = _add_component(design, "R", "resistor", "10k", dnp=dnp, variants=variants)
    components.append(r_boot_ref)
    _connect_pin(design, vdd_net, r_boot_ref, "1")
    _connect_pin(design, gpio0_net, r_boot_ref, "2")

    # Main bypass capacitor
    c_bp1_ref = _add_component(design, "C", "capacitor", "10uF", dnp=dnp, variants=variants)
    components.append(c_bp1_ref)
    _connect_pin(design, vdd_net, c_bp1_ref, "1")
    _connect_pin(design, gnd_net, c_bp1_ref, "2")

    # Small bypass capacitor
    c_bp2_ref = _add_component(design, "C", "capacitor", "100nF", dnp=dnp, variants=variants)
    components.append(c_bp2_ref)
    _connect_pin(design, vdd_net, c_bp2_ref, "1")
    _connect_pin(design, gnd_net, c_bp2_ref, "2")

    block = Block(id=block_id, name="ESP32_S3_Strapping", components=components)
    design.blocks.append(block)
    return block


# ---------------------------------------------------------------------------
# Parametric blocks — values are *computed* (via the calculators), not guessed.
# These are the correct-by-construction building blocks for real synthesis.
# ---------------------------------------------------------------------------


def instantiate_led_indicator(
    design: Design,
    block_id: str,
    supply_net: str = "VCC",
    gnd_net: str = "GND",
    *,
    supply_v: float,
    forward_v: float = 2.0,
    current_ma: float = 10.0,
    series: int = 24,
    dnp: bool = False,
    variants: dict[str, bool] | None = None,
) -> Block:
    """LED indicator with a *computed* E-series current-limiting resistor.

    Wiring: ``supply -> R -> LED anode``, ``LED cathode -> gnd``. The resistor is
    sized by :func:`led_series_resistor` so the LED current stays at/under the
    target — no guessed value.
    """
    res = led_series_resistor(supply_v, forward_v, current_ma, series=series)
    components: list[str] = []
    r_ref = _add_component(design, "R", "resistor", _ohms_to_str(res.chosen_ohms), dnp=dnp, variants=variants)
    components.append(r_ref)
    d_ref = _add_component(design, "D", "led", "LED", dnp=dnp, variants=variants)
    components.append(d_ref)
    anode_net = f"{block_id}_LED_A"
    _connect_pin(design, supply_net, r_ref, "1")
    _connect_pin(design, anode_net, r_ref, "2")
    _connect_pin(design, anode_net, d_ref, "ANODE")
    _connect_pin(design, gnd_net, d_ref, "CATHODE")
    block = Block(id=block_id, name="LED_Indicator", components=components)
    design.blocks.append(block)
    return block


def instantiate_i2c_pullups(
    design: Design,
    block_id: str,
    sda_net: str = "SDA",
    scl_net: str = "SCL",
    vdd_net: str = "VCC",
    *,
    supply_v: float = 3.3,
    bus_capacitance_pf: float = 100.0,
    bus_speed_hz: int = 100_000,
    series: int = 24,
    dnp: bool = False,
    variants: dict[str, bool] | None = None,
) -> Block:
    """I2C SDA/SCL pull-ups with a *computed* recommended value (NXP UM10204)."""
    pull = i2c_pullup(supply_v, bus_capacitance_pf, bus_speed_hz=bus_speed_hz, series=series)
    value = _ohms_to_str(pull.recommended_ohms)
    components: list[str] = []
    for signal_net in (sda_net, scl_net):
        r_ref = _add_component(design, "R", "resistor", value, dnp=dnp, variants=variants)
        components.append(r_ref)
        _connect_pin(design, vdd_net, r_ref, "1")
        _connect_pin(design, signal_net, r_ref, "2")
    block = Block(id=block_id, name="I2C_Pullups", components=components)
    design.blocks.append(block)
    return block


def instantiate_voltage_divider(
    design: Design,
    block_id: str,
    in_net: str = "VIN",
    out_net: str = "VOUT",
    gnd_net: str = "GND",
    *,
    input_v: float,
    output_v: float,
    r_bottom: float,
    series: int = 24,
    dnp: bool = False,
    variants: dict[str, bool] | None = None,
) -> Block:
    """Resistive divider with a *computed* top resistor for a target output."""
    div = divider_for_output(input_v, output_v, r_bottom, series=series)
    components: list[str] = []
    rt_ref = _add_component(design, "R", "resistor", _ohms_to_str(div.r_top_ohms), dnp=dnp, variants=variants)
    components.append(rt_ref)
    rb_ref = _add_component(design, "R", "resistor", _ohms_to_str(div.r_bottom_ohms), dnp=dnp, variants=variants)
    components.append(rb_ref)
    _connect_pin(design, in_net, rt_ref, "1")
    _connect_pin(design, out_net, rt_ref, "2")
    _connect_pin(design, out_net, rb_ref, "1")
    _connect_pin(design, gnd_net, rb_ref, "2")
    block = Block(id=block_id, name="Voltage_Divider", components=components)
    design.blocks.append(block)
    return block


def instantiate_ldo(
    design: Design,
    block_id: str,
    vin_net: str = "VIN",
    vout_net: str = "VOUT",
    gnd_net: str = "GND",
    *,
    output_v: float,
    cin_val: str = "1uF",
    cout_val: str = "1uF",
    dnp: bool = False,
    variants: dict[str, bool] | None = None,
) -> Block:
    """Generic 3-terminal LDO regulator with input/output decoupling.

    Wiring (SOT-23-3 LDO: 1=IN, 2=GND, 3=OUT): ``vin -> Cin -> U(IN)``,
    ``U(OUT) -> Cout -> vout``. The output voltage is recorded in the regulator
    value so the part is selectable downstream; the caps follow datasheet-typical
    1 µF in/out for stability.
    """
    components: list[str] = []
    u_ref = _add_component(design, "U", "ldo", f"LDO_{output_v:g}V", dnp=dnp, variants=variants)
    components.append(u_ref)
    cin_ref = _add_component(design, "C", "capacitor", cin_val, dnp=dnp, variants=variants)
    components.append(cin_ref)
    cout_ref = _add_component(design, "C", "capacitor", cout_val, dnp=dnp, variants=variants)
    components.append(cout_ref)

    _connect_pin(design, vin_net, u_ref, "1")
    _connect_pin(design, gnd_net, u_ref, "2")
    _connect_pin(design, vout_net, u_ref, "3")
    _connect_pin(design, vin_net, cin_ref, "1")
    _connect_pin(design, gnd_net, cin_ref, "2")
    _connect_pin(design, vout_net, cout_ref, "1")
    _connect_pin(design, gnd_net, cout_ref, "2")

    block = Block(id=block_id, name="LDO_Regulator", components=components)
    design.blocks.append(block)
    return block


def instantiate_rs485_transceiver(
    design: Design,
    block_id: str,
    rail_net: str = "3V3",
    gnd_net: str = "GND",
    a_net: str = "RS485_A",
    b_net: str = "RS485_B",
    ro_net: str = "RS485_RO",
    di_net: str = "RS485_DI",
    re_net: str = "RS485_nRE",
    de_net: str = "RS485_DE",
    *,
    termination: bool = True,
    dnp: bool = False,
    variants: dict[str, bool] | None = None,
) -> Block:
    """Half-duplex RS-485 transceiver (MAX3485, 3.3 V) with decoupling and termination.

    SOIC-8 pinout (75176-family): 1=RO, 2=/RE, 3=DE, 4=DI, 5=GND, 6=A, 7=B, 8=VCC.
    A 100 nF bypass sits on the rail, and a 120 Ω resistor terminates the A/B pair
    at the bus end when ``termination`` is set.
    """
    components: list[str] = []
    u_ref = _add_component(design, "U", "ic", "MAX3485", dnp=dnp, variants=variants, mpn="MAX3485")
    components.append(u_ref)
    _connect_pin(design, ro_net, u_ref, "1")
    _connect_pin(design, re_net, u_ref, "2")
    _connect_pin(design, de_net, u_ref, "3")
    _connect_pin(design, di_net, u_ref, "4")
    _connect_pin(design, gnd_net, u_ref, "5")
    _connect_pin(design, a_net, u_ref, "6")
    _connect_pin(design, b_net, u_ref, "7")
    _connect_pin(design, rail_net, u_ref, "8")

    c_ref = _add_component(design, "C", "capacitor", "100nF", dnp=dnp, variants=variants)
    components.append(c_ref)
    _connect_pin(design, rail_net, c_ref, "1")
    _connect_pin(design, gnd_net, c_ref, "2")

    if termination:
        r_ref = _add_component(design, "R", "resistor", "120", dnp=dnp, variants=variants)
        components.append(r_ref)
        _connect_pin(design, a_net, r_ref, "1")
        _connect_pin(design, b_net, r_ref, "2")

    block = Block(id=block_id, name="RS485_Transceiver", components=components)
    design.blocks.append(block)
    return block


def instantiate_can_transceiver(
    design: Design,
    block_id: str,
    rail_net: str = "3V3",
    gnd_net: str = "GND",
    canh_net: str = "CANH",
    canl_net: str = "CANL",
    txd_net: str = "CAN_TXD",
    rxd_net: str = "CAN_RXD",
    *,
    termination: bool = True,
    dnp: bool = False,
    variants: dict[str, bool] | None = None,
) -> Block:
    """CAN transceiver (SN65HVD230, 3.3 V) with decoupling and bus termination.

    SOIC-8 pinout: 1=TXD, 2=GND, 3=VCC, 4=RXD, 6=CANL, 7=CANH, 8=Rs. Rs is tied to
    GND for high-speed mode. A 100 nF bypass sits on the rail, and a 120 Ω resistor
    terminates the CANH/CANL pair when ``termination`` is set.
    """
    components: list[str] = []
    u_ref = _add_component(design, "U", "ic", "SN65HVD230", dnp=dnp, variants=variants, mpn="SN65HVD230")
    components.append(u_ref)
    _connect_pin(design, txd_net, u_ref, "1")
    _connect_pin(design, gnd_net, u_ref, "2")
    _connect_pin(design, rail_net, u_ref, "3")
    _connect_pin(design, rxd_net, u_ref, "4")
    _connect_pin(design, canl_net, u_ref, "6")
    _connect_pin(design, canh_net, u_ref, "7")
    _connect_pin(design, gnd_net, u_ref, "8")  # Rs -> GND: high-speed mode

    c_ref = _add_component(design, "C", "capacitor", "100nF", dnp=dnp, variants=variants)
    components.append(c_ref)
    _connect_pin(design, rail_net, c_ref, "1")
    _connect_pin(design, gnd_net, c_ref, "2")

    if termination:
        r_ref = _add_component(design, "R", "resistor", "120", dnp=dnp, variants=variants)
        components.append(r_ref)
        _connect_pin(design, canh_net, r_ref, "1")
        _connect_pin(design, canl_net, r_ref, "2")

    block = Block(id=block_id, name="CAN_Transceiver", components=components)
    design.blocks.append(block)
    return block
