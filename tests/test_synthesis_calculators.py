"""Tests for component-value calculators."""

from __future__ import annotations

import math

import pytest

from zaptrace.synthesis.calculators import (
    boost_inductor_capacitor,
    boot_reset_strap_plan,
    buck_inductor_capacitor,
    decoupling_plan,
    divider_for_output,
    divider_output_v,
    e_series_ceil,
    e_series_floor,
    i2c_pullup,
    ldo_selection,
    led_series_resistor,
    lipo_charge_resistor,
    mosfet_soa_check,
    nearest_e_series,
    pull_resistor,
    rc_cutoff_hz,
    rc_resistor_for_cutoff,
    usb_c_cc_termination,
)


class TestESeries:
    def test_nearest_picks_closest(self) -> None:
        assert nearest_e_series(263, 24) == 270  # 240 vs 270 -> 270
        assert nearest_e_series(300, 24) == 300  # exact E24 value
        assert nearest_e_series(4700, 24) == 4700

    def test_ceil_and_floor(self) -> None:
        assert e_series_ceil(263, 24) == 270
        assert e_series_floor(263, 24) == 240
        assert e_series_ceil(300, 24) == 300
        assert e_series_floor(300, 24) == 300

    def test_e12_is_coarser_than_e24(self) -> None:
        # 2.4k exists in E24 but not E12; E12 snaps to 2.2k
        assert nearest_e_series(2400, 24) == 2400
        assert nearest_e_series(2400, 12) == 2200

    def test_works_across_decades(self) -> None:
        assert nearest_e_series(0.47, 24) == pytest.approx(0.47)
        assert nearest_e_series(4_700_000, 24) == 4_700_000

    def test_invalid_inputs(self) -> None:
        with pytest.raises(ValueError):
            nearest_e_series(0, 24)
        with pytest.raises(ValueError):
            nearest_e_series(100, 96)  # unsupported series


class TestLedResistor:
    def test_clean_case(self) -> None:
        r = led_series_resistor(5.0, 2.0, 10.0)
        assert r.ideal_ohms == pytest.approx(300.0)
        assert r.chosen_ohms == 300.0
        assert r.actual_current_a == pytest.approx(0.010)
        assert r.resistor_power_w == pytest.approx(0.03)

    def test_rounds_up_so_current_does_not_exceed_target(self) -> None:
        r = led_series_resistor(3.3, 2.0, 5.0)  # ideal 260 -> E24 ceil 270
        assert r.ideal_ohms == pytest.approx(260.0)
        assert r.chosen_ohms == 270.0
        assert r.actual_current_a < 0.005  # below the 5 mA target, never above

    def test_supply_below_vf_raises(self) -> None:
        with pytest.raises(ValueError):
            led_series_resistor(1.8, 2.0, 10.0)


class TestDivider:
    def test_output_voltage(self) -> None:
        assert divider_output_v(5.0, 10_000, 10_000) == pytest.approx(2.5)

    def test_choose_top_resistor(self) -> None:
        d = divider_for_output(5.0, 2.5, 10_000)
        assert d.r_top_ohms == 10_000
        assert d.actual_output_v == pytest.approx(2.5)

    def test_choose_top_resistor_snaps_to_e_series(self) -> None:
        d = divider_for_output(12.0, 3.3, 10_000)  # ideal top ~26.4k -> 27k
        assert d.r_top_ohms == 27_000
        assert d.actual_output_v == pytest.approx(3.243, rel=1e-3)

    def test_invalid_output(self) -> None:
        with pytest.raises(ValueError):
            divider_for_output(5.0, 5.0, 10_000)  # output not < input


class TestRcFilter:
    def test_cutoff(self) -> None:
        assert rc_cutoff_hz(1000, 1e-6) == pytest.approx(1.0 / (2 * math.pi * 1e-3), rel=1e-6)

    def test_resistor_for_cutoff_round_trips(self) -> None:
        # ~159.155 Hz with 1uF -> 1k resistor
        r = rc_resistor_for_cutoff(159.1549, 1e-6)
        assert r == 1000

    def test_invalid(self) -> None:
        with pytest.raises(ValueError):
            rc_cutoff_hz(0, 1e-6)


class TestI2cPullup:
    def test_standard_mode_range(self) -> None:
        p = i2c_pullup(3.3, 100, bus_speed_hz=100_000)
        assert p.min_ohms == pytest.approx(966.67, rel=1e-3)
        assert p.max_ohms == pytest.approx(11802, rel=1e-3)
        assert p.recommended_ohms == 11_000  # largest E24 <= max
        assert p.min_ohms < p.recommended_ohms < p.max_ohms

    def test_fast_mode_recommends_smaller_pullup(self) -> None:
        p = i2c_pullup(3.3, 100, bus_speed_hz=400_000)
        assert p.recommended_ohms == 3_300

    def test_too_much_capacitance_for_fast_mode_raises(self) -> None:
        with pytest.raises(ValueError):
            i2c_pullup(3.3, 400, bus_speed_hz=400_000)  # r_max < r_min

    def test_unsupported_speed_raises(self) -> None:
        with pytest.raises(ValueError):
            i2c_pullup(3.3, 100, bus_speed_hz=12_345)


class TestUsbCCcTermination:
    def test_sink_presents_rd_5k1_to_gnd(self) -> None:
        t = usb_c_cc_termination("sink")
        assert t.resistor == "Rd"
        assert t.ohms == 5_100.0
        assert t.connection == "CC1/CC2 to GND"
        assert t.advertised_current_a is None

    def test_ufp_alias_matches_sink(self) -> None:
        assert usb_c_cc_termination("UFP").ohms == usb_c_cc_termination("sink").ohms

    def test_source_rp_advertises_current_tier(self) -> None:
        assert usb_c_cc_termination("source").ohms == 56_000.0  # default power
        assert usb_c_cc_termination("source", 1.5).ohms == 22_000.0
        assert usb_c_cc_termination("source", 3.0).ohms == 10_000.0
        assert usb_c_cc_termination("source", 3.0).advertised_current_a == 3.0

    def test_source_above_3a_requires_pd(self) -> None:
        with pytest.raises(ValueError):
            usb_c_cc_termination("source", 5.0)

    def test_unknown_role_raises(self) -> None:
        with pytest.raises(ValueError):
            usb_c_cc_termination("host")


class TestDecouplingPlan:
    def test_one_cap_per_power_pin_plus_bulk(self) -> None:
        plan = decoupling_plan(4, 3.3)
        assert plan.per_pin_nf == 100.0
        assert plan.per_pin_count == 4
        assert plan.bulk_uf == 10.0  # default minimum

    def test_voltage_rating_derates_to_twice_rail(self) -> None:
        assert decoupling_plan(1, 3.3).cap_voltage_rating_v == 10.0  # 2*3.3=6.6 -> 10
        assert decoupling_plan(1, 5.0).cap_voltage_rating_v == 10.0  # 2*5=10 -> 10 exactly
        assert decoupling_plan(1, 12.0).cap_voltage_rating_v == 25.0  # 2*12=24 -> 25

    def test_bulk_override_floored_at_minimum(self) -> None:
        assert decoupling_plan(2, 3.3, bulk_uf=47).bulk_uf == 47.0
        assert decoupling_plan(2, 3.3, bulk_uf=1).bulk_uf == 10.0  # below min -> raised

    def test_invalid_inputs(self) -> None:
        with pytest.raises(ValueError):
            decoupling_plan(0, 3.3)
        with pytest.raises(ValueError):
            decoupling_plan(1, 0)


class TestLipoChargeResistor:
    def test_500ma_uses_2k_prog(self) -> None:
        r = lipo_charge_resistor(500)  # ideal 2.0k
        assert r.chosen_ohms == 2_000
        assert r.actual_current_ma == pytest.approx(500.0)

    def test_rounds_resistor_up_so_current_stays_at_or_under_target(self) -> None:
        r = lipo_charge_resistor(300)  # ideal 3.333k -> E24 ceil 3.6k
        assert r.chosen_ohms == 3_600
        assert r.actual_current_ma < 300.0

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError):
            lipo_charge_resistor(50)  # below MCP73831 100 mA floor
        with pytest.raises(ValueError):
            lipo_charge_resistor(800)  # above 500 mA ceiling


class TestBuckInductorCapacitor:
    def test_typical_12v_to_3v3(self) -> None:
        r = buck_inductor_capacitor(12.0, 3.3, 2.0, 500_000)
        assert r.duty_cycle == pytest.approx(0.275, rel=1e-3)
        assert r.ripple_current_a == pytest.approx(0.6)
        assert r.peak_inductor_current_a == pytest.approx(2.3)
        assert r.inductor_uh == pytest.approx(7.975, rel=1e-2)
        assert r.inductor_chosen_uh == 8.2  # nearest E12
        assert r.output_cap_uf == pytest.approx(4.545, rel=1e-2)
        assert r.output_cap_chosen_uf == 4.7  # E12 ceil

    def test_higher_frequency_shrinks_inductor(self) -> None:
        low = buck_inductor_capacitor(12.0, 5.0, 1.0, 200_000)
        high = buck_inductor_capacitor(12.0, 5.0, 1.0, 2_000_000)
        assert high.inductor_uh < low.inductor_uh

    def test_invalid_vout_not_below_vin(self) -> None:
        with pytest.raises(ValueError):
            buck_inductor_capacitor(5.0, 5.0, 1.0, 500_000)

    def test_invalid_ripple_ratio(self) -> None:
        with pytest.raises(ValueError):
            buck_inductor_capacitor(12.0, 3.3, 2.0, 500_000, ripple_ratio=0.0)


class TestPullResistor:
    def test_pull_up_basic(self) -> None:
        result = pull_resistor(3.3, direction="up")
        assert result.resistor_chosen_ohms > 0
        assert result.direction == "up"
        assert "pull-up" in result.note

    def test_pull_down_basic(self) -> None:
        result = pull_resistor(3.3, direction="down")
        assert result.direction == "down"
        assert "pull-down" in result.note

    def test_lower_current_gives_higher_resistance(self) -> None:
        r_loose = pull_resistor(3.3, direction="up", max_sink_current_ma=1.0)
        r_tight = pull_resistor(3.3, direction="up", max_sink_current_ma=0.1)
        assert r_tight.resistor_chosen_ohms >= r_loose.resistor_chosen_ohms

    def test_invalid_direction_raises(self) -> None:
        with pytest.raises(ValueError):
            pull_resistor(3.3, direction="sideways")

    def test_invalid_rail_raises(self) -> None:
        with pytest.raises(ValueError):
            pull_resistor(-1.0)


class TestBootResetStrapPlan:
    def test_stm32_plan(self) -> None:
        plan = boot_reset_strap_plan("stm32")
        assert plan.mcu_family == "stm32"
        pin_names = [s.signal_name for s in plan.strap_pins]
        assert "BOOT0" in pin_names
        assert "NRST" in pin_names

    def test_esp32_plan(self) -> None:
        plan = boot_reset_strap_plan("ESP32")
        assert "EN" in [s.signal_name for s in plan.strap_pins]
        assert "IO0" in [s.signal_name for s in plan.strap_pins]

    def test_rp2040_plan(self) -> None:
        plan = boot_reset_strap_plan("rp2040")
        assert "RUN" in [s.signal_name for s in plan.strap_pins]

    def test_unknown_family_falls_back_to_generic(self) -> None:
        plan = boot_reset_strap_plan("atmega2560")
        assert "RESET" in [s.signal_name for s in plan.strap_pins]

    def test_note_is_populated(self) -> None:
        plan = boot_reset_strap_plan("nrf52")
        assert plan.note
        assert "RESET" in plan.note


class TestBoostLc:
    def test_boost_5v_to_12v(self) -> None:
        result = boost_inductor_capacitor(5.0, 12.0, 0.5, 300_000.0)
        assert result.duty_cycle == pytest.approx(1 - 5.0 / 12.0, rel=0.01)
        assert result.inductor_uh > 0
        assert result.output_cap_uf > 0

    def test_peak_current_exceeds_average_input(self) -> None:
        result = boost_inductor_capacitor(3.3, 5.0, 1.0, 500_000.0)
        avg_iin = 1.0 * 5.0 / 3.3
        assert result.peak_inductor_current_a > avg_iin

    def test_invalid_vin_gt_vout(self) -> None:
        with pytest.raises(ValueError):
            boost_inductor_capacitor(12.0, 5.0, 1.0, 300_000.0)

    def test_invalid_ripple(self) -> None:
        with pytest.raises(ValueError):
            boost_inductor_capacitor(5.0, 12.0, 1.0, 300_000.0, ripple_ratio=1.5)


class TestLdoSelection:
    def test_normal_operation(self) -> None:
        result = ldo_selection(5.0, 3.3, 0.5)
        assert result.power_dissipation_w == pytest.approx((5.0 - 3.3) * 0.5, rel=0.01)
        assert result.min_vin_v == pytest.approx(3.3 + 0.3, rel=0.01)

    def test_vin_equals_vout_raises(self) -> None:
        with pytest.raises(ValueError):
            ldo_selection(3.3, 3.3, 0.5)

    def test_vin_below_dropout_raises(self) -> None:
        with pytest.raises(ValueError):
            ldo_selection(3.4, 3.3, 1.0, ldo_dropout_v=0.5)  # 3.3+0.5=3.8 > 3.4

    def test_thermal_budget_in_note(self) -> None:
        result = ldo_selection(12.0, 5.0, 0.1)
        assert "Pd=" in result.note
        assert "Tj=" in result.note


class TestMosfetSoa:
    def test_safe_operating_point(self) -> None:
        result = mosfet_soa_check(20.0, 0.05, vds_max=100.0, id_max=10.0, pd_max_w=50.0)
        assert result.soa_ok
        assert result.vds_ok
        assert result.id_ok
        assert result.pd_ok

    def test_overvoltage_fails(self) -> None:
        result = mosfet_soa_check(90.0, 0.5, vds_max=100.0, id_max=10.0, pd_max_w=50.0, derating=0.8)
        assert not result.vds_ok  # 90 > 100*0.8=80 V

    def test_overcurrent_fails(self) -> None:
        result = mosfet_soa_check(5.0, 9.0, vds_max=100.0, id_max=10.0, pd_max_w=50.0, derating=0.8)
        assert not result.id_ok  # 9 > 10*0.8=8 A

    def test_margins_are_above_one_when_ok(self) -> None:
        result = mosfet_soa_check(10.0, 0.1, vds_max=100.0, id_max=10.0, pd_max_w=50.0)
        assert result.margin_vds > 1.0
        assert result.margin_id > 1.0
        assert result.margin_pd > 1.0

    def test_thermal_power_limit_can_be_stricter_than_datasheet_rating(self) -> None:
        result = mosfet_soa_check(
            10.0,
            0.5,
            vds_max=100.0,
            id_max=10.0,
            pd_max_w=50.0,
            theta_ja_c_per_w=50.0,
            t_ambient_c=25.0,
            t_junction_max_c=150.0,
            derating=0.8,
        )
        assert not result.pd_ok  # thermal limit is 2.5 W, derated to 2.0 W
        assert not result.soa_ok
        assert "thermal=2.5W" in result.note
        assert "Tj_est=275.0°C/150°C" in result.note

    def test_higher_ambient_reduces_power_budget(self) -> None:
        cool = mosfet_soa_check(
            10.0,
            0.1,
            vds_max=100.0,
            id_max=10.0,
            pd_max_w=50.0,
            theta_ja_c_per_w=50.0,
            t_ambient_c=25.0,
            t_junction_max_c=150.0,
        )
        hot = mosfet_soa_check(
            10.0,
            0.1,
            vds_max=100.0,
            id_max=10.0,
            pd_max_w=50.0,
            theta_ja_c_per_w=50.0,
            t_ambient_c=125.0,
            t_junction_max_c=150.0,
        )
        assert cool.pd_ok
        assert not hot.pd_ok
        assert cool.margin_pd > hot.margin_pd

    def test_invalid_thermal_resistance(self) -> None:
        with pytest.raises(ValueError, match="theta_ja_c_per_w"):
            mosfet_soa_check(
                10.0,
                0.1,
                vds_max=100.0,
                id_max=10.0,
                pd_max_w=50.0,
                theta_ja_c_per_w=0.0,
            )

    def test_invalid_derating(self) -> None:
        with pytest.raises(ValueError):
            mosfet_soa_check(10.0, 1.0, vds_max=100.0, id_max=10.0, pd_max_w=50.0, derating=0.0)
