"""Tests for bounded rip-up and reroute (issue #127).

Covers:
* RipupConfig: defaults, to_dict()
* NetConflict: to_dict(), score determinism
* RipupIteration: improvement property, to_dict()
* RipupResult: accepted, completion rates, to_dict(), to_json(), result_hash
* run_ripup_reroute():
  - skipped when no unrouted nets
  - pass when all nets have positions and can be rerouted
  - partial when only some nets recover
  - no_solution when no positions for any net
  - timeout path (using very short max_seconds)
  - determinism: same input → same result_hash
  - conflict scoring: higher score first, lexicographic tie-break
  - iteration budgets respected
  - cost inflation tracked per iteration
  - remaining_conflicts present on partial/no_solution
  - improvement count is correct
  - rip_per_iter cap respected
  - design state valid at all exit paths
"""

from __future__ import annotations

import copy
import json

import pytest

import zaptrace.algo.ripup_reroute as ripup_mod
from zaptrace.algo.ripup_reroute import (
    DEFAULT_RIPUP_CONFIG,
    NetConflict,
    RipupConfig,
    RipupIteration,
    RipupResult,
    run_ripup_reroute,
)

# ---------------------------------------------------------------------------
# RipupConfig
# ---------------------------------------------------------------------------


class TestRipupConfig:
    def test_defaults(self) -> None:
        assert DEFAULT_RIPUP_CONFIG.max_iterations == 10
        assert DEFAULT_RIPUP_CONFIG.max_seconds == pytest.approx(30.0)
        assert DEFAULT_RIPUP_CONFIG.min_improvement == pytest.approx(0.0)
        assert DEFAULT_RIPUP_CONFIG.cost_inflation == pytest.approx(1.5)
        assert DEFAULT_RIPUP_CONFIG.max_rip_per_iter == 5

    def test_to_dict_keys(self) -> None:
        d = DEFAULT_RIPUP_CONFIG.to_dict()
        assert {"max_iterations", "max_seconds", "min_improvement", "cost_inflation", "max_rip_per_iter"} <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(DEFAULT_RIPUP_CONFIG.to_dict())

    def test_custom_config(self) -> None:
        cfg = RipupConfig(max_iterations=3, max_seconds=5.0, max_rip_per_iter=2)
        assert cfg.max_iterations == 3
        assert cfg.max_seconds == pytest.approx(5.0)
        assert cfg.max_rip_per_iter == 2


# ---------------------------------------------------------------------------
# NetConflict
# ---------------------------------------------------------------------------


class TestNetConflict:
    def test_to_dict_keys(self) -> None:
        c = NetConflict(net_name="VCC", conflict_degree=2, estimated_length_mm=10.0, conflict_score=30.0)
        d = c.to_dict()
        required = {"net_name", "conflict_degree", "estimated_length_mm", "conflict_score", "attempts", "last_reason"}
        assert required <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(NetConflict(net_name="GND").to_dict())


# ---------------------------------------------------------------------------
# RipupIteration
# ---------------------------------------------------------------------------


class TestRipupIteration:
    def test_improvement_property(self) -> None:
        it = RipupIteration(
            iteration=1,
            nets_ripped=["A"],
            nets_recovered=["A"],
            nets_remaining=[],
            routed_before=5,
            routed_after=6,
        )
        assert it.improvement == 1

    def test_negative_improvement(self) -> None:
        # Ripped but not recovered
        it = RipupIteration(
            iteration=1,
            nets_ripped=["A"],
            nets_recovered=[],
            nets_remaining=["A"],
            routed_before=5,
            routed_after=5,
        )
        assert it.improvement == 0

    def test_to_dict_keys(self) -> None:
        it = RipupIteration(
            iteration=1,
            nets_ripped=["A"],
            nets_recovered=["A"],
            nets_remaining=[],
            routed_before=5,
            routed_after=6,
        )
        d = it.to_dict()
        required = {
            "iteration",
            "nets_ripped",
            "nets_recovered",
            "nets_remaining",
            "routed_before",
            "routed_after",
            "improvement",
            "elapsed_s",
        }
        assert required <= d.keys()

    def test_serialisable(self) -> None:
        it = RipupIteration(1, ["A"], ["A"], [], 5, 6)
        json.dumps(it.to_dict())


# ---------------------------------------------------------------------------
# RipupResult
# ---------------------------------------------------------------------------


class TestRipupResult:
    def _pass_result(self) -> RipupResult:
        return RipupResult(
            status="pass",
            design_name="esp32_test",
            routed_nets_before=8,
            routed_nets_after=10,
            total_nets=10,
            config=DEFAULT_RIPUP_CONFIG,
        )

    def test_accepted_when_pass(self) -> None:
        assert self._pass_result().accepted is True

    def test_not_accepted_when_partial(self) -> None:
        r = RipupResult(status="partial", design_name="x")
        assert r.accepted is False

    def test_not_accepted_when_no_solution(self) -> None:
        r = RipupResult(status="no_solution", design_name="x")
        assert r.accepted is False

    def test_not_accepted_when_timeout(self) -> None:
        r = RipupResult(status="timeout", design_name="x")
        assert r.accepted is False

    def test_not_accepted_when_skipped(self) -> None:
        r = RipupResult(status="skipped", design_name="x")
        assert r.accepted is False

    def test_completion_rate_before(self) -> None:
        r = self._pass_result()
        assert abs(r.completion_rate_before - 0.8) < 0.001

    def test_completion_rate_after(self) -> None:
        r = self._pass_result()
        assert r.completion_rate_after == pytest.approx(1.0)

    def test_improvement(self) -> None:
        r = self._pass_result()
        assert r.improvement == 2

    def test_to_dict_keys(self) -> None:
        d = self._pass_result().to_dict()
        required = {
            "status",
            "design_name",
            "routed_nets_before",
            "routed_nets_after",
            "total_nets",
            "completion_rate_before",
            "completion_rate_after",
            "improvement",
            "accepted",
            "remaining_conflicts",
            "iterations",
            "config",
            "elapsed_s",
            "result_hash",
        }
        assert required <= d.keys()

    def test_to_json_round_trips(self) -> None:
        j = self._pass_result().to_json()
        d = json.loads(j)
        assert d["status"] == "pass"
        assert d["accepted"] is True

    def test_completion_rate_zero_total(self) -> None:
        r = RipupResult(status="skipped", design_name="empty", total_nets=0)
        assert r.completion_rate_before == pytest.approx(1.0)
        assert r.completion_rate_after == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# run_ripup_reroute — skipped path
# ---------------------------------------------------------------------------


class TestRunRipupSkipped:
    def test_skipped_when_no_unrouted(self) -> None:
        result = run_ripup_reroute("board", unrouted_nets=[], routed_nets=10, total_nets=10)
        assert result.status == "skipped"

    def test_skipped_has_no_iterations(self) -> None:
        result = run_ripup_reroute("board", unrouted_nets=[], routed_nets=5, total_nets=5)
        assert result.iterations == []

    def test_skipped_result_hash_nonempty(self) -> None:
        result = run_ripup_reroute("board", unrouted_nets=[], routed_nets=5, total_nets=5)
        assert len(result.result_hash) == 64

    def test_skipped_accepted_false(self) -> None:
        result = run_ripup_reroute("board", unrouted_nets=[], routed_nets=5, total_nets=5)
        assert result.accepted is False

    def test_skipped_completion_rate_100(self) -> None:
        result = run_ripup_reroute("board", unrouted_nets=[], routed_nets=10, total_nets=10)
        assert result.completion_rate_after == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# run_ripup_reroute — pass path (all nets have positions)
# ---------------------------------------------------------------------------


def _simple_positions(nets: list[str]) -> dict[str, list[tuple[float, float]]]:
    """Create well-separated node positions so all nets can route."""
    result = {}
    for idx, net in enumerate(nets):
        x_offset = idx * 20.0
        result[net] = [(x_offset, 0.0), (x_offset + 5.0, 5.0)]
    return result


class TestRunRipupPass:
    def test_pass_when_all_routed(self) -> None:
        nets = ["NET_A", "NET_B"]
        result = run_ripup_reroute(
            "board",
            unrouted_nets=nets,
            routed_nets=8,
            total_nets=10,
            node_positions=_simple_positions(nets),
        )
        assert result.status == "pass"

    def test_pass_accepted(self) -> None:
        nets = ["NET_A"]
        result = run_ripup_reroute(
            "board",
            unrouted_nets=nets,
            routed_nets=9,
            total_nets=10,
            node_positions=_simple_positions(nets),
        )
        assert result.accepted is True

    def test_pass_no_remaining_conflicts(self) -> None:
        nets = ["NET_A", "NET_B", "NET_C"]
        result = run_ripup_reroute(
            "board",
            unrouted_nets=nets,
            routed_nets=7,
            total_nets=10,
            node_positions=_simple_positions(nets),
        )
        assert result.status == "pass"
        assert result.remaining_conflicts == []

    def test_pass_improvement_matches_count(self) -> None:
        nets = ["NET_A", "NET_B"]
        result = run_ripup_reroute(
            "board",
            unrouted_nets=nets,
            routed_nets=8,
            total_nets=10,
            node_positions=_simple_positions(nets),
        )
        assert result.improvement == 2
        assert result.routed_nets_after == 10

    def test_pass_at_least_one_iteration(self) -> None:
        nets = ["NET_A"]
        result = run_ripup_reroute(
            "board",
            unrouted_nets=nets,
            routed_nets=9,
            total_nets=10,
            node_positions=_simple_positions(nets),
        )
        assert len(result.iterations) >= 1

    def test_result_hash_64_chars(self) -> None:
        nets = ["NET_A"]
        result = run_ripup_reroute(
            "board",
            unrouted_nets=nets,
            routed_nets=9,
            total_nets=10,
            node_positions=_simple_positions(nets),
        )
        assert len(result.result_hash) == 64


# ---------------------------------------------------------------------------
# run_ripup_reroute — no_solution path
# ---------------------------------------------------------------------------


class TestRunRipupNoSolution:
    def test_no_solution_when_no_positions(self) -> None:
        result = run_ripup_reroute(
            "board",
            unrouted_nets=["VCC", "GND"],
            routed_nets=5,
            total_nets=7,
            node_positions={},
            config=RipupConfig(max_iterations=2),
        )
        # No positions → routing always fails → no improvement → no_solution
        assert result.status == "no_solution"

    def test_no_solution_not_accepted(self) -> None:
        result = run_ripup_reroute(
            "board",
            unrouted_nets=["VCC"],
            routed_nets=5,
            total_nets=6,
            node_positions={},
            config=RipupConfig(max_iterations=1),
        )
        assert result.accepted is False

    def test_no_solution_has_remaining_conflicts(self) -> None:
        result = run_ripup_reroute(
            "board",
            unrouted_nets=["VCC", "GND"],
            routed_nets=5,
            total_nets=7,
            node_positions={},
            config=RipupConfig(max_iterations=2),
        )
        assert len(result.remaining_conflicts) > 0

    def test_no_solution_iterations_ran(self) -> None:
        result = run_ripup_reroute(
            "board",
            unrouted_nets=["VCC"],
            routed_nets=5,
            total_nets=6,
            node_positions={},
            config=RipupConfig(max_iterations=3),
        )
        assert len(result.iterations) >= 1


# ---------------------------------------------------------------------------
# run_ripup_reroute — partial path
# ---------------------------------------------------------------------------


class TestRunRipupPartial:
    def test_partial_when_some_recover(self) -> None:
        # NET_A has positions (can route), NET_B has no positions (cannot route)
        result = run_ripup_reroute(
            "board",
            unrouted_nets=["NET_A", "NET_B"],
            routed_nets=8,
            total_nets=10,
            node_positions={"NET_A": [(0.0, 0.0), (10.0, 10.0)]},
            config=RipupConfig(max_iterations=3, max_rip_per_iter=2),
        )
        assert result.status == "partial"
        assert result.improvement >= 1

    def test_partial_not_accepted(self) -> None:
        result = run_ripup_reroute(
            "board",
            unrouted_nets=["NET_A", "NET_B"],
            routed_nets=8,
            total_nets=10,
            node_positions={"NET_A": [(0.0, 0.0), (5.0, 5.0)]},
            config=RipupConfig(max_iterations=2, max_rip_per_iter=2),
        )
        assert result.accepted is False


# ---------------------------------------------------------------------------
# run_ripup_reroute — timeout path
# ---------------------------------------------------------------------------


class TestRunRipupTimeout:
    def test_timeout_when_budget_exceeded(self) -> None:
        # Use very small budget to force timeout
        nets = [f"NET_{i}" for i in range(20)]
        positions: dict[str, list[tuple[float, float]]] = {}
        # Nets with no positions cannot route, forcing max iterations to run
        # But we set max_seconds=0.0001 so wall clock expires instantly
        result = run_ripup_reroute(
            "board",
            unrouted_nets=nets,
            routed_nets=0,
            total_nets=20,
            node_positions=positions,
            config=RipupConfig(max_iterations=100, max_seconds=0.000001),
        )
        assert result.status in {"timeout", "no_solution"}

    def test_timeout_result_still_serialisable(self) -> None:
        nets = [f"NET_{i}" for i in range(5)]
        result = run_ripup_reroute(
            "board",
            unrouted_nets=nets,
            routed_nets=0,
            total_nets=5,
            node_positions={},
            config=RipupConfig(max_iterations=3, max_seconds=0.000001),
        )
        json.dumps(result.to_dict())


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_input_same_hash(self) -> None:
        nets = ["NET_X", "NET_Y"]
        positions = _simple_positions(nets)
        r1 = run_ripup_reroute("board", unrouted_nets=nets, routed_nets=8, total_nets=10, node_positions=positions)
        r2 = run_ripup_reroute("board", unrouted_nets=nets, routed_nets=8, total_nets=10, node_positions=positions)
        assert r1.result_hash == r2.result_hash

    def test_different_designs_different_hash(self) -> None:
        nets = ["NET_X"]
        positions = _simple_positions(nets)
        r1 = run_ripup_reroute("board_A", unrouted_nets=nets, routed_nets=9, total_nets=10, node_positions=positions)
        r2 = run_ripup_reroute("board_B", unrouted_nets=nets, routed_nets=9, total_nets=10, node_positions=positions)
        assert r1.result_hash != r2.result_hash

    def test_different_unrouted_different_hash(self) -> None:
        positions = {"NET_X": [(0.0, 0.0), (5.0, 5.0)], "NET_Y": [(20.0, 0.0), (25.0, 5.0)]}
        r1 = run_ripup_reroute("board", unrouted_nets=["NET_X"], routed_nets=9, total_nets=10, node_positions=positions)
        r2 = run_ripup_reroute("board", unrouted_nets=["NET_Y"], routed_nets=9, total_nets=10, node_positions=positions)
        assert r1.result_hash != r2.result_hash


# ---------------------------------------------------------------------------
# Conflict scoring
# ---------------------------------------------------------------------------


class TestConflictScoring:
    def test_remaining_conflicts_sorted_by_score(self) -> None:
        result = run_ripup_reroute(
            "board",
            unrouted_nets=["A", "B", "C"],
            routed_nets=0,
            total_nets=3,
            node_positions={},
            config=RipupConfig(max_iterations=1),
        )
        conflicts = result.remaining_conflicts
        scores = [c.conflict_score for c in conflicts]
        # Sorted descending
        assert scores == sorted(scores, reverse=True)

    def test_remaining_conflicts_include_all_unresolved(self) -> None:
        result = run_ripup_reroute(
            "board",
            unrouted_nets=["A", "B"],
            routed_nets=0,
            total_nets=2,
            node_positions={},
            config=RipupConfig(max_iterations=1),
        )
        names = {c.net_name for c in result.remaining_conflicts}
        assert names == {"A", "B"}


# ---------------------------------------------------------------------------
# Budget and iteration caps
# ---------------------------------------------------------------------------


class TestBudgetCaps:
    def test_max_iterations_respected(self) -> None:
        nets = [f"NET_{i}" for i in range(10)]
        result = run_ripup_reroute(
            "board",
            unrouted_nets=nets,
            routed_nets=0,
            total_nets=10,
            node_positions={},
            config=RipupConfig(max_iterations=3, max_seconds=60.0),
        )
        assert len(result.iterations) <= 3

    def test_rip_per_iter_cap(self) -> None:
        nets = [f"NET_{i}" for i in range(10)]
        result = run_ripup_reroute(
            "board",
            unrouted_nets=nets,
            routed_nets=0,
            total_nets=10,
            node_positions={},
            config=RipupConfig(max_iterations=1, max_rip_per_iter=3),
        )
        for it in result.iterations:
            assert len(it.nets_ripped) <= 3

    def test_config_present_in_result(self) -> None:
        cfg = RipupConfig(max_iterations=2)
        result = run_ripup_reroute("board", unrouted_nets=["VCC"], routed_nets=0, total_nets=1, config=cfg)
        assert result.config.max_iterations == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_net_single_position_no_crash(self) -> None:
        # Single position can't form a route (needs at least 2 nodes)
        result = run_ripup_reroute(
            "board",
            unrouted_nets=["VCC"],
            routed_nets=0,
            total_nets=1,
            node_positions={"VCC": [(0.0, 0.0)]},
            config=RipupConfig(max_iterations=1),
        )
        assert result.status in {"no_solution", "partial", "timeout"}

    def test_large_net_list_no_crash(self) -> None:
        nets = [f"NET_{i}" for i in range(50)]
        result = run_ripup_reroute(
            "board",
            unrouted_nets=nets,
            routed_nets=0,
            total_nets=50,
            node_positions={},
            config=RipupConfig(max_iterations=2, max_rip_per_iter=5),
        )
        assert result.status in {"no_solution", "partial", "timeout", "pass"}

    def test_zero_total_nets(self) -> None:
        result = run_ripup_reroute(
            "board",
            unrouted_nets=[],
            routed_nets=0,
            total_nets=0,
        )
        assert result.status == "skipped"
        assert result.completion_rate_after == pytest.approx(1.0)

    def test_result_always_serialisable(self) -> None:
        for nets in [[], ["A"], ["A", "B", "C"]]:
            result = run_ripup_reroute(
                "board",
                unrouted_nets=nets,
                routed_nets=0,
                total_nets=max(1, len(nets)),
                node_positions=_simple_positions(nets),
                config=RipupConfig(max_iterations=2),
            )
            json.dumps(result.to_dict())


class TestRipupRefactorCharacterization:
    def test_conflict_ranking_preserves_score_then_name_tie_break(self) -> None:
        route_table = {"R1": [(0.0, 0.0, 10.0, 10.0)]}
        positions = {
            "A": [(0.0, 0.0), (10.0, 10.0)],
            "B": [(20.0, 20.0), (30.0, 30.0)],
            "C": [(0.0, 0.0), (5.0, 5.0)],
        }

        conflicts = ripup_mod._score_conflicts(["C", "B", "A"], route_table, positions)

        assert [conflict.net_name for conflict in conflicts] == ["A", "B", "C"]
        assert [conflict.conflict_degree for conflict in conflicts] == [1, 0, 1]
        assert [conflict.conflict_score for conflict in conflicts] == [28.2843, 14.1421, 14.1421]

    def test_failed_reroute_preserves_caller_route_table(self) -> None:
        initial = {
            "KEEP": [(0.0, 0.0, 1.0, 1.0)],
            "FAIL": [(2.0, 2.0, 3.0, 3.0)],
        }
        before = copy.deepcopy(initial)

        result = run_ripup_reroute(
            "board",
            unrouted_nets=["FAIL"],
            routed_nets=1,
            total_nets=2,
            node_positions={},
            config=RipupConfig(max_iterations=1),
            _initial_route_table=initial,
        )

        assert result.status == "no_solution"
        assert initial == before
        assert result.iterations[0].nets_ripped == ["FAIL"]
        assert result.iterations[0].nets_recovered == []

    def test_result_hash_preserves_committed_fixture_value(self) -> None:
        result = run_ripup_reroute(
            "board",
            unrouted_nets=["A", "B"],
            routed_nets=8,
            total_nets=10,
            node_positions={
                "A": [(0.0, 0.0), (10.0, 10.0)],
                "B": [(20.0, 0.0), (25.0, 5.0)],
            },
            config=RipupConfig(max_iterations=3),
        )

        assert result.result_hash == "575b19f48848f6c8de780be5f79f4b884e3f997f40659d62c0403a45d540bb4d"
