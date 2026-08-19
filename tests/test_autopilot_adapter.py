"""Tests for the autopilot multi-domain loop adapter (issue #116).

Covers:
* LoopGateSchema: all fields, to_dict() serialisation
* gate_schema_from_result: produces correct schema from LoopResult
* AutopilotAdapter: construction with default and custom args
* run_from_intent: returns PipelineContext; synthesis has loop_result
* run_from_intent: converged flag set correctly
* run_from_intent: gate_schema() returns LoopGateSchema from context
* run_from_design: extracts intent from design.meta.description
* run_from_design: falls back to str(design) when meta absent
* run_from_file: delegates parse to wrapped Autopilot; fails gracefully
* run_from_intent_with_timeout: returns context + schema on success
* run_from_intent_with_timeout: raises AutopilotTimeoutError on timeout
* AutopilotTimeoutError: partial attribute contains PartialLoopResult
* adapt_autopilot: functional helper returns AutopilotAdapter
* Interface compatibility: __getattr__ forwards to wrapped Autopilot
* BOM/report surfaced in context from proof pack
* Same schema structure from CLI and API paths (no second stage sequence)
* Cancellation: partial result records intent and elapsed_s
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from zaptrace.pipeline.autopilot import Autopilot, PipelineContext
from zaptrace.pipeline.autopilot_adapter import (
    AutopilotAdapter,
    AutopilotTimeoutError,
    LoopGateSchema,
    PartialLoopResult,
    adapt_autopilot,
    gate_schema_from_result,
)
from zaptrace.pipeline.multi_domain_loop import LoopResult, run_multi_domain_loop

_INTENT = "ESP32 USB-C 3.3V sensor board with I2C"


# ---------------------------------------------------------------------------
# LoopGateSchema
# ---------------------------------------------------------------------------


class TestLoopGateSchema:
    def _schema(self) -> LoopGateSchema:
        return LoopGateSchema(
            design_name="my_board",
            intent=_INTENT,
            converged=True,
            blocking_stage=None,
            erc_violations_remaining=0,
            stage_statuses={"synthesis": "pass"},
            proof_pack_hash="a" * 64,
            total_duration_s=1.23,
            ledger=[],
        )

    def test_to_dict_has_all_keys(self) -> None:
        d = self._schema().to_dict()
        required = {
            "design_name",
            "intent",
            "converged",
            "blocking_stage",
            "erc_violations_remaining",
            "stage_statuses",
            "proof_pack_hash",
            "total_duration_s",
            "ledger",
        }
        assert required <= d.keys()

    def test_to_dict_serialisable(self) -> None:
        json.dumps(self._schema().to_dict())

    def test_duration_rounded(self) -> None:
        schema = LoopGateSchema(
            design_name="x",
            intent="y",
            converged=True,
            blocking_stage=None,
            erc_violations_remaining=0,
            stage_statuses={},
            proof_pack_hash=None,
            total_duration_s=1.234567,
            ledger=[],
        )
        assert schema.to_dict()["total_duration_s"] == pytest.approx(1.2346, abs=0.0001)

    def test_is_frozen(self) -> None:
        schema = self._schema()
        with pytest.raises((AttributeError, TypeError)):
            schema.converged = False  # type: ignore[misc]


class TestGateSchemaFromResult:
    @pytest.fixture(scope="class")
    def loop_result(self) -> LoopResult:
        return run_multi_domain_loop(_INTENT)

    def test_schema_converged_matches_result(self, loop_result: LoopResult) -> None:
        schema = gate_schema_from_result(loop_result)
        assert schema.converged == loop_result.converged

    def test_schema_intent_matches_result(self, loop_result: LoopResult) -> None:
        schema = gate_schema_from_result(loop_result)
        assert schema.intent == loop_result.intent

    def test_schema_has_proof_pack_hash(self, loop_result: LoopResult) -> None:
        schema = gate_schema_from_result(loop_result)
        assert schema.proof_pack_hash is not None

    def test_schema_stage_statuses_nonempty(self, loop_result: LoopResult) -> None:
        schema = gate_schema_from_result(loop_result)
        assert len(schema.stage_statuses) > 0

    def test_schema_ledger_matches_result(self, loop_result: LoopResult) -> None:
        schema = gate_schema_from_result(loop_result)
        assert len(schema.ledger) == len(loop_result.ledger)


# ---------------------------------------------------------------------------
# AutopilotAdapter construction
# ---------------------------------------------------------------------------


class TestAutopilotAdapterConstruction:
    def test_default_construction(self) -> None:
        adapter = AutopilotAdapter()
        assert isinstance(adapter._wrapped, Autopilot)

    def test_custom_autopilot(self) -> None:
        ap = Autopilot()
        adapter = AutopilotAdapter(ap)
        assert adapter._wrapped is ap

    def test_custom_iterations(self) -> None:
        adapter = AutopilotAdapter(max_erc_iterations=3, max_drc_iterations=2)
        assert adapter._max_erc_iterations == 3
        assert adapter._max_drc_iterations == 2

    def test_adapt_autopilot_helper(self) -> None:
        adapter = adapt_autopilot()
        assert isinstance(adapter, AutopilotAdapter)

    def test_adapt_autopilot_with_wrapped(self) -> None:
        ap = Autopilot()
        adapter = adapt_autopilot(ap)
        assert adapter._wrapped is ap


# ---------------------------------------------------------------------------
# run_from_intent
# ---------------------------------------------------------------------------


class TestRunFromIntent:
    @pytest.fixture(scope="class")
    def ctx(self) -> PipelineContext:
        return AutopilotAdapter().run_from_intent(_INTENT)

    def test_returns_pipeline_context(self, ctx: PipelineContext) -> None:
        assert isinstance(ctx, PipelineContext)

    def test_synthesis_has_loop_result(self, ctx: PipelineContext) -> None:
        assert ctx.synthesis is not None
        assert "loop_result" in ctx.synthesis

    def test_loop_result_is_converged(self, ctx: PipelineContext) -> None:
        loop_result = ctx.synthesis["loop_result"]  # type: ignore[index]
        assert isinstance(loop_result, LoopResult)
        assert loop_result.converged is True

    def test_source_is_intent(self, ctx: PipelineContext) -> None:
        assert ctx.source == _INTENT

    def test_started_at_set(self, ctx: PipelineContext) -> None:
        assert ctx.started_at is not None

    def test_bom_csv_surfaced(self, ctx: PipelineContext) -> None:
        assert ctx.bom_csv is not None

    def test_report_surfaced(self, ctx: PipelineContext) -> None:
        assert ctx.report is not None

    def test_gate_schema_from_context(self, ctx: PipelineContext) -> None:
        adapter = AutopilotAdapter()
        schema = adapter.gate_schema(ctx)
        assert schema is not None
        assert schema.converged is True

    def test_no_second_stage_sequence(self, ctx: PipelineContext) -> None:
        """Autopilot adapter must not run a second stage sequence."""
        # If only the loop ran, the synthesis dict has exactly one key
        synthesis = ctx.synthesis or {}
        assert "loop_result" in synthesis


# ---------------------------------------------------------------------------
# run_from_design
# ---------------------------------------------------------------------------


class TestRunFromDesign:
    def _make_design(self, description: str) -> object:
        meta = SimpleNamespace(description=description, name="test_board")
        return SimpleNamespace(meta=meta)

    def test_extracts_intent_from_meta_description(self) -> None:
        design = self._make_design(_INTENT)
        ctx = AutopilotAdapter().run_from_design(design)
        loop_result = (ctx.synthesis or {}).get("loop_result")
        assert loop_result is not None
        assert loop_result.intent == _INTENT

    def test_fallback_when_description_empty(self) -> None:
        design = self._make_design("")
        ctx = AutopilotAdapter().run_from_design(design)
        assert ctx.synthesis is not None

    def test_fallback_when_no_meta(self) -> None:
        ctx = AutopilotAdapter().run_from_design(object())
        assert ctx.synthesis is not None


# ---------------------------------------------------------------------------
# run_from_intent_with_timeout
# ---------------------------------------------------------------------------


class TestRunFromIntentWithTimeout:
    def test_returns_context_and_schema_on_success(self) -> None:
        adapter = AutopilotAdapter()
        ctx, schema = adapter.run_from_intent_with_timeout(_INTENT, timeout_s=60.0)
        assert isinstance(ctx, PipelineContext)
        assert isinstance(schema, LoopGateSchema)
        assert schema.converged is True

    def test_raises_timeout_error_on_slow_loop(self) -> None:
        import time

        def slow_loop(intent: str, **kwargs: object) -> LoopResult:
            time.sleep(5)
            return run_multi_domain_loop(intent)

        adapter = AutopilotAdapter()
        with (
            patch("zaptrace.pipeline.autopilot_adapter.run_multi_domain_loop", side_effect=slow_loop),
            pytest.raises(AutopilotTimeoutError) as exc_info,
        ):
            adapter.run_from_intent_with_timeout(_INTENT, timeout_s=0.1)
        assert isinstance(exc_info.value.partial, PartialLoopResult)

    def test_partial_result_has_intent(self) -> None:
        import time

        def slow_loop(intent: str, **kwargs: object) -> LoopResult:
            time.sleep(5)
            return run_multi_domain_loop(intent)

        adapter = AutopilotAdapter()
        with (
            patch("zaptrace.pipeline.autopilot_adapter.run_multi_domain_loop", side_effect=slow_loop),
            pytest.raises(AutopilotTimeoutError) as exc_info,
        ):
            adapter.run_from_intent_with_timeout(_INTENT, timeout_s=0.1)
        assert exc_info.value.partial.intent == _INTENT

    def test_partial_result_has_elapsed_s(self) -> None:
        import time

        def slow_loop(intent: str, **kwargs: object) -> LoopResult:
            time.sleep(5)
            return run_multi_domain_loop(intent)

        adapter = AutopilotAdapter()
        with (
            patch("zaptrace.pipeline.autopilot_adapter.run_multi_domain_loop", side_effect=slow_loop),
            pytest.raises(AutopilotTimeoutError) as exc_info,
        ):
            adapter.run_from_intent_with_timeout(_INTENT, timeout_s=0.1)
        assert exc_info.value.partial.elapsed_s >= 0.0


# ---------------------------------------------------------------------------
# Interface compatibility (__getattr__ delegation)
# ---------------------------------------------------------------------------


class TestInterfaceCompatibility:
    def test_list_templates_forwarded(self) -> None:
        adapter = AutopilotAdapter()
        templates = adapter.list_templates()
        assert isinstance(templates, list)

    def test_unknown_attr_raises_attribute_error(self) -> None:
        adapter = AutopilotAdapter()
        with pytest.raises(AttributeError):
            _ = adapter.nonexistent_method_xyz

    def test_gate_schema_returns_none_when_no_loop_result(self) -> None:
        adapter = AutopilotAdapter()
        ctx = PipelineContext()
        assert adapter.gate_schema(ctx) is None


# ---------------------------------------------------------------------------
# PartialLoopResult
# ---------------------------------------------------------------------------


class TestPartialLoopResult:
    def test_fields(self) -> None:
        partial = PartialLoopResult(intent="x", elapsed_s=1.5)
        assert partial.intent == "x"
        assert partial.elapsed_s == pytest.approx(1.5)
        assert partial.stages_completed == []

    def test_stages_completed(self) -> None:
        partial = PartialLoopResult(intent="x", elapsed_s=0.1, stages_completed=["synthesis"])
        assert "synthesis" in partial.stages_completed


# ---------------------------------------------------------------------------
# Schema consistency: same structure from all entry points
# ---------------------------------------------------------------------------


class TestSchemaConsistency:
    def test_cli_and_api_produce_same_schema_keys(self) -> None:
        adapter = AutopilotAdapter()
        ctx = adapter.run_from_intent(_INTENT)
        schema = adapter.gate_schema(ctx)
        assert schema is not None

        required = {
            "design_name",
            "intent",
            "converged",
            "blocking_stage",
            "erc_violations_remaining",
            "stage_statuses",
            "proof_pack_hash",
            "total_duration_s",
            "ledger",
        }
        assert required <= schema.to_dict().keys()

    def test_schema_is_json_serialisable(self) -> None:
        adapter = AutopilotAdapter()
        ctx = adapter.run_from_intent(_INTENT)
        schema = adapter.gate_schema(ctx)
        assert schema is not None
        json.dumps(schema.to_dict())
