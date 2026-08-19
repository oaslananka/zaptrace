from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from zaptrace.generation.intent import (
    ArtifactPolicy,
    BoardGenerationIntent,
    board_generation_intent_json,
    load_board_generation_intent,
    minimal_board_generation_intent_example,
    validate_board_generation_intent,
)


def test_minimal_board_generation_intent_example_validates() -> None:
    intent = validate_board_generation_intent(minimal_board_generation_intent_example())

    assert intent.schema_version == "1.0"
    assert intent.family_id == "esp32_usb_sensor"
    assert intent.family_title() == "ESP32 USB sensor node"
    assert intent.artifact_policy.generate_kicad_project is True
    assert intent.artifact_policy.fabrication_claim_allowed is False
    assert "not fabrication-ready" in " ".join(intent.non_claims)
    assert any(requirement.release_blocking for requirement in intent.requirements)


def test_board_generation_intent_json_round_trip(tmp_path: Path) -> None:
    intent = BoardGenerationIntent.model_validate(minimal_board_generation_intent_example())
    payload = json.loads(board_generation_intent_json(intent))
    path = tmp_path / "intent.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_board_generation_intent(path)

    assert loaded == intent
    assert payload["target_output_dir"] == "generated/esp32_usb_sensor"


def test_board_generation_intent_rejects_unsupported_family() -> None:
    data = minimal_board_generation_intent_example()
    data["family_id"] = "unknown_family"

    with pytest.raises(ValidationError, match="unknown board family"):
        validate_board_generation_intent(data)


def test_board_generation_intent_rejects_unsafe_output_path() -> None:
    data = minimal_board_generation_intent_example()
    data["target_output_dir"] = "../outside"

    with pytest.raises(ValidationError, match="safe relative path"):
        validate_board_generation_intent(data)


def test_board_generation_intent_rejects_fabrication_claims() -> None:
    with pytest.raises(ValidationError, match="may not allow fabrication-ready claims"):
        ArtifactPolicy(fabrication_claim_allowed=True)


def test_board_generation_intent_requires_fabrication_non_claim() -> None:
    data = minimal_board_generation_intent_example()
    data["non_claims"] = ["engineering review only"]

    with pytest.raises(ValidationError, match="not fabrication-ready"):
        validate_board_generation_intent(data)


def test_board_generation_intent_requires_traceable_release_blocking_requirement() -> None:
    data = minimal_board_generation_intent_example()
    for requirement in data["requirements"]:
        requirement["release_blocking"] = False

    with pytest.raises(ValidationError, match="release-blocking requirement"):
        validate_board_generation_intent(data)


def test_board_generation_intent_requires_kicad_presence_when_generation_enabled() -> None:
    data = minimal_board_generation_intent_example()
    data["evidence"]["kicad_project_presence"] = False

    with pytest.raises(ValidationError, match="kicad_project_presence"):
        validate_board_generation_intent(data)
