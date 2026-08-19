"""Regression coverage for shared RF validation and band labels."""

import pytest

from zaptrace.synthesis.rf import antenna_keepout, l_network_matching, list_rf_modules, wavelength_mm


@pytest.mark.parametrize(
    "calculator",
    [
        lambda: wavelength_mm(0.0),
        lambda: antenna_keepout(0.0),
        lambda: l_network_matching(50.0, 25.0, 0.0),
    ],
)
def test_frequency_calculators_share_the_same_positive_error(calculator) -> None:
    with pytest.raises(ValueError, match="^freq_hz must be positive$"):
        calculator()


def test_2_4_ghz_modules_retain_the_published_band_label() -> None:
    modules = [
        module for module in list_rf_modules() if module.module_id in {"ESP32-WROOM-32", "NINA-W102", "nRF52840-DK"}
    ]

    assert len(modules) == 3
    assert all(module.freq_bands == ["2.4 GHz"] for module in modules)
