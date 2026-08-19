"""Behavior coverage for domain-split agent tool implementations."""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from zaptrace.agent import _tool_impls as facade
from zaptrace.agent.tool_impls import design as design_tools
from zaptrace.agent.tool_impls import pipeline as pipeline_tools
from zaptrace.agent.tool_impls import routing as routing_tools
from zaptrace.core.models import NetClass
from zaptrace.core.parser import parse_str
from zaptrace.erc.models import ERCResult
from zaptrace.pipeline.autopilot import PipelineContext, PipelineStage, StageResult

_DESIGN_YAML = """meta:
  name: DomainCoverage
components:
  r1:
    ref: R1
    type: resistor
    value: 10k
  c1:
    ref: C1
    type: capacitor
    value: 100n
nets:
  signal:
    name: SIGNAL
    nodes:
      - R1.pin1
      - C1.pin1
  orphan_after_c1:
    name: C_ONLY
    nodes:
      - C1.pin2
board:
  width_mm: 50
  height_mm: 40
  layers: 2
"""


def setup_function() -> None:
    facade._sessions.clear()


def _seed(session_id: str = "domain") -> Any:
    design = parse_str(_DESIGN_YAML)
    session = facade._get_session(session_id)
    session["designs"][design.meta.name] = design
    return design


def test_design_domain_success_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "design.yaml"
    source.write_text(_DESIGN_YAML, encoding="utf-8")
    monkeypatch.setattr(design_tools, "_validate_path", lambda path, must_exist=False: Path(path))

    parsed = design_tools.tool_design_parse_file(str(source), session_id="design-file")
    assert parsed["design_name"] == "DomainCoverage"
    assert parsed["component_count"] == 2

    inspected = design_tools.tool_design_inspect("DomainCoverage", session_id="design-file")
    assert inspected["meta"]["name"] == "DomainCoverage"
    nets = design_tools.tool_design_list_nets("DomainCoverage", session_id="design-file")
    assert nets["nets"]["signal"]["nodes"][0]["component"] == "R1"

    original = facade._get_session("design-file")["designs"]["DomainCoverage"]
    modified = copy.deepcopy(original)
    modified.meta.name = "DomainCoverageModified"
    modified.board.width_mm = 75
    facade._get_session("design-file")["designs"][modified.meta.name] = modified
    diff = design_tools.tool_design_diff("DomainCoverage", modified.meta.name, session_id="design-file")
    assert diff["changed_count"] == 1
    assert "1 changed" in diff["summary"]

    board = design_tools.tool_board_update(
        "DomainCoverage", width_mm=60, height_mm=45, layers=4, session_id="design-file"
    )
    assert board == {"design": "DomainCoverage", "width_mm": 60, "height_mm": 45, "layers": 4}

    added = design_tools.tool_component_add(
        "DomainCoverage",
        component_id="",
        ref="U1",
        type_name="mcu",
        value="demo",
        footprint="QFN",
        session_id="design-file",
    )
    assert added["component_id"]
    removed = design_tools.tool_component_remove("DomainCoverage", "c1", session_id="design-file")
    assert removed["removed_orphan_nets"] == ["orphan_after_c1"]
    remaining = facade._get_session("design-file")["designs"]["DomainCoverage"]
    assert [node.component_ref for node in remaining.nets["signal"].nodes] == ["R1"]


def test_design_domain_error_paths() -> None:
    _seed()
    with pytest.raises(ValueError, match="Available"):
        design_tools.tool_design_inspect("missing", session_id="domain")
    with pytest.raises(ValueError, match="not found"):
        design_tools.tool_design_list_nets("missing", session_id="domain")
    with pytest.raises(ValueError, match="left.*not found"):
        design_tools.tool_design_diff("left", "DomainCoverage", session_id="domain")
    with pytest.raises(ValueError, match="right.*not found"):
        design_tools.tool_design_diff("DomainCoverage", "right", session_id="domain")
    with pytest.raises(ValueError, match="not found"):
        design_tools.tool_board_update("missing", session_id="domain")
    with pytest.raises(ValueError, match="not found"):
        design_tools.tool_component_add("missing", "x", "X1", "test", session_id="domain")
    with pytest.raises(ValueError, match="not in design"):
        design_tools.tool_component_remove("DomainCoverage", "missing", session_id="domain")


def test_routing_domain_success_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    design = _seed("routing")
    monkeypatch.setattr(
        "zaptrace.algo.placer.place_components",
        lambda _design: {"r1": (1.0, 2.0), "c1": (3.0, 4.0)},
    )
    placed = routing_tools.tool_place_components("DomainCoverage", session_id="routing")
    assert placed["positions"]["r1"] == [1.0, 2.0]

    route_result = SimpleNamespace(
        routed_nets=2,
        total_nets=2,
        coverage_pct=100.0,
        unrouted_nets=[],
        segments=[object(), object()],
    )
    monkeypatch.setattr("zaptrace.algo.router.route_nets", lambda _design, _positions: route_result)
    routed = routing_tools.tool_route_nets("DomainCoverage", session_id="routing")
    assert routed["segment_count"] == 2

    def classify(target: Any) -> None:
        target.net_classes = {net_id: NetClass.SIGNAL_LOW for net_id in target.nets}

    monkeypatch.setattr("zaptrace.ee.classifier.classify_design", classify)
    monkeypatch.setattr("zaptrace.ee.classifier.summarize_classification", lambda _design: {"signal_low": 2})
    monkeypatch.setattr("zaptrace.ee.classifier.get_net_class", lambda _design, _net_id: NetClass.SIGNAL_LOW)

    classified = routing_tools.tool_board_classify_nets("DomainCoverage", session_id="routing")
    assert classified["classification"] == {"signal_low": 2}
    exported = routing_tools.tool_board_export("DomainCoverage", session_id="routing")
    assert exported["board"]["width_mm"] == 50
    assert exported["board"]["min_clearance_mm"] == 0.2
    assert exported["board"]["min_trace_width_mm"] == 0.2
    summarized = routing_tools.tool_board_summarize_nets("DomainCoverage", session_id="routing")
    assert len(summarized["nets"]) == 2
    direct = routing_tools.tool_design_classify_nets("DomainCoverage", session_id="routing")
    assert direct["nets_classified"] == 2

    smart_routing = SimpleNamespace(routed_nets=2, total_nets=2, unrouted_nets=[], coverage_pct=100.0)
    trace_result = SimpleNamespace(total_trace_length_mm=12.5, traces=[object(), object()])
    monkeypatch.setattr("zaptrace.ee.knowledge.KnowledgeBase", lambda: object())
    monkeypatch.setattr(
        "zaptrace.algo.router.route_design_smart",
        lambda _design, _positions, kb, layer: (smart_routing, trace_result, {"kb": kb, "layer": layer}),
    )
    smart = routing_tools.tool_design_route_smart("DomainCoverage", layer="B.Cu", session_id="routing")
    assert smart["trace_count"] == 2
    assert smart["total_trace_length_mm"] == 12.5
    assert design.net_classes


def test_routing_domain_error_paths() -> None:
    _seed("routing-errors")
    facade._get_session("routing-errors")["positions"] = {}
    with pytest.raises(ValueError, match="not found"):
        routing_tools.tool_place_components("missing", session_id="routing-errors")
    with pytest.raises(ValueError, match="not found"):
        routing_tools.tool_route_nets("missing", session_id="routing-errors")
    with pytest.raises(ValueError, match="not found"):
        routing_tools.tool_board_classify_nets("missing", session_id="routing-errors")
    with pytest.raises(ValueError, match="not found"):
        routing_tools.tool_board_export("missing", session_id="routing-errors")
    with pytest.raises(ValueError, match="not found"):
        routing_tools.tool_board_summarize_nets("missing", session_id="routing-errors")
    with pytest.raises(ValueError, match="Run place_components first"):
        routing_tools.tool_design_route_smart("DomainCoverage", session_id="routing-errors")
    with pytest.raises(ValueError, match="not found"):
        routing_tools.tool_design_classify_nets("missing", session_id="routing-errors")


class _FakeAutopilot:
    def __init__(self, output_dir: str | Path | None = None) -> None:
        self._output_dir = Path(output_dir) if output_dir else Path(".")

    @staticmethod
    def _completed_context(source: str) -> PipelineContext:
        design = parse_str(_DESIGN_YAML)
        context = PipelineContext(
            design=design,
            source=source,
            erc_result=ERCResult.from_violations([], design.meta.name),
            started_monotonic=1.0,
            finished_monotonic=2.25,
        )
        context.results[PipelineStage.PARSE] = StageResult(PipelineStage.PARSE, True)
        return context

    def run_from_file(self, path: Path) -> PipelineContext:
        return self._completed_context(str(path))

    def run_from_intent(self, intent: str) -> PipelineContext:
        return self._completed_context(intent)

    def run_stage(self, context: PipelineContext, stage: PipelineStage) -> PipelineContext:
        context.results[stage] = StageResult(stage, True, duration_ms=3.5)
        return context


class _NoResultAutopilot(_FakeAutopilot):
    def run_stage(self, context: PipelineContext, stage: PipelineStage) -> PipelineContext:
        return context


def _patch_pipeline(monkeypatch: pytest.MonkeyPatch, autopilot_type: type[_FakeAutopilot] = _FakeAutopilot) -> None:
    monkeypatch.setattr(pipeline_tools, "Autopilot", autopilot_type)
    monkeypatch.setattr(pipeline_tools, "_get_autopilot", autopilot_type)
    monkeypatch.setattr(pipeline_tools, "_validate_path", lambda path, must_exist=False: Path(path))


def test_pipeline_run_and_status_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pipeline(monkeypatch)
    source = tmp_path / "source.yaml"
    source.write_text(_DESIGN_YAML, encoding="utf-8")

    from_file = pipeline_tools.tool_pipeline_run(
        source=str(source), output_dir=str(tmp_path / "out"), session_id="pipeline"
    )
    assert from_file["all_successful"] is True
    assert from_file["duration_seconds"] == 1.25
    assert "DomainCoverage" in facade._get_session("pipeline")["erc_results"]

    from_intent = pipeline_tools.tool_pipeline_run(intent="demo intent", session_id="pipeline-intent")
    assert from_intent["stages_completed"] == 1
    with pytest.raises(ValueError, match="Provide either"):
        pipeline_tools.tool_pipeline_run(session_id="pipeline")

    session = facade._get_session("pipeline")
    session["positions"] = {"DomainCoverage": {"r1": (1.0, 2.0)}}
    session["routing"] = {"DomainCoverage": object()}
    status = pipeline_tools.tool_pipeline_status("DomainCoverage", session_id="pipeline")
    assert status["stages_completed"] == ["parse/synthesize", "validate", "place", "route"]


def test_pipeline_run_stage_all_input_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pipeline(monkeypatch)
    _seed("stage")
    source = tmp_path / "source.yaml"
    source.write_text(_DESIGN_YAML, encoding="utf-8")

    by_design = pipeline_tools.tool_pipeline_run_stage("validate", design_name="DomainCoverage", session_id="stage")
    assert by_design == {"stage": "validate", "success": True, "error": None, "duration_ms": 3.5}
    assert pipeline_tools.tool_pipeline_run_stage("parse", source=str(source))["success"] is True
    assert pipeline_tools.tool_pipeline_run_stage("synthesize", intent="demo")["success"] is True
    with pytest.raises(ValueError, match="Provide one of"):
        pipeline_tools.tool_pipeline_run_stage("validate")

    _patch_pipeline(monkeypatch, _NoResultAutopilot)
    with pytest.raises(RuntimeError, match="did not produce a result"):
        pipeline_tools.tool_pipeline_run_stage("synthesize", intent="demo")


def test_pipeline_patch_suggestion_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    design = _seed("patches")
    session = facade._get_session("patches")
    with pytest.raises(ValueError, match="Design 'missing' not found"):
        pipeline_tools.tool_patch_suggest("missing", session_id="patches")
    with pytest.raises(ValueError, match="No ERC result"):
        pipeline_tools.tool_patch_suggest("DomainCoverage", session_id="patches")

    erc_result = SimpleNamespace(violations=[])
    session["erc_results"] = {"DomainCoverage": erc_result}
    monkeypatch.setattr(
        pipeline_tools,
        "suggest_patches",
        lambda received_design, received_result: [
            {"design": received_design.meta.name, "same_result": received_result is erc_result}
        ],
    )
    result = pipeline_tools.tool_patch_suggest("DomainCoverage", session_id="patches")
    assert result["patches"] == [{"design": design.meta.name, "same_result": True}]
