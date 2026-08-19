from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from zaptrace.generation import (
    architecture_traceability_report_json,
    build_architecture_traceability_report,
    compile_electronics_intent_to_architecture,
    electronics_architecture_artifact_json,
)

CORPUS_PATH = Path("tests/fixtures/architecture/prompts.yaml")


def _cases() -> list[dict[str, Any]]:
    payload = yaml.safe_load(CORPUS_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    return payload


@pytest.mark.parametrize("case", _cases(), ids=lambda case: str(case["id"]))
def test_architecture_compiler_corpus_is_deterministic(case: dict[str, Any]) -> None:
    first = compile_electronics_intent_to_architecture(case["intent"], design_name=case["id"])
    second = compile_electronics_intent_to_architecture(case["intent"], design_name=case["id"])

    first_artifact_json = electronics_architecture_artifact_json(first)
    second_artifact_json = electronics_architecture_artifact_json(second)
    first_trace_json = architecture_traceability_report_json(build_architecture_traceability_report(first))
    second_trace_json = architecture_traceability_report_json(build_architecture_traceability_report(second))

    assert first_artifact_json == second_artifact_json
    assert first_trace_json == second_trace_json
    assert first.status.value == case["expected_status"]
    assert {item.id for item in first.subsystems} == set(case["expected_subsystems"])
    assert {item.name for item in first.interfaces} == set(case["expected_interfaces"])
    assert {item.net_name for item in first.power_tree} == set(case["expected_rails"])
    assert {item.code for item in first.conflicts} == set(case["expected_conflicts"])

    report = build_architecture_traceability_report(first)
    if case["expected_status"] == "ready":
        assert report.blocked is False
        assert report.fully_traced is True
        assert report.uncovered_requirement_ids == []
        assert report.untraced_elements == []
    else:
        assert report.blocked is True
        assert report.human_review_required is True
