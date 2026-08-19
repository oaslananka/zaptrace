"""Tests for switching power-supply design calculators."""

from __future__ import annotations

import pytest

from zaptrace.synthesis.power_supply import (
    buck_duty_cycle,
    buck_inductor_henries,
    buck_output_cap_farads,
    design_buck,
    inductor_ripple_current_a,
)


def test_buck_duty_cycle() -> None:
    assert buck_duty_cycle(12.0, 3.3) == pytest.approx(0.275)
    with pytest.raises(ValueError):
        buck_duty_cycle(3.3, 5.0)  # vout > vin


def test_buck_inductor() -> None:
    # 12V -> 3.3V, 2A, 500 kHz, 30% ripple -> ~7.98 uH
    inductor = buck_inductor_henries(12.0, 3.3, 2.0, 500_000.0, ripple_ratio=0.3)
    assert inductor == pytest.approx(7.975e-6, rel=1e-3)


def test_inductor_ripple_round_trips() -> None:
    inductor = buck_inductor_henries(12.0, 3.3, 2.0, 500_000.0, ripple_ratio=0.3)
    ripple = inductor_ripple_current_a(12.0, 3.3, inductor, 500_000.0)
    assert ripple == pytest.approx(0.6, rel=1e-3)  # 30% of 2 A


def test_buck_output_cap() -> None:
    # dIL 0.6 A, 500 kHz, 10 mV ripple -> 15 uF
    cap = buck_output_cap_farads(0.6, 500_000.0, 0.01)
    assert cap == pytest.approx(15e-6, rel=1e-3)


def test_design_buck_combiner() -> None:
    design = design_buck(12.0, 3.3, 2.0, 500_000.0)
    assert design.duty_cycle == pytest.approx(0.275)
    assert design.inductor_h == pytest.approx(7.975e-6, rel=1e-3)
    assert design.ripple_current_a == pytest.approx(0.6, rel=1e-3)
    assert design.output_cap_f == pytest.approx(15e-6, rel=1e-3)


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        buck_inductor_henries(12.0, 3.3, 0.0, 500_000.0)  # iout 0
    with pytest.raises(ValueError):
        buck_inductor_henries(12.0, 3.3, 2.0, 500_000.0, ripple_ratio=1.5)  # ratio > 1
    with pytest.raises(ValueError):
        buck_output_cap_farads(0.6, 500_000.0, 0.0)  # vripple 0
