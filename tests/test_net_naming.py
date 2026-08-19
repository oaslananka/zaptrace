"""Tests for canonical schematic net naming."""

from __future__ import annotations

import pytest

from zaptrace.synthesis.net_naming import _bus_signal_name, canonical_net_name


@pytest.mark.parametrize(
    ("prefix", "signal", "params", "expected"),
    [
        ("I2C", "SDA", {}, "I2C_SDA"),
        ("I2C", "SCL", {"bus": "1"}, "I2C1_SCL"),
        ("SPI", "MISO", {"bus": "A"}, "SPIA_MISO"),
        ("UART", "TX", {"bus": "0"}, "UART0_TX"),
    ],
)
def test_bus_signal_name_preserves_optional_bus_contract(
    prefix: str,
    signal: str,
    params: dict[str, str],
    expected: str,
) -> None:
    assert _bus_signal_name(prefix, signal, params) == expected


@pytest.mark.parametrize(
    ("signal_type", "params", "expected"),
    [
        (" power ", {"rail": "+3v3"}, "+3V3"),
        ("ground", {}, "GND"),
        ("ground", {"domain": "a"}, "AGND"),
        ("i2c_sda", {}, "I2C_SDA"),
        ("i2c_scl", {"bus": "2"}, "I2C2_SCL"),
        ("spi_sck", {}, "SPI_SCK"),
        ("spi_mosi", {"bus": "3"}, "SPI3_MOSI"),
        ("spi_miso", {"bus": "3"}, "SPI3_MISO"),
        ("spi_cs", {"bus": "2", "device": "flash"}, "SPI2_CS_FLASH"),
        ("uart_tx", {}, "UART_TX"),
        ("uart_rx", {"bus": "4"}, "UART4_RX"),
        ("usb_dp", {}, "USB_FS_DP"),
        ("usb_dm", {"speed": "hs"}, "USB_HS_DM"),
        ("clock", {}, "SYS_CLK"),
        ("reset", {}, "nRST"),
        ("reset", {"active_low": "no"}, "RESET"),
        ("gpio", {"function": "status led/1"}, "STATUS_LED_1"),
    ],
)
def test_canonical_net_name_preserves_all_supported_signal_contracts(
    signal_type: str,
    params: dict[str, str],
    expected: str,
) -> None:
    assert canonical_net_name(signal_type, **params) == expected


def test_unknown_signal_type_error_preserves_caller_input() -> None:
    with pytest.raises(ValueError, match="Unknown signal_type ' Mystery '"):
        canonical_net_name(" Mystery ")
