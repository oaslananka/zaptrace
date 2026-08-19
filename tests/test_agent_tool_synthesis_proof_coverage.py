"""Behavior coverage for synthesis and proof agent tool domains."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from zaptrace.agent import _tool_impls as facade
from zaptrace.agent.tool_impls import proof as proof_tools
from zaptrace.agent.tool_impls import synthesis as synthesis_tools
from zaptrace.core.parser import parse_str
from zaptrace.erc.models import ERCResult, ERCSeverity, ERCViolation

_DESIGN_YAML = """meta:
  name: SynthesisCoverage
components:
  r1:
    ref: R1
    type: resistor
    value: 10k
board:
  width_mm: 50
  height_mm: 40
  layers: 2
"""


def setup_function() -> None:
    facade._sessions.clear()


def _object(**values: Any) -> Any:
    return SimpleNamespace(**values)


def _design() -> Any:
    return parse_str(_DESIGN_YAML)


def _seed(session_id: str = "synthesis") -> Any:
    design = _design()
    facade._get_session(session_id)["designs"][design.meta.name] = design
    return design


def test_requirement_power_and_board_planning_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    from zaptrace.synthesis import architecture, power_tree, requirements

    parsed = _object(id="requirements")
    monkeypatch.setattr(requirements, "parse_requirements", lambda intent: parsed)
    monkeypatch.setattr(
        requirements,
        "review_assumptions",
        lambda received, approvals=None: {
            "same_requirements": received is parsed,
            "approvals": approvals,
        },
    )
    monkeypatch.setattr(
        power_tree,
        "plan_power_tree",
        lambda received: {"same_requirements": received is parsed, "stages": []},
    )
    monkeypatch.setattr(
        architecture,
        "plan_architecture",
        lambda received: _object(to_dict=lambda: {"same_requirements": received is parsed}),
    )

    review = synthesis_tools.tool_requirements_review("demo", {"voltage": "approved"})
    assert review["review"] == {
        "same_requirements": True,
        "approvals": {"voltage": "approved"},
    }
    assert synthesis_tools.tool_power_tree_plan("demo")["power_tree"]["same_requirements"] is True
    assert synthesis_tools.tool_board_plan("demo")["architecture"]["same_requirements"] is True


def test_synthesize_board_and_checked_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from zaptrace.synthesis import architecture, requirements

    design = _design()
    parsed = _object(id="requirements")
    plan = _object(
        unrealized_blocks=[_object(block_id="unrealized")],
        unmet=[_object(block_id="sensor", token="missing-part")],
    )
    decision_log = _object(to_dicts=lambda: [{"decision": "selected"}])
    monkeypatch.setattr(requirements, "parse_requirements", lambda intent: parsed)
    monkeypatch.setattr(
        architecture,
        "build_architecture_design",
        lambda received: (design, plan, decision_log) if received is parsed else None,
    )

    synthesized = synthesis_tools.tool_synthesize_board("demo", session_id="board")
    assert synthesized["design_name"] == "SynthesisCoverage"
    assert synthesized["unrealized_blocks"] == ["unrealized"]
    assert synthesized["unmet_requirements"] == [{"block_id": "sensor", "token": "missing-part"}]
    assert synthesized["decisions"] == [{"decision": "selected"}]

    warning = ERCViolation(
        rule_id="COVERAGE",
        severity=ERCSeverity.WARNING,
        message="review",
    )
    erc_result = ERCResult.from_violations([warning], design.meta.name)

    class Runner:
        def run(self, received: Any) -> ERCResult:
            assert received is design
            return erc_result

    monkeypatch.setattr(synthesis_tools, "_get_erc_runner_type", lambda: Runner)
    checked = synthesis_tools.tool_synthesize_board_and_check("demo", session_id="board-checked")
    assert checked["erc"]["passed"] is True
    assert checked["erc"]["total_warnings"] == 1
    assert checked["erc"]["violations"] == [{"rule_id": "COVERAGE", "severity": "warning", "message": "review"}]
    assert facade._get_session("board-checked")["erc_results"][design.meta.name] is erc_result


def test_repair_footprint_bias_simulation_and_benchmark_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zaptrace.analysis import dc_bias, sim_gate
    from zaptrace.synthesis import benchmark, footprint_resolver, repair

    design = _design()
    patch = _object(to_dict=lambda: {"kind": "footprint"})
    repair_result = _object(
        converged=True,
        fully_clean=False,
        patches=[patch],
        remaining=[{"rule": "manual-review"}],
    )
    plan = _object(unrealized_blocks=[_object(block_id="rf")])
    footprints = _object(to_dict=lambda: {"resolved": 1, "unresolved": 0})
    monkeypatch.setattr(
        repair,
        "synthesize_and_repair",
        lambda intent: {
            "design": design,
            "plan": plan,
            "repair": repair_result,
            "footprints": footprints,
        },
    )

    repaired = synthesis_tools.tool_synthesize_board_repair("demo", session_id="repair")
    assert repaired["converged"] is True
    assert repaired["fully_clean"] is False
    assert repaired["patches"] == [{"kind": "footprint"}]
    assert repaired["unrealized_blocks"] == ["rf"]
    assert repaired["footprints"] == {"resolved": 1, "unresolved": 0}

    stored = _seed("analysis")
    monkeypatch.setattr(
        footprint_resolver,
        "resolve_footprints",
        lambda received: _object(to_dict=lambda: {"same_design": received is stored}),
    )
    monkeypatch.setattr(
        dc_bias,
        "resolve_dc_bias",
        lambda received: _object(to_dict=lambda: {"same_design": received is stored}),
    )
    monkeypatch.setattr(
        sim_gate,
        "run_simulation_gate",
        lambda received, strict: _object(to_dict=lambda: {"same_design": received is stored, "strict": strict}),
    )
    monkeypatch.setattr(
        benchmark,
        "run_benchmark",
        lambda: _object(to_dict=lambda: {"mean_score": 91.0}),
    )

    assert synthesis_tools.tool_resolve_footprints("SynthesisCoverage", session_id="analysis")["same_design"] is True
    assert synthesis_tools.tool_dc_bias_check("SynthesisCoverage", session_id="analysis")["same_design"] is True
    simulation = synthesis_tools.tool_simulation_gate("SynthesisCoverage", strict=True, session_id="analysis")
    assert simulation["same_design"] is True
    assert simulation["strict"] is True
    assert synthesis_tools.tool_synthesis_benchmark() == {"mean_score": 91.0}

    for tool in (
        synthesis_tools.tool_resolve_footprints,
        synthesis_tools.tool_dc_bias_check,
        synthesis_tools.tool_simulation_gate,
    ):
        with pytest.raises(ValueError, match="not found"):
            tool("missing", session_id="analysis")


def test_board_score_adapter_uses_repair_bias_and_scorecard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zaptrace.analysis import dc_bias
    from zaptrace.synthesis import repair, scorecard

    design = _design()
    plan = _object()
    repair_result = _object()
    footprints = _object()
    bias = _object()
    card = _object(to_dict=lambda: {"score": 88, "status": "review"})
    monkeypatch.setattr(
        repair,
        "synthesize_and_repair",
        lambda intent: {
            "design": design,
            "plan": plan,
            "repair": repair_result,
            "footprints": footprints,
        },
    )
    monkeypatch.setattr(dc_bias, "resolve_dc_bias", lambda received: bias)

    def score_board(
        received_design: Any,
        received_plan: Any,
        received_repair: Any,
        received_footprints: Any,
        received_bias: Any,
    ) -> Any:
        assert (
            received_design,
            received_plan,
            received_repair,
            received_footprints,
            received_bias,
        ) == (design, plan, repair_result, footprints, bias)
        return card

    monkeypatch.setattr(scorecard, "score_board", score_board)
    result = synthesis_tools.tool_synthesize_board_score("demo", session_id="score")
    assert result == {
        "intent": "demo",
        "design_name": "SynthesisCoverage",
        "component_count": 1,
        "score": 88,
        "status": "review",
    }
    assert facade._get_session("score")["designs"][design.meta.name] is design


class _CheckDefinition:
    def __init__(self, **values: Any) -> None:
        self.values = values


class _ProofResult:
    def __init__(self, name: str, passed: bool, status: str = "pass") -> None:
        self.name = name
        self.passed = passed
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "status": self.status}


class _ProofRunner:
    def __init__(self, design: Any) -> None:
        self.design = design

    def run_checks(self, checks: list[_CheckDefinition]) -> list[_ProofResult]:
        assert self.design.meta.name == "SynthesisCoverage"
        assert checks
        return [
            _ProofResult("passing", True),
            _ProofResult("failing", False, "fail"),
            _ProofResult("skipped", False, "skip"),
        ]


def test_proof_run_design_default_custom_and_missing_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zaptrace.proof as proof_package

    _seed("proof")
    monkeypatch.setattr(proof_package, "CheckDefinition", _CheckDefinition)
    monkeypatch.setattr(proof_package, "ProofRunner", _ProofRunner)

    default = proof_tools.tool_proof_run_design("SynthesisCoverage", session_id="proof")
    assert default["passed"] is False
    assert default["total"] == 3
    assert default["passed_count"] == 1
    assert default["failed_count"] == 1

    custom = proof_tools.tool_proof_run_design(
        "SynthesisCoverage",
        checks=[{"name": "custom", "type": "routed", "description": "Custom"}],
        session_id="proof",
    )
    assert custom["results"][0]["name"] == "passing"

    with pytest.raises(ValueError, match="not found"):
        proof_tools.tool_proof_run_design("missing", session_id="proof")


def test_proof_list_checks_supports_directory_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zaptrace.proof as proof_package

    proof_file = tmp_path / "proof.yaml"
    proof_file.write_text("name: demo\n", encoding="utf-8")
    check = _object(
        name="routing",
        type="routed",
        severity=_object(value="error"),
        description="All nets routed",
        category=_object(value="routing"),
    )
    manifest = _object(
        name="Demo Pack",
        description="Coverage pack",
        version="1.0",
        design_path="design.yaml",
        checks=[check],
        model=_object(model_dump=lambda: {"min_clearance_mm": 0.2}),
    )
    pack = _object(manifest=manifest)

    monkeypatch.setattr(
        proof_tools,
        "_validate_path",
        lambda path, must_exist=False: Path(path),
    )
    monkeypatch.setattr(
        proof_package.ProofPack,
        "load",
        lambda path: pack if Path(path) == proof_file else None,
    )

    result = proof_tools.tool_proof_list_checks(str(tmp_path))
    assert result["name"] == "Demo Pack"
    assert result["checks"] == [
        {
            "name": "routing",
            "type": "routed",
            "severity": "error",
            "description": "All nets routed",
            "category": "routing",
        }
    ]
    assert result["constraints"] == {"min_clearance_mm": 0.2}
