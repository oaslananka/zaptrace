"""Regression coverage for architecture fabrication-readiness non-claims."""

from zaptrace.generation.architecture import (
    compile_electronics_intent_to_architecture,
    convert_architecture_to_board_generation_intent,
)


def test_architecture_and_generation_intent_retain_fabrication_nonclaim() -> None:
    ready = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail"
    )
    vague = compile_electronics_intent_to_architecture("make a small board")
    intent = convert_architecture_to_board_generation_intent(ready)

    assert "not fabrication-ready" in ready.non_claims
    assert "not fabrication-ready" in vague.non_claims
    assert "not fabrication-ready" in intent.non_claims
