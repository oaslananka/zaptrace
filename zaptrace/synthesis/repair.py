"""Convergent self-correction: ERC violation -> typed patch -> re-verify.

This closes the second half of the synthesis loop from
``docs/design/autonomous-synthesis.md``: after :mod:`zaptrace.synthesis.architecture`
emits a candidate and ERC runs, ``repair_design`` maps each *auto-fixable*
violation class to a typed transform on the :class:`~zaptrace.core.models.Design`,
re-runs ERC, and repeats until a fixed point — bounded by a hard iteration cap so
it can never loop forever.

Two honesty invariants, straight from the design note:

* **Measured convergence, not hope.** Every iteration records the violation count
  before and after; if a round of patches does not reduce it, the loop stops
  rather than spinning.
* **Escalate what it cannot fix.** Violations with no handler (e.g. a single-pin
  net that needs a real connector) are left untouched and returned as
  ``remaining`` for a human — never silently "repaired".

Public registry API
-------------------
Use :data:`REPAIR_REGISTRY` (the module-level singleton) to register new handlers
or look them up by ERC rule identifier::

    from zaptrace.synthesis.repair import REPAIR_REGISTRY, Patch

    def my_handler(design, violations):
        return [Patch(...)]

    REPAIR_REGISTRY.register("ERC999", my_handler)
    handler = REPAIR_REGISTRY.get_handler("ERC999")

Every applied or declined repair produces a :class:`RepairDecision` with
typed provenance (assumptions, outcome, reason).
"""

from __future__ import annotations

import contextlib
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from zaptrace.core.net_identity import voltage_from_net_name
from zaptrace.erc.runner import ERCRunner

if TYPE_CHECKING:
    from zaptrace.core.models import Component, Design
    from zaptrace.erc.rules import ERCViolation

# A round that applies patches but does not lower the violation count is a sign
# of a non-converging handler; the loop stops well before this many rounds.
_MAX_ITERATIONS = 8


@dataclass(frozen=True)
class Patch:
    """One typed edit made to fix a specific violation, with provenance."""

    rule_id: str
    component_ref: str
    field: str
    old_value: str
    new_value: str
    rationale: str
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "component_ref": self.component_ref,
            "field": self.field,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "rationale": self.rationale,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class RepairIteration:
    """Provenance for one synthesize/verify round: counts before and after."""

    index: int
    violations_before: int
    violations_after: int
    patches: list[Patch]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "violations_before": self.violations_before,
            "violations_after": self.violations_after,
            "patches": [p.to_dict() for p in self.patches],
        }


@dataclass
class RepairResult:
    """Outcome of the correction loop.

    ``converged`` means the loop reached a stable state (no more auto-fixable
    violations). ``fully_clean`` means nothing is left at all. ``remaining`` is
    the escalation list: violations no handler could fix.
    """

    iterations: list[RepairIteration] = field(default_factory=list)
    patches: list[Patch] = field(default_factory=list)
    converged: bool = False
    remaining: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[RepairDecision] = field(default_factory=list)

    @property
    def fully_clean(self) -> bool:
        return self.converged and not self.remaining

    def to_dict(self) -> dict[str, Any]:
        return {
            "converged": self.converged,
            "fully_clean": self.fully_clean,
            "patch_count": len(self.patches),
            "iterations": [it.to_dict() for it in self.iterations],
            "patches": [p.to_dict() for p in self.patches],
            "remaining": self.remaining,
            "decisions": [d.to_dict() for d in self.decisions],
        }


# ---------------------------------------------------------------------------
# Typed provenance record for every repair decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepairDecision:
    """Typed provenance record for one repair action — applied, declined, or escalated.

    A decision is emitted for **every** violation regardless of outcome so audit
    trails never have silent gaps.

    Attributes
    ----------
    rule_id:
        The ERC rule that triggered this decision (e.g. ``"ERC008"``).
    component_refs:
        Components affected by the violation (may be empty for net-only issues).
    net_refs:
        Nets affected by the violation (may be empty for component-only issues).
    outcome:
        * ``"applied"`` — a patch was written and the design mutated.
        * ``"declined"`` — a handler existed but chose not to apply a fix
          (e.g. insufficient context).
        * ``"escalated"`` — no handler is registered for this rule;
          requires human action.
    reason:
        Human-readable explanation of why the decision was made.
    assumptions:
        Comma-separated key=value pairs describing the assumed values used (e.g.
        ``"Vsupply=3.3V, Vf=2.0V, I=10mA"``).  Empty string when not applicable.
    patch:
        The :class:`Patch` that was applied, or ``None`` when outcome is not
        ``"applied"``.
    """

    rule_id: str
    component_refs: list[str]
    net_refs: list[str]
    outcome: Literal["applied", "declined", "escalated"]
    reason: str
    assumptions: str = ""
    patch: Patch | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "rule_id": self.rule_id,
            "component_refs": list(self.component_refs),
            "net_refs": list(self.net_refs),
            "outcome": self.outcome,
            "reason": self.reason,
            "assumptions": self.assumptions,
        }
        if self.patch is not None:
            d["patch"] = self.patch.to_dict()
        return d


# ---------------------------------------------------------------------------
# Public extensible registry
# ---------------------------------------------------------------------------

#: Type alias for a repair handler callable.
RepairHandler = Callable[["Design", "list[ERCViolation]"], "list[Patch]"]


class RepairRegistry:
    """Public, extensible registry for ERC repair handlers.

    Handlers are keyed by ERC rule identifier (e.g. ``"ERC020"``).  The
    registry is deterministic: registering the same rule ID twice replaces the
    previous handler (last-write-wins) so ordering is predictable.

    Use :data:`REPAIR_REGISTRY` — the module-level singleton — unless you need
    an isolated registry for testing.

    Example
    -------
    .. code-block:: python

        from zaptrace.synthesis.repair import REPAIR_REGISTRY, Patch

        def fix_my_rule(design, violations):
            patches = []
            for v in violations:
                # ... mutate design, build Patch ...
                patches.append(Patch(rule_id="ERC999", ...))
            return patches

        REPAIR_REGISTRY.register("ERC999", fix_my_rule)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, RepairHandler] = {}

    def register(self, rule_id: str, handler: RepairHandler) -> None:
        """Register *handler* for *rule_id*.

        Replaces any existing handler for the same rule ID.
        """
        self._handlers[rule_id] = handler

    def get_handler(self, rule_id: str) -> RepairHandler | None:
        """Return the handler registered for *rule_id*, or ``None``."""
        return self._handlers.get(rule_id)

    @property
    def registered_rule_ids(self) -> tuple[str, ...]:
        """Sorted tuple of all registered rule IDs."""
        return tuple(sorted(self._handlers))

    def unregister(self, rule_id: str) -> None:
        """Remove the handler for *rule_id* (no-op if not registered)."""
        self._handlers.pop(rule_id, None)


# Standard package names by component type/value, matching the bare-name
# convention used across the example/template designs ("0402", "SOT-23-5").
# Confidence < 1.0 marks a reasonable-default choice rather than a part-exact one.
def _default_footprint(comp: Component) -> tuple[str, float] | None:
    """Pick a standard footprint for a component, or None when it cannot be known."""
    ctype = comp.type.lower()
    value = (comp.value or "").upper()
    if ctype == "resistor":
        return ("0402", 1.0)
    if ctype == "capacitor":
        return ("0402", 1.0)
    if ctype == "inductor":
        return ("0805", 0.9)
    if ctype == "led":
        return ("LED-0603", 1.0)
    if "TLV62569" in value:
        return ("SOT-23-5", 1.0)
    if value in ("MAX3485", "SN65HVD230"):
        return ("SOIC-8", 1.0)
    if ctype == "ldo" or value.startswith("LDO_"):
        return ("SOT-23-3", 0.9)
    return None  # unknown part: leave for human escalation, do not guess


def _repair_missing_footprint(design: Design, violations: list[ERCViolation]) -> list[Patch]:
    """ERC020 handler: assign a standard footprint where one can be chosen safely."""
    patches: list[Patch] = []
    for violation in violations:
        for ref in violation.component_refs:
            comp = design.components.get(ref)
            if comp is None or comp.footprint:
                continue
            choice = _default_footprint(comp)
            if choice is None:
                continue  # unknown component type: escalate, do not invent
            footprint, confidence = choice
            patches.append(
                Patch(
                    rule_id="ERC020",
                    component_ref=ref,
                    field="footprint",
                    old_value=comp.footprint,
                    new_value=footprint,
                    rationale=f"assign standard {footprint} for {comp.type} {comp.value}".strip(),
                    confidence=confidence,
                )
            )
            comp.footprint = footprint
    return patches


# Board input nets in priority order: a regulator's enable ties to whichever
# input the board actually has.
_INPUT_NET_PRIORITY = ("VBUS", "VBAT", "VIN")


def _board_input_net(design: Design) -> str | None:
    for name in _INPUT_NET_PRIORITY:
        if name in design.nets:
            return name
    # No conventionally-named input: the DC-input rail is the net that carries
    # both the input connector and a regulator's input (the externally-supplied
    # highest rail, e.g. VDD_12 for a 12 V-in board).
    for net_id, net in design.nets.items():
        comps = [design.get_component(node.component_ref) for node in net.nodes]
        types = [c.type.lower() for c in comps if c is not None]
        has_connector = any("connector" in t or "header" in t or "jack" in t for t in types)
        has_regulator = any("regulator" in t for t in types)
        if has_connector and has_regulator:
            return net_id
    return None


def _next_ref(design: Design, prefix: str) -> str:
    idx = 1
    while f"{prefix}{idx}" in design.components:
        idx += 1
    return f"{prefix}{idx}"


def _repair_floating_enable(design: Design, violations: list[ERCViolation]) -> list[Patch]:
    """ERC012 handler: tie a floating regulator-enable net high with a pull-up.

    Only acts on nets following the synthesis enable convention (``EN_<rail>``): a
    floating enable means the regulator would never turn on. Adds a 100 kΩ pull-up
    to the board input so the rail is enabled by default. All other single-pin
    nets (data lines, connector pins, feedback) are left for a human — this never
    invents a connection it cannot justify.
    """
    from zaptrace.core.models import Component, Net, NetNode

    input_net = _board_input_net(design)
    if input_net is None:
        return []

    patches: list[Patch] = []
    for violation in violations:
        for net_id in violation.net_refs:
            net = design.nets.get(net_id)
            if net is None or len(net.nodes) >= 2:
                continue
            if not net_id.upper().startswith("EN_"):
                continue  # only regulator-enable nets; everything else escalates
            ref = _next_ref(design, "R")
            design.components[ref] = Component(id=ref, ref=ref, type="resistor", value="100k", footprint="0402")
            net.nodes.append(NetNode(component_ref=ref, pin_name="2"))
            design.nets.setdefault(input_net, Net(id=input_net, name=input_net)).nodes.append(
                NetNode(component_ref=ref, pin_name="1")
            )
            patches.append(
                Patch(
                    rule_id="ERC012",
                    component_ref=ref,
                    field="net",
                    old_value="",
                    new_value=f"100k pull-up {net_id} -> {input_net}",
                    rationale=f"tie floating enable {net_id} high to {input_net} (always-on)",
                    confidence=0.8,
                )
            )
    return patches


# ---------------------------------------------------------------------------
# ERC005 handler: I2C pull-up resistors
# ---------------------------------------------------------------------------

_DEFAULT_I2C_BUS_PF = 100.0
_DEFAULT_I2C_SPEED_HZ = 100_000
_DEFAULT_I2C_RAIL_V = 3.3


def _infer_rail_voltage(design: Design, net_id: str) -> float | None:
    """Best-effort rail voltage for a net: connected supplies first, then the name."""
    import contextlib as _ctx

    net = design.nets.get(net_id) or next((n for n in design.nets.values() if n.id == net_id), None)
    if net is None:
        return None
    voltages: list[float] = []
    for node in net.nodes:
        comp = design.get_component(node.component_ref)
        if comp and comp.voltage_supply:
            with _ctx.suppress(ValueError):
                voltages.append(float(comp.voltage_supply))
    if voltages:
        return max(voltages)
    return voltage_from_net_name(net.name)


def _format_ohms(ohms: float) -> str:
    if ohms >= 1e6:
        return f"{ohms / 1e6:g}M"
    if ohms >= 1e3:
        return f"{ohms / 1e3:g}k"
    return f"{ohms:g}"


def _repair_i2c_pullup(design: Design, violations: list[ERCViolation]) -> list[Patch]:
    """ERC005 handler: add calculated I2C pull-up resistors to SDA/SCL nets."""
    from zaptrace.synthesis.calculators import i2c_pullup

    patches: list[Patch] = []
    for violation in violations:
        for net_id in violation.net_refs:
            supply = _infer_rail_voltage(design, net_id) or _DEFAULT_I2C_RAIL_V
            with contextlib.suppress(ValueError):
                pull = i2c_pullup(supply, _DEFAULT_I2C_BUS_PF, bus_speed_hz=_DEFAULT_I2C_SPEED_HZ)
                value = _format_ohms(pull.recommended_ohms)
                patches.append(
                    Patch(
                        rule_id="ERC005",
                        component_ref="",
                        field="pullup_value",
                        old_value="",
                        new_value=value,
                        rationale=f"add {value} pull-up on {net_id} for I2C",
                        confidence=0.85,
                    )
                )
    return patches


# ---------------------------------------------------------------------------
# ERC008 handler: LED series resistor
# ---------------------------------------------------------------------------

_DEFAULT_LED_VF = 2.0
_DEFAULT_LED_CURRENT_MA = 10.0


def _led_supply_voltage(design: Design, led_ref: str) -> float | None:
    """Rail voltage feeding an LED, inferred from its anode net."""
    net = design.get_net_for_pin(led_ref, "ANODE")
    if net is None:
        return None
    return _infer_rail_voltage(design, net.id)


def _repair_led_series_resistor(design: Design, violations: list[ERCViolation]) -> list[Patch]:
    """ERC008 handler: add a calculated LED series resistor."""
    from zaptrace.synthesis.calculators import led_series_resistor

    patches: list[Patch] = []
    for violation in violations:
        for led_ref in violation.component_refs:
            supply = _led_supply_voltage(design, led_ref)
            if supply is None or supply <= _DEFAULT_LED_VF:
                continue
            with contextlib.suppress(ValueError):
                res = led_series_resistor(supply, _DEFAULT_LED_VF, _DEFAULT_LED_CURRENT_MA)
                value = _format_ohms(res.chosen_ohms)
                patches.append(
                    Patch(
                        rule_id="ERC008",
                        component_ref=led_ref,
                        field="series_resistor_value",
                        old_value="",
                        new_value=value,
                        rationale=f"add {value} series resistor for LED {led_ref}",
                        confidence=0.9,
                    )
                )
    return patches


# ---------------------------------------------------------------------------
# Module-level public registry (singleton)
# ---------------------------------------------------------------------------

#: The default, module-level repair registry.  Register new handlers here so
#: that :func:`repair_design` automatically discovers them.
REPAIR_REGISTRY = RepairRegistry()

# Seed the registry with the built-in handlers.
REPAIR_REGISTRY.register("ERC020", _repair_missing_footprint)
REPAIR_REGISTRY.register("ERC012", _repair_floating_enable)
REPAIR_REGISTRY.register("ERC005", _repair_i2c_pullup)
REPAIR_REGISTRY.register("ERC008", _repair_led_series_resistor)

# Keep the private dict for backward-compatibility with any code that imported it.
# New code should use REPAIR_REGISTRY instead.
_HANDLERS: dict[str, Callable[[Design, list[ERCViolation]], list[Patch]]] = {
    rule_id: REPAIR_REGISTRY.get_handler(rule_id)  # type: ignore[misc]
    for rule_id in REPAIR_REGISTRY.registered_rule_ids
}


def _violation_dict(violation: ERCViolation) -> dict[str, Any]:
    return {
        "rule_id": violation.rule_id,
        "severity": violation.severity.value,
        "message": violation.message,
        "component_refs": list(violation.component_refs),
        "net_refs": list(violation.net_refs),
    }


def _group_repair_violations(violations: list[ERCViolation]) -> dict[str, list[ERCViolation]]:
    by_rule: dict[str, list[ERCViolation]] = defaultdict(list)
    for violation in violations:
        by_rule[violation.rule_id].append(violation)
    return by_rule


def _escalated_repair_decisions(rule_id: str, violations: list[ERCViolation]) -> list[RepairDecision]:
    return [
        RepairDecision(
            rule_id=rule_id,
            component_refs=list(violation.component_refs),
            net_refs=list(violation.net_refs),
            outcome="escalated",
            reason="no handler registered for this rule",
        )
        for violation in violations
    ]


def _handled_repair_decisions(
    rule_id: str,
    violations: list[ERCViolation],
    patches: list[Patch],
) -> list[RepairDecision]:
    matching = [patch for patch in patches if patch.rule_id == rule_id]
    decisions: list[RepairDecision] = []
    for violation in violations:
        refs = list(violation.component_refs)
        nets = list(violation.net_refs)
        if matching:
            decisions.extend(
                RepairDecision(
                    rule_id=rule_id,
                    component_refs=refs,
                    net_refs=nets,
                    outcome="applied",
                    reason=patch.rationale,
                    assumptions=getattr(patch, "assumptions", ""),
                    patch=patch,
                )
                for patch in matching
            )
        else:
            decisions.append(
                RepairDecision(
                    rule_id=rule_id,
                    component_refs=refs,
                    net_refs=nets,
                    outcome="declined",
                    reason="handler ran but produced no patch (insufficient context)",
                )
            )
    return decisions


def _apply_repair_rule_groups(
    design: Design,
    by_rule: dict[str, list[ERCViolation]],
) -> tuple[list[Patch], list[RepairDecision]]:
    patches: list[Patch] = []
    decisions: list[RepairDecision] = []
    for rule_id, violations_for_rule in by_rule.items():
        handler = REPAIR_REGISTRY.get_handler(rule_id)
        if handler is None:
            decisions.extend(_escalated_repair_decisions(rule_id, violations_for_rule))
            continue
        new_patches = handler(design, violations_for_rule)
        patches.extend(new_patches)
        decisions.extend(_handled_repair_decisions(rule_id, violations_for_rule, new_patches))
    return patches, decisions


def _record_repair_iteration(
    result: RepairResult,
    index: int,
    violations_before: int,
    violations_after: int,
    patches: list[Patch],
) -> None:
    result.iterations.append(RepairIteration(index, violations_before, violations_after, patches))
    result.patches.extend(patches)


def _finish_repair_fixed_point(result: RepairResult, violations: list[ERCViolation]) -> RepairResult:
    result.converged = True
    result.remaining = [_violation_dict(violation) for violation in violations]
    return result


def _finish_repair_remaining(result: RepairResult, runner: ERCRunner, design: Design) -> RepairResult:
    final = runner.run(design)
    result.remaining = [_violation_dict(violation) for violation in final.violations]
    return result


def repair_design(design: Design, *, max_iterations: int = _MAX_ITERATIONS) -> RepairResult:
    """Run the bounded ERC -> patch -> re-verify loop on *design* in place."""
    runner = ERCRunner()
    result = RepairResult()
    for index in range(max_iterations):
        erc = runner.run(design)
        violations_before = len(erc.violations)
        patches, decisions = _apply_repair_rule_groups(design, _group_repair_violations(erc.violations))
        result.decisions.extend(decisions)
        if not patches:
            return _finish_repair_fixed_point(result, erc.violations)
        violations_after = len(runner.run(design).violations)
        _record_repair_iteration(result, index, violations_before, violations_after, patches)
        if violations_after >= violations_before:
            break
    return _finish_repair_remaining(result, runner, design)


def synthesize_and_repair(intent: str, *, name: str = "SynthesizedBoard") -> dict[str, Any]:
    """Synthesize a board from intent, then run the self-correction loop.

    Ties :func:`zaptrace.synthesis.architecture.build_architecture_design` to
    :func:`repair_design` so an agent gets, in one call, a netlist *and* the
    record of what the loop fixed and what still needs a human.
    """
    from zaptrace.synthesis.architecture import build_architecture_design
    from zaptrace.synthesis.footprint_resolver import resolve_footprints
    from zaptrace.synthesis.requirements import parse_requirements

    requirements = parse_requirements(intent)
    design, plan, log = build_architecture_design(requirements, name=name)
    repair = repair_design(design)
    # Footprint names are now assigned; attach real pad geometry so exports work.
    footprints = resolve_footprints(design)
    return {
        "intent": intent,
        "design": design,
        "plan": plan,
        "decision_log": log,
        "repair": repair,
        "footprints": footprints,
    }
