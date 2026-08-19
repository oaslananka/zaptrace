"""Synthesis explainability framework.

Every decision in the synthesis pipeline — which topology, which component value,
which protection part — should carry an explanation that cites the datasheet,
the calculator function, or the design rule that drove it.

This module provides a lightweight decision-log data structure and helpers so
that any synthesis step can record *why* a choice was made, giving human
reviewers (and agent auditors) a traceable answer to "why this part/value/connection?"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SynthesisDecision:
    """A single explainable decision made during synthesis.

    ``category`` groups related decisions (e.g. ``"topology"``, ``"value"``,
    ``"protection"``, ``"testpoint"``). ``rationale`` is free-form prose that
    a human reviewer can read. ``citations`` reference datasheet URLs, calculator
    function names, or design-guide rules — the more specific, the more trust
    the reviewer can place in the decision.
    """

    category: str
    parameter: str = ""  # what was decided (e.g. "LED R1 value", "buck inductor")
    value: str = ""  # what was chosen (e.g. "330 Ω", "10 μH")
    rationale: str = ""
    citations: list[str] = field(default_factory=list)
    calculator: str = ""  # e.g. "led_series_resistor", "buck_inductor_capacitor"
    confidence: float = 1.0  # 0.0 = guess, 1.0 = exact calculation

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SynthesisDecisionLog:
    """Collector for synthesis decisions, threaded through the pipeline.

    Usage::

        log = SynthesisDecisionLog()
        log.record("value", "LED R1", "330 Ω",
                   rationale="(5V - 2V) / 10 mA = 300 Ω ideal, snapped to E24 330 Ω",
                   calculator="led_series_resistor")
        log.record("topology", "3.3V rail", "buck converter",
                   rationale="drop 5V -> 3.3V at 500 mA dissipates 0.85 W > 0.5 W LDO limit",
                   calculator="plan_power_tree")
    """

    def __init__(self) -> None:
        self._decisions: list[SynthesisDecision] = []

    def record(
        self,
        category: str,
        parameter: str = "",
        value: str = "",
        *,
        rationale: str = "",
        citations: list[str] | None = None,
        calculator: str = "",
        confidence: float = 1.0,
    ) -> None:
        """Record a synthesis decision."""
        self._decisions.append(
            SynthesisDecision(
                category=category,
                parameter=parameter,
                value=value,
                rationale=rationale,
                citations=citations or [],
                calculator=calculator,
                confidence=confidence,
            )
        )

    @property
    def decisions(self) -> list[SynthesisDecision]:
        return list(self._decisions)

    def by_category(self, category: str) -> list[SynthesisDecision]:
        """Return all decisions in a given category."""
        return [d for d in self._decisions if d.category == category]

    def summary(self) -> str:
        """One-line summary."""
        counts: dict[str, int] = {}
        for d in self._decisions:
            counts[d.category] = counts.get(d.category, 0) + 1
        parts = [f"{count} {cat}" for cat, count in sorted(counts.items())]
        return f"{len(self._decisions)} synthesis decisions: {', '.join(parts)}"

    def to_dicts(self) -> list[dict[str, Any]]:
        return [d.to_dict() for d in self._decisions]


def format_decision_log_as_markdown(log: SynthesisDecisionLog) -> str:
    """Render the decision log as human-readable Markdown.

    Useful for inclusion in proof-pack reports or CLI output so a reviewer
    can see every decision the synthesis pipeline made.
    """
    if not log._decisions:
        return "*No synthesis decisions recorded.*"

    lines = ["## Synthesis Decision Log", ""]
    for i, decision in enumerate(log._decisions, 1):
        lines.append(f"### {i}. {decision.category}: {decision.parameter}")
        lines.append("")
        if decision.value:
            lines.append(f"- **Chosen value:** {decision.value}")
        if decision.rationale:
            lines.append(f"- **Rationale:** {decision.rationale}")
        if decision.calculator:
            lines.append(f"- **Calculator:** `{decision.calculator}()`")
        if decision.citations:
            for cite in decision.citations:
                lines.append(f"- **Citation:** {cite}")
        lines.append("")
    return "\n".join(lines)
