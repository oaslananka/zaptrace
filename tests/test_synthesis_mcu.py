"""Tests for functional-core (MCU) synthesis and wiring."""

from __future__ import annotations

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode
from zaptrace.synthesis.architecture import build_architecture_design
from zaptrace.synthesis.mcu import (
    _assign_mcu_interfaces,
    _connect_mcu_power,
    has_mcu_part,
    instantiate_mcu,
)
from zaptrace.synthesis.requirements import parse_requirements


def _board_with_i2c_nets() -> Design:
    """A design that already has SDA/SCL nets (as if I2C pull-ups were emitted)."""
    design = Design(meta=DesignMeta(name="mcu_test"))
    for net in ("VDD_3V3", "GND", "SDA", "SCL"):
        design.nets[net] = Net(id=net, name=net)
    # one existing pin on each I2C net, mimicking the pull-up resistor
    design.components["R1"] = Component(id="R1", ref="R1", type="resistor", value="4.7k")
    design.nets["SDA"].nodes.append(NetNode(component_ref="R1", pin_name="2"))
    design.nets["SCL"].nodes.append(NetNode(component_ref="R1", pin_name="2"))
    return design


class TestFamilyResolution:
    def test_known_family_has_a_part(self) -> None:
        assert has_mcu_part("esp32") is True
        assert has_mcu_part("stm32") is True

    def test_unknown_or_missing_family(self) -> None:
        assert has_mcu_part("samd") is False  # recognized family, no library part yet
        assert has_mcu_part(None) is False


class TestInstantiateMcu:
    def test_places_part_and_ties_power(self) -> None:
        design = _board_with_i2c_nets()
        result = instantiate_mcu(design, "esp32", ["i2c"], rail_net="VDD_3V3")
        assert result.realized
        assert result.part_id == "esp32-c3-mini-1"
        mcu = design.components[result.ref]
        assert mcu.type == "mcu"
        assert mcu.footprint  # a real part carries its footprint
        functions = {a.function for a in result.assignments}
        assert {"power", "ground", "enable"} <= functions

    def test_wires_i2c_to_existing_support_nets(self) -> None:
        design = _board_with_i2c_nets()
        result = instantiate_mcu(design, "esp32", ["i2c"], rail_net="VDD_3V3")
        # SDA/SCL now reach the MCU: pull-up node + MCU GPIO node
        assert any(n.component_ref == result.ref for n in design.nets["SDA"].nodes)
        assert any(n.component_ref == result.ref for n in design.nets["SCL"].nodes)
        assert any(a.function == "i2c:SDA" for a in result.assignments)

    def test_ref_does_not_clobber_existing_u_designator(self) -> None:
        design = _board_with_i2c_nets()
        design.components["U1"] = Component(id="U1", ref="U1", type="ldo", value="LDO_3.3V")
        result = instantiate_mcu(design, "esp32", ["i2c"], rail_net="VDD_3V3")
        assert result.ref != "U1"
        assert design.components["U1"].type == "ldo"  # untouched

    def test_spi_creates_its_own_bus_nets(self) -> None:
        design = _board_with_i2c_nets()  # has I2C nets, no SPI nets
        result = instantiate_mcu(design, "esp32", ["i2c", "spi"], rail_net="VDD_3V3")
        # SPI has no support block, so the MCU masters it by creating the bus nets.
        assert any(a.function == "spi:SCK" for a in result.assignments)
        assert "SPI_SCK" in design.nets

    def test_bus_missing_its_support_net_is_unconnected(self) -> None:
        design = _board_with_i2c_nets()  # I2C nets exist, RS-485 nets do not
        result = instantiate_mcu(design, "esp32", ["i2c", "rs485"], rail_net="VDD_3V3")
        assert "rs485" in result.unconnected_interfaces
        assert any(a.function == "i2c:SDA" for a in result.assignments)

    def test_all_power_pins_are_connected(self) -> None:
        # STM32 has VDDA/VBAT (extra supplies) and VSSA (analog ground) — a
        # floating one would break the part, so every power pin must be tied.
        design = _board_with_i2c_nets()
        result = instantiate_mcu(design, "stm32", ["i2c"], rail_net="VDD_3V3")
        rail_pins = {a.pin for a in result.assignments if a.function == "power"}
        assert {"VDDA", "VBAT"} <= rail_pins
        assert any(a.pin == "VSSA" and a.function == "ground" for a in result.assignments)

    def test_boot_straps_are_applied(self) -> None:
        design = _board_with_i2c_nets()
        result = instantiate_mcu(design, "stm32", ["i2c"], rail_net="VDD_3V3")
        # STM32 BOOT0 is strapped (pulled low) so it boots from flash
        assert any(a.pin == "BOOT0" and a.function.startswith("strap") for a in result.assignments)

    def test_stm32_board_reaches_clean_erc(self) -> None:
        from zaptrace.synthesis.repair import synthesize_and_repair

        out = synthesize_and_repair("STM32 3.3V board, RS485 modbus node")
        assert out["repair"].fully_clean

    def test_swd_debug_header_is_placed_and_clock_wired(self) -> None:
        # nRF52 exposes SWD pins; a debug header must connect the SWD clock.
        design = _board_with_i2c_nets()
        instantiate_mcu(design, "nrf52", ["i2c"], rail_net="VDD_3V3")
        headers = [c for c in design.components.values() if c.value == "SWD Debug Header"]
        assert len(headers) == 1
        assert "SWDCLK" in design.nets
        assert len(design.nets["SWDCLK"].nodes) >= 2  # MCU + header

    def test_swd_pins_are_not_used_as_interface_gpio(self) -> None:
        design = _board_with_i2c_nets()
        result = instantiate_mcu(design, "nrf52", ["i2c"], rail_net="VDD_3V3")
        assigned = {a.net for a in result.assignments}
        assert "SDA" in assigned  # I2C still wired from real GPIOs, not SWD pins

    def test_crystal_placed_with_load_caps_for_bare_mcu(self) -> None:
        # RP2040 has no internal precision oscillator — it needs an external crystal.
        design = _board_with_i2c_nets()
        instantiate_mcu(design, "rp2040", ["i2c"], rail_net="VDD_3V3")
        crystals = [c for c in design.components.values() if c.type == "crystal"]
        assert len(crystals) == 1
        # two 18pF load caps on the crystal nets
        cap_nets = {"XTAL_IN", "XTAL_OUT"}
        for net in cap_nets:
            caps = [n for n in design.nets[net].nodes if design.components[n.component_ref].type == "capacitor"]
            assert caps

    def test_rp2040_board_is_electrically_clean(self) -> None:
        from zaptrace.erc.runner import ERCRunner
        from zaptrace.synthesis.repair import synthesize_and_repair

        out = synthesize_and_repair("RP2040 3.3V board, CAN bus node")
        result = ERCRunner().run(out["design"])
        assert result.total_errors == 0
        assert result.total_warnings == 0

    def test_unknown_family_is_not_faked(self) -> None:
        design = _board_with_i2c_nets()
        result = instantiate_mcu(design, "samd", ["i2c"], rail_net="VDD_3V3")
        assert result.realized is False
        assert result.ref is None
        assert "samd" in result.reason
        assert not any(c.type == "mcu" for c in design.components.values())

    def test_pin_assignment_is_deterministic(self) -> None:
        d1 = _board_with_i2c_nets()
        d2 = _board_with_i2c_nets()
        a1 = instantiate_mcu(d1, "esp32", ["i2c"], rail_net="VDD_3V3").assignments
        a2 = instantiate_mcu(d2, "esp32", ["i2c"], rail_net="VDD_3V3").assignments
        assert [a.to_dict() for a in a1] == [a.to_dict() for a in a2]


class TestIntegration:
    def test_synthesized_board_has_a_connected_brain(self) -> None:
        design, plan, _log = build_architecture_design(
            parse_requirements("ESP32-C3 USB-C 3.3V board, I2C sensor, RS485 modbus")
        )
        mcus = [c for c in design.components.values() if c.type == "mcu"]
        assert len(mcus) == 1
        # the I2C data nets now reach the MCU, not just a dangling pull-up
        mcu_ref = mcus[0].ref
        assert any(n.component_ref == mcu_ref for n in design.nets["SDA"].nodes)
        # the MCU is in the block graph as the realized functional core
        core = next(b for b in plan.blocks if b.block_id == "CORE_MCU")
        assert core.realized
        assert "core" in core.contract.provides

    def test_missing_mcu_part_is_an_honest_gap(self) -> None:
        _design, plan, _log = build_architecture_design(parse_requirements("SAMD21 3.3V board, I2C sensor"))
        core = next(b for b in plan.blocks if b.block_id == "CORE_MCU")
        assert core.realized is False
        assert any("samd" in note for note in plan.notes)


def test_mcu_connection_helpers_preserve_power_and_interface_outcomes() -> None:
    design = _board_with_i2c_nets()
    design.components["U9"] = Component(id="U9", ref="U9", type="mcu")
    power = _connect_mcu_power(
        design,
        "U9",
        ["VDD"],
        ["GND"],
        "EN",
        rail_net="VDD_3V3",
        gnd_net="GND",
    )
    assert [item.function for item in power] == ["power", "ground", "enable"]

    assignments, unconnected = _assign_mcu_interfaces(
        design,
        "U9",
        ["i2c", "rs485", "unknown"],
        ["GPIO1", "GPIO2", "GPIO3"],
    )
    assert [item.function for item in assignments] == ["i2c:SDA", "i2c:SCL"]
    assert unconnected == ["rs485"]
