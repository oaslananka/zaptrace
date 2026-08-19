import pytest

from zaptrace.core.models import Design, DesignMeta
from zaptrace.synthesis.blocks import (
    instantiate_adxl355_decoupling,
    instantiate_esp32_s3_strapping,
    instantiate_i2c_pullups,
    instantiate_led_indicator,
    instantiate_rj45_bob_smith,
    instantiate_sync_buck_tlv62569,
    instantiate_usb_c_ufp_cc,
    instantiate_voltage_divider,
)


@pytest.fixture
def empty_design() -> Design:
    return Design(meta=DesignMeta(name="TestDesign"))


def test_adxl355_decoupling(empty_design: Design) -> None:
    block = instantiate_adxl355_decoupling(empty_design, "B1")

    assert block.name == "ADXL355_Decoupling"
    assert len(block.components) == 6
    assert len(empty_design.components) == 6

    # Assert values
    vals = sorted([empty_design.components[ref].value for ref in block.components])
    assert vals == sorted(["100nF", "1uF", "10uF", "100nF", "1uF", "10uF"])

    # Assert nets
    assert "VDDA" in empty_design.nets
    assert "VDDD" in empty_design.nets
    assert "GND" in empty_design.nets

    vdda_net = empty_design.nets["VDDA"]
    vddd_net = empty_design.nets["VDDD"]
    gnd_net = empty_design.nets["GND"]

    assert len(vdda_net.nodes) == 3
    assert len(vddd_net.nodes) == 3
    assert len(gnd_net.nodes) == 6


def test_sync_buck_tlv62569(empty_design: Design) -> None:
    block = instantiate_sync_buck_tlv62569(empty_design, "B2", inductor_val="2.2uH", cin_val="10uF", cout_val="22uF")

    assert block.name == "Sync_Buck_TLV62569"
    assert len(block.components) == 4

    comps = [empty_design.components[ref] for ref in block.components]
    types = sorted([c.type for c in comps])
    assert types == sorted(["regulator", "capacitor", "capacitor", "inductor"])

    assert "TLV62569" in [c.value for c in comps]
    assert "2.2uH" in [c.value for c in comps]
    assert "10uF" in [c.value for c in comps]
    assert "22uF" in [c.value for c in comps]

    # Check some connections
    assert "VIN" in empty_design.nets
    assert "VOUT" in empty_design.nets
    assert "SW" in empty_design.nets

    sw_nodes = empty_design.nets["SW"].nodes
    assert len(sw_nodes) == 2  # U and L


def test_usb_c_ufp_cc(empty_design: Design) -> None:
    block = instantiate_usb_c_ufp_cc(empty_design, "B3")

    assert block.name == "USB_C_UFP_CC"
    assert len(block.components) == 2

    comps = [empty_design.components[ref] for ref in block.components]
    for c in comps:
        assert c.type == "resistor"
        assert c.value == "5.1k"

    assert "CC1" in empty_design.nets
    assert "CC2" in empty_design.nets
    assert "GND" in empty_design.nets

    assert len(empty_design.nets["CC1"].nodes) == 1
    assert len(empty_design.nets["CC2"].nodes) == 1
    assert len(empty_design.nets["GND"].nodes) == 2


def test_rj45_bob_smith(empty_design: Design) -> None:
    block = instantiate_rj45_bob_smith(empty_design, "B4")

    assert block.name == "RJ45_BobSmith"
    assert len(block.components) == 5

    comps = [empty_design.components[ref] for ref in block.components]
    resistors = [c for c in comps if c.type == "resistor"]
    capacitors = [c for c in comps if c.type == "capacitor"]

    assert len(resistors) == 4
    for r in resistors:
        assert r.value == "75"

    assert len(capacitors) == 1
    assert capacitors[0].value == "1nF"
    assert capacitors[0].voltage_rating == 2000.0


def test_esp32_s3_strapping(empty_design: Design) -> None:
    block = instantiate_esp32_s3_strapping(empty_design, "B5")

    assert block.name == "ESP32_S3_Strapping"
    assert len(block.components) == 5

    comps = [empty_design.components[ref] for ref in block.components]
    resistors = [c for c in comps if c.type == "resistor"]
    capacitors = [c for c in comps if c.type == "capacitor"]

    assert len(resistors) == 2
    assert len(capacitors) == 3

    assert sorted([r.value for r in resistors]) == sorted(["10k", "10k"])
    assert sorted([c.value for c in capacitors]) == sorted(["1uF", "10uF", "100nF"])


def test_blocks_respect_dnp_variants(empty_design: Design) -> None:
    variants = {"V1": True, "V2": False}
    block = instantiate_usb_c_ufp_cc(empty_design, "B6", dnp=True, variants=variants)

    for ref in block.components:
        comp = empty_design.components[ref]
        assert comp.dnp is True
        assert comp.variants == variants


def test_led_indicator_computes_resistor(empty_design: Design) -> None:
    block = instantiate_led_indicator(empty_design, "B_LED", "VCC", "GND", supply_v=5.0)
    assert block.name == "LED_Indicator"
    assert len(block.components) == 2
    comps = [empty_design.components[ref] for ref in block.components]
    # (5 - 2.0) / 10 mA = 300 ohm, computed and E-series snapped
    resistor = next(c for c in comps if c.type == "resistor")
    assert resistor.value == "300"
    assert any(c.type == "led" for c in comps)
    # wiring: supply through the resistor, LED cathode to ground
    assert len(empty_design.nets["VCC"].nodes) == 1
    assert len(empty_design.nets["GND"].nodes) == 1
    assert len(empty_design.nets["B_LED_LED_A"].nodes) == 2  # resistor <-> LED anode


def test_i2c_pullups_computes_value(empty_design: Design) -> None:
    block = instantiate_i2c_pullups(empty_design, "B_I2C", supply_v=3.3, bus_capacitance_pf=100.0)
    assert block.name == "I2C_Pullups"
    assert len(block.components) == 2
    values = {empty_design.components[ref].value for ref in block.components}
    assert values == {"11k"}  # 3.3 V, 100 pF, 100 kHz -> 11k
    assert len(empty_design.nets["SDA"].nodes) == 1
    assert len(empty_design.nets["SCL"].nodes) == 1
    assert len(empty_design.nets["VCC"].nodes) == 2


def test_voltage_divider_computes_top(empty_design: Design) -> None:
    block = instantiate_voltage_divider(empty_design, "B_DIV", input_v=5.0, output_v=2.5, r_bottom=10_000)
    assert block.name == "Voltage_Divider"
    assert len(block.components) == 2
    values = sorted(empty_design.components[ref].value for ref in block.components)
    assert values == ["10k", "10k"]  # top computed = 10k, bottom = 10k
    assert len(empty_design.nets["VOUT"].nodes) == 2  # both resistors meet at VOUT


def test_parametric_blocks_respect_dnp(empty_design: Design) -> None:
    block = instantiate_led_indicator(empty_design, "B_LED", supply_v=5.0, dnp=True)
    assert all(empty_design.components[ref].dnp for ref in block.components)
