"""Regression tests for the deterministic ERC repair scorecard (issue #107).

Covers:
* Corpus has ≥ 10 fault classes covering distinct ERC rule IDs
* Every corpus case is classified (fixed, declined, or escalated — never missing)
* Scorecard output is byte-stable across repeated runs
* Regression fails when a corpus entry changes its classification
* Each ScorecardEntry has correct fields populated
* ScorecardResult.to_dict() is byte-stable
* All three outcome categories (fixed / declined / escalated) are represented
* Custom corpus parameter works
"""

from __future__ import annotations

import json

import pytest

from zaptrace.erc.scorecard import (
    CORPUS,
    ScorecardFixture,
    ScorecardResult,
    run_scorecard,
)

# ---------------------------------------------------------------------------
# Corpus shape invariants
# ---------------------------------------------------------------------------


class TestCorpusShape:
    def test_corpus_has_at_least_ten_entries(self) -> None:
        assert len(CORPUS) >= 10, f"Corpus must have ≥10 entries, got {len(CORPUS)}"

    def test_all_fixture_ids_unique(self) -> None:
        ids = [f.fixture_id for f in CORPUS]
        assert len(ids) == len(set(ids)), "Corpus fixture_ids must be unique"

    def test_all_rule_ids_nonempty(self) -> None:
        for f in CORPUS:
            assert f.rule_id, f"fixture_id={f.fixture_id} has empty rule_id"

    def test_expected_outcomes_are_valid(self) -> None:
        valid = {"fixed", "declined", "escalated"}
        for f in CORPUS:
            assert f.expected_outcome in valid, (
                f"fixture_id={f.fixture_id}: expected_outcome={f.expected_outcome!r} not in {valid}"
            )

    def test_corpus_covers_distinct_rule_ids(self) -> None:
        rule_ids = {f.rule_id for f in CORPUS}
        assert len(rule_ids) >= 7, f"Corpus should cover ≥7 distinct ERC rules, got {len(rule_ids)}: {rule_ids}"

    def test_factories_are_callable(self) -> None:
        for f in CORPUS:
            assert callable(f.factory), f"factory for {f.fixture_id} is not callable"

    def test_factories_return_fresh_designs(self) -> None:
        """Each factory call returns a distinct object (no shared state)."""
        for fixture in CORPUS:
            d1 = fixture.factory()
            d2 = fixture.factory()
            assert d1 is not d2, f"factory for {fixture.fixture_id} returned the same object twice"


# ---------------------------------------------------------------------------
# Scorecard run results
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def scorecard() -> ScorecardResult:
    """Run the scorecard once and share the result across this module."""
    return run_scorecard()


class TestScorecardRunResults:
    def test_entry_count_matches_corpus(self, scorecard: ScorecardResult) -> None:
        assert scorecard.total_fixtures == len(CORPUS)

    def test_all_entries_have_valid_outcome(self, scorecard: ScorecardResult) -> None:
        valid = {"fixed", "declined", "escalated"}
        for e in scorecard.entries:
            assert e.actual_outcome in valid, f"entry {e.fixture_id} has invalid outcome {e.actual_outcome!r}"

    def test_all_three_outcome_categories_present(self, scorecard: ScorecardResult) -> None:
        actual_outcomes = {e.actual_outcome for e in scorecard.entries}
        for expected in ("fixed", "declined", "escalated"):
            assert expected in actual_outcomes, (
                f"No {expected!r} case in scorecard — corpus must cover all three outcome categories"
            )

    def test_all_entries_have_evidence(self, scorecard: ScorecardResult) -> None:
        for e in scorecard.entries:
            assert e.evidence, f"entry {e.fixture_id} has empty evidence string"

    def test_entries_sorted_by_rule_then_fixture_id(self, scorecard: ScorecardResult) -> None:
        keys = [(e.rule_id, e.fixture_id) for e in scorecard.entries]
        assert keys == sorted(keys), "Entries must be sorted by (rule_id, fixture_id)"

    def test_violations_before_gte_zero(self, scorecard: ScorecardResult) -> None:
        for e in scorecard.entries:
            assert e.violations_before >= 0, f"entry {e.fixture_id}: negative violations_before"

    def test_decisions_list_populated(self, scorecard: ScorecardResult) -> None:
        """Every entry that did not escalate must have at least one decision."""
        for e in scorecard.entries:
            if e.actual_outcome != "escalated":
                assert len(e.decisions) >= 1, f"entry {e.fixture_id} (outcome={e.actual_outcome}) has no decisions"


# ---------------------------------------------------------------------------
# Regression: all corpus cases pass
# ---------------------------------------------------------------------------


class TestRegressionPassFail:
    def test_all_cases_pass(self, scorecard: ScorecardResult) -> None:
        failures = scorecard.failed_entries()
        if failures:
            lines = [f"  {e.fixture_id}: expected={e.expected_outcome}, actual={e.actual_outcome}" for e in failures]
            msg = "Corpus regression failures detected:\n" + "\n".join(lines)
            pytest.fail(msg)

    def test_regression_pass_count_equals_total(self, scorecard: ScorecardResult) -> None:
        assert scorecard.regression_passes == scorecard.total_fixtures

    def test_regression_failure_count_is_zero(self, scorecard: ScorecardResult) -> None:
        assert scorecard.regression_failures == 0


# ---------------------------------------------------------------------------
# Byte-stability
# ---------------------------------------------------------------------------


class TestByteStability:
    def test_to_json_is_deterministic(self) -> None:
        j1 = run_scorecard().to_json()
        j2 = run_scorecard().to_json()
        j3 = run_scorecard().to_json()
        assert j1 == j2, "to_json() is not byte-stable between run 1 and run 2"
        assert j2 == j3, "to_json() is not byte-stable between run 2 and run 3"

    def test_to_json_parses_as_valid_json(self) -> None:
        j = run_scorecard().to_json()
        data = json.loads(j)
        assert isinstance(data, dict)
        assert "entries" in data

    def test_to_dict_entry_keys_are_complete(self) -> None:
        result = run_scorecard()
        required = {
            "fixture_id",
            "rule_id",
            "description",
            "expected_outcome",
            "actual_outcome",
            "violations_before",
            "violations_after",
            "decisions_count",
            "evidence",
            "regression_pass",
        }
        for entry in result.to_dict()["entries"]:
            missing = required - entry.keys()
            assert not missing, f"Entry {entry.get('fixture_id')!r} is missing keys: {missing}"

    def test_to_dict_top_level_keys(self) -> None:
        d = run_scorecard().to_dict()
        required = {"total_fixtures", "regression_passes", "regression_failures", "entries"}
        assert required <= d.keys()

    def test_json_keys_are_sorted(self) -> None:
        """JSON output uses sorted keys (sort_keys=True)."""
        j = run_scorecard().to_json()
        data = json.loads(j)
        # Re-encode without sort_keys and verify they match when both sorted.
        assert j == json.dumps(data, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Custom corpus parameter
# ---------------------------------------------------------------------------


class TestCustomCorpus:
    def _make_minimal_fixture(self, outcome: str = "escalated") -> ScorecardFixture:
        from zaptrace.core.models import Component, Design, DesignMeta

        def factory() -> Design:
            d = Design(meta=DesignMeta(name="custom-test"))
            d.components["U1"] = Component(id="U1", ref="U1", type="ic", value="X", footprint="0402")
            return d

        return ScorecardFixture(
            fixture_id="CUSTOM-001",
            rule_id="ERC999",
            description="Custom test fixture",
            factory=factory,
            expected_outcome=outcome,
        )

    def test_custom_corpus_runs(self) -> None:
        fixture = self._make_minimal_fixture()
        result = run_scorecard(corpus=[fixture])
        assert result.total_fixtures == 1

    def test_custom_corpus_entry_has_fixture_id(self) -> None:
        fixture = self._make_minimal_fixture()
        result = run_scorecard(corpus=[fixture])
        assert result.entries[0].fixture_id == "CUSTOM-001"

    def test_empty_corpus_returns_empty_result(self) -> None:
        result = run_scorecard(corpus=[])
        assert result.total_fixtures == 0
        assert result.regression_passes == 0
        assert result.regression_failures == 0


# ---------------------------------------------------------------------------
# Individual fixture entry checks
# ---------------------------------------------------------------------------


class TestIndividualEntries:
    @pytest.mark.parametrize(
        "fixture_id,expected_outcome",
        [(f.fixture_id, f.expected_outcome) for f in CORPUS],
    )
    def test_fixture_outcome(self, fixture_id: str, expected_outcome: str) -> None:
        fixture = next(f for f in CORPUS if f.fixture_id == fixture_id)
        result = run_scorecard(corpus=[fixture])
        entry = result.entries[0]
        assert entry.actual_outcome == expected_outcome, (
            f"Corpus drift detected for {fixture_id}: expected={expected_outcome}, actual={entry.actual_outcome}"
        )
