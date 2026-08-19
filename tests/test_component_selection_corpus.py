from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from zaptrace.library.loader import LibraryLoader
from zaptrace.library.selection import ComponentSelectionRequirement, select_component

CORPUS_PATH = Path("tests/fixtures/component_selection/prompts.yaml")


def _cases() -> list[dict[str, object]]:
    payload = yaml.safe_load(CORPUS_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    return payload


def test_component_selection_corpus_has_twenty_representative_prompts() -> None:
    cases = _cases()

    assert len(cases) == 20
    assert len({str(case["id"]) for case in cases}) == 20
    assert len({str(case["category"]) for case in cases}) >= 10


@pytest.mark.parametrize("case", _cases())
def test_component_selection_corpus_is_deterministic_and_explainable(case: dict[str, object]) -> None:
    specs = LibraryLoader().load_all()
    candidate_ids = [str(item) for item in case["candidate_ids"]]  # type: ignore[index]
    candidates = [specs[component_id] for component_id in candidate_ids]
    requirement = ComponentSelectionRequirement.model_validate(
        {
            "requirement_id": case["id"],
            "position": case["position"],
            "category": case["category"],
            "allowed_packages": case.get("allowed_packages", []),
            "required_footprint": case.get("required_footprint", ""),
        }
    )

    first = select_component(requirement, candidates)
    second = select_component(requirement, list(reversed(candidates)))

    assert first.blocked is bool(case.get("expected_blocked", False))
    assert first.selected_component_id == str(case.get("expected_selected_id", ""))
    assert first.decision_hash == second.decision_hash
    assert first.rationale
    assert all(item.score_dimensions for item in first.assessments)
    assert all(len(item.assessment_hash) == 64 for item in first.assessments)
