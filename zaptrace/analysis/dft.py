"""Design-for-test and bring-up analysis.

Looks at a design's testability *before* fabrication — whether power rails have
test points and whether there is a debug/programming and reset access path —
and produces a structured bring-up checklist, so a board can be powered up and
debugged without surprises.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from zaptrace.core.models import Design, NetType

_DEBUG_NET_TOKENS = ("swd", "swclk", "swdio", "jtag", "tck", "tms", "tdi", "tdo", "uart", "rxd", "txd")
_DEBUG_TYPE_TOKENS = ("swd", "jtag", "debug", "header", "tag-connect", "tagconnect")
_RESET_NET_TOKENS = ("reset", "nrst", "rst")


def _testpoint_refs(design: Design) -> set[str]:
    return {c.ref for c in design.components.values() if c.ref.upper().startswith("TP")}


def _nets_touched_by(design: Design, refs: set[str]) -> set[str]:
    touched: set[str] = set()
    for net in design.nets.values():
        if any(node.component_ref in refs for node in net.nodes):
            touched.add(net.id)
    return touched


@dataclass
class TestabilityReport:
    testpoint_count: int = 0
    power_rails_covered: list[str] = field(default_factory=list)
    power_rails_uncovered: list[str] = field(default_factory=list)
    has_debug_access: bool = False
    has_reset_access: bool = False
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_testability(design: Design) -> TestabilityReport:
    """Assess test-point coverage and debug/reset access of a design."""
    tp_refs = _testpoint_refs(design)
    tp_nets = _nets_touched_by(design, tp_refs)

    covered: list[str] = []
    uncovered: list[str] = []
    for net in design.nets.values():
        if net.type != NetType.POWER:
            continue
        (covered if net.id in tp_nets else uncovered).append(net.name)

    has_debug = any(
        any(tok in c.type.lower() for tok in _DEBUG_TYPE_TOKENS) for c in design.components.values()
    ) or any(any(tok in net.name.lower() for tok in _DEBUG_NET_TOKENS) for net in design.nets.values())

    has_reset = any(any(tok in net.name.lower() for tok in _RESET_NET_TOKENS) for net in design.nets.values())

    recommendations: list[str] = []
    for rail in sorted(uncovered):
        recommendations.append(f"Add a test point on power rail '{rail}' for bring-up probing.")
    if not has_debug:
        recommendations.append("Add a debug/programming interface (SWD/JTAG header or test points).")
    if not has_reset:
        recommendations.append("Expose the reset net (test point) so the MCU can be reset during bring-up.")

    return TestabilityReport(
        testpoint_count=len(tp_refs),
        power_rails_covered=sorted(covered),
        power_rails_uncovered=sorted(uncovered),
        has_debug_access=has_debug,
        has_reset_access=has_reset,
        recommendations=recommendations,
    )


def bringup_checklist(design: Design) -> list[str]:
    """Produce an ordered, design-tailored board bring-up checklist."""
    report = analyze_testability(design)
    power_rails = sorted(net.name for net in design.nets.values() if net.type == NetType.POWER)

    steps: list[str] = [
        "Visually inspect for solder bridges, missing/incorrect parts, and component orientation.",
        "Check for shorts between each power rail and ground with a multimeter before applying power.",
        "Power up through a current-limited bench supply and watch the inrush/quiescent current.",
    ]
    for rail in power_rails:
        steps.append(f"Measure the '{rail}' rail and confirm it is within tolerance.")
    if report.has_debug_access:
        steps.append("Connect the debug/programming interface and confirm the target is detected.")
    else:
        steps.append("No debug access found — add one before attempting to program the board.")
    steps.append("Flash a minimal blink/heartbeat firmware to confirm the MCU runs.")
    steps.append("Bring up each interface/peripheral one at a time and verify with a known-good device.")
    return steps


# ---------------------------------------------------------------------------
# Testpoint auto-insertion policy
# ---------------------------------------------------------------------------

_TP_DIAMETER_MM = 1.0  # standard SMD test-point pad diameter
_TP_DRILL_MM = 0.0  # SMD (no drill); through-hole TPs would be > 0


@dataclass(frozen=True)
class TestpointSpec:
    """Specification for a single testpoint to insert."""

    net_name: str
    reason: str
    tp_ref: str
    diameter_mm: float = _TP_DIAMETER_MM
    drill_mm: float = _TP_DRILL_MM

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TestpointInsertionPlan:
    """Auto-insertion plan: which testpoints to add and why."""

    testpoints: list[TestpointSpec] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def tp_insertion_plan(design: Design, *, tp_ref_start: int = 1) -> TestpointInsertionPlan:
    """Generate a testpoint auto-insertion policy for a design.

    Adds testpoints to:
    - Every power rail that lacks a testpoint.
    - The reset net if exposed (for reset-during-bring-up).
    - High-current nets (from ``NetConstraints.is_high_current``).

    The plan is advisory: it lists which nets need testpoints and assigns
    reference designators (TP1, TP2, …). The caller is responsible for
    physically placing the testpoints in the layout.

    Args:
        design: The design to analyse.
        tp_ref_start: Starting reference number for TP designators.
    """
    report = analyze_testability(design)
    plan = TestpointInsertionPlan()
    counter = tp_ref_start

    # Power rails with no coverage
    for rail in report.power_rails_uncovered:
        plan.testpoints.append(
            TestpointSpec(
                net_name=rail,
                reason="Power rail lacks a testpoint — required for bring-up probing",
                tp_ref=f"TP{counter}",
            )
        )
        counter += 1

    # Reset net exposure
    if not report.has_reset_access:
        for net in design.nets.values():
            if any(tok in net.name.lower() for tok in _RESET_NET_TOKENS):
                plan.testpoints.append(
                    TestpointSpec(
                        net_name=net.name,
                        reason="Reset net should be probed during bring-up",
                        tp_ref=f"TP{counter}",
                    )
                )
                counter += 1
                break

    # High-current nets with no testpoint
    tp_refs = _testpoint_refs(design)
    tp_nets = _nets_touched_by(design, tp_refs)
    for net in design.nets.values():
        if net.constraints and net.constraints.is_high_current and net.id not in tp_nets:
            plan.testpoints.append(
                TestpointSpec(
                    net_name=net.name,
                    reason="High-current net should be monitored at bring-up",
                    tp_ref=f"TP{counter}",
                )
            )
            counter += 1

    if not plan.testpoints:
        plan.notes.append("All probed nets already have testpoints — no insertions needed.")
    else:
        plan.notes.append(
            f"{len(plan.testpoints)} testpoint(s) recommended; "
            f"use {_TP_DIAMETER_MM} mm SMD pads (GND plane nearby for scope probe return)."
        )

    return plan
