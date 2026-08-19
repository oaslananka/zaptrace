"""Tests for block-composition architecture synthesis."""

from __future__ import annotations

from zaptrace.synthesis.architecture import (
    ArchitecturePlan,
    BlockContract,
    PlannedBlock,
    build_architecture_design,
    plan_architecture,
)
from zaptrace.synthesis.requirements import parse_requirements


def _plan(intent: str) -> ArchitecturePlan:
    return plan_architecture(parse_requirements(intent))


class TestComposition:
    def test_regulator_provides_rail_that_interface_requires(self) -> None:
        plan = _plan("USB-C powered board, 3.3V rail, I2C sensor")
        reg = next(b for b in plan.blocks if b.kind == "regulator")
        i2c = next(b for b in plan.blocks if b.block_id == "IF_I2C")
        assert "rail:VDD_3V3" in reg.contract.provides
        assert "rail:VDD_3V3" in i2c.contract.requires
        # the requirement is satisfied, so nothing is unmet
        assert plan.unmet == []

    def test_interface_without_a_rail_is_an_unmet_requirement(self) -> None:
        # An I2C bus but no power source/rail: the bus has no rail to run from.
        plan = _plan("tiny I2C sensor breakout")
        assert any(u.block_id == "IF_I2C" and u.token == "rail:VDD_3V3" for u in plan.unmet)

    def test_gnd_is_a_global_net_and_never_unmet(self) -> None:
        plan = _plan("USB-C powered board, 3.3V rail")
        assert all(u.token != "net:GND" for u in plan.unmet)


class TestHonesty:
    def test_unrealized_interface_is_kept_not_dropped(self) -> None:
        # BLE has no RF front-end block yet: it must stay in the plan, not vanish.
        plan = _plan("nRF52 board, 3.3V rail, BLE sensor")
        ble = next(b for b in plan.blocks if b.block_id == "IF_BLE")
        assert ble.realized is False
        assert ble in plan.unrealized_blocks
        assert "rf" in ble.rationale.lower()

    def test_rs485_is_realized_with_a_transceiver_block(self) -> None:
        plan = _plan("STM32 board, 3.3V rail, RS485 modbus node")
        rs485 = next(b for b in plan.blocks if b.block_id == "IF_RS485")
        assert rs485.realized is True
        assert "rail:VDD_3V3" in rs485.contract.requires

    def test_boost_regulator_is_unrealized(self) -> None:
        # A rail above the system voltage needs a boost, which has no block yet.
        plan = _plan("battery board, single Li-ion cell, 5V rail")
        boost = next((b for b in plan.blocks if b.kind == "regulator" and not b.realized), None)
        assert boost is not None
        assert any("boost" in n for n in plan.notes)

    def test_point_to_point_interface_needs_no_support_block(self) -> None:
        plan = _plan("MCU board, 3.3V rail, SPI flash")
        spi = next(b for b in plan.blocks if b.block_id == "IF_SPI")
        assert spi.realized is True
        assert spi.contract.requires == ()


class TestNetlistEmission:
    def test_emits_realized_blocks_only(self) -> None:
        req = parse_requirements("USB-C powered board, 3.3V rail, I2C sensor, RS485 modbus, BLE radio")
        design, _plan, _log = build_architecture_design(req)
        emitted = {b.id for b in design.blocks}
        # Realized power + I2C + RS485 blocks are emitted; the unrealized BLE is not.
        assert "PB_REG_VDD_3V3" in emitted
        assert "IF_I2C" in emitted
        assert "IF_RS485" in emitted
        assert "IF_BLE" not in emitted
        assert design.components  # something was emitted

    def test_deterministic_across_runs(self) -> None:
        req = parse_requirements("USB-C powered board, 3.3V rail, I2C sensor, SPI flash")
        d1, _, _ = build_architecture_design(req)
        d2, _, _ = build_architecture_design(req)
        assert sorted(d1.components) == sorted(d2.components)
        assert sorted(d1.nets) == sorted(d2.nets)

    def test_decision_log_records_gaps_and_values(self) -> None:
        req = parse_requirements("USB-C powered board, 3.3V rail, I2C sensor, BLE radio")
        _design, _plan, log = build_architecture_design(req)
        cats = {d.category for d in log.decisions}
        assert "gap" in cats  # BLE (no RF block yet) recorded as a gap
        assert "value" in cats  # a computed value (I2C pull-ups / buck)

    def test_buck_value_is_computed_for_large_drop(self) -> None:
        # 12V -> 3.3V at 1A dissipates >0.5W: a buck with computed L/C.
        req = parse_requirements("industrial board, 12V input, 3.3V rail at 1A")
        _design, _plan, log = build_architecture_design(req)
        buck = next((d for d in log.decisions if d.calculator == "buck_inductor_capacitor"), None)
        assert buck is not None
        assert "uH" in buck.value


class TestSerialization:
    def test_plan_to_dict_round_trips_shape(self) -> None:
        plan = _plan("USB-C powered board, 3.3V rail, I2C sensor, RS485 modbus")
        data = plan.to_dict()
        assert set(data) == {"blocks", "rails_v", "unmet_requirements", "notes"}
        assert all({"block_id", "provides", "requires", "realized"} <= set(b) for b in data["blocks"])

    def test_block_contract_defaults_are_empty(self) -> None:
        block = PlannedBlock(block_id="X", kind="interface", rationale="r", contract=BlockContract(), realized=True)
        assert block.contract.provides == ()
        assert block.contract.requires == ()


class TestArchitectureRefactorCharacterization:
    def test_composite_plan_preserves_block_and_contract_order(self) -> None:
        plan = _plan("ESP32-C3 USB-C 3.3V board, I2C sensor, SPI flash, RS485 modbus, CAN bus")

        assert [block.block_id for block in plan.blocks] == [
            "PB_USB_C_CC",
            "J_USB_C",
            "PB_REG_VDD_3V3",
            "IF_CAN",
            "IF_I2C",
            "IF_RS485",
            "IF_SPI",
            "IF_USB",
            "CORE_MCU",
            "PERIPH_BME280",
            "PERIPH_W25Q128JV",
        ]
        assert [(item.block_id, item.token) for item in plan.unmet] == []
        assert plan.notes == []

    def test_external_input_and_unrealized_gaps_preserve_plan_order(self) -> None:
        plan = _plan("SAMD21 3.3V board, BLE sensor")

        assert [(block.block_id, block.kind, block.realized) for block in plan.blocks] == [
            ("J_DC_VDD_3V3", "connector", True),
            ("IF_BLE", "interface", False),
            ("CORE_MCU", "mcu", False),
        ]
        assert plan.notes == ["MCU family 'samd' has no library part yet"]
        assert [(item.block_id, item.token) for item in plan.unmet] == []

    def test_composite_design_preserves_emission_and_decision_order(self) -> None:
        requirements = parse_requirements("ESP32-C3 USB-C 3.3V board, I2C sensor, SPI flash, RS485 modbus, CAN bus")

        design, _plan_result, log = build_architecture_design(requirements)

        assert [block.id for block in design.blocks] == [
            "PB_USB_C_CC",
            "PB_REG_VDD_3V3",
            "IF_CAN",
            "IF_I2C",
            "IF_RS485",
        ]
        assert [(d.category, d.parameter, d.value, d.calculator, d.confidence) for d in log.decisions] == [
            ("topology", "PB_USB_C_CC", "USB-C CC Rd", "usb_c_cc_termination", 1.0),
            ("topology", "J_USB_C", "USB-C receptacle J1", "", 1.0),
            ("topology", "PB_REG_VDD_3V3", "LDO 3.3V", "", 1.0),
            ("topology", "IF_CAN", "CAN transceiver (SN65HVD230)", "", 1.0),
            ("value", "IF_I2C", "I2C pull-ups", "i2c_pullup", 1.0),
            ("topology", "IF_RS485", "RS-485 transceiver (MAX3485)", "", 1.0),
            ("note", "IF_SPI", "no support block required", "", 1.0),
            ("topology", "IF_USB", "covered by USB-C input", "", 1.0),
            ("topology", "CORE_MCU", "esp32-c3-mini-1 core, 15 pins wired", "", 1.0),
            ("topology", "PERIPH_BME280", "bme280 on I2C bus", "", 1.0),
            ("topology", "PERIPH_W25Q128JV", "w25q128jv on SPI bus", "", 1.0),
        ]

    def test_buck_and_external_connector_preserve_decision_order(self) -> None:
        requirements = parse_requirements("industrial board, 12V input, 3.3V rail at 1A")

        _design, _plan_result, log = build_architecture_design(requirements)

        assert [(d.category, d.parameter, d.value, d.calculator) for d in log.decisions] == [
            ("value", "PB_REG_VDD_3V3", "buck 3.3V (L=15uH, Cout=2.7uF)", "buck_inductor_capacitor"),
            ("topology", "J_DC_VDD_12", "DC power input J1", ""),
        ]
