"""Regression coverage for strict simulation-gate skip reasons."""

import pytest

from zaptrace.analysis.sim_gate import (
    AcReference,
    TransientReference,
    _gate_verdict,
    run_ac_gate,
    run_transient_gate,
)
from zaptrace.analysis.spice_sim import AcResult, TransientResult


@pytest.mark.parametrize("gate_kind", ["dc", "transient", "ac"])
def test_strict_skip_reasons_share_the_same_blocking_suffix(
    gate_kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if gate_kind == "dc":
        reason = _gate_verdict("skipped", all_checks_passed=True, has_checks=False, strict=True)[2]
    elif gate_kind == "transient":
        monkeypatch.setattr(
            "zaptrace.analysis.spice_sim.run_transient",
            lambda *_args, **_kwargs: TransientResult(status="skipped", reason="not installed"),
        )
        reason = run_transient_gate(
            "* test\n.end\n",
            TransientReference(node="vout", target_v=3.3),
            strict=True,
        ).reason
    else:
        monkeypatch.setattr(
            "zaptrace.analysis.spice_sim.run_ac",
            lambda *_args, **_kwargs: AcResult(status="skipped", node="vout", reason="not installed"),
        )
        reason = run_ac_gate(
            "* test\n.end\n",
            AcReference(node="vout"),
            strict=True,
        ).reason

    assert reason.endswith(" (blocking in strict mode)")
