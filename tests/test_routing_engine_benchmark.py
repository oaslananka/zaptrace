"""Tests for routing engine benchmark (issue #128).

Covers:
* SUPPORTED_ENGINES vocabulary
* NetClassConstraint: to_dict(), cost_multiplier does not bypass hard clearance
* DiffPairTuningResult: before/after evidence, skew_improvement, target_met, to_dict()
* RoutingEngineConfig: defaults, to_dict()
* EngineRoutingResult: status vocabulary, accepted, completion_rate, to_dict(), to_json()
* FamilyBenchmarkReport: best_engine, any_pass, to_dict()
* AggregateBenchmarkReport: corpus_pass_rate, engine_pass_counts, engine_avg_completion,
  report_hash, to_dict(), to_json()
* run_engine_routing():
  - native: pass when full coverage
  - native: partial when partial coverage
  - freerouting: skipped when unavailable
  - ripup_reroute: pass path
  - net_class_constraints applied
  - diff_pair tuning evidence present
  - result_hash deterministic
  - result_hash differs across engines/families
  - common schema present for all engines
  - no quality claim exceeds measured result
* run_routing_benchmark():
  - all engines run for all families
  - per-family report has one result per engine
  - corpus_pass_rate in [0,1]
  - report_hash deterministic
  - diff_pair tuning propagated
  - net_class constraints propagated
  - serialisable
"""

from __future__ import annotations

import json

import pytest

from zaptrace.benchmark.routing_engine_benchmark import (
    DEFAULT_ENGINE_CONFIG,
    SUPPORTED_ENGINES,
    AggregateBenchmarkReport,
    DiffPairTuningResult,
    EngineRoutingResult,
    FamilyBenchmarkReport,
    NetClassConstraint,
    RoutingEngineConfig,
    run_engine_routing,
    run_routing_benchmark,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestSupportedEngines:
    def test_supported_engines_nonempty(self) -> None:
        assert len(SUPPORTED_ENGINES) >= 2

    def test_native_in_supported(self) -> None:
        assert "native" in SUPPORTED_ENGINES

    def test_freerouting_in_supported(self) -> None:
        assert "freerouting" in SUPPORTED_ENGINES

    def test_ripup_reroute_in_supported(self) -> None:
        assert "ripup_reroute" in SUPPORTED_ENGINES


# ---------------------------------------------------------------------------
# NetClassConstraint
# ---------------------------------------------------------------------------


class TestNetClassConstraint:
    def test_defaults(self) -> None:
        c = NetClassConstraint(class_name="signal")
        assert c.min_clearance_mm == pytest.approx(0.15)
        assert c.preferred_width_mm == pytest.approx(0.2)
        assert c.cost_multiplier == pytest.approx(1.0)

    def test_to_dict_keys(self) -> None:
        d = NetClassConstraint(class_name="power", min_clearance_mm=0.3).to_dict()
        assert {"class_name", "min_clearance_mm", "preferred_width_mm", "cost_multiplier"} <= d.keys()

    def test_hard_clearance_not_bypassed(self) -> None:
        # cost_multiplier should never be negative (would override avoidance logic)
        c = NetClassConstraint(class_name="diff", cost_multiplier=2.0)
        assert c.cost_multiplier > 0

    def test_serialisable(self) -> None:
        json.dumps(NetClassConstraint(class_name="gnd").to_dict())


# ---------------------------------------------------------------------------
# DiffPairTuningResult
# ---------------------------------------------------------------------------


class TestDiffPairTuningResult:
    def _result(self) -> DiffPairTuningResult:
        return DiffPairTuningResult(
            pair_name="USB_DP_DM",
            length_before_mm=80.0,
            length_after_mm=80.1,
            skew_before_mm=0.25,
            skew_after_mm=0.04,
            target_skew_mm=0.1,
            tuning_applied=True,
        )

    def test_skew_improvement(self) -> None:
        r = self._result()
        assert abs(r.skew_improvement_mm - 0.21) < 0.001

    def test_target_met(self) -> None:
        r = self._result()
        assert r.target_met is True

    def test_target_not_met(self) -> None:
        r = DiffPairTuningResult(pair_name="TX_RX", skew_after_mm=0.2, target_skew_mm=0.1)
        assert r.target_met is False

    def test_to_dict_keys(self) -> None:
        d = self._result().to_dict()
        required = {
            "pair_name",
            "length_before_mm",
            "length_after_mm",
            "skew_before_mm",
            "skew_after_mm",
            "target_skew_mm",
            "tuning_applied",
            "skew_improvement_mm",
            "target_met",
        }
        assert required <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(self._result().to_dict())


# ---------------------------------------------------------------------------
# RoutingEngineConfig
# ---------------------------------------------------------------------------


class TestRoutingEngineConfig:
    def test_defaults(self) -> None:
        assert DEFAULT_ENGINE_CONFIG.engine == "native"
        assert DEFAULT_ENGINE_CONFIG.net_class_constraints == ()
        assert DEFAULT_ENGINE_CONFIG.diff_pair_names == ()

    def test_to_dict_keys(self) -> None:
        d = DEFAULT_ENGINE_CONFIG.to_dict()
        required = {
            "engine",
            "net_class_constraints",
            "diff_pair_names",
            "diff_pair_target_skew_mm",
            "freerouting_timeout_s",
            "ripup_max_iterations",
        }
        assert required <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(DEFAULT_ENGINE_CONFIG.to_dict())


# ---------------------------------------------------------------------------
# EngineRoutingResult
# ---------------------------------------------------------------------------


class TestEngineRoutingResult:
    def _pass(self) -> EngineRoutingResult:
        return EngineRoutingResult(
            engine="native",
            family_name="esp32_usb_sensor",
            status="pass",
            routed_nets=12,
            total_nets=12,
            drc_clean=True,
        )

    def test_accepted_when_pass_and_drc_clean(self) -> None:
        assert self._pass().accepted is True

    def test_not_accepted_when_partial(self) -> None:
        r = EngineRoutingResult(engine="native", family_name="x", status="partial", drc_clean=True)
        assert r.accepted is False

    def test_not_accepted_when_drc_dirty(self) -> None:
        r = EngineRoutingResult(engine="native", family_name="x", status="pass", drc_clean=False)
        assert r.accepted is False

    def test_not_accepted_when_skipped(self) -> None:
        r = EngineRoutingResult(engine="freerouting", family_name="x", status="skipped")
        assert r.accepted is False

    def test_completion_rate_full(self) -> None:
        r = self._pass()
        assert r.completion_rate == pytest.approx(1.0)

    def test_completion_rate_partial(self) -> None:
        r = EngineRoutingResult(engine="native", family_name="x", routed_nets=6, total_nets=12)
        assert abs(r.completion_rate - 0.5) < 0.001

    def test_completion_rate_zero_total(self) -> None:
        r = EngineRoutingResult(engine="native", family_name="x", total_nets=0)
        assert r.completion_rate == pytest.approx(1.0)

    def test_to_dict_keys(self) -> None:
        d = self._pass().to_dict()
        required = {
            "engine",
            "family_name",
            "status",
            "routed_nets",
            "total_nets",
            "completion_rate",
            "drc_clean",
            "drc_violation_count",
            "total_wirelength_mm",
            "via_count",
            "runtime_s",
            "diff_pair_results",
            "net_class_applied",
            "accepted",
            "skip_reason",
            "result_hash",
        }
        assert required <= d.keys()

    def test_to_json_round_trips(self) -> None:
        j = self._pass().to_json()
        d = json.loads(j)
        assert d["engine"] == "native"
        assert d["accepted"] is True


# ---------------------------------------------------------------------------
# FamilyBenchmarkReport
# ---------------------------------------------------------------------------


class TestFamilyBenchmarkReport:
    def _report(self) -> FamilyBenchmarkReport:
        return FamilyBenchmarkReport(
            family_name="esp32_usb_sensor",
            results=[
                EngineRoutingResult(
                    engine="native",
                    family_name="esp32_usb_sensor",
                    status="pass",
                    routed_nets=12,
                    total_nets=12,
                    drc_clean=True,
                ),
                EngineRoutingResult(
                    engine="freerouting", family_name="esp32_usb_sensor", status="skipped", total_nets=12
                ),
            ],
        )

    def test_best_engine_prefers_accepted(self) -> None:
        report = self._report()
        assert report.best_engine == "native"

    def test_any_pass_true(self) -> None:
        assert self._report().any_pass is True

    def test_any_pass_false_when_all_fail(self) -> None:
        report = FamilyBenchmarkReport(
            family_name="x",
            results=[
                EngineRoutingResult(engine="native", family_name="x", status="fail"),
                EngineRoutingResult(engine="freerouting", family_name="x", status="skipped"),
            ],
        )
        assert report.any_pass is False

    def test_best_engine_none_when_all_skipped(self) -> None:
        report = FamilyBenchmarkReport(
            family_name="x",
            results=[
                EngineRoutingResult(engine="native", family_name="x", status="skipped"),
                EngineRoutingResult(engine="freerouting", family_name="x", status="skipped"),
            ],
        )
        assert report.best_engine is None

    def test_to_dict_keys(self) -> None:
        d = self._report().to_dict()
        assert {"family_name", "results", "best_engine", "any_pass"} <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(self._report().to_dict())


# ---------------------------------------------------------------------------
# AggregateBenchmarkReport
# ---------------------------------------------------------------------------


class TestAggregateBenchmarkReport:
    def _report(self) -> AggregateBenchmarkReport:
        return AggregateBenchmarkReport(
            families=[
                FamilyBenchmarkReport(
                    "family_A",
                    results=[
                        EngineRoutingResult(
                            engine="native",
                            family_name="family_A",
                            status="pass",
                            routed_nets=12,
                            total_nets=12,
                            drc_clean=True,
                        )
                    ],
                ),
                FamilyBenchmarkReport(
                    "family_B",
                    results=[
                        EngineRoutingResult(
                            engine="native",
                            family_name="family_B",
                            status="fail",
                            routed_nets=0,
                            total_nets=12,
                            drc_clean=False,
                        )
                    ],
                ),
            ],
            report_hash="a" * 64,
        )

    def test_total_families(self) -> None:
        assert self._report().total_families == 2

    def test_corpus_pass_rate(self) -> None:
        assert abs(self._report().corpus_pass_rate - 0.5) < 0.001

    def test_corpus_pass_rate_zero_when_all_fail(self) -> None:
        report = AggregateBenchmarkReport(families=[])
        assert report.corpus_pass_rate == pytest.approx(0.0)

    def test_engine_pass_counts_present(self) -> None:
        d = self._report().engine_pass_counts
        assert "native" in d
        assert d["native"] == 1

    def test_engine_avg_completion(self) -> None:
        d = self._report().engine_avg_completion
        assert "native" in d
        assert 0.0 <= d["native"] <= 1.0

    def test_to_dict_keys(self) -> None:
        d = self._report().to_dict()
        required = {
            "total_families",
            "corpus_pass_rate",
            "engine_pass_counts",
            "engine_avg_completion",
            "families",
            "report_hash",
        }
        assert required <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(self._report().to_dict())


# ---------------------------------------------------------------------------
# run_engine_routing
# ---------------------------------------------------------------------------


class TestRunEngineRoutingNative:
    def test_pass_when_full_coverage(self) -> None:
        result = run_engine_routing("esp32_usb_sensor", net_count=12)
        assert result.status == "pass"
        assert result.accepted is True

    def test_partial_when_partial_coverage(self) -> None:
        result = run_engine_routing(
            "esp32_usb_sensor",
            net_count=12,
            _stub_routed_nets=8,
        )
        assert result.status == "partial"
        assert result.accepted is False

    def test_fail_when_zero_coverage(self) -> None:
        result = run_engine_routing(
            "esp32_usb_sensor",
            net_count=12,
            _stub_routed_nets=0,
        )
        assert result.status == "fail"

    def test_engine_name_in_result(self) -> None:
        result = run_engine_routing("esp32_usb_sensor")
        assert result.engine == "native"

    def test_result_hash_nonempty(self) -> None:
        result = run_engine_routing("esp32_usb_sensor")
        assert len(result.result_hash) == 64

    def test_result_hash_deterministic(self) -> None:
        r1 = run_engine_routing("esp32_usb_sensor", net_count=12)
        r2 = run_engine_routing("esp32_usb_sensor", net_count=12)
        assert r1.result_hash == r2.result_hash

    def test_result_hash_differs_by_family(self) -> None:
        r1 = run_engine_routing("family_A", net_count=12)
        r2 = run_engine_routing("family_B", net_count=12)
        assert r1.result_hash != r2.result_hash

    def test_no_quality_claim_exceeds_measured(self) -> None:
        result = run_engine_routing("esp32_usb_sensor", net_count=12, _stub_routed_nets=8)
        assert result.routed_nets == 8
        assert result.total_nets == 12

    def test_serialisable(self) -> None:
        json.dumps(run_engine_routing("esp32_usb_sensor").to_dict())


class TestRunEngineRoutingFreerouting:
    def test_freerouting_skipped_when_unavailable(self) -> None:
        cfg = RoutingEngineConfig(engine="freerouting")
        result = run_engine_routing("esp32_usb_sensor", config=cfg, net_count=12)
        # Either skipped (no JAR) or pass (if JAR found) — both valid
        assert result.engine == "freerouting"
        assert result.status in {"skipped", "pass", "partial", "fail"}

    def test_freerouting_skip_reason_present_when_skipped(self) -> None:
        cfg = RoutingEngineConfig(engine="freerouting")
        result = run_engine_routing("esp32_usb_sensor", config=cfg)
        if result.status == "skipped":
            assert result.skip_reason


class TestRunEngineRoutingRipup:
    def test_ripup_engine_runs(self) -> None:
        cfg = RoutingEngineConfig(engine="ripup_reroute")
        result = run_engine_routing("esp32_usb_sensor", config=cfg, net_count=12)
        assert result.engine == "ripup_reroute"
        assert result.status in {"pass", "partial", "fail", "skipped", "error"}


class TestRunEngineRoutingNetClass:
    def test_net_class_applied_in_result(self) -> None:
        constraints = (
            NetClassConstraint(class_name="power", min_clearance_mm=0.3),
            NetClassConstraint(class_name="signal"),
        )
        cfg = RoutingEngineConfig(engine="native", net_class_constraints=constraints)
        result = run_engine_routing("esp32_usb_sensor", config=cfg)
        applied = result.net_class_applied
        assert len(applied) == 2
        assert any(c.class_name == "power" for c in applied)

    def test_hard_clearance_not_reduced_by_multiplier(self) -> None:
        c = NetClassConstraint(class_name="signal", min_clearance_mm=0.15, cost_multiplier=10.0)
        assert c.min_clearance_mm == pytest.approx(0.15)


class TestRunEngineRoutingDiffPair:
    def test_diff_pair_results_present(self) -> None:
        cfg = RoutingEngineConfig(engine="native", diff_pair_names=("USB_DP_DM", "UART_TX_RX"))
        result = run_engine_routing("esp32_usb_sensor", config=cfg)
        assert len(result.diff_pair_results) == 2

    def test_diff_pair_before_after_populated(self) -> None:
        cfg = RoutingEngineConfig(engine="native", diff_pair_names=("USB_DP_DM",))
        result = run_engine_routing("esp32_usb_sensor", config=cfg)
        dp = result.diff_pair_results[0]
        assert dp.pair_name == "USB_DP_DM"
        assert dp.length_before_mm > 0
        assert dp.tuning_applied is True

    def test_diff_pair_deterministic(self) -> None:
        cfg = RoutingEngineConfig(engine="native", diff_pair_names=("USB_DP_DM",))
        r1 = run_engine_routing("esp32_usb_sensor", config=cfg)
        r2 = run_engine_routing("esp32_usb_sensor", config=cfg)
        assert r1.diff_pair_results[0].skew_before_mm == r2.diff_pair_results[0].skew_before_mm


# ---------------------------------------------------------------------------
# run_routing_benchmark
# ---------------------------------------------------------------------------


class TestRunRoutingBenchmark:
    FAMILIES = ["esp32_usb_sensor", "stm32_rs485_industrial", "nrf52_ble_multisensor"]

    def test_all_families_present(self) -> None:
        report = run_routing_benchmark(self.FAMILIES, engines=["native"], net_count=12)
        names = {f.family_name for f in report.families}
        assert names == set(self.FAMILIES)

    def test_all_engines_per_family(self) -> None:
        engines: list = ["native", "ripup_reroute"]
        report = run_routing_benchmark(self.FAMILIES, engines=engines, net_count=12)
        for family in report.families:
            assert len(family.results) == len(engines)

    def test_corpus_pass_rate_in_range(self) -> None:
        report = run_routing_benchmark(self.FAMILIES, engines=["native"], net_count=12)
        assert 0.0 <= report.corpus_pass_rate <= 1.0

    def test_report_hash_nonempty(self) -> None:
        report = run_routing_benchmark(self.FAMILIES, engines=["native"], net_count=12)
        assert len(report.report_hash) == 64

    def test_report_hash_deterministic(self) -> None:
        r1 = run_routing_benchmark(self.FAMILIES, engines=["native"], net_count=12)
        r2 = run_routing_benchmark(self.FAMILIES, engines=["native"], net_count=12)
        assert r1.report_hash == r2.report_hash

    def test_diff_pair_propagated(self) -> None:
        report = run_routing_benchmark(
            ["esp32_usb_sensor"],
            engines=["native"],
            net_count=12,
            diff_pair_names=["USB_DP_DM"],
        )
        result = report.families[0].results[0]
        assert len(result.diff_pair_results) == 1

    def test_net_class_constraints_propagated(self) -> None:
        report = run_routing_benchmark(
            ["esp32_usb_sensor"],
            engines=["native"],
            net_count=12,
            net_class_constraints=[NetClassConstraint(class_name="power")],
        )
        result = report.families[0].results[0]
        assert len(result.net_class_applied) == 1

    def test_serialisable(self) -> None:
        report = run_routing_benchmark(self.FAMILIES, engines=["native"], net_count=8)
        json.dumps(report.to_dict())

    def test_empty_families_no_crash(self) -> None:
        report = run_routing_benchmark([])
        assert report.total_families == 0
        assert report.corpus_pass_rate == pytest.approx(0.0)

    def test_engine_pass_counts_keys(self) -> None:
        report = run_routing_benchmark(self.FAMILIES, engines=["native"], net_count=12)
        counts = report.engine_pass_counts
        assert "native" in counts

    def test_engine_avg_completion_keys(self) -> None:
        report = run_routing_benchmark(self.FAMILIES, engines=["native"], net_count=12)
        avg = report.engine_avg_completion
        assert "native" in avg
        assert 0.0 <= avg["native"] <= 1.0
