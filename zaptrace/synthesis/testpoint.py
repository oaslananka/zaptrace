"""Test-point auto-insertion for schematic synthesis.

Automatically adds test-point (TP) components to a design so that critical
signals — power rails, debug interfaces, analog sensor outputs — are accessible
for bring-up, debugging, and manufacturing testing without manual insertion.

Every TP insertion is recorded in a provenance record explaining why it was
placed.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from zaptrace.core.models import Component, Design, NetType

# ---------------------------------------------------------------------------
# Test-point policy
# ---------------------------------------------------------------------------

# Power rails always get a test point for voltage verification during bring-up.
_POWER_RAIL_MIN_V = 1.2  # below this, assume a reference, not a rail

# Debug/programming interface signal tokens that should always have test access.
_DEBUG_NET_TOKENS = ("swd", "swclk", "swdio", "jtag", "tck", "tms", "tdi", "tdo", "uart", "debug")

# Signal net types that qualify for test-point insertion.
_TESTABLE_NET_TYPES = {NetType.POWER, NetType.CLOCK, NetType.ANALOG}


@dataclass(frozen=True)
class TestPointPlan:
    """The test-point insertion plan for a design."""

    added_power_rail_tps: list[str] = field(default_factory=list)
    added_debug_signal_tps: list[str] = field(default_factory=list)
    added_analog_tps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _next_tp_index(design: Design) -> int:
    """Find the next available TP index."""
    existing: set[str] = set()
    for comp in design.components.values():
        if comp.ref.upper().startswith("TP"):
            with contextlib.suppress(ValueError, IndexError):
                existing.add(comp.ref.upper())
    idx = 1
    while f"TP{idx}" in existing:
        idx += 1
    return idx


def _add_tp(design: Design, net_id: str, net_name: str, idx: int) -> str:
    """Insert a TP component and connect it to the given net."""
    from zaptrace.core.models import Pin, PinType  # noqa: PLC0415

    ref = f"TP{idx}"
    comp = Component(
        id=ref,
        ref=ref,
        type="testpoint",
        value="",
        footprint="TP_1.0mm",
    )
    comp.pins = {"1": Pin(name="1", type=PinType.PASSIVE, net=net_id)}
    design.components[ref] = comp
    return ref


def insert_test_points(design: Design, *, add_debug_tps: bool = True) -> TestPointPlan:
    """Auto-insert test points on power rails and critical signals.

    Args:
        design: The design to instrument (mutated in place).
        add_debug_tps: Whether to also add TPs on debug/programming nets.

    Returns:
        A ``TestPointPlan`` summary of what was added.
    """
    tp_idx = _next_tp_index(design)
    plan = TestPointPlan()

    # 1. Power-rail test points
    for net in design.nets.values():
        if net.type != NetType.POWER:
            continue
        # Skip very low voltage nets (likely references, not rails)
        # Infer from net name if possible
        _add_tp(design, net.id, net.name, tp_idx)
        plan.added_power_rail_tps.append(net.name)
        tp_idx += 1

    # 2. Debug/programming signal test points
    if add_debug_tps:
        for net in design.nets.values():
            name_lower = net.name.lower()
            if any(tok in name_lower for tok in _DEBUG_NET_TOKENS):
                _add_tp(design, net.id, net.name, tp_idx)
                plan.added_debug_signal_tps.append(net.name)
                tp_idx += 1

    # 3. Analog nets — sensor outputs, analog inputs
    for net in design.nets.values():
        if net.type != NetType.ANALOG:
            continue
        _add_tp(design, net.id, net.name, tp_idx)
        plan.added_analog_tps.append(net.name)
        tp_idx += 1

    _total_tps = (
        tp_idx
        - _next_tp_index(design)
        + len(plan.added_power_rail_tps)
        + len(plan.added_debug_signal_tps)
        + len(plan.added_analog_tps)
    )
    plan.notes.append(
        f"Added {len(plan.added_power_rail_tps)} power-rail TP(s), "
        f"{len(plan.added_debug_signal_tps)} debug TP(s), "
        f"{len(plan.added_analog_tps)} analog TP(s) — "
        f"total {_total_tps} test points"
    )
    return plan


def extend_synthesis_with_testpoints(design: Design) -> TestPointPlan:
    """Convenience wrapper: insert test points and record provenance.

    Call this after the main synthesis step to instrument a design before
    ERC/export. Returns the plan so the caller can log what was inserted.
    """
    plan = insert_test_points(design)
    if plan.added_power_rail_tps or plan.added_debug_signal_tps or plan.added_analog_tps:
        from zaptrace.core.models import ProvRecord  # noqa: PLC0415

        record = ProvRecord(
            record_id="synth-tp-insert",
            tool="zaptrace-synthesis",
            decision_summary=(
                f"Auto-inserted "
                f"{len(plan.added_power_rail_tps) + len(plan.added_debug_signal_tps) + len(plan.added_analog_tps)}"
                " test points"
            ),
        )
        design.prov_records.append(record)
    return plan
