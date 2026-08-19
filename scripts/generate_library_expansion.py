#!/usr/bin/env python3
"""Generate governed component library entries to reach 500+ unique parts (issue #129).

This script generates YAML files following the existing library schema, covering:
  - Common passives (resistors, capacitors, inductors, ferrites, crystals)
  - Power ICs (LDOs, DC-DC, power switches, supervisors)
  - MCUs (STM32, nRF52, ESP32, RP2040, PIC)
  - Sensors (temperature, IMU, proximity, optical, flow)
  - Connectors (FFC/FPC, SIM, card, headers, USB variants)
  - Memory (EEPROM, NOR flash, SRAM)
  - RF components (transceivers, PA, LNA, filters)
  - Timing (oscillators, RTCs, PLLs)
  - Protection (TVS, ESD, fuses, resettable fuses, varistors)
  - Security (secure element, crypto IC)
  - Interface (level shifters, USB hub, UART bridge, CAN transceiver)
  - Optoelectronics (RGB LED, driver ICs, IR emitter, phototransistor)

Usage:
    python scripts/generate_library_expansion.py [--dry-run] [--output-dir data/library]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from zaptrace.library.migration import migrate_record

LIBRARY_ROOT = Path(__file__).parent.parent / "data" / "library"

_PRODUCTION_NOTE = "confirm exact orderable MPN and authorized distributor before production"
_COMPLIANCE_NOTE = "do not treat starter-library metadata as regulatory certification"
_ON_SEMI = "ON Semi"
_DIODES_INC = "Diodes Inc"
_SILICON_LABS = "Silicon Labs"


def _provenance(reviewed: bool = False) -> dict:
    return {
        "reviewed_by": "library-ci" if reviewed else "unreviewed",
        "source": "offline-manifest",
        "generation": "scripts/generate_library_expansion.py",
    }


def _sourcing(mpn: str, manufacturer: str) -> dict:
    return {
        "mpn": mpn,
        "manufacturer": manufacturer,
        "status": "starter-library-entry",
        "production_note": _PRODUCTION_NOTE,
    }


def _compliance() -> dict:
    return {
        "rohs": "supplier-confirmation-required",
        "reach": "supplier-confirmation-required",
        "production_note": _COMPLIANCE_NOTE,
    }


def passive_pins() -> dict:
    return {
        "P1": {"type": "passive", "description": "Terminal 1"},
        "P2": {"type": "passive", "description": "Terminal 2"},
    }


def _part(
    part_id: str,
    name: str,
    category: str,
    manufacturer: str,
    mpn: str,
    description: str,
    package: str,
    footprint: str,
    datasheet: str,
    pins: dict,
    properties: dict | None = None,
    electrical_limits: dict | None = None,
    voltage_supply: str = "",
) -> dict:
    legacy = {
        "id": part_id,
        "name": name,
        "category": category,
        "manufacturer": manufacturer,
        "mpn": mpn,
        "description": description,
        "datasheet": datasheet,
        "package": package,
        "footprint": footprint,
        "lifecycle": "active",
        "voltage_supply": voltage_supply,
        "pins": pins,
        "properties": properties or {},
        "electrical_limits": electrical_limits or {},
        "sourcing": _sourcing(mpn, manufacturer),
        "compliance": _compliance(),
        "provenance": _provenance(),
    }
    migrated, _changed = migrate_record(legacy)
    return migrated


def generate_resistors() -> list[tuple[str, str, dict]]:
    parts = []
    for pkg in ["0201", "0402", "0603", "0805", "1206", "1210", "2512"]:
        pid = f"res-{pkg.lower()}-std"
        parts.append(
            (
                "passive",
                f"res-{pkg.lower()}-std",
                _part(
                    pid,
                    f"Resistor SMD {pkg}",
                    "passive",
                    "Generic",
                    f"RES-{pkg}",
                    f"Standard SMD resistor, {pkg} package, 0.1% tolerance",
                    pkg,
                    pkg,
                    f"internal://zaptrace/component-family/res-{pkg.lower()}",
                    passive_pins(),
                    properties={"package_size": pkg, "tolerance_pct": 0.1},
                    electrical_limits={"max_power_w": 0.1 if pkg in ("0201", "0402") else 0.25},
                ),
            )
        )
    for pkg in ["0402", "0603", "0805", "1206"]:
        pid = f"res-network-4x-{pkg.lower()}"
        parts.append(
            (
                "passive",
                pid,
                _part(
                    pid,
                    f"Resistor Network 4x {pkg}",
                    "passive",
                    "Generic",
                    f"RN4-{pkg}",
                    f"4-resistor network SMD, {pkg} package",
                    f"SOT-143-{pkg}",
                    f"ResistorNetwork4-{pkg}",
                    f"internal://zaptrace/component-family/res-network-{pkg.lower()}",
                    {f"P{i}": {"type": "passive", "description": f"Terminal {i}"} for i in range(1, 9)},
                ),
            )
        )
    return parts


def generate_capacitors() -> list[tuple[str, str, dict]]:
    parts = []
    for pkg in ["0201", "0402", "0603", "0805", "1206", "1210", "1812"]:
        pid = f"cap-mlcc-{pkg.lower()}-100n"
        parts.append(
            (
                "passive",
                pid,
                _part(
                    pid,
                    f"Cap MLCC {pkg} 100nF",
                    "passive",
                    "Generic",
                    f"CC{pkg}-100N",
                    f"MLCC capacitor 100nF, {pkg}, X7R, 50V",
                    pkg,
                    pkg,
                    f"internal://zaptrace/component-family/cap-mlcc-{pkg.lower()}",
                    passive_pins(),
                    properties={"capacitance": "100nF", "dielectric": "X7R", "voltage_v": 50},
                    electrical_limits={"rated_voltage_v": 50},
                ),
            )
        )
    for pkg in ["0402", "0603", "0805"]:
        pid = f"cap-mlcc-{pkg.lower()}-1u"
        parts.append(
            (
                "passive",
                pid,
                _part(
                    pid,
                    f"Cap MLCC {pkg} 1uF",
                    "passive",
                    "Generic",
                    f"CC{pkg}-1U",
                    f"MLCC capacitor 1uF, {pkg}, X5R, 10V",
                    pkg,
                    pkg,
                    f"internal://zaptrace/component-family/cap-mlcc-{pkg.lower()}",
                    passive_pins(),
                    properties={"capacitance": "1uF", "dielectric": "X5R", "voltage_v": 10},
                    electrical_limits={"rated_voltage_v": 10},
                ),
            )
        )
    pid = "cap-electrolytic-10uf-25v"
    parts.append(
        (
            "passive",
            pid,
            _part(
                pid,
                "Cap Electrolytic 10uF 25V",
                "passive",
                "Panasonic",
                "EEUFC1E100",
                "Electrolytic capacitor 10uF 25V, radial",
                "Radial-D5.0",
                "CP_Radial_D5.0mm_P2.00mm",
                "https://industrial.panasonic.com/cdbs/www-data/pdf/RDF0000/ABA0000C1215.pdf",
                passive_pins(),
                electrical_limits={"rated_voltage_v": 25, "capacitance_uf": 10},
            ),
        )
    )
    return parts


def generate_inductors() -> list[tuple[str, str, dict]]:
    parts = []
    for pkg, current, current_a in [
        ("0402", "300mA", 0.3),
        ("0603", "500mA", 0.5),
        ("0805", "1A", 1.0),
        ("1210", "3A", 3.0),
    ]:
        pid = f"ind-power-{pkg.lower()}"
        parts.append(
            (
                "passive",
                pid,
                _part(
                    pid,
                    f"Power Inductor {pkg} {current}",
                    "passive",
                    "TDK",
                    f"VLS{pkg}CX",
                    f"Shielded power inductor {pkg}, {current}",
                    pkg,
                    pkg,
                    "https://product.tdk.com/info/en/catalog/datasheets/inductor_automotive_power_vlsxcx_en.pdf",
                    passive_pins(),
                    properties={"current_rating": current, "inductance": "10uH"},
                    electrical_limits={"current_rating_a": current_a},
                ),
            )
        )
    return parts


def generate_power_ics() -> list[tuple[str, str, dict]]:
    parts = []
    ldos = [
        (
            "rt9013-33gb",
            "RT9013-33GB",
            "RT9013",
            "Richtek",
            "SOT-23-5",
            "LDO 3.3V 500mA",
            "https://www.richtek.com/assets/product_file/RT9013/DS9013-11.pdf",
        ),
        (
            "lp5907mnx-3.3",
            "LP5907MNX-3.3",
            "LP5907",
            "TI",
            "SOT-23-5",
            "Ultra-low noise LDO 3.3V 250mA",
            "https://www.ti.com/lit/ds/symlink/lp5907.pdf",
        ),
        (
            "mcp1703-3302e-db",
            "MCP1703-3302E/DB",
            "MCP1703",
            "Microchip",
            "SOT-23-3",
            "LDO 3.3V 250mA",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/20001985B.pdf",
        ),
        (
            "ncp117st33t3g",
            "NCP117ST33T3G",
            "NCP117",
            _ON_SEMI,
            "SOT-223",
            "LDO 3.3V 1A",
            "https://www.onsemi.com/pub/Collateral/NCP117-D.PDF",
        ),
        (
            "tlv75733pdbvr",
            "TLV75733PDBVR",
            "TLV757",
            "TI",
            "SOT-23-5",
            "LDO 3.3V 1A, PSRR 68dB",
            "https://www.ti.com/lit/ds/symlink/tlv757p.pdf",
        ),
        (
            "xc6206p332mr",
            "XC6206P332MR",
            "XC6206",
            "Torex",
            "SOT-23-3",
            "LDO 3.3V 200mA",
            "https://www.torexsemi.com/file/xc6206/XC6206.pdf",
        ),
        (
            "tps7a4901dgnr",
            "TPS7A4901DGNR",
            "TPS7A49",
            "TI",
            "MSOP-8",
            "Wide Vin adj LDO 1A",
            "https://www.ti.com/lit/ds/symlink/tps7a49.pdf",
        ),
        (
            "lt1763cs8-3.3",
            "LT1763CS8-3.3",
            "LT1763",
            "Linear/ADI",
            "SO-8",
            "Ultra-low-noise LDO 3.3V 500mA",
            "https://www.analog.com/media/en/technical-documentation/data-sheets/1763fa.pdf",
        ),
        (
            "tps72325dbvr",
            "TPS72325DBVR",
            "TPS723",
            "TI",
            "SOT-23-5",
            "LDO 2.5V 150mA",
            "https://www.ti.com/lit/ds/symlink/tps723.pdf",
        ),
    ]
    for pid, name, mpn, mfr, pkg, desc, ds in ldos:
        parts.append(
            (
                "power",
                pid,
                _part(
                    pid,
                    name,
                    "power",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "VIN": {"type": "power", "description": "Input voltage"},
                        "VOUT": {"type": "output", "description": "Regulated output"},
                        "GND": {"type": "power", "description": "Ground"},
                        "EN": {"type": "input", "description": "Enable"},
                        "BYP": {"type": "input", "description": "Bypass/NC"},
                    },
                    voltage_supply="5.0",
                ),
            )
        )
    dcdcs = [
        (
            "tps62130argr",
            "TPS62130ARGR",
            "TPS62130",
            "TI",
            "WSON-16",
            "Sync buck 3A 3MHz",
            "https://www.ti.com/lit/ds/symlink/tps62130.pdf",
        ),
        (
            "tps54360b-ddar",
            "TPS54360BDDAR",
            "TPS54360",
            "TI",
            "HSOIC-8",
            "Buck 3.5A 60V",
            "https://www.ti.com/lit/ds/symlink/tps54360b.pdf",
        ),
        (
            "lm5166xqdsxrq1",
            "LM5166XQDSXRQ1",
            "LM5166",
            "TI",
            "WSON-8",
            "Buck 0.5A 65V",
            "https://www.ti.com/lit/ds/symlink/lm5166.pdf",
        ),
        (
            "mp2307dn-lf-z",
            "MP2307DN-LF-Z",
            "MP2307",
            "MPS",
            "SOIC-8",
            "Buck 3A 23V 340kHz",
            "https://www.monolithicpower.com/en/documentview/productdocument/index/version/2/document_type/Datasheet/lang/en/sku/MP2307",
        ),
        (
            "tps6128x-q1",
            "TPS61281EVM",
            "TPS61281",
            "TI",
            "WSON-6",
            "Boost 3.5A 15V",
            "https://www.ti.com/lit/ds/symlink/tps61281.pdf",
        ),
        (
            "lt8640s#pbf",
            "LT8640S",
            "LT8640",
            "ADI",
            "LQFN-16",
            "Silent Switcher buck 5A 42V",
            "https://www.analog.com/media/en/technical-documentation/data-sheets/lt8640s.pdf",
        ),
        (
            "max17222evkit",
            "MAX17222",
            "MAX17222",
            "Maxim",
            "WLP-9",
            "Boost 400mA 5V",
            "https://datasheets.maximintegrated.com/en/ds/MAX17222.pdf",
        ),
        (
            "bq24297rget",
            "BQ24297RGET",
            "BQ24297",
            "TI",
            "QFN-24",
            "I2C charger 3A for 1/2 cell Li-Ion",
            "https://www.ti.com/lit/ds/symlink/bq24297.pdf",
        ),
        (
            "mcp73871-2cciml",
            "MCP73871-2CCI/ML",
            "MCP73871",
            "Microchip",
            "QFN-20",
            "Li-Ion charge mgmt 2A",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/MCP73871-Data-Sheet-20002090E.pdf",
        ),
        (
            "max20078atga",
            "MAX20078ATGA+",
            "MAX20078",
            "Maxim",
            "TQFN-40",
            "48V 2-phase buck 20A",
            "https://datasheets.maximintegrated.com/en/ds/MAX20078.pdf",
        ),
    ]
    for pid, name, mpn, mfr, pkg, desc, ds in dcdcs:
        parts.append(
            (
                "power",
                pid,
                _part(
                    pid,
                    name,
                    "power",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "VIN": {"type": "power", "description": "Input voltage"},
                        "VOUT": {"type": "output", "description": "Regulated output"},
                        "GND": {"type": "power", "description": "Ground"},
                        "SW": {"type": "output", "description": "Switching node"},
                        "FB": {"type": "input", "description": "Feedback"},
                        "EN": {"type": "input", "description": "Enable"},
                    },
                    voltage_supply="12.0",
                ),
            )
        )
    # Power supervisors, load switches, eFuses
    power_misc = [
        (
            "tps3839g33dbvr",
            "TPS3839G33DBVR",
            "TPS3839",
            "TI",
            "SOT-23-3",
            "Voltage supervisor 3.3V open-drain",
            "https://www.ti.com/lit/ds/symlink/tps3839.pdf",
        ),
        (
            "max16054ata",
            "MAX16054ATA+",
            "MAX16054",
            "Maxim",
            "SOT-23-6",
            "Push-button controller",
            "https://datasheets.maximintegrated.com/en/ds/MAX16054.pdf",
        ),
        (
            "tps2553drvr",
            "TPS2553DRVR",
            "TPS2553",
            "TI",
            "DRVR-6",
            "Current limited load switch 5.5V",
            "https://www.ti.com/lit/ds/symlink/tps2553.pdf",
        ),
        (
            "stf202-33t1g",
            "STF202-33T1G",
            "STF202",
            _ON_SEMI,
            "SOT-323-6",
            "Dual MOSFET load switch",
            "https://www.onsemi.com/pdf/datasheet/stf202-d.pdf",
        ),
        (
            "tps2116dbvr",
            "TPS2116DBVR",
            "TPS2116",
            "TI",
            "SOT-23-5",
            "Power multiplexer 2:1 5.5V",
            "https://www.ti.com/lit/ds/symlink/tps2116.pdf",
        ),
        (
            "sg6418-033xtf",
            "SG6418-033XTF",
            "SG6418",
            "Sg Micro",
            "SOT-23-5",
            "Linear regulator 3.3V 300mA",
            "https://example.com/sg6418.pdf",
        ),
        (
            "ts30042-m033qnit",
            "TS30042-M033QNIT",
            "TS30042",
            "Taiwan Semi",
            "SOT-23-5",
            "LDO 3.3V 300mA",
            "internal://zaptrace/component-family/ts30042",
        ),
        (
            "pca9306dctt",
            "PCA9306DCTT",
            "PCA9306",
            "TI",
            "DSBGA-6",
            "Dual I2C level translator",
            "https://www.ti.com/lit/ds/symlink/pca9306.pdf",
        ),
        (
            "max890leuk",
            "MAX890LEUK+T",
            "MAX890",
            "Maxim",
            "SOT-23-5",
            "1A reverse voltage protection",
            "https://datasheets.maximintegrated.com/en/ds/MAX890.pdf",
        ),
        (
            "bdpc0004efv-c",
            "BDPC0004EFV-C",
            "BDPC0004",
            "Rohm",
            "VSON010X2",
            "12V 4A gate driver",
            "https://fscdn.rohm.com/en/products/databook/datasheet/ic/gate_driver/bdpc0004efv-e.pdf",
        ),
    ]
    for pid, name, mpn, mfr, pkg, desc, ds in power_misc:
        parts.append(
            (
                "power",
                pid,
                _part(
                    pid,
                    name,
                    "power",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "VIN": {"type": "power", "description": "Input"},
                        "VOUT": {"type": "output", "description": "Output"},
                        "GND": {"type": "power", "description": "Ground"},
                        "CTRL": {"type": "input", "description": "Control/Enable"},
                    },
                ),
            )
        )
    return parts


def generate_mcus() -> list[tuple[str, str, dict]]:
    mcus = [
        (
            "stm32f103c8t6",
            "STM32F103C8T6",
            "STM32F103C8T6",
            "STMicro",
            "LQFP-48",
            "ARM Cortex-M3 72MHz 64KB Flash",
            "https://www.st.com/resource/en/datasheet/stm32f103c8.pdf",
        ),
        (
            "stm32f401ccu6",
            "STM32F401CCU6",
            "STM32F401CCU6",
            "STMicro",
            "UFQFPN-48",
            "Cortex-M4 84MHz 256KB",
            "https://www.st.com/resource/en/datasheet/stm32f401cc.pdf",
        ),
        (
            "stm32g031k8t6",
            "STM32G031K8T6",
            "STM32G031K8T6",
            "STMicro",
            "LQFP-32",
            "Cortex-M0+ 64MHz 64KB",
            "https://www.st.com/resource/en/datasheet/stm32g031k8.pdf",
        ),
        (
            "stm32l452ret6",
            "STM32L452RET6",
            "STM32L452RET6",
            "STMicro",
            "LQFP-64",
            "Cortex-M4 80MHz ultra-low power",
            "https://www.st.com/resource/en/datasheet/stm32l452re.pdf",
        ),
        (
            "stm32u585cit6q",
            "STM32U585CIT6Q",
            "STM32U585CIT6Q",
            "STMicro",
            "UFBGA-169",
            "Cortex-M33 160MHz TrustZone",
            "https://www.st.com/resource/en/datasheet/stm32u585ci.pdf",
        ),
        (
            "nrf52810-qfaa-r7",
            "nRF52810-QFAA",
            "nRF52810-QFAA-R7",
            "Nordic",
            "QFN-48",
            "Bluetooth 5.0 Cortex-M4 16KB RAM",
            "https://infocenter.nordicsemi.com/pdf/nRF52810_PS_v1.3.pdf",
        ),
        (
            "nrf52832-qfaa-r7",
            "nRF52832-QFAA",
            "nRF52832-QFAA-R7",
            "Nordic",
            "QFN-48",
            "Bluetooth 5.0 Cortex-M4 512KB",
            "https://infocenter.nordicsemi.com/pdf/nRF52832_PS_v1.8.pdf",
        ),
        (
            "nrf9160-sica-r3",
            "nRF9160-SICA",
            "nRF9160-SICA-R3",
            "Nordic",
            "LGA-256",
            "LTE-M/NB-IoT Cortex-M33",
            "https://infocenter.nordicsemi.com/pdf/nRF9160_PS_v2.2.pdf",
        ),
        (
            "esp32-s3-mini-1-n8",
            "ESP32-S3-MINI-1-N8",
            "ESP32-S3-MINI-1-N8",
            "Espressif",
            "LCC-56",
            "WiFi+BT5 Xtensa LX7 8MB",
            "https://www.espressif.com/sites/default/files/documentation/esp32-s3-mini-1_mini-1u_datasheet_en.pdf",
        ),
        (
            "rp2040",
            "RP2040",
            "RP2040",
            "Raspberry Pi",
            "QFN-56",
            "Dual-core Cortex-M0+ 133MHz 264KB SRAM",
            "https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf",
        ),
        (
            "rp2350a",
            "RP2350A",
            "RP2350A",
            "Raspberry Pi",
            "QFN-60",
            "Dual Cortex-M33 150MHz 520KB SRAM",
            "https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf",
        ),
        (
            "pic16f18446-iml",
            "PIC16F18446-I/ML",
            "PIC16F18446",
            "Microchip",
            "QFN-20",
            "PIC16 20MHz 28KB flash",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/PIC16F18446-Datasheet-40001985.pdf",
        ),
        (
            "attiny85v-10mu",
            "ATtiny85V-10MU",
            "ATtiny85V",
            "Microchip",
            "QFN-20",
            "AVR 1MHz-10MHz 8KB flash",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-2586-AVR-8-bit-Microcontroller-ATtiny25-ATtiny45-ATtiny85_Datasheet.pdf",
        ),
        (
            "samd21g18a-mu",
            "SAMD21G18A-MU",
            "SAMD21G18A",
            "Microchip",
            "QFN-48",
            "ARM Cortex-M0+ 48MHz 256KB USB",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/SAM-D21DA1-Family-Data-Sheet-DS40001882G.pdf",
        ),
        (
            "saml21j18b-mu",
            "SAML21J18B-MU",
            "SAML21J18B",
            "Microchip",
            "QFN-64",
            "Cortex-M0+ ultra-low power 256KB",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/SAM-L21-Family-Datasheet-DS60001477C.pdf",
        ),
        (
            "gd32f103c8t6",
            "GD32F103C8T6",
            "GD32F103C8T6",
            "GigaDevice",
            "LQFP-48",
            "Cortex-M3 108MHz 64KB compatible STM32",
            "https://www.gigadevice.com/datasheet/gd32f103xxxx-datasheet/",
        ),
        (
            "ch32v203g6u6",
            "CH32V203G6U6",
            "CH32V203G6U6",
            "WCH",
            "QFN-28",
            "RISC-V 144MHz 32KB USB FS",
            "https://www.wch-ic.com/products/CH32V203.html",
        ),
        (
            "k22fn512vlq12",
            "MK22FN512VLQ12",
            "K22FN512VLQ12",
            "NXP",
            "LQFP-144",
            "Kinetis Cortex-M4 120MHz 512KB",
            "https://www.nxp.com/docs/en/data-sheet/K22P144M120SF5V2.pdf",
        ),
    ]
    parts = []
    for pid, name, mpn, mfr, pkg, desc, ds in mcus:
        parts.append(
            (
                "mcu",
                pid,
                _part(
                    pid,
                    name,
                    "mcu",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "VDD": {"type": "power", "description": "Supply voltage"},
                        "GND": {"type": "power", "description": "Ground"},
                        "RESET": {"type": "input", "description": "Reset (active low)"},
                        "XTAL1": {"type": "input", "description": "Crystal input"},
                        "XTAL2": {"type": "output", "description": "Crystal output"},
                        "GPIO": {"type": "bidirectional", "description": "General purpose I/O"},
                        "SWDIO": {"type": "bidirectional", "description": "SWD data"},
                        "SWCLK": {"type": "input", "description": "SWD clock"},
                    },
                    voltage_supply="3.3",
                ),
            )
        )
    return parts


def generate_sensors() -> list[tuple[str, str, dict]]:
    sensors = [
        (
            "lsm6dso",
            "LSM6DSO",
            "LSM6DSO",
            "STMicro",
            "LGA-14",
            "IMU 6-axis accel+gyro SPI/I2C",
            "https://www.st.com/resource/en/datasheet/lsm6dso.pdf",
        ),
        (
            "icm-42688-p",
            "ICM-42688-P",
            "ICM-42688-P",
            "TDK InvenSense",
            "LGA-14",
            "6-axis IMU ±2000dps ±16g",
            "https://invensense.tdk.com/wp-content/uploads/2020/11/DS-000347-ICM-42688-P-v1.6.pdf",
        ),
        (
            "lis3mdltr",
            "LIS3MDL",
            "LIS3MDLTR",
            "STMicro",
            "LGA-12",
            "3-axis magnetometer ±16 gauss",
            "https://www.st.com/resource/en/datasheet/lis3mdl.pdf",
        ),
        (
            "shtc3",
            "SHTC3",
            "SHTC3",
            "Sensirion",
            "UFDFPN-4",
            "Humidity+temp 1.8V ultra-low power",
            "https://www.sensirion.com/media/documents/643F9C8E/63FC1A65/Sensirion_Humidity_Sensors_SHTC3_Datasheet.pdf",
        ),
        (
            "htu21d-f",
            "HTU21D-F",
            "HTU21D-F",
            "TE Connectivity",
            "DFN-6",
            "Digital humidity sensor ±2% RH",
            "https://www.te.com/commerce/DocumentDelivery/DDEController?Action=showdoc&DocId=Data+Sheet%7FHPC199_6%7FA%7Fpdf%7FEnglish%7FENG_DS_HPC199_6_A.pdf",
        ),
        (
            "bmp388",
            "BMP388",
            "BMP388",
            "Bosch",
            "LGA-10",
            "Barometric pressure 300-1250 hPa",
            "https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp388-ds001.pdf",
        ),
        (
            "ms5611-01ba03",
            "MS5611-01BA03",
            "MS5611-01BA03",
            "TE Connectivity",
            "SMD-8",
            "Pressure 10-1200 mbar 24-bit",
            "https://www.te.com/commerce/DocumentDelivery/DDEController?Action=showdoc&DocId=Data+Sheet%7FMS5611-01BA03%7FB3%7Fpdf%7FEnglish%7FENG_DS_MS5611-01BA03_B3.pdf",
        ),
        (
            "vcnl4040m3oae",
            "VCNL4040",
            "VCNL4040M3OAE",
            "Vishay",
            "OPLGA-8",
            "Proximity sensor with ambient light",
            "https://www.vishay.com/docs/84274/vcnl4040.pdf",
        ),
        (
            "apds-9960",
            "APDS-9960",
            "APDS-9960",
            "Broadcom",
            "LCC-8",
            "Gesture+proximity+color+ALS sensor",
            "https://docs.broadcom.com/doc/AV02-4191EN",
        ),
        (
            "tcs34725fnr",
            "TCS34725",
            "TCS34725FNR",
            "AMS",
            "OLGA-16",
            "Color+ALS sensor I2C",
            "https://ams.com/documents/20143/36005/TCS3472_DS000390_2-00.pdf",
        ),
        (
            "mlx90614esf-baa",
            "MLX90614ESF-BAA",
            "MLX90614ESF-BAA",
            "Melexis",
            "TO-39",
            "IR thermometer ±0.5°C",
            "https://www.melexis.com/-/media/files/documents/datasheets/mlx90614-datasheet-melexis.pdf",
        ),
        (
            "vl53l0x",
            "VL53L0X",
            "VL53L0X",
            "STMicro",
            "LGA-12",
            "ToF ranging 2m 940nm laser",
            "https://www.st.com/resource/en/datasheet/vl53l0x.pdf",
        ),
        (
            "vl53l5cx",
            "VL53L5CX",
            "VL53L5CX",
            "STMicro",
            "LGA-16",
            "ToF 8x8 zone SPAD sensor 4m",
            "https://www.st.com/resource/en/datasheet/vl53l5cx.pdf",
        ),
        (
            "max30102",
            "MAX30102",
            "MAX30102",
            "Maxim",
            "OLGA-14",
            "Pulse oximeter & heart rate sensor",
            "https://datasheets.maximintegrated.com/en/ds/MAX30102.pdf",
        ),
        (
            "isl29125iroz-t7a",
            "ISL29125",
            "ISL29125IROZ-T7A",
            "Renesas",
            "ODFN-6",
            "RGB color light sensor I2C",
            "https://www.renesas.com/us/en/document/dst/isl29125-datasheet",
        ),
        (
            "ism330dhcx",
            "ISM330DHCX",
            "ISM330DHCX",
            "STMicro",
            "LGA-14",
            "Industrial 6-axis IMU IP67",
            "https://www.st.com/resource/en/datasheet/ism330dhcx.pdf",
        ),
        (
            "bma456",
            "BMA456",
            "BMA456",
            "Bosch",
            "LGA-12",
            "16g 3-axis accelerometer step counter",
            "https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bma456-ds000.pdf",
        ),
        (
            "sps30",
            "SPS30",
            "SPS30",
            "Sensirion",
            "DIP-5",
            "PM2.5 particulate matter sensor UART/I2C",
            "https://www.sensirion.com/media/documents/8600FF88/616542B5/Sensirion_PM_Sensors_Datasheet_SPS30.pdf",
        ),
        (
            "sgp40-d-r4",
            "SGP40",
            "SGP40-D-R4",
            "Sensirion",
            "DFN-6",
            "VOC index gas sensor I2C",
            "https://www.sensirion.com/media/documents/F76CEFD1/61633C5B/Sensirion_Gas_Sensors_SGP40_Datasheet.pdf",
        ),
        (
            "ina3221aidgsr",
            "INA3221",
            "INA3221AIDGSR",
            "TI",
            "HTSSOP-20",
            "3-channel current/voltage monitor",
            "https://www.ti.com/lit/ds/symlink/ina3221.pdf",
        ),
        (
            "hx711",
            "HX711",
            "HX711",
            "AVIA Semiconductor",
            "SOP-16",
            "24-bit ADC for weigh scales",
            "https://cdn.sparkfun.com/datasheets/Sensors/ForceFlex/hx711_english.pdf",
        ),
        (
            "mcp3208-ci-sl",
            "MCP3208-CI/SL",
            "MCP3208",
            "Microchip",
            "SOIC-16",
            "8-ch 12-bit SPI ADC",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/21298e.pdf",
        ),
        (
            "tmp117naidrl",
            "TMP117",
            "TMP117NAIDRL",
            "TI",
            "WSON-6",
            "High accuracy digital thermometer ±0.1°C",
            "https://www.ti.com/lit/ds/symlink/tmp117.pdf",
        ),
        (
            "ntc-10k-0402",
            "NTC Thermistor 10k 0402",
            "B57891M0103K000",
            "TDK",
            "0402",
            "NTC 10k@25°C B=3988K",
            "https://product.tdk.com/system/files/dam/doc/product/sensor/ntc/ntc_smd/data_sheet/tpye_b57891m.pdf",
        ),
        (
            "ds18b20",
            "DS18B20",
            "DS18B20",
            "Maxim",
            "TO-92",
            "1-Wire digital thermometer ±0.5°C",
            "https://datasheets.maximintegrated.com/en/ds/DS18B20.pdf",
        ),
    ]
    parts = []
    for pid, name, mpn, mfr, pkg, desc, ds in sensors:
        parts.append(
            (
                "sensor",
                pid,
                _part(
                    pid,
                    name,
                    "sensor",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "VDD": {"type": "power", "description": "Supply"},
                        "GND": {"type": "power", "description": "Ground"},
                        "SDA": {"type": "bidirectional", "description": "I2C SDA / MOSI"},
                        "SCL": {"type": "input", "description": "I2C SCL / SCK"},
                        "INT": {"type": "output", "description": "Interrupt"},
                        "CS": {"type": "input", "description": "Chip select (SPI)"},
                    },
                    voltage_supply="3.3",
                ),
            )
        )
    return parts


def generate_connectors() -> list[tuple[str, str, dict]]:
    connectors = [
        (
            "ffc-fpc-10p-0.5mm",
            "FFC/FPC 10pin 0.5mm",
            "FFC_10P_05",
            "Generic",
            "FFC-10P-0.5mm",
            "FFC/FPC 10-pin 0.5mm pitch",
            "internal://zaptrace/connector-family/ffc-fpc",
        ),
        (
            "ffc-fpc-20p-0.5mm",
            "FFC/FPC 20pin 0.5mm",
            "FFC_20P_05",
            "Generic",
            "FFC-20P-0.5mm",
            "FFC/FPC 20-pin 0.5mm pitch",
            "internal://zaptrace/connector-family/ffc-fpc",
        ),
        (
            "sim-card-6p",
            "SIM Card Holder 6P",
            "SIM_6P",
            "Amphenol",
            "SIM-6P",
            "Nano SIM card holder 6-contact",
            "https://www.amphenol.com/product/product_detail/38/",
        ),
        (
            "microsd-push-pull",
            "MicroSD Push-Pull",
            "DM3D-SF",
            "Hirose",
            "MSD-8P",
            "MicroSD card holder push-pull",
            "https://www.hirose.com/product/en/products/DM3/DM3D-SF/",
        ),
        (
            "usb-c-6p-mid-mount",
            "USB-C 6P Mid-Mount",
            "TYPE-C-31-M-12",
            "Korean Hroparts",
            "USB-C-6P",
            "USB-C 6P mid-mount SMD",
            "https://www.hroparts.com/product/usb-c-type-c-smd",
        ),
        (
            "hdmi-type-a-19p",
            "HDMI Type A 19P",
            "HDMI_A_19P",
            "Amphenol",
            "HDMI-A-19P",
            "HDMI Type-A 19-pin vertical",
            "https://www.amphenol.com/product/product_detail/40/",
        ),
        (
            "dp-displayport-20p",
            "DisplayPort 20P",
            "DP_20P",
            "JAE",
            "DP-20P",
            "DisplayPort receptacle 20-pin",
            "internal://zaptrace/connector-family/dp",
        ),
        (
            "ethernet-rj45-magjack",
            "RJ45 MagJack 10/100",
            "HR911105A",
            "Hanrun",
            "RJ45-MD-MAGJACK",
            "RJ45 with magnetics 10/100 Ethernet",
            "https://www.hanrun.com/downfiles/HR911105A.pdf",
        ),
        (
            "header-2x5-2.54mm",
            "Header 2x5 2.54mm",
            "PINHD-2X5",
            "Generic",
            "PinHeader-2x5-2.54mm",
            "Pin header 10-pin 2x5 2.54mm pitch",
            "internal://zaptrace/connector-family/pinhd",
        ),
        (
            "header-1x8-2.54mm",
            "Header 1x8 2.54mm",
            "PINHD-1X8",
            "Generic",
            "PinHeader-1x8-2.54mm",
            "Pin header 8-pin single row 2.54mm",
            "internal://zaptrace/connector-family/pinhd",
        ),
        (
            "terminal-3p-3.5mm",
            "Terminal Block 3P 3.5mm",
            "TB3P-35",
            "Phoenix",
            "TB-3P-3.5mm",
            "Screw terminal 3P 3.5mm pitch",
            "https://www.phoenixcontact.com/",
        ),
        (
            "banana-4mm-m",
            "Banana Jack 4mm",
            "BJ-4MM",
            "Mueller",
            "BananJack-4mm",
            "4mm banana jack socket for test",
            "internal://zaptrace/connector-family/banana",
        ),
    ]
    parts = []
    for pid, name, mpn, mfr, pkg, desc, ds in connectors:
        pin_count = int(mpn.split("_")[1]) if "_" in mpn and mpn.split("_")[1].isdigit() else 4
        parts.append(
            (
                "connector",
                pid,
                _part(
                    pid,
                    name,
                    "connector",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {f"P{i}": {"type": "passive", "description": f"Pin {i}"} for i in range(1, min(pin_count + 1, 9))},
                ),
            )
        )
    return parts


def generate_memory() -> list[tuple[str, str, dict]]:
    memories = [
        (
            "m24m02-drmn6tp",
            "M24M02-DR",
            "M24M02-DRMN6TP",
            "STMicro",
            "SO-8",
            "I2C EEPROM 2Mb 1MHz",
            "https://www.st.com/resource/en/datasheet/m24m02-dr.pdf",
        ),
        (
            "cat24c256wi-gt3",
            "CAT24C256",
            "CAT24C256WI-GT3",
            _ON_SEMI,
            "SOIC-8",
            "I2C EEPROM 256Kb",
            "https://www.onsemi.com/pdf/datasheet/cat24c256-d.pdf",
        ),
        (
            "w25q128jvsiq",
            "W25Q128JV",
            "W25Q128JVSIQ",
            "Winbond",
            "SOP-8",
            "SPI NOR Flash 128Mb 133MHz",
            "https://www.winbond.com/resource-files/w25q128jv_dtr%20revc%2003272018%20plus.pdf",
        ),
        (
            "gd25q64cwig",
            "GD25Q64C",
            "GD25Q64CWIG",
            "GigaDevice",
            "SOIC-8",
            "SPI NOR Flash 64Mb 120MHz",
            "https://www.gigadevice.com/datasheet/gd25q64c/",
        ),
        (
            "mx25l51245gm2i-08g",
            "MX25L51245G",
            "MX25L51245GM2I-08G",
            "Macronix",
            "SOP-16",
            "SPI NOR Flash 512Mb",
            "https://www.macronix.com/Lists/Datasheet/Attachments/8715/MX25L51245G,%203V,%20512Mb,%20v1.4.pdf",
        ),
        (
            "is62wv51216bll-55tli",
            "IS62WV51216B",
            "IS62WV51216BLL-55TLI",
            "ISSI",
            "TSOP-44",
            "SRAM 8Mb 55ns parallel",
            "https://www.issi.com/WW/pdf/62-65WV51216BFLL.pdf",
        ),
        (
            "cy62157ev30ll-45zsxi",
            "CY62157EV30",
            "CY62157EV30LL-45ZSXI",
            "Infineon/Cypress",
            "BGA-48",
            "4Mb fast SRAM 45ns",
            "https://www.infineon.com/dgdl/Infineon-CY62157EV30-DataSheet-v08_00-EN.pdf",
        ),
        (
            "mt41k128m16jt-125",
            "MT41K128M16JT",
            "MT41K128M16JT-125",
            "Micron",
            "FBGA-96",
            "DDR3L 256MB 800MHz",
            "https://media-www.micron.com/media/micron/global/documents/products/data-sheet/dram/ddr3l/2gb_ddr3l.pdf",
        ),
        (
            "sdram-mt48lc16m16a2p",
            "MT48LC16M16A2P",
            "MT48LC16M16A2P-7E:G",
            "Micron",
            "TSOP-54",
            "SDRAM 256MB 143MHz",
            "https://media-www.micron.com/media/micron/global/documents/products/data-sheet/dram/sdram/sdram_256mb_3_3v.pdf",
        ),
    ]
    parts = []
    for pid, name, mpn, mfr, pkg, desc, ds in memories:
        parts.append(
            (
                "memory",
                pid,
                _part(
                    pid,
                    name,
                    "memory",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "VCC": {"type": "power", "description": "Supply voltage"},
                        "GND": {"type": "power", "description": "Ground"},
                        "CS": {"type": "input", "description": "Chip select"},
                        "SCK": {"type": "input", "description": "Serial clock / CLK"},
                        "MOSI": {"type": "input", "description": "Data input DI/DQ0"},
                        "MISO": {"type": "output", "description": "Data output DO/DQ1"},
                        "WP": {"type": "input", "description": "Write protect"},
                        "HOLD": {"type": "input", "description": "Hold/Reset"},
                    },
                    voltage_supply="3.3",
                ),
            )
        )
    return parts


def generate_rf() -> list[tuple[str, str, dict]]:
    rf_parts = [
        (
            "cc2500rget",
            "CC2500",
            "CC2500RGET",
            "TI",
            "QFN-20",
            "2.4GHz RF transceiver 1Mbps",
            "https://www.ti.com/lit/ds/symlink/cc2500.pdf",
        ),
        (
            "rfm95w-915s2",
            "RFM95W",
            "RFM95W-915S2",
            "HopeRF",
            "SMD-22",
            "LoRa 915MHz SX1276 +20dBm",
            "https://www.hoperf.com/data/upload/portal/20190801/RFM95W-V2.0.pdf",
        ),
        (
            "at86rf233-zu",
            "AT86RF233",
            "AT86RF233-ZU",
            "Microchip",
            "QFN-32",
            "802.15.4 2.4GHz transceiver",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-8351-MCU_Wireless-AT86RF233_Datasheet.pdf",
        ),
        (
            "sky13414-485lf",
            "SKY13414-485LF",
            "SKY13414-485LF",
            "Skyworks",
            "MLF-12",
            "SPDT RF switch 6GHz 2W",
            "https://www.skyworksinc.com/-/media/Skyworks/SL/documents/public/data-sheets/SKY13414-485LF.pdf",
        ),
        (
            "se2435l",
            "SE2435L",
            "SE2435L",
            "SiGe Semi",
            "QFN-20",
            "2.4GHz FEM PA+LNA for WiFi/BT",
            "https://www.skyworksinc.com/-/media/Skyworks/SL/documents/public/data-sheets/se2435l.pdf",
        ),
        (
            "bfp840esd",
            "BFP840ESD",
            "BFP840ESD H6327",
            "Infineon",
            "SOT-343",
            "NPN RF transistor 25GHz NF=0.4dB",
            "https://www.infineon.com/dgdl/Infineon-BFP840ESD-DS-v02_01-EN.pdf",
        ),
        (
            "murata-chip-ant-868",
            "Chip Antenna 868MHz",
            "ANFCA0750A14A00",
            "Murata",
            "LGA-0201",
            "Chip antenna 868MHz -1.5dBi",
            "https://www.murata.com/en-eu/api/pdfdownloadapi?cate=&partno=ANFCA0750A14A00",
        ),
        (
            "avx-sma-pcb-868",
            "SMA PCB Antenna 868MHz",
            "SMA-ANT-868",
            "AVX/Kyocera",
            "SMA-THT",
            "PCB mount SMA antenna 3dBi",
            "internal://zaptrace/connector-family/rf-antenna",
        ),
        (
            "epcos-saw-2450mhz",
            "SAW Filter 2.45GHz",
            "B5157",
            "TDK EPCOS",
            "SMD-6",
            "SAW bandpass filter 2450MHz",
            "https://product.tdk.com/info/en/catalog/datasheets/rf_saw_bf_b5157.pdf",
        ),
        (
            "murata-balun-2450",
            "Balun 2450MHz",
            "LDB21SDJ3F0004A",
            "Murata",
            "SMD-8",
            "50Ω balun for WiFi/BT 2.4GHz",
            "https://www.murata.com/en-us/products/connectivitymodule/balun",
        ),
        (
            "rfm69hcw",
            "RFM69HCW",
            "RFM69HCW-915S2",
            "HopeRF",
            "SMD-22",
            "ISM 915MHz SX1231 +20dBm FSK OOK",
            "https://www.hoperf.com/data/upload/portal/20190801/RFM69HCW-V1.1.pdf",
        ),
        (
            "sx1280imltrt",
            "SX1280",
            "SX1280IMLTRT",
            "Semtech",
            "QFN-24",
            "2.4GHz LoRa ranging transceiver +12.5dBm",
            "https://semtech.com/uploads/documents/DS_SX1280-1_V2.2.pdf",
        ),
    ]
    parts = []
    for pid, name, mpn, mfr, pkg, desc, ds in rf_parts:
        parts.append(
            (
                "rf",
                pid,
                _part(
                    pid,
                    name,
                    "rf",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "VCC": {"type": "power", "description": "Supply"},
                        "GND": {"type": "power", "description": "Ground"},
                        "ANT": {"type": "bidirectional", "description": "RF antenna"},
                        "MOSI": {"type": "input", "description": "SPI MOSI"},
                        "MISO": {"type": "output", "description": "SPI MISO"},
                        "SCK": {"type": "input", "description": "SPI SCK"},
                        "CS": {"type": "input", "description": "SPI CS"},
                        "IRQ": {"type": "output", "description": "Interrupt"},
                    },
                    voltage_supply="3.3",
                ),
            )
        )
    return parts


def generate_timing() -> list[tuple[str, str, dict]]:
    timing = [
        (
            "abracon-asmb-12.000mhz",
            "ASMB 12.0MHz Crystal",
            "ASMB-12.000MHZ-LC-T",
            "Abracon",
            "SMD-2P",
            "12MHz crystal ±20ppm 18pF",
            "https://abracon.com/abrasive/ASMB.pdf",
        ),
        (
            "epson-fa-128-16mhz",
            "FA-128 16MHz Crystal",
            "FA-128 16.000MHZ 8PF",
            "Epson",
            "SMD-2P",
            "16MHz crystal ±10ppm 8pF",
            "https://5.epson.com/File/media/Crystal_product/XTAL/HC49U_FCC_FAU_FA128.pdf",
        ),
        (
            "ndk-nte7050sb-25mhz",
            "NTD7050SB 25MHz TCXO",
            "NTE7050SB-25M",
            "NDK",
            "SMD-4P",
            "TCXO 25MHz ±2.5ppm",
            "https://ndk.com/images/products/search/documentation/NTE7050SB.pdf",
        ),
        (
            "rv8803-c7-ta-020",
            "RV-8803 RTC",
            "RV-8803-C7-32.768kHz-TA-020",
            "Micro Crystal",
            "VDFN-14",
            "RTC I2C 32kHz TCXO crystal",
            "https://www.microcrystal.com/fileadmin/Media/Products/RTC/App.Manual/RV-8803-C7_App-Manual.pdf",
        ),
        (
            "pcf8523t-1",
            "PCF8523T",
            "PCF8523T/1,118",
            "NXP",
            "SOIC-8",
            "RTC I2C alarm timer 3.0V",
            "https://www.nxp.com/docs/en/data-sheet/PCF8523.pdf",
        ),
        (
            "ds3231sn-t-r",
            "DS3231SN",
            "DS3231SN#T&R",
            "Maxim",
            "SOIC-16",
            "I2C RTC ±2ppm TXCO integrated crystal",
            "https://datasheets.maximintegrated.com/en/ds/DS3231.pdf",
        ),
        (
            "mx-pll-si5351a",
            "Si5351A-B-GT",
            "Si5351A-B-GT",
            _SILICON_LABS,
            "MSOP-10",
            "Any-frequency CMOS clock gen I2C",
            "https://www.silabs.com/documents/public/data-sheets/Si5351-B.pdf",
        ),
        (
            "idt5v9885pgi8",
            "IDT5V9885PGI8",
            "5V9885PGI8",
            "Renesas/IDT",
            "QFN-8",
            "Programmable clock oscillator",
            "https://www.renesas.com/us/en/document/dst/5v9885-datasheet",
        ),
        (
            "ndk-nx3225sa-20mhz",
            "NX3225SA 20MHz OSC",
            "NX3225SA-20M-EXS00A-CS18354",
            "NDK",
            "SMD-4P",
            "20MHz CMOS oscillator ±25ppm",
            "https://ndk.com/images/products/search/documentation/NX3225SA.pdf",
        ),
        (
            "ecs-2520mv-240-bn-tr",
            "ECS-2520MV 24MHz",
            "ECS-2520MV-240-BN-TR",
            "ECS",
            "SMD-4P",
            "24MHz MEMS oscillator ±20ppm",
            "https://ecsxtal.com/store/pdf/ECS-2520MV.pdf",
        ),
        (
            "seikoepson-sg8002",
            "SG-8002 Oscillator",
            "SG8002CA 1.000000M-PTBL:ROHS",
            "Epson",
            "DIP-4",
            "1MHz CMOS OSC ±50ppm",
            "https://5.epson.com/",
        ),
        (
            "st-m41t82m6f",
            "M41T82 RTC",
            "M41T82M6F",
            "STMicro",
            "VFQFPN-12",
            "RTC SPI/I2C 1Hz–32kHz square wave",
            "https://www.st.com/resource/en/datasheet/m41t82.pdf",
        ),
    ]
    parts = []
    for pid, name, mpn, mfr, pkg, desc, ds in timing:
        parts.append(
            (
                "timing",
                pid,
                _part(
                    pid,
                    name,
                    "timing",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "XOUT": {"type": "output", "description": "Crystal/clock output"},
                        "XIN": {"type": "input", "description": "Crystal/reference input"},
                        "VCC": {"type": "power", "description": "Supply"},
                        "GND": {"type": "power", "description": "Ground"},
                    },
                    voltage_supply="3.3",
                ),
            )
        )
    return parts


def generate_protection() -> list[tuple[str, str, dict]]:
    protection = [
        (
            "tvs-smaj5.0a",
            "SMAJ5.0A TVS",
            "SMAJ5.0A",
            "Vishay",
            "SMA",
            "TVS diode 5V 400W unidirectional",
            "https://www.vishay.com/docs/88293/smaj5.pdf",
        ),
        (
            "tvs-smaj12a",
            "SMAJ12A TVS",
            "SMAJ12A",
            "Vishay",
            "SMA",
            "TVS diode 12V 400W unidirectional",
            "https://www.vishay.com/docs/88293/smaj12.pdf",
        ),
        (
            "esd-prtr5v0u2x",
            "PRTR5V0U2X ESD",
            "PRTR5V0U2X",
            "Nexperia",
            "SOT-363",
            "ESD USB line protection dual rail",
            "https://assets.nexperia.com/documents/data-sheet/PRTR5V0U2X.pdf",
        ),
        (
            "esd-usblc6-4sc6",
            "USBLC6-4SC6 ESD",
            "USBLC6-4SC6",
            "STMicro",
            "SOT-363",
            "ESD USB 4-line protection",
            "https://www.st.com/resource/en/datasheet/usblc6-4sc6.pdf",
        ),
        (
            "ptc-rgef050",
            "RGEF050 PTC Fuse",
            "RGEF050",
            "TE/Raychem",
            "1812",
            "PTC resettable fuse 500mA 33V",
            "https://www.te.com/commerce/DocumentDelivery/DDEController?Action=showdoc&DocId=Data+Sheet%7FRGEF%7F0709%7Fpdf",
        ),
        (
            "ptc-nanosmdc050f",
            "NANO SMDC050F PTC",
            "NANO-SMDC050F/24X-2",
            "Littelfuse",
            "0402",
            "PTC fuse 500mA 24V 0402",
            "https://www.littelfuse.com/",
        ),
        (
            "fuse-0402-1a",
            "Fuse 1A 0402",
            "0402L100SLYR",
            "Littelfuse",
            "0402",
            "Fast blow fuse 1A 32V 0402",
            "https://www.littelfuse.com/",
        ),
        (
            "varistor-v07e140",
            "Varistor V07E140",
            "V07E140P",
            "TDK Epcos",
            "Disc-7mm",
            "Metal oxide varistor 140V",
            "https://product.tdk.com/info/en/catalog/datasheets/varistor_standard_leadtype_en.pdf",
        ),
        (
            "esd-ip4220cz6-tz",
            "IP4220CZ6-TZ ESD",
            "IP4220CZ6-TZ",
            "Nexperia",
            "SOT-23-6",
            "ESD I2C SDA/SCL dual line 3.3V",
            "https://assets.nexperia.com/documents/data-sheet/IP4220CZ6.pdf",
        ),
        (
            "tvs-pesd5v0s1ba",
            "PESD5V0S1BA TVS",
            "PESD5V0S1BA,115",
            "Nexperia",
            "SOD-323",
            "TVS 5V 250mW unidirectional",
            "https://assets.nexperia.com/documents/data-sheet/PESD5V0S1BA.pdf",
        ),
        (
            "tvs-smbj30a",
            "SMBJ30A TVS",
            "SMBJ30A",
            "Vishay",
            "SMB",
            "TVS diode 30V 600W bidirectional",
            "https://www.vishay.com/docs/88397/smbj.pdf",
        ),
        (
            "gdt-cg72sr-090lc",
            "CG72SR-090LC Gas Tube",
            "CG72SR-090LC",
            "Bourns",
            "SMD-2P",
            "Gas discharge tube 90V 20kA",
            "https://www.bourns.com/docs/Product-Datasheets/CG72SR.pdf",
        ),
    ]
    parts = []
    for pid, name, mpn, mfr, pkg, desc, ds in protection:
        parts.append(
            (
                "protection",
                pid,
                _part(
                    pid,
                    name,
                    "protection",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "A": {"type": "bidirectional", "description": "Anode / Line 1"},
                        "K": {"type": "bidirectional", "description": "Cathode / Line 2"},
                    },
                ),
            )
        )
    return parts


def generate_security() -> list[tuple[str, str, dict]]:
    security = [
        (
            "atecc608a-mahda",
            "ATECC608A",
            "ATECC608A-MAHDA-T",
            "Microchip",
            "UDFN-8",
            "CryptoAuth secure element ECC508",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/ATECC608A-TNGMOD-CryptoAuthentication-Device-Summary-Data-Sheet-DS40002237A.pdf",
        ),
        (
            "se050c2-t1a-1021",
            "SE050C2",
            "SE050C2T1A/1022",
            "NXP",
            "WLCSP-12",
            "Secure element IoT I2C SCP03",
            "https://www.nxp.com/docs/en/data-sheet/SE050-DATASHEET.pdf",
        ),
        (
            "maxq1065gef+",
            "MAXQ1065",
            "MAXQ1065GEF+",
            "Maxim",
            "TQFN-28",
            "DeepCover secure microcontroller",
            "https://datasheets.maximintegrated.com/en/ds/MAXQ1065.pdf",
        ),
        (
            "stm32wba52cgu6",
            "STM32WBA52",
            "STM32WBA52CGU6",
            "STMicro",
            "UFQFPN-48",
            "Cortex-M33 BLE 5.4 PSA L3 TrustZone",
            "https://www.st.com/resource/en/datasheet/stm32wba52cg.pdf",
        ),
        (
            "a71ch020ahna4",
            "A71CH020",
            "A71CH020AHNA4",
            "NXP",
            "HVQFN-32",
            "A71CH I2C secure element HSM",
            "https://www.nxp.com/docs/en/data-sheet/A71CH.pdf",
        ),
        (
            "ds28e36q+u",
            "DS28E36Q",
            "DS28E36Q+U",
            "Maxim",
            "TDFN-8",
            "DeepCover secure authenticator",
            "https://datasheets.maximintegrated.com/en/ds/DS28E36.pdf",
        ),
        (
            "optiga-trust-m-sle95250",
            "OPTIGA Trust M",
            "SLE97144XSLE9888XPXS025",
            "Infineon",
            "USON-10",
            "TLS/mTLS secure element PSA L2",
            "https://www.infineon.com/dgdl/Infineon-OPTIGA_Trust_M_SLE95250_SLE95251-DataSheet-v03_00-EN.pdf",
        ),
        (
            "stsafe-a100",
            "STSAFE-A100",
            "STSAFEA100SFGX",
            "STMicro",
            "UFDFPN-8",
            "Secure auth element I2C X.509 ECDSA",
            "https://www.st.com/resource/en/datasheet/stsafe-a100.pdf",
        ),
    ]
    parts = []
    for pid, name, mpn, mfr, pkg, desc, ds in security:
        parts.append(
            (
                "security",
                pid,
                _part(
                    pid,
                    name,
                    "security",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "VCC": {"type": "power", "description": "Supply 1.62V–3.6V"},
                        "GND": {"type": "power", "description": "Ground"},
                        "SDA": {"type": "bidirectional", "description": "I2C SDA"},
                        "SCL": {"type": "input", "description": "I2C SCL"},
                        "RESET": {"type": "input", "description": "Reset"},
                        "INT": {"type": "output", "description": "Interrupt / Alert"},
                    },
                    voltage_supply="3.3",
                ),
            )
        )
    return parts


def generate_interface() -> list[tuple[str, str, dict]]:
    iface = [
        (
            "sn74lvc8t245pwt",
            "SN74LVC8T245",
            "SN74LVC8T245PWTR",
            "TI",
            "TSSOP-24",
            "8-bit dual-supply bus transceiver",
            "https://www.ti.com/lit/ds/symlink/sn74lvc8t245.pdf",
        ),
        (
            "txs0108epwr",
            "TXS0108E",
            "TXS0108EPWR",
            "TI",
            "TSSOP-20",
            "8-ch auto-dir level shifter",
            "https://www.ti.com/lit/ds/symlink/txs0108e.pdf",
        ),
        (
            "pca9548adwr",
            "PCA9548A",
            "PCA9548ADWR",
            "TI",
            "SOIC-20",
            "I2C bus switch 8-channel",
            "https://www.ti.com/lit/ds/symlink/pca9548a.pdf",
        ),
        (
            "usb2514bi-aezg",
            "USB2514BI",
            "USB2514BI/AEZG",
            "Microchip",
            "QFN-36",
            "USB 2.0 4-port Hub controller",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/USB2513B-2514B-2533B-2534B-Data-Sheet-DS00001692C.pdf",
        ),
        (
            "cp2102n-a02-gqfn28",
            "CP2102N",
            "CP2102N-A02-GQFN28R",
            _SILICON_LABS,
            "QFN-28",
            "USB-to-UART bridge 12Mbps",
            "https://www.silabs.com/documents/public/data-sheets/cp2102n-datasheet.pdf",
        ),
        (
            "ch343p",
            "CH343P",
            "CH343P",
            "WCH",
            "SSOP-20",
            "USB full-speed UART 3Mbps multi-interface",
            "https://www.wch-ic.com/products/CH343P.html",
        ),
        (
            "tja1042t-3-1j",
            "TJA1042T",
            "TJA1042T/3/1J",
            "NXP",
            "SO-8",
            "CAN FD transceiver 5Mbps",
            "https://www.nxp.com/docs/en/data-sheet/TJA1042.pdf",
        ),
        (
            "max3485esd-t",
            "MAX3485E",
            "MAX3485ESD+T",
            "Maxim",
            "SOIC-8",
            "RS-485/422 transceiver 3.3V 10Mbps",
            "https://datasheets.maximintegrated.com/en/ds/MAX3483E-MAX3491E.pdf",
        ),
        (
            "spi-iso-adum3151brsz",
            "ADuM3151B",
            "ADUM3151BRSZ",
            "ADI",
            "QSOP-20",
            "6-channel SPI digital isolator",
            "https://www.analog.com/media/en/technical-documentation/data-sheets/ADuM3150_3151.pdf",
        ),
        (
            "iso7742dwr",
            "ISO7742",
            "ISO7742DWR",
            "TI",
            "SOIC-16",
            "4-ch reinforced digital isolator",
            "https://www.ti.com/lit/ds/symlink/iso7742.pdf",
        ),
        (
            "ft2232hl-reel",
            "FT2232HL",
            "FT2232HL-REEL",
            "FTDI",
            "LQFP-64",
            "Dual USB HS UART/JTAG/SPI/I2C interface",
            "https://ftdichip.com/wp-content/uploads/2020/07/DS_FT2232H.pdf",
        ),
        (
            "sc16is752ipwr",
            "SC16IS752",
            "SC16IS752IPWR",
            "NXP",
            "TSSOP-28",
            "Dual UART with SPI/I2C interface",
            "https://www.nxp.com/docs/en/data-sheet/SC16IS752_SC16IS762.pdf",
        ),
    ]
    parts = []
    for pid, name, mpn, mfr, pkg, desc, ds in iface:
        parts.append(
            (
                "interface",
                pid,
                _part(
                    pid,
                    name,
                    "interface",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "VCC": {"type": "power", "description": "Supply"},
                        "GND": {"type": "power", "description": "Ground"},
                        "DIN": {"type": "input", "description": "Data in"},
                        "DOUT": {"type": "output", "description": "Data out"},
                        "CLK": {"type": "input", "description": "Clock"},
                        "CS": {"type": "input", "description": "Chip select"},
                        "OE": {"type": "input", "description": "Output enable"},
                        "DIR": {"type": "input", "description": "Direction"},
                    },
                ),
            )
        )
    return parts


def generate_optoelectronics() -> list[tuple[str, str, dict]]:
    opto = [
        (
            "apa106-f5",
            "APA106 F5",
            "APA106-F5",
            "APA",
            "THT-5mm",
            "RGB LED addressable 5mm WS2812B compatible",
            "https://cdn-shop.adafruit.com/datasheets/APA106.pdf",
        ),
        (
            "led-red-0603",
            "LED Red 0603",
            "APTD1608SURCK",
            "Kingbright",
            "0603",
            "Red LED 0603 620nm 20mA",
            "https://www.kingbright.com/attachments/file/psproduct/APTD1608SURCK-Datasheet.PDF",
        ),
        (
            "led-green-0603",
            "LED Green 0603",
            "APTD1608SGCK",
            "Kingbright",
            "0603",
            "Green LED 0603 525nm 20mA",
            "https://www.kingbright.com/attachments/file/psproduct/APTD1608SGCK-Datasheet.PDF",
        ),
        (
            "led-blue-0603",
            "LED Blue 0603",
            "APTD1608SUBCCK",
            "Kingbright",
            "0603",
            "Blue LED 0603 470nm 20mA",
            "https://www.kingbright.com/attachments/file/psproduct/APTD1608SUBCCK-Datasheet.PDF",
        ),
        (
            "led-white-0402",
            "LED White 0402",
            "KPHHS-1005SURCK",
            "Kingbright",
            "0402",
            "White LED 0402 20mA 2000mcd",
            "https://www.kingbright.com/",
        ),
        (
            "tlp291-4gb",
            "TLP291-4(GB)",
            "TLP291-4(GB,SE",
            "Toshiba",
            "SO-16",
            "Quad optocoupler NPN CTR 50%",
            "https://toshiba.semicon-storage.com/info/TLP291-4_datasheet_en_20210101.pdf?did=14657",
        ),
        (
            "sfh610a-1",
            "SFH610A-1",
            "SFH610A-1",
            "Vishay",
            "DIP-4",
            "Optocoupler NPN transistor output CTR 50%",
            "https://www.vishay.com/docs/83740/sfh610a.pdf",
        ),
        (
            "veml7700-tt",
            "VEML7700",
            "VEML7700-TT",
            "Vishay",
            "ODFN-4",
            "Ambient light sensor 16-bit 0.0036 lux",
            "https://www.vishay.com/docs/84286/veml7700.pdf",
        ),
        (
            "ir-emitter-850nm-0805",
            "IR Emitter 850nm 0805",
            "IR-LED-850NM",
            "Vishay",
            "0805",
            "IR LED 850nm 100mA 0805",
            "internal://zaptrace/optoelectronic-family/ir-emitter",
        ),
        (
            "tlc5947dap",
            "TLC5947",
            "TLC5947DAP",
            "TI",
            "HTSSOP-32",
            "24-ch 12-bit PWM LED driver SPI",
            "https://www.ti.com/lit/ds/symlink/tlc5947.pdf",
        ),
        (
            "is31fl3731-qfls4-tr",
            "IS31FL3731",
            "IS31FL3731-QFLS4-TR",
            "Lumissil",
            "QFN-32",
            "144-LED char frame driver I2C",
            "https://www.lumissil.com/assets/pdf/core/IS31FL3731_DS.pdf",
        ),
        (
            "ptc06nez9k",
            "PT-C06 Phototransistor",
            "PT-C06NENZ9K",
            "Everlight",
            "DIP-2",
            "NPN phototransistor 940nm",
            "https://everlighteurope.com/index.php?controller=attachment&id_attachment=3022",
        ),
    ]
    parts = []
    for pid, name, mpn, mfr, pkg, desc, ds in opto:
        parts.append(
            (
                "optoelectronic",
                pid,
                _part(
                    pid,
                    name,
                    "optoelectronic",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "A": {"type": "input", "description": "Anode / VCC"},
                        "K": {"type": "output", "description": "Cathode / GND"},
                        "C": {"type": "output", "description": "Collector (if transistor output)"},
                        "E": {"type": "power", "description": "Emitter (if transistor output)"},
                    },
                ),
            )
        )
    return parts


def generate_passive_values() -> list[tuple[str, str, dict]]:
    """Generate resistor, capacitor, inductor value variants."""
    parts = []
    # Resistors - value variants for multiple packages
    r_values = [
        ("10r", "10R", "10"),
        ("22r", "22R", "22"),
        ("47r", "47R", "47"),
        ("100r", "100R", "100"),
        ("220r", "220R", "220"),
        ("470r", "470R", "470"),
        ("1k", "1kR", "1k"),
        ("2k2", "2.2kR", "2k2"),
        ("4k7", "4.7kR", "4k7"),
        ("10k", "10kR", "10k"),
        ("22k", "22kR", "22k"),
        ("47k", "47kR", "47k"),
        ("100k", "100kR", "100k"),
        ("220k", "220kR", "220k"),
        ("470k", "470kR", "470k"),
        ("1m", "1MR", "1M"),
        ("0r-shunt", "0R Shunt", "0R"),
        ("10r-1w", "10R 1W", "10-1W"),
        ("1r-2w", "1R 2W", "1-2W"),
        ("560r", "560R", "560"),
        ("1k5", "1.5kR", "1k5"),
        ("3k3", "3.3kR", "3k3"),
        ("6k8", "6.8kR", "6k8"),
        ("15k", "15kR", "15k"),
        ("33k", "33kR", "33k"),
        ("68k", "68kR", "68k"),
        ("150k", "150kR", "150k"),
        ("330k", "330kR", "330k"),
    ]
    for val_id, val_name, mpn_val in r_values:
        for pkg in ["0402", "0603", "0805", "1206"]:
            pid = f"res-{pkg.lower()}-{val_id}"
            parts.append(
                (
                    "passive",
                    pid,
                    _part(
                        pid,
                        f"Resistor {pkg} {val_name}",
                        "passive",
                        "Generic",
                        f"RES-{pkg}-{mpn_val}",
                        f"SMD resistor {val_name} {pkg} 1% 0.1W",
                        pkg,
                        pkg,
                        f"internal://zaptrace/component-family/res-{pkg.lower()}",
                        passive_pins(),
                        properties={"package_size": pkg, "resistance": val_name, "tolerance_pct": 1},
                        electrical_limits={"max_power_w": 0.1},
                    ),
                )
            )
    # Capacitors - value variants
    c_values = [
        ("1pf", "1pF", "1P"),
        ("10pf", "10pF", "10P"),
        ("100pf", "100pF", "100P"),
        ("1nf", "1nF", "1N"),
        ("10nf", "10nF", "10N"),
        ("4u7", "4.7uF", "4U7"),
        ("10u", "10uF", "10U"),
        ("22u", "22uF", "22U"),
        ("47u", "47uF", "47U"),
        ("100u", "100uF", "100U"),
    ]
    for val_id, val_name, mpn_val in c_values:
        for pkg in ["0402", "0603"]:
            pid = f"cap-{pkg.lower()}-{val_id}"
            parts.append(
                (
                    "passive",
                    pid,
                    _part(
                        pid,
                        f"Cap MLCC {pkg} {val_name}",
                        "passive",
                        "Generic",
                        f"CAP-{pkg}-{mpn_val}",
                        f"MLCC capacitor {val_name} {pkg} X7R 50V",
                        pkg,
                        pkg,
                        f"internal://zaptrace/component-family/cap-mlcc-{pkg.lower()}",
                        passive_pins(),
                        properties={"capacitance": val_name, "dielectric": "X7R", "voltage_v": 50},
                        electrical_limits={"rated_voltage_v": 50},
                    ),
                )
            )
    # More ferrite beads and inductors
    for pkg, imp in [("0402", "600R"), ("0603", "600R"), ("0805", "1k")]:
        pid = f"ferrite-{pkg.lower()}-{imp.lower()}"
        parts.append(
            (
                "passive",
                pid,
                _part(
                    pid,
                    f"Ferrite Bead {pkg} {imp}@100MHz",
                    "passive",
                    "Murata",
                    f"BLM{pkg.upper()[1:]}{imp}",
                    f"Ferrite bead {imp} @ 100MHz, {pkg}",
                    pkg,
                    pkg,
                    "https://product.tdk.com/info/en/catalog/datasheets/beads_automotive_blmxxpg_en.pdf",
                    passive_pins(),
                    properties={"impedance_at_100mhz": imp},
                ),
            )
        )
    # Additional capacitors for 0805 package (decoupling and bulk)
    extra_c = [
        ("33u", "33uF", "33U", "X5R", 10),
        ("47u-0805", "47uF 0805", "47U-0805", "X5R", 10),
        ("100n-c0g", "100nF C0G", "100N-C0G", "C0G", 50),
        ("220pf-c0g", "220pF C0G", "220P-C0G", "C0G", 100),
        ("470pf-c0g", "470pF C0G", "470P-C0G", "C0G", 100),
        ("1u-x7r-16v", "1uF X7R 16V", "1U-X7R-16V", "X7R", 16),
    ]
    for val_id, val_name, mpn_val, diel, volt in extra_c:
        pid = f"cap-0805-{val_id}"
        parts.append(
            (
                "passive",
                pid,
                _part(
                    pid,
                    f"Cap MLCC 0805 {val_name}",
                    "passive",
                    "Generic",
                    f"CAP-0805-{mpn_val}",
                    f"MLCC capacitor {val_name} 0805 {diel} {volt}V",
                    "0805",
                    "0805",
                    "internal://zaptrace/component-family/cap-mlcc-0805",
                    passive_pins(),
                    properties={"capacitance": val_name, "dielectric": diel, "voltage_v": volt},
                    electrical_limits={"rated_voltage_v": volt},
                ),
            )
        )
    # Bourns 3296 records are curated part-level review candidates under
    # data/library/passive and must not be regenerated from family templates.
    return parts


def generate_more_power() -> list[tuple[str, str, dict]]:
    """Generate additional power management ICs."""
    parts = []
    # Motor/gate drivers, power monitors
    misc_power = [
        (
            "drv8833cpwp",
            "DRV8833C",
            "DRV8833CPWP",
            "TI",
            "HTSSOP-16",
            "Dual H-bridge motor driver 1.5A 10V",
            "https://www.ti.com/lit/ds/symlink/drv8833c.pdf",
        ),
        (
            "tb6612fng-el",
            "TB6612FNG",
            "TB6612FNGEL",
            "Toshiba",
            "SSOP-24",
            "Dual motor driver 1.2A 15V",
            "https://toshiba.semicon-storage.com/info/TB6612FNG_datasheet_en_20141001.pdf",
        ),
        (
            "a4988settr-t",
            "A4988",
            "A4988SETTR-T",
            "Allegro",
            "TQFP-28",
            "Stepper motor driver 2A 35V microstepping",
            "https://www.allegromicro.com/en/Products/Motor-Driver-And-Interface-ICs/Brushless-DC-Motor-Drivers/A4988",
        ),
        (
            "ir2104spbf",
            "IR2104",
            "IR2104SPBF",
            "Infineon",
            "SOIC-8",
            "Half-bridge MOSFET gate driver 600V",
            "https://www.infineon.com/dgdl/Infineon-IR2104-DataSheet-v01_00-EN.pdf",
        ),
        (
            "ucc27517bdbvr",
            "UCC27517B",
            "UCC27517BDBVR",
            "TI",
            "SOT-23-5",
            "4A gate driver 35V",
            "https://www.ti.com/lit/ds/symlink/ucc27517b.pdf",
        ),
        (
            "max40108aua-t",
            "MAX40108",
            "MAX40108AUA+T",
            "Maxim",
            "SOT-23-8",
            "Zero-drift 36V dual-supply amp",
            "https://datasheets.maximintegrated.com/en/ds/MAX40108.pdf",
        ),
        (
            "tps61023dsgr",
            "TPS61023",
            "TPS61023DSGR",
            "TI",
            "WSON-8",
            "Boost 1.5A 5.5V input fixed 5V",
            "https://www.ti.com/lit/ds/symlink/tps61023.pdf",
        ),
        (
            "lm2575hvt-5.0",
            "LM2575HVT-5.0",
            "LM2575HVT-5.0/NOPB",
            "TI",
            "TO-220-5",
            "Buck 1A 63V 52kHz",
            "https://www.ti.com/lit/ds/symlink/lm2575hv.pdf",
        ),
        (
            "mc34063adr2g",
            "MC34063A",
            "MC34063ADR2G",
            _ON_SEMI,
            "SOIC-8",
            "DC-DC converter controller buck/boost/inverting",
            "https://www.onsemi.com/pdf/datasheet/mc34063a-d.pdf",
        ),
        (
            "stps10l25m",
            "STPS10L25M",
            "STPS10L25M",
            "STMicro",
            "D2PAK",
            "Schottky diode 10A 25V",
            "https://www.st.com/resource/en/datasheet/stps10l25m.pdf",
        ),
        (
            "sma4007-tp",
            "SMA4007 Rectifier",
            "SMA4007-TP",
            "MCC",
            "SMA",
            "1A 1kV fast recovery rectifier",
            "https://www.mccsemi.com/pdf/Products/SMA4007.PDF",
        ),
        (
            "irf7324pbf",
            "IRF7324",
            "IRF7324PBF",
            "Infineon",
            "SO-8",
            "Dual P-ch MOSFET -30V -5.3A",
            "https://www.infineon.com/dgdl/irf7324pbf.pdf",
        ),
        (
            "ao3400a",
            "AO3400A",
            "AO3400A",
            "AOS",
            "SOT-23",
            "N-ch MOSFET 30V 5.7A Vgs=1V",
            "https://www.aosmd.com/res/data_sheets/AO3400A.pdf",
        ),
        (
            "pmos-ao3401a",
            "AO3401A PMOS",
            "AO3401A",
            "AOS",
            "SOT-23",
            "P-ch MOSFET -30V -4A Vgs=-1V",
            "https://www.aosmd.com/res/data_sheets/AO3401A.pdf",
        ),
        (
            "ntrc4151nt1g",
            "NTRC4151N",
            "NTRC4151NT1G",
            _ON_SEMI,
            "SOT-363",
            "Dual complementary MOSFET 20V 2A",
            "https://www.onsemi.com/pdf/datasheet/ntrc4151n-d.pdf",
        ),
    ]
    for pid, name, mpn, mfr, pkg, desc, ds in misc_power:
        parts.append(
            (
                "power",
                pid,
                _part(
                    pid,
                    name,
                    "power",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "VIN": {"type": "power", "description": "Input"},
                        "VOUT": {"type": "output", "description": "Output"},
                        "GND": {"type": "power", "description": "Ground"},
                        "CTRL": {"type": "input", "description": "Control/Enable"},
                    },
                ),
            )
        )
    return parts


def generate_more_mcus() -> list[tuple[str, str, dict]]:
    parts = []
    mcus = [
        (
            "attiny412-ssfr",
            "ATtiny412",
            "ATTINY412-SSFR",
            "Microchip",
            "SOIC-8",
            "AVR tiny 20MHz 4KB 8-pin",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/ATtiny212-214-412-414-416-DataSheet-DS40002287A.pdf",
        ),
        (
            "atmega328pb-au",
            "ATmega328PB",
            "ATMEGA328PB-AU",
            "Microchip",
            "TQFP-32",
            "AVR 20MHz 32KB 2KB SRAM",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/ATmega48PB-88PB-168PB-328PB-DS40002061B.pdf",
        ),
        (
            "stm32c011f4p6",
            "STM32C011F4P6",
            "STM32C011F4P6",
            "STMicro",
            "UFQFPN-20",
            "Cortex-M0+ 48MHz 16KB entry-level",
            "https://www.st.com/resource/en/datasheet/stm32c011f4.pdf",
        ),
        (
            "stm32h503kbt6",
            "STM32H503KBT6",
            "STM32H503KBT6",
            "STMicro",
            "LQFP-32",
            "Cortex-M33 250MHz 128KB",
            "https://www.st.com/resource/en/datasheet/stm32h503kb.pdf",
        ),
        (
            "esp32-h2-mini-1-h4",
            "ESP32-H2-MINI-1-H4",
            "ESP32-H2-MINI-1-H4",
            "Espressif",
            "LCC-34",
            "802.15.4+BLE5 RISC-V",
            "https://www.espressif.com/sites/default/files/documentation/esp32-h2-mini-1_mini-1u_datasheet_en.pdf",
        ),
        (
            "nrf54l15-qkaa-r7",
            "nRF54L15-QKAA",
            "nRF54L15-QKAA-R7",
            "Nordic",
            "QFN-48",
            "Cortex-M33 128MHz BT 6.0",
            "https://infocenter.nordicsemi.com/",
        ),
        (
            "cc2340r5rhbr",
            "CC2340R5",
            "CC2340R5RHBR",
            "TI",
            "QFN-22",
            "Matter/Thread/BLE5 Cortex-M0+",
            "https://www.ti.com/lit/ds/symlink/cc2340r5.pdf",
        ),
        (
            "cc1312r7rskt",
            "CC1312R7",
            "CC1312R7RSKT",
            "TI",
            "RGZ-48",
            "Sub-1GHz+BLE5 Cortex-M4F 352KB",
            "https://www.ti.com/lit/ds/symlink/cc1312r7.pdf",
        ),
        (
            "MAX78000FTHR",
            "MAX78000",
            "MAX78000FTHR",
            "Maxim",
            "WLP-94",
            "AI microcontroller Cortex-M4+RISC-V CNN",
            "https://datasheets.maximintegrated.com/en/ds/MAX78000.pdf",
        ),
        (
            "imxrt1062cvl5b",
            "IMXRT1062",
            "IMXRT1062CVL5B",
            "NXP",
            "BGA-196",
            "Crossover MCU Cortex-M7 600MHz",
            "https://www.nxp.com/docs/en/data-sheet/IMXRT1060RM.pdf",
        ),
    ]
    for pid, name, mpn, mfr, pkg, desc, ds in mcus:
        parts.append(
            (
                "mcu",
                pid,
                _part(
                    pid,
                    name,
                    "mcu",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "VDD": {"type": "power", "description": "Supply"},
                        "GND": {"type": "power", "description": "Ground"},
                        "RESET": {"type": "input", "description": "Reset"},
                        "GPIO": {"type": "bidirectional", "description": "I/O"},
                    },
                    voltage_supply="3.3",
                ),
            )
        )
    return parts


def generate_more_sensors() -> list[tuple[str, str, dict]]:
    parts = []
    sensors = [
        (
            "bmi270",
            "BMI270",
            "BMI270",
            "Bosch",
            "LGA-14",
            "Low-power 6-axis IMU 0.65mA always-on",
            "https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi270-ds000.pdf",
        ),
        (
            "icm-20948",
            "ICM-20948",
            "ICM-20948",
            "TDK InvenSense",
            "QFN-24",
            "9-axis IMU accel+gyro+mag",
            "https://invensense.tdk.com/wp-content/uploads/2016/06/DS-000189-ICM-20948-v1.3.pdf",
        ),
        (
            "lps22hh-tr",
            "LPS22HH",
            "LPS22HHTR",
            "STMicro",
            "HLGA-10L",
            "MEMS pressure 260-1260 hPa SPI/I2C",
            "https://www.st.com/resource/en/datasheet/lps22hh.pdf",
        ),
        (
            "hmc5883l",
            "HMC5883L",
            "HMC5883L",
            "Honeywell",
            "LCC-16",
            "3-axis magnetometer I2C ±8 gauss",
            "https://cdn-shop.adafruit.com/datasheets/HMC5883L_3-Axis_Digital_Compass_IC.pdf",
        ),
        (
            "ccs811b",
            "CCS811B",
            "CCS811B-JOPD500",
            "ScioSense",
            "LGA-10",
            "eCO2 TVOC gas sensor I2C",
            "https://www.sciosense.com/wp-content/uploads/2020/01/CCS811_Datasheet.pdf",
        ),
        (
            "mlx90393etq-aab-001-re",
            "MLX90393",
            "MLX90393ETQ-AAB-001-RE",
            "Melexis",
            "QFN-16",
            "3D Magnetometer SPI/I2C",
            "https://www.melexis.com/-/media/files/documents/datasheets/mlx90393-datasheet-melexis.pdf",
        ),
        (
            "hdc1080dmbr",
            "HDC1080",
            "HDC1080DMBR",
            "TI",
            "WSON-6",
            "Humidity+temp I2C ±2% RH",
            "https://www.ti.com/lit/ds/symlink/hdc1080.pdf",
        ),
        (
            "si7021-a20-im",
            "Si7021-A20",
            "SI7021-A20-IM",
            _SILICON_LABS,
            "QFN-6",
            "I2C humidity sensor ±3% RH",
            "https://www.silabs.com/documents/public/data-sheets/Si7021-A20.pdf",
        ),
        (
            "ltr-329als-01",
            "LTR-329ALS",
            "LTR-329ALS-01",
            "LITE-ON",
            "OLGA-6",
            "Ambient light sensor I2C 0.01-64klux",
            "https://optoelectronics.liteon.com/upload/download/DS86-2013-0003/LTR-329ALS-01_DS_V1.pdf",
        ),
        (
            "max17048g-t10",
            "MAX17048",
            "MAX17048G+T10",
            "Maxim",
            "TDFN-8",
            "LiPo fuel gauge 1-cell I2C",
            "https://datasheets.maximintegrated.com/en/ds/MAX17048-MAX17049.pdf",
        ),
        (
            "hall-a1302eu-t",
            "A1302EU",
            "A1302EUAETN-T",
            "Allegro",
            "SOT-23W-3",
            "Hall effect sensor 5V continuous",
            "https://www.allegromicro.com/en/Products/Magnetic-Linear-And-Angular-Position-Sensor-ICs/Linear-Position-Sensor-ICs/A1302",
        ),
        (
            "hx711-soic16",
            "HX711 SOIC16",
            "HX711SOIC16",
            "AVIA Semi",
            "SOIC-16",
            "24-bit ADC weight scale amplifier",
            "https://cdn.sparkfun.com/datasheets/Sensors/ForceFlex/hx711_english.pdf",
        ),
    ]
    for pid, name, mpn, mfr, pkg, desc, ds in sensors:
        parts.append(
            (
                "sensor",
                pid,
                _part(
                    pid,
                    name,
                    "sensor",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "VDD": {"type": "power", "description": "Supply"},
                        "GND": {"type": "power", "description": "Ground"},
                        "SDA": {"type": "bidirectional", "description": "I2C SDA"},
                        "SCL": {"type": "input", "description": "I2C SCL"},
                        "INT": {"type": "output", "description": "Interrupt"},
                    },
                    voltage_supply="3.3",
                ),
            )
        )
    return parts


def generate_discrete_semiconductors() -> list[tuple[str, str, dict]]:
    """Discrete diodes, transistors, MOSFETs, and BJTs."""
    parts = []
    discretes = [
        (
            "1n4148ws-t1-e3",
            "1N4148WS",
            "1N4148WS-T1-E3",
            "Vishay",
            "SOD-323",
            "Small signal diode 100V 150mA",
            "https://www.vishay.com/docs/85748/1n4148ws.pdf",
        ),
        (
            "bat54cw-7-f",
            "BAT54CW",
            "BAT54CW-7-F",
            _DIODES_INC,
            "SOT-323-3",
            "Dual schottky 30V 200mA",
            "https://www.diodes.com/assets/Datasheets/BAT54CW.pdf",
        ),
        (
            "ss14-e3-61t",
            "SS14 Schottky",
            "SS14-E3/61T",
            "Vishay",
            "SMA",
            "Schottky 40V 1A",
            "https://www.vishay.com/docs/88746/ss14.pdf",
        ),
        (
            "b5819ws-7-f",
            "B5819WS",
            "B5819WS-7-F",
            _DIODES_INC,
            "SOD-323",
            "Schottky 40V 1A ultra-low Vf",
            "https://www.diodes.com/assets/Datasheets/B5819WS.pdf",
        ),
        (
            "leds4148",
            "1N4148 SOD-80",
            "1N4148",
            "Nexperia",
            "SOD-80C",
            "Small signal diode 100V 0.2A leaded",
            "https://assets.nexperia.com/documents/data-sheet/1N4148.pdf",
        ),
        (
            "2n7002k-7",
            "2N7002K",
            "2N7002K-7",
            _DIODES_INC,
            "SOT-23",
            "N-ch MOSFET 60V 380mA Vgs=1V",
            "https://www.diodes.com/assets/Datasheets/2N7002K.pdf",
        ),
        (
            "bss138p-7-f",
            "BSS138P",
            "BSS138P-7-F",
            _DIODES_INC,
            "SOT-23",
            "P-ch MOSFET -50V -200mA",
            "https://www.diodes.com/assets/Datasheets/BSS138P.pdf",
        ),
        (
            "si2301cds-t1-ge3",
            "SI2301CDS",
            "SI2301CDS-T1-GE3",
            "Vishay",
            "SOT-23",
            "P-ch MOSFET -20V -2.8A",
            "https://www.vishay.com/docs/70292/si2301cds.pdf",
        ),
        (
            "dmn3404l-7",
            "DMN3404L",
            "DMN3404L-7",
            _DIODES_INC,
            "SOT-23",
            "N-ch MOSFET 30V 4.2A",
            "https://www.diodes.com/assets/Datasheets/DMN3404L.pdf",
        ),
        (
            "bc847blt1g",
            "BC847B",
            "BC847BLT1G",
            _ON_SEMI,
            "SOT-23",
            "NPN BJT 100mA 45V",
            "https://www.onsemi.com/pdf/datasheet/bc847b-d.pdf",
        ),
        (
            "bc857blt1g",
            "BC857B",
            "BC857BLT1G",
            _ON_SEMI,
            "SOT-23",
            "PNP BJT 100mA 45V",
            "https://www.onsemi.com/pdf/datasheet/bc857b-d.pdf",
        ),
        (
            "2sc1815gr",
            "2SC1815-GR",
            "2SC1815GR",
            "Toshiba",
            "TO-92",
            "NPN BJT 150mA 50V low noise",
            "https://toshiba.semicon-storage.com/info/2SC1815_datasheet_en_20060328.pdf",
        ),
        (
            "bcp53-16-115",
            "BCP53-16",
            "BCP53-16,115",
            "Nexperia",
            "SOT-223",
            "PNP 1A 40V medium power",
            "https://assets.nexperia.com/documents/data-sheet/BCP53.pdf",
        ),
        (
            "mmbta13lt1g",
            "MMBTA13",
            "MMBTA13LT1G",
            _ON_SEMI,
            "SOT-23",
            "NPN darlington 500mA 30V",
            "https://www.onsemi.com/pdf/datasheet/mmbta13-d.pdf",
        ),
        (
            "bza55c15te17",
            "BZA55C15",
            "BZA55C15TE17",
            "Vishay",
            "SOD-323",
            "Zener 15V 200mW",
            "https://www.vishay.com/docs/85660/bza55c.pdf",
        ),
        (
            "bzx84c3v3lt1g",
            "BZX84C3V3",
            "BZX84C3V3LT1G",
            _ON_SEMI,
            "SOT-23",
            "Zener 3.3V 225mW",
            "https://www.onsemi.com/pdf/datasheet/bzx84c2v4-d.pdf",
        ),
        (
            "usbpd-fusb302bmpx",
            "FUSB302B",
            "FUSB302BMPX",
            _ON_SEMI,
            "QFN-24",
            "USB Type-C PD controller",
            "https://www.onsemi.com/pdf/datasheet/fusb302b-d.pdf",
        ),
        (
            "stusb4500jhr",
            "STUSB4500",
            "STUSB4500JHR",
            "STMicro",
            "QFN-20",
            "USB-C PD sink I2C NVM",
            "https://www.st.com/resource/en/datasheet/stusb4500.pdf",
        ),
    ]
    for pid, name, mpn, mfr, pkg, desc, ds in discretes:
        cat = "power" if any(x in pid for x in ("usb", "fusb", "stusb")) else "protection"
        parts.append(
            (
                cat,
                pid,
                _part(
                    pid,
                    name,
                    cat,
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "A": {"type": "bidirectional", "description": "Anode / Gate / Base"},
                        "K": {"type": "bidirectional", "description": "Cathode / Source / Emitter"},
                        "G": {"type": "input", "description": "Gate (MOSFET) / Collector (BJT)"},
                    },
                ),
            )
        )
    return parts


def generate_more_connectors() -> list[tuple[str, str, dict]]:
    parts = []
    connectors = [
        (
            "pcie-x1-slot",
            "PCIe x1 Slot",
            "PCI-E-X1",
            "Molex",
            "PCIe-x1",
            "PCI Express x1 slot connector",
            "internal://zaptrace/connector-family/pcie",
        ),
        (
            "m2-2280-key-m",
            "M.2 Key-M 2280",
            "M2-2280-M",
            "Amphenol",
            "M.2-M-80",
            "M.2 2280 Key-M socket NVMe",
            "internal://zaptrace/connector-family/m2",
        ),
        (
            "qsfp28-cage",
            "QSFP28 Cage",
            "QSFP28-2x1",
            "Amphenol",
            "QSFP28",
            "QSFP28 100G fiber cage receptacle",
            "https://www.amphenol.com/product/product_detail/41/",
        ),
        (
            "usb-a-2.0-thd",
            "USB-A 2.0 THD",
            "USB-A-THD",
            "Molex",
            "USB-A-THD",
            "USB Type-A 2.0 through-hole",
            "internal://zaptrace/connector-family/usb-a",
        ),
        (
            "usb-a-3.0-smd",
            "USB-A 3.0 SMD",
            "USB-A-3-SMD",
            "Molex",
            "USB-A-3-SMD",
            "USB Type-A 3.0 SMD",
            "internal://zaptrace/connector-family/usb-a3",
        ),
        (
            "dp-mini-20p",
            "Mini DisplayPort 20P",
            "MDP-20P",
            "Hirose",
            "MDP-20P",
            "Mini DisplayPort 20-pin receptacle",
            "internal://zaptrace/connector-family/dp-mini",
        ),
        (
            "jtag-2x5-1.27mm",
            "JTAG 2x5 1.27mm",
            "JTAG-2X5-1.27",
            "Generic",
            "Header-2x5-1.27mm",
            "JTAG/SWD 10-pin 1.27mm debug connector",
            "internal://zaptrace/connector-family/jtag",
        ),
        (
            "swd-2x5-1.27mm",
            "SWD 2x5 1.27mm",
            "SWD-2X5-1.27",
            "Generic",
            "Header-2x5-1.27mm-SWD",
            "ARM SWD debug header 10-pin 1.27mm",
            "internal://zaptrace/connector-family/swd",
        ),
        (
            "grove-4p-2mm",
            "Grove 4P 2mm",
            "GROVE-4P-2MM",
            "Seeed",
            "Grove-2mm",
            "Grove compatible 4-pin 2mm pitch",
            "https://wiki.seeedstudio.com/Grove_System/",
        ),
        (
            "jst-xh-3p",
            "JST-XH 3P",
            "B3B-XH-A",
            "JST",
            "XH-3P",
            "JST XH 3-pin 2.5mm battery connector",
            "https://www.jst.com/",
        ),
        (
            "jst-sh-4p",
            "JST-SH 4P",
            "BM04B-SRSS-TB",
            "JST",
            "SH-4P",
            "JST SH 4-pin 1.0mm QWIIC/StemmaQT",
            "https://www.jst.com/",
        ),
        (
            "wr-mx-52610409100700aalf",
            "LVDS 40P FPC",
            "52610409100700AALF",
            "Würth",
            "FPC-40P-0.5mm",
            "LVDS 40-pin 0.5mm FPC connector",
            "https://www.we-online.com/",
        ),
        (
            "rugged-d-sub-9-male",
            "D-Sub 9P Male",
            "DSUB-09-M",
            "Amphenol",
            "DSUB-9M",
            "DB9 male D-subminiature RS232",
            "internal://zaptrace/connector-family/dsub",
        ),
        (
            "barrel-jack-5.5-2.1",
            "Barrel Jack 5.5/2.1mm",
            "PRT-00119",
            "CUI",
            "BARREL-5.5-2.1",
            "DC power jack 5.5/2.1mm SMD",
            "https://www.cuidevices.com/",
        ),
    ]
    for pid, name, mpn, mfr, pkg, desc, ds in connectors:
        parts.append(
            (
                "connector",
                pid,
                _part(
                    pid,
                    name,
                    "connector",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "P1": {"type": "passive", "description": "Pin 1"},
                        "P2": {"type": "passive", "description": "Pin 2"},
                        "GND": {"type": "power", "description": "Ground / Shield"},
                    },
                ),
            )
        )
    return parts


def generate_wifi_bt_modules() -> list[tuple[str, str, dict]]:
    """WiFi/BT modules and SOM components."""
    modules = [
        (
            "esp-wroom-02d",
            "ESP-WROOM-02D",
            "ESP-WROOM-02D",
            "Espressif",
            "SMD-18",
            "WiFi 802.11 b/g/n module 4MB ESP8266",
            "https://www.espressif.com/sites/default/files/documentation/esp-wroom-02d_esp-wroom-02u_datasheet_en.pdf",
        ),
        (
            "ublox-nina-w102",
            "NINA-W102",
            "NINA-W102-00B",
            "u-blox",
            "LCC-88",
            "WiFi/BT 4.2 module 2.4GHz standalone",
            "https://www.u-blox.com/en/docs/UBX-17065507",
        ),
        (
            "nordic-thingy91-x",
            "Nordic Thingy:91 X module",
            "NRF9161-SICA",
            "Nordic",
            "LGA-10",
            "LTE-M NB-IoT 1.8GHz DECT NR+",
            "https://infocenter.nordicsemi.com/pdf/nRF9161_PS_v1.0.pdf",
        ),
        (
            "at-winc3400-mr210ca",
            "WINC3400",
            "ATWINC3400-MR210CA",
            "Microchip",
            "LCC-40",
            "WiFi+BLE4.0 module FCC/CE",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/ATWINC3400-MR210CA-Datasheet-DS70005346.pdf",
        ),
        (
            "bc660k-gl",
            "BC660K-GL",
            "BC660K-GL",
            "Quectel",
            "LCC-80",
            "NB-IoT module LTE Cat NB2",
            "https://www.quectel.com/UploadFile/Product/Quectel_BC660K-GL_Series_Specification_V1.4.pdf",
        ),
        (
            "sim7020e",
            "SIM7020E",
            "SIM7020E",
            "SIMCom",
            "LCC-54",
            "NB-IoT module B1/B3/B5/B8/B20",
            "https://simcom.com/product/SIM7020E.html",
        ),
        (
            "wilcs1000-mrt",
            "WILCS1000-MRT",
            "WILCS1000-MRT",
            "Microchip",
            "QFN-40",
            "Secure WiFi IoT controller",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/70005346B.pdf",
        ),
        (
            "m5311",
            "M5311",
            "M5311-GNSLA",
            "China Mobile",
            "LCC-68",
            "NB-IoT+GNSS module cat NB2",
            "internal://zaptrace/rf-module/m5311",
        ),
        (
            "ag9312",
            "AG9312 WiFi Module",
            "AG9312",
            "AirGain",
            "SMD-18",
            "WiFi 802.11 b/g/n 2.4GHz UART",
            "internal://zaptrace/rf-module/ag9312",
        ),
        (
            "xbee3-zigbee",
            "XBee 3 Zigbee",
            "XB3-24Z8PT",
            "Digi Int'l",
            "SMD-20",
            "Zigbee 3.0 2.4GHz 6.3km LOS",
            "https://www.digi.com/resources/documentation/digidocs/pdfs/90001539.pdf",
        ),
        (
            "rwg0050aa00000",
            "RN2483A",
            "RWG0050AA00000",
            "Microchip",
            "SMD-28",
            "LoRa 868MHz RN2483A TTL FCC/CE",
            "https://ww1.microchip.com/downloads/en/DeviceDoc/50002346C.pdf",
        ),
        (
            "ai-wb2-12f",
            "Ai-WB2-12F",
            "Ai-WB2-12F",
            "Ai-Thinker",
            "LCC-12",
            "WiFi6+BLE5 BL602 12MB flash",
            "https://docs.ai-thinker.com/",
        ),
        (
            "rak3172",
            "RAK3172",
            "RAK3172",
            "RAK Wireless",
            "SMD-32",
            "LoRa 868/915MHz STM32WLE5 4MB",
            "https://docs.rakwireless.com/Product-Categories/WisDuo/RAK3172-Module/Datasheet/",
        ),
        (
            "bg95-m2",
            "BG95-M2",
            "BG95M2LAR02A04M",
            "Quectel",
            "LCC-64",
            "LTE Cat M1/NB2 + GNSS module",
            "https://www.quectel.com/",
        ),
        (
            "em9191",
            "EM9191",
            "EM9191",
            "Sierra Wireless",
            "M.2",
            "5G Sub-6GHz M.2 module",
            "https://www.sierrawireless.com/",
        ),
    ]
    parts = []
    for pid, name, mpn, mfr, pkg, desc, ds in modules:
        parts.append(
            (
                "rf",
                pid,
                _part(
                    pid,
                    name,
                    "rf",
                    mfr,
                    mpn,
                    desc,
                    pkg,
                    pkg,
                    ds,
                    {
                        "VCC": {"type": "power", "description": "Supply 3.3V"},
                        "GND": {"type": "power", "description": "Ground"},
                        "TX": {"type": "output", "description": "UART TX"},
                        "RX": {"type": "input", "description": "UART RX"},
                        "ANT": {"type": "bidirectional", "description": "RF antenna"},
                        "EN": {"type": "input", "description": "Enable/Reset"},
                    },
                    voltage_supply="3.3",
                ),
            )
        )
    return parts


def collect_all_parts() -> list[tuple[str, str, dict]]:
    all_parts = []
    all_parts.extend(generate_resistors())
    all_parts.extend(generate_capacitors())
    all_parts.extend(generate_inductors())
    all_parts.extend(generate_power_ics())
    all_parts.extend(generate_mcus())
    all_parts.extend(generate_sensors())
    all_parts.extend(generate_connectors())
    all_parts.extend(generate_memory())
    all_parts.extend(generate_rf())
    all_parts.extend(generate_timing())
    all_parts.extend(generate_protection())
    all_parts.extend(generate_security())
    all_parts.extend(generate_interface())
    all_parts.extend(generate_optoelectronics())
    all_parts.extend(generate_passive_values())
    all_parts.extend(generate_more_power())
    all_parts.extend(generate_more_mcus())
    all_parts.extend(generate_more_sensors())
    all_parts.extend(generate_discrete_semiconductors())
    all_parts.extend(generate_more_connectors())
    all_parts.extend(generate_wifi_bt_modules())
    return all_parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate library expansion to 500+ parts")
    parser.add_argument("--dry-run", action="store_true", help="Report count without writing files")
    parser.add_argument("--output-dir", type=Path, default=LIBRARY_ROOT)
    args = parser.parse_args(argv)

    parts = collect_all_parts()
    ids_seen: set[str] = set()
    written = 0
    skipped = 0

    for category, part_id, data in parts:
        if part_id in ids_seen:
            print(f"  DUP: {part_id}", file=sys.stderr)
            skipped += 1
            continue
        ids_seen.add(part_id)

        target = Path(args.output_dir) / category / f"{part_id}.yaml"
        if target.exists():
            skipped += 1
            continue

        if args.dry_run:
            written += 1
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)
        written += 1

    total_existing = sum(1 for _ in Path(args.output_dir).rglob("*.yaml"))
    action = "Would write" if args.dry_run else "Wrote"
    print(f"{action} {written} new parts ({skipped} already exist)")
    total_after = total_existing + written if args.dry_run else total_existing
    print(f"Total after: {total_after} parts in library")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
