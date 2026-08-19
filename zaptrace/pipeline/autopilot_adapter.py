"""Autopilot adapter: routes entry points through the multi-domain loop (issue #116).

This module provides a thin adapter layer so that existing Autopilot entry
points (CLI, API, SDK, MCP) transparently delegate to ``run_multi_domain_loop``
without maintaining a second orchestration sequence.

Public surface
--------------
AutopilotAdapter          – wraps an Autopilot instance; overrides the three
                            entry points to call the multi-domain loop instead
adapt_autopilot()         – functional adapter; returns an AutopilotAdapter
LoopGateSchema            – canonical gate and evidence schema emitted by all
                            callers (CLI, API, SDK, MCP)
gate_schema_from_result() – produces LoopGateSchema from a LoopResult

Interface compatibility
-----------------------
``AutopilotAdapter`` is a drop-in for ``Autopilot``; every public method that
exists on ``Autopilot`` is delegated.  New behaviour is added via three
overridden entry points:

  * ``run_from_intent``  → delegates to ``run_multi_domain_loop()``
  * ``run_from_design``  → delegates to ``run_multi_domain_loop()`` (via design
                           intent extracted from ``design.meta.description``)
  * ``run_from_file``    → parses the file first (via the wrapped Autopilot),
                           then delegates to ``run_multi_domain_loop()``

All three return a ``PipelineContext`` that is backward-compatible with
existing callers; the full ``LoopResult`` is attached under
``ctx.synthesis["loop_result"]`` for callers that need stage gates and
repair ledgers.

Cancellation and timeout
------------------------
``run_from_intent_with_timeout()`` wraps the adapter entry point in a
``concurrent.futures.ThreadPoolExecutor`` and raises
``AutopilotTimeoutError`` if the loop does not complete in time.
``PartialLoopResult`` is returned in the exception for artifact recovery.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from zaptrace.pipeline.autopilot import Autopilot, PipelineContext, PipelineStage, StageResult
from zaptrace.pipeline.multi_domain_loop import LoopResult, run_multi_domain_loop

# ---------------------------------------------------------------------------
# Canonical gate-and-evidence schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoopGateSchema:
    """Canonical evidence record emitted by all entry points (CLI, API, MCP).

    All fields are serialisable to JSON/dict — this is the contract that the
    MCP documentation generator uses.
    """

    design_name: str
    intent: str
    converged: bool
    blocking_stage: str | None
    erc_violations_remaining: int
    stage_statuses: dict[str, str]
    proof_pack_hash: str | None
    total_duration_s: float
    ledger: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "design_name": self.design_name,
            "intent": self.intent,
            "converged": self.converged,
            "blocking_stage": self.blocking_stage,
            "erc_violations_remaining": self.erc_violations_remaining,
            "stage_statuses": self.stage_statuses,
            "proof_pack_hash": self.proof_pack_hash,
            "total_duration_s": round(self.total_duration_s, 4),
            "ledger": self.ledger,
        }


def gate_schema_from_result(result: LoopResult) -> LoopGateSchema:
    """Build a ``LoopGateSchema`` from a ``LoopResult``."""
    return LoopGateSchema(
        design_name=result.design_name,
        intent=result.intent,
        converged=result.converged,
        blocking_stage=result.blocking_stage,
        erc_violations_remaining=result.erc_violations_remaining,
        stage_statuses=result.stage_statuses,
        proof_pack_hash=(result.proof_pack.pack_hash if result.proof_pack else None),
        total_duration_s=result.total_duration_s,
        ledger=[e.to_dict() for e in result.ledger],
    )


# ---------------------------------------------------------------------------
# Timeout error / partial result
# ---------------------------------------------------------------------------


@dataclass
class PartialLoopResult:
    """Artifact record for a loop that did not complete before the deadline."""

    intent: str
    elapsed_s: float
    stages_completed: list[str] = field(default_factory=list)


class AutopilotTimeoutError(TimeoutError):
    """Raised when ``run_from_intent_with_timeout`` exceeds its deadline."""

    def __init__(self, message: str, partial: PartialLoopResult) -> None:
        super().__init__(message)
        self.partial = partial


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class AutopilotAdapter:
    """Thin adapter: delegates to the multi-domain loop instead of the old
    stage sequence.

    ``AutopilotAdapter`` is a drop-in for ``Autopilot``; all public methods
    that exist on ``Autopilot`` are forwarded.

    Parameters
    ----------
    autopilot:
        The wrapped ``Autopilot`` instance used for file parsing and as a
        fallback for any non-overridden methods.
    max_erc_iterations:
        Maximum ERC repair iterations passed to ``run_multi_domain_loop``.
    max_drc_iterations:
        Maximum DRC repair iterations passed to ``run_multi_domain_loop``.
    """

    def __init__(
        self,
        autopilot: Autopilot | None = None,
        *,
        max_erc_iterations: int = 5,
        max_drc_iterations: int = 3,
    ) -> None:
        self._wrapped = autopilot or Autopilot()
        self._max_erc_iterations = max_erc_iterations
        self._max_drc_iterations = max_drc_iterations

    # ------------------------------------------------------------------
    # Overridden entry points — delegate to multi-domain loop
    # ------------------------------------------------------------------

    def run_from_intent(self, intent: str) -> PipelineContext:
        """Run the full multi-domain loop from a synthesis intent string.

        Returns a backward-compatible ``PipelineContext``; the ``LoopResult``
        is attached at ``ctx.synthesis["loop_result"]`` for callers that need
        stage gates and repair ledgers.
        """
        t0 = perf_counter()
        loop_result = run_multi_domain_loop(
            intent,
            max_erc_iterations=self._max_erc_iterations,
            max_drc_iterations=self._max_drc_iterations,
        )
        ctx = self._loop_result_to_context(loop_result, t0)
        return ctx

    def run_from_design(self, design: object) -> PipelineContext:
        """Run the multi-domain loop from an existing Design object.

        The intent is extracted from ``design.meta.description`` when
        present; otherwise the design name is used as a fallback.
        """
        t0 = perf_counter()
        # Extract intent from design metadata
        meta = getattr(design, "meta", None)
        intent: str = ""
        if meta is not None:
            intent = getattr(meta, "description", "") or getattr(meta, "name", "") or ""
        if not intent:
            intent = str(design)

        loop_result = run_multi_domain_loop(
            intent,
            max_erc_iterations=self._max_erc_iterations,
            max_drc_iterations=self._max_drc_iterations,
        )
        ctx = self._loop_result_to_context(loop_result, t0)
        return ctx

    def run_from_file(self, path: str) -> PipelineContext:
        """Parse a design file, then run the multi-domain loop.

        The wrapped Autopilot is used to parse the file.  The loaded design
        is then passed to ``run_from_design``.
        """
        t0 = perf_counter()
        parse_ctx = self._wrapped.run_from_file(path)
        ctx = self.run_from_design(parse_ctx.design) if parse_ctx.design is not None else parse_ctx
        ctx.started_at = parse_ctx.started_at
        ctx.started_monotonic = t0
        return ctx

    # ------------------------------------------------------------------
    # Timeout-aware entry point
    # ------------------------------------------------------------------

    def run_from_intent_with_timeout(
        self,
        intent: str,
        timeout_s: float,
    ) -> tuple[PipelineContext, LoopGateSchema]:
        """Run the multi-domain loop with a hard timeout.

        Parameters
        ----------
        intent:
            Synthesis intent string.
        timeout_s:
            Maximum wall-clock seconds allowed.

        Returns
        -------
        tuple[PipelineContext, LoopGateSchema]
            Both a backward-compatible context and the canonical gate schema.

        Raises
        ------
        AutopilotTimeoutError
            When the loop does not complete before *timeout_s*.  The
            ``partial`` attribute on the exception contains a
            ``PartialLoopResult`` for artifact recovery.
        """
        t0 = perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.run_from_intent, intent)
            try:
                ctx = future.result(timeout=timeout_s)
            except concurrent.futures.TimeoutError:
                elapsed = perf_counter() - t0
                raise AutopilotTimeoutError(
                    f"multi-domain loop did not complete within {timeout_s:.1f}s",
                    partial=PartialLoopResult(intent=intent, elapsed_s=elapsed),
                ) from None

        loop_result: LoopResult | None = (ctx.synthesis or {}).get("loop_result")
        schema = gate_schema_from_result(loop_result) if loop_result else _empty_gate_schema(intent)
        return ctx, schema

    # ------------------------------------------------------------------
    # Gate schema accessor (no side effects)
    # ------------------------------------------------------------------

    def gate_schema(self, ctx: PipelineContext) -> LoopGateSchema | None:
        """Extract the canonical gate schema from a pipeline context, if present."""
        synthesis = ctx.synthesis or {}
        loop_result: LoopResult | None = synthesis.get("loop_result")
        if loop_result is None:
            return None
        return gate_schema_from_result(loop_result)

    # ------------------------------------------------------------------
    # Forward all other methods to the wrapped Autopilot
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _loop_result_to_context(self, loop_result: LoopResult, t0: float) -> PipelineContext:
        """Convert a ``LoopResult`` into a backward-compatible ``PipelineContext``."""
        now = datetime.now(UTC)
        t1 = perf_counter()

        ctx = PipelineContext(
            source=loop_result.intent,
            synthesis={"loop_result": loop_result},
            output_dir=self._wrapped._output_dir,  # noqa: SLF001
            started_at=now,
            started_monotonic=t0,
            finished_monotonic=t1,
        )
        ctx.finished_at = now

        # Translate converged/blocking into a synthetic stage result
        synth_success = loop_result.converged or loop_result.blocking_stage != "synthesis"
        ctx.results[PipelineStage.SYNTHESIZE] = StageResult(
            stage=PipelineStage.SYNTHESIZE,
            success=synth_success,
            data=loop_result.to_dict(),
        )

        # Surface BOM and report from proof pack when available
        if loop_result.proof_pack is not None:
            ctx.bom_csv = loop_result.proof_pack.artifacts.get("bom_csv")
            ctx.report = loop_result.proof_pack.artifacts.get("report")
            ctx.svg = loop_result.proof_pack.artifacts.get("svg")

        return ctx


# ---------------------------------------------------------------------------
# Functional helper
# ---------------------------------------------------------------------------


def adapt_autopilot(
    autopilot: Autopilot | None = None,
    *,
    max_erc_iterations: int = 5,
    max_drc_iterations: int = 3,
) -> AutopilotAdapter:
    """Return an ``AutopilotAdapter`` wrapping *autopilot* (or a fresh one)."""
    return AutopilotAdapter(
        autopilot,
        max_erc_iterations=max_erc_iterations,
        max_drc_iterations=max_drc_iterations,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _empty_gate_schema(intent: str) -> LoopGateSchema:
    return LoopGateSchema(
        design_name="",
        intent=intent,
        converged=False,
        blocking_stage=None,
        erc_violations_remaining=0,
        stage_statuses={},
        proof_pack_hash=None,
        total_duration_s=0.0,
        ledger=[],
    )
