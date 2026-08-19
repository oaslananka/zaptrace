"""Tests for synthesis explainability framework."""

from __future__ import annotations

from zaptrace.synthesis.explain import SynthesisDecision, SynthesisDecisionLog, format_decision_log_as_markdown


class TestSynthesisDecision:
    def test_minimal_decision(self) -> None:
        d = SynthesisDecision(category="value", parameter="R1", value="330 Ω")
        assert d.category == "value"
        assert d.confidence == 1.0

    def test_full_decision(self) -> None:
        d = SynthesisDecision(
            category="topology",
            parameter="3.3V rail",
            value="buck converter",
            rationale="drop 5V -> 3.3V at 500 mA exceeds LDO dissipation limit",
            calculator="plan_power_tree",
            citations=["TLV62569 datasheet §8.2"],
            confidence=0.95,
        )
        assert d.calculator == "plan_power_tree"
        assert len(d.citations) == 1

    def test_to_dict(self) -> None:
        d = SynthesisDecision(category="value", parameter="C1", value="100 nF")
        data = d.to_dict()
        assert data["category"] == "value"
        assert data["value"] == "100 nF"


class TestSynthesisDecisionLog:
    def test_empty_log(self) -> None:
        log = SynthesisDecisionLog()
        assert len(log.decisions) == 0
        assert log.summary() == "0 synthesis decisions: "

    def test_record(self) -> None:
        log = SynthesisDecisionLog()
        log.record("value", "LED R1", "330 Ω", rationale="(5 - 2)/0.01 = 300 Ω, snapped to E24")
        assert len(log.decisions) == 1
        assert log.decisions[0].category == "value"

    def test_multiple_categories(self) -> None:
        log = SynthesisDecisionLog()
        log.record("topology", "5V rail", "buck", rationale="heat")
        log.record("value", "L1", "10 μH", rationale="buck calculator")
        log.record("protection", "USB", "TVS", rationale="ESD protection")
        assert len(log.decisions) == 3
        assert len(log.by_category("topology")) == 1
        assert len(log.by_category("value")) == 1

    def test_summary(self) -> None:
        log = SynthesisDecisionLog()
        log.record("topology", "a", "b")
        log.record("value", "c", "d")
        log.record("value", "e", "f")
        summary = log.summary()
        assert "3 synthesis decisions" in summary
        assert "1 topology" in summary
        assert "2 value" in summary

    def test_markdown_output(self) -> None:
        log = SynthesisDecisionLog()
        log.record(
            "value", "LED R1", "330 Ω", rationale="Standard current-limiting resistor", calculator="led_series_resistor"
        )
        md = format_decision_log_as_markdown(log)
        assert "Synthesis Decision Log" in md
        assert "LED R1" in md
        assert "330 Ω" in md
        assert "led_series_resistor" in md

    def test_empty_markdown(self) -> None:
        log = SynthesisDecisionLog()
        md = format_decision_log_as_markdown(log)
        assert "No synthesis decisions recorded" in md
