"""Tests for design synthesis engine."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import zaptrace.synthesis.engine as engine_mod
from zaptrace.core.exceptions import SynthesisError
from zaptrace.synthesis.engine import (
    SYNTHESIS_METHOD,
    TemplateSelection,
    list_templates,
    synthesize,
    synthesize_with_provenance,
)

_MALFORMED_YAML = "meta: {name: [unclosed"


class TestSynthesize:
    def test_synthesize_matches_existing(self) -> None:
        """Should match 'esp32 i2c sensor' to ESP32 I2C Sensor template."""
        design = synthesize("esp32 i2c sensor")
        assert design is not None
        assert design.meta.name != ""

    def test_synthesize_ble_node(self) -> None:
        design = synthesize("nrf52840 ble sensor node")
        assert design is not None

    def test_synthesize_unknown_intent_raises(self) -> None:
        with pytest.raises(SynthesisError):
            synthesize("zzz_nonexistent_xyz_technology")

    def test_synthesize_stm32_rs485(self) -> None:
        design = synthesize("stm32 rs485 modbus industrial")
        assert design is not None

    def test_synthesize_usb_hid(self) -> None:
        design = synthesize("rp2040 usb hid keyboard")
        assert design is not None

    def test_synthesize_lora_gateway(self) -> None:
        design = synthesize("esp32 lora gateway")
        assert design is not None

    def test_synthesize_power_monitor(self) -> None:
        design = synthesize("esp32 power monitor i2c")
        assert design is not None

    def test_synthesize_motor_driver(self) -> None:
        design = synthesize("rp2040 motor driver brushless")
        assert design is not None


class TestTemplateSelectionProvenance:
    """Synthesis must self-describe as template selection, with traceable provenance."""

    def test_provenance_identifies_selected_template(self) -> None:
        design, selection = synthesize_with_provenance("esp32 i2c sensor")
        assert isinstance(selection, TemplateSelection)
        assert selection.template_id == "esp32_i2c_sensor"
        assert selection.template_name == design.meta.name
        assert selection.match_score > 0

    def test_method_is_template_selection_not_synthesis(self) -> None:
        _, selection = synthesize_with_provenance("rp2040 usb hid keyboard")
        # The honest label must not overclaim from-scratch synthesis.
        assert selection.method == SYNTHESIS_METHOD == "template_selection"

    def test_unknown_intent_raises(self) -> None:
        with pytest.raises(SynthesisError):
            synthesize_with_provenance("zzz_nonexistent_xyz_technology")

    def test_synthesize_is_provenance_design(self) -> None:
        # Backward-compatible synthesize() returns the same design as the
        # provenance-aware variant.
        design = synthesize("esp32 i2c sensor")
        design2, _ = synthesize_with_provenance("esp32 i2c sensor")
        assert design.meta.name == design2.meta.name

    def test_tool_reports_template_selection(self) -> None:
        from zaptrace.agent._tool_impls import tool_synthesize_design

        result = tool_synthesize_design("esp32 i2c sensor")
        assert result["method"] == "template_selection"
        assert result["selection"]["template_id"] == "esp32_i2c_sensor"
        assert result["selection"]["match_score"] > 0
        assert "not from-scratch" in result["note"]


class TestListTemplates:
    def test_templates_returned(self) -> None:
        templates = list_templates()
        assert len(templates) >= 8  # at least 8 templates expected
        for t in templates:
            assert "id" in t
            assert "name" in t

    def test_template_has_tags(self) -> None:
        templates = list_templates()
        for t in templates:
            assert isinstance(t.get("tags", []), list)


class TestUnparseableTemplatesSurface:
    """A malformed template must be logged (not silently swallowed)."""

    def test_synthesize_logs_and_skips_unparseable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
    ) -> None:
        # A valid template the intent matches, plus a malformed one alongside it.
        valid = (engine_mod.TEMPLATES_DIR / "attiny85_io.yaml").read_text()
        (tmp_path / "attiny85_io.yaml").write_text(valid)
        (tmp_path / "broken_attiny.yaml").write_text(_MALFORMED_YAML)
        monkeypatch.setattr(engine_mod, "TEMPLATES_DIR", tmp_path)

        with caplog.at_level(logging.WARNING, logger="zaptrace.synthesis.engine"):
            design = synthesize("attiny85 io")

        assert design is not None
        assert any("Skipping unparseable template" in r.message for r in caplog.records)

    def test_list_templates_logs_unparseable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "broken.yaml").write_text(_MALFORMED_YAML)
        monkeypatch.setattr(engine_mod, "TEMPLATES_DIR", tmp_path)

        with caplog.at_level(logging.WARNING, logger="zaptrace.synthesis.engine"):
            templates = list_templates()

        assert {"id": "broken", "name": "broken"} in templates
        assert any("failed to load for listing" in r.message for r in caplog.records)
