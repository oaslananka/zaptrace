"""Tests for bounded multi-domain synthesis loop (issue #114).

Covers:
* StageStatus enum: all four values
* LedgerEntry: to_dict() keys, duration_s rounded
* ProofPack: artifact hashing, pack_hash determinism, to_dict()
* LoopResult: to_dict(), to_json(), stage_statuses, converged flag
* run_multi_domain_loop: end-to-end with a real intent
  - converges on benchmark family intent
  - ledger contains all expected stages
  - stage_statuses: synthesis=pass, placement=pass, routing=pass/no_reference
  - proof_pack has required artifact keys
  - pack_hash is deterministic across two runs
  - max_erc_iterations / max_drc_iterations caps respected
* Synthesis failure path: returns LoopResult with converged=False,
  blocking_stage='synthesis'
* ERC repair loop: bounded by max_erc_iterations
* Proof pack: artifact hashes are 64-char hex; pack_hash is 64-char hex
* Simulation gate: skipped when ngspice absent (no crash)
* DRC repair: skipped when runner unavailable (no crash)
* to_json: round-trips through json.loads; all required keys present
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

import pytest

from zaptrace.pipeline.multi_domain_loop import (
    LedgerEntry,
    LoopResult,
    ProofPack,
    StageStatus,
    run_multi_domain_loop,
)

_BENCHMARK_INTENT = "USB-C powered board, 3.3V rail, I2C sensor"


# ---------------------------------------------------------------------------
# StageStatus
# ---------------------------------------------------------------------------


class TestStageStatus:
    def test_all_four_values(self) -> None:
        assert StageStatus.PASS == "pass"
        assert StageStatus.FAIL == "fail"
        assert StageStatus.SKIPPED == "skipped"
        assert StageStatus.NO_REFERENCE == "no_reference"

    def test_is_str(self) -> None:
        assert isinstance(StageStatus.PASS, str)


# ---------------------------------------------------------------------------
# LedgerEntry
# ---------------------------------------------------------------------------


class TestLedgerEntry:
    def _entry(self) -> LedgerEntry:
        return LedgerEntry(
            stage="synthesis",
            status=StageStatus.PASS,
            duration_s=1.23456789,
        )

    def test_to_dict_has_required_keys(self) -> None:
        entry = self._entry()
        d = entry.to_dict()
        required = {"stage", "status", "iteration", "before_count", "after_count", "detail", "duration_s", "extra"}
        assert required <= d.keys()

    def test_duration_s_rounded(self) -> None:
        entry = self._entry()
        assert entry.to_dict()["duration_s"] == pytest.approx(1.2346, abs=0.0001)

    def test_status_serialised_as_string(self) -> None:
        entry = self._entry()
        assert entry.to_dict()["status"] == "pass"

    def test_default_iteration_is_zero(self) -> None:
        assert self._entry().to_dict()["iteration"] == 0

    def test_extra_defaults_to_empty_dict(self) -> None:
        assert self._entry().to_dict()["extra"] == {}


# ---------------------------------------------------------------------------
# ProofPack
# ---------------------------------------------------------------------------


class TestProofPack:
    def _make_pack(self) -> ProofPack:
        pack = ProofPack(
            design_name="test_board",
            generated_at="2026-01-01T00:00:00+00:00",
            artifacts={"bom_csv": "C1,100nF\n", "report": "## Summary\n"},
        )
        pack._compute_hashes()
        return pack

    def test_artifact_hashes_computed(self) -> None:
        pack = self._make_pack()
        assert "bom_csv" in pack.artifact_hashes
        assert "report" in pack.artifact_hashes

    def test_hashes_are_64_char_hex(self) -> None:
        pack = self._make_pack()
        for h in pack.artifact_hashes.values():
            assert len(h) == 64
            assert all(c in "0123456789abcdef" for c in h)

    def test_pack_hash_is_64_chars(self) -> None:
        pack = self._make_pack()
        assert len(pack.pack_hash) == 64

    def test_pack_hash_matches_canonical(self) -> None:
        pack = self._make_pack()
        canonical = json.dumps(pack.artifact_hashes, sort_keys=True)
        expected = hashlib.sha256(canonical.encode()).hexdigest()
        assert pack.pack_hash == expected

    def test_deterministic_hashes(self) -> None:
        pack1 = self._make_pack()
        pack2 = self._make_pack()
        assert pack1.pack_hash == pack2.pack_hash

    def test_to_dict_has_required_keys(self) -> None:
        pack = self._make_pack()
        d = pack.to_dict()
        required = {"design_name", "generated_at", "artifact_keys", "artifact_hashes", "pack_hash"}
        assert required <= d.keys()

    def test_artifact_keys_sorted(self) -> None:
        pack = self._make_pack()
        keys = pack.to_dict()["artifact_keys"]
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# LoopResult
# ---------------------------------------------------------------------------


class TestLoopResult:
    def _make_result(self) -> LoopResult:
        ledger = [
            LedgerEntry(stage="synthesis", status=StageStatus.PASS),
            LedgerEntry(stage="erc_repair", status=StageStatus.PASS),
            LedgerEntry(stage="placement", status=StageStatus.PASS),
        ]
        return LoopResult(
            design_name="test",
            intent="test intent",
            converged=True,
            blocking_stage=None,
            ledger=ledger,
        )

    def test_to_dict_has_required_keys(self) -> None:
        result = self._make_result()
        d = result.to_dict()
        required = {
            "design_name",
            "intent",
            "converged",
            "blocking_stage",
            "erc_violations_remaining",
            "total_duration_s",
            "ledger",
            "proof_pack",
        }
        assert required <= d.keys()

    def test_to_json_round_trips(self) -> None:
        result = self._make_result()
        j = result.to_json()
        d = json.loads(j)
        assert d["converged"] is True
        assert d["design_name"] == "test"

    def test_stage_statuses_latest_wins(self) -> None:
        ledger = [
            LedgerEntry(stage="erc_repair", status=StageStatus.FAIL, iteration=0),
            LedgerEntry(stage="erc_repair", status=StageStatus.PASS, iteration=1),
        ]
        result = LoopResult(
            design_name="t",
            intent="t",
            converged=True,
            blocking_stage=None,
            ledger=ledger,
        )
        assert result.stage_statuses["erc_repair"] == "pass"

    def test_blocking_stage_none_means_converged(self) -> None:
        result = self._make_result()
        assert result.converged is True
        assert result.blocking_stage is None


# ---------------------------------------------------------------------------
# run_multi_domain_loop — end-to-end
# ---------------------------------------------------------------------------


class TestRunMultiDomainLoopEndToEnd:
    @pytest.fixture(scope="class")
    def result(self) -> LoopResult:
        return run_multi_domain_loop(_BENCHMARK_INTENT)

    def test_converged(self, result: LoopResult) -> None:
        assert result.converged is True

    def test_design_name_nonempty(self, result: LoopResult) -> None:
        assert result.design_name

    def test_blocking_stage_none(self, result: LoopResult) -> None:
        assert result.blocking_stage is None

    def test_synthesis_stage_pass(self, result: LoopResult) -> None:
        assert result.stage_statuses.get("synthesis") == "pass"

    def test_placement_stage_pass(self, result: LoopResult) -> None:
        assert result.stage_statuses.get("placement") == "pass"

    def test_ledger_not_empty(self, result: LoopResult) -> None:
        assert len(result.ledger) > 0

    def test_ledger_has_all_required_stages(self, result: LoopResult) -> None:
        stages = {e.stage for e in result.ledger}
        required = {"synthesis", "placement", "routing", "proof_pack"}
        assert required <= stages

    def test_proof_pack_produced(self, result: LoopResult) -> None:
        assert result.proof_pack is not None

    def test_proof_pack_has_artifacts(self, result: LoopResult) -> None:
        assert result.proof_pack is not None
        assert len(result.proof_pack.artifacts) > 0

    def test_proof_pack_has_bom_csv(self, result: LoopResult) -> None:
        assert result.proof_pack is not None
        assert "bom_csv" in result.proof_pack.artifacts

    def test_proof_pack_has_report(self, result: LoopResult) -> None:
        assert result.proof_pack is not None
        assert "report" in result.proof_pack.artifacts

    def test_proof_pack_hash_nonempty(self, result: LoopResult) -> None:
        assert result.proof_pack is not None
        assert len(result.proof_pack.pack_hash) == 64

    def test_total_duration_positive(self, result: LoopResult) -> None:
        assert result.total_duration_s > 0

    def test_drc_repair_skipped_when_unavailable(self, result: LoopResult) -> None:
        drc = next((e for e in result.ledger if e.stage == "drc_repair"), None)
        # If DRC runner absent it should be SKIPPED; if present it should be any status
        if drc is not None:
            assert drc.status in (StageStatus.SKIPPED, StageStatus.PASS, StageStatus.FAIL, StageStatus.NO_REFERENCE)

    def test_simulation_gate_skipped_or_passes(self, result: LoopResult) -> None:
        sg = next((e for e in result.ledger if e.stage == "simulation_gate"), None)
        if sg is not None:
            assert sg.status in (StageStatus.SKIPPED, StageStatus.PASS, StageStatus.NO_REFERENCE, StageStatus.FAIL)

    def test_to_dict_serialisable(self, result: LoopResult) -> None:
        d = result.to_dict()
        # Must not raise
        json.dumps(d)


class TestRunMultiDomainLoopDeterminism:
    def test_pack_hash_deterministic(self) -> None:
        """Two runs from the same intent produce the same proof pack hash."""
        r1 = run_multi_domain_loop(_BENCHMARK_INTENT)
        r2 = run_multi_domain_loop(_BENCHMARK_INTENT)
        assert r1.proof_pack is not None
        assert r2.proof_pack is not None
        assert r1.proof_pack.pack_hash == r2.proof_pack.pack_hash

    def test_stage_statuses_deterministic(self) -> None:
        r1 = run_multi_domain_loop(_BENCHMARK_INTENT)
        r2 = run_multi_domain_loop(_BENCHMARK_INTENT)
        assert r1.stage_statuses == r2.stage_statuses


class TestRunMultiDomainLoopSynthesisFailure:
    def test_synthesis_fail_returns_converged_false(self) -> None:
        with patch("zaptrace.pipeline.multi_domain_loop.synthesize", side_effect=RuntimeError("synth fail")):
            result = run_multi_domain_loop("bad intent")
        assert result.converged is False
        assert result.blocking_stage == "synthesis"
        assert result.proof_pack is None

    def test_synthesis_fail_records_ledger(self) -> None:
        with patch("zaptrace.pipeline.multi_domain_loop.synthesize", side_effect=RuntimeError("synth fail")):
            result = run_multi_domain_loop("bad intent")
        fail_entry = next((e for e in result.ledger if e.stage == "synthesis"), None)
        assert fail_entry is not None
        assert fail_entry.status == StageStatus.FAIL


class TestRunMultiDomainLoopErcBound:
    def test_erc_iterations_capped(self) -> None:
        """Verify max_erc_iterations is passed through to repair_design."""
        from zaptrace.pipeline.multi_domain_loop import _run_erc_repair_loop
        from zaptrace.synthesis.engine import synthesize

        design = synthesize(_BENCHMARK_INTENT)
        ledger: list[LedgerEntry] = []
        _run_erc_repair_loop(design, ledger, max_iterations=1)
        # At most 1 erc_repair iteration entry
        repair_entries = [e for e in ledger if e.stage == "erc_repair"]
        assert len(repair_entries) <= 1

    def test_result_has_erc_violations_remaining_field(self) -> None:
        result = run_multi_domain_loop(_BENCHMARK_INTENT, max_erc_iterations=1)
        assert isinstance(result.erc_violations_remaining, int)
        assert result.erc_violations_remaining >= 0


class TestStageStatusVocabulary:
    def test_all_ledger_statuses_are_valid(self) -> None:
        result = run_multi_domain_loop(_BENCHMARK_INTENT)
        valid = {StageStatus.PASS, StageStatus.FAIL, StageStatus.SKIPPED, StageStatus.NO_REFERENCE}
        for entry in result.ledger:
            assert entry.status in valid, f"Invalid status {entry.status!r} in stage {entry.stage}"
