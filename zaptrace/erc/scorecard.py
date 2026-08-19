"""Deterministic ERC repair scorecard over ten high-value fault classes.

The scorecard runs a stable corpus of mutated :class:`~zaptrace.core.models.Design`
fixtures through :func:`~zaptrace.synthesis.repair.repair_design` and records, for
each case:

* the ERC rule that was triggered
* the detector outcome (how many violations fired)
* the handler attempted (from :data:`~zaptrace.synthesis.repair.REPAIR_REGISTRY`)
* before/after violation counts
* outcome classification: ``"fixed"``, ``"declined"``, or ``"escalated"``
* evidence string for traceability

Serialisation is byte-stable: entries are sorted by ``rule_id`` then
``fixture_id`` and every collection is ordered before encoding.

Public API
----------
``CORPUS``
    The list of :class:`ScorecardFixture` instances that define the corpus.
``run_scorecard()``
    Execute the full corpus and return a :class:`ScorecardResult`.
``ScorecardResult.to_dict()``
    Byte-stable serialisation.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zaptrace.core.models import Design


# ---------------------------------------------------------------------------
# Corpus entry definition
# ---------------------------------------------------------------------------


@dataclass
class ScorecardFixture:
    """One labelled corpus entry: a factory that produces a mutated design plus metadata.

    Attributes
    ----------
    fixture_id:
        Stable, unique identifier (e.g. ``"ERC020-missing-footprint"``).
    rule_id:
        The ERC rule this fixture is designed to trigger.
    description:
        One-line human description of the injected fault.
    factory:
        Zero-argument callable that returns a fresh :class:`~zaptrace.core.models.Design`
        with the fault already injected.  Must be pure and side-effect-free.
    expected_outcome:
        One of ``"fixed"``, ``"declined"``, or ``"escalated"``.  Used by the
        regression test to detect corpus drift.
    """

    fixture_id: str
    rule_id: str
    description: str
    factory: Callable[[], Design]
    expected_outcome: str  # "fixed" | "declined" | "escalated"


# ---------------------------------------------------------------------------
# Scorecard result
# ---------------------------------------------------------------------------


@dataclass
class ScorecardEntry:
    """Result row for one fixture execution.

    Attributes
    ----------
    fixture_id:
        Matches :attr:`ScorecardFixture.fixture_id`.
    rule_id:
        ERC rule that fired.
    description:
        Human description from the fixture.
    expected_outcome:
        What the corpus says should happen.
    actual_outcome:
        ``"fixed"`` — at least one applied decision reduced violations to zero.
        ``"declined"`` — a handler ran but produced no patches.
        ``"escalated"`` — no handler registered for this rule.
    violations_before:
        Total violations in the design before repair.
    violations_after:
        Total violations remaining after repair.
    decisions:
        All :class:`~zaptrace.synthesis.repair.RepairDecision` objects recorded.
    evidence:
        One-line evidence string for reporting.
    """

    fixture_id: str
    rule_id: str
    description: str
    expected_outcome: str
    actual_outcome: str
    violations_before: int
    violations_after: int
    decisions: list[Any]  # list[RepairDecision]
    evidence: str

    @property
    def regression_pass(self) -> bool:
        """True when the actual outcome matches what the corpus expects."""
        return self.actual_outcome == self.expected_outcome

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "rule_id": self.rule_id,
            "description": self.description,
            "expected_outcome": self.expected_outcome,
            "actual_outcome": self.actual_outcome,
            "violations_before": self.violations_before,
            "violations_after": self.violations_after,
            "decisions_count": len(self.decisions),
            "evidence": self.evidence,
            "regression_pass": self.regression_pass,
        }


@dataclass
class ScorecardResult:
    """Aggregate result of running the full corpus.

    Attributes
    ----------
    entries:
        One entry per fixture, sorted by ``rule_id`` then ``fixture_id``.
    total_fixtures:
        Number of corpus cases run.
    regression_passes:
        Cases where actual_outcome == expected_outcome.
    regression_failures:
        Cases where they differ (corpus drift).
    """

    entries: list[ScorecardEntry] = field(default_factory=list)

    @property
    def total_fixtures(self) -> int:
        return len(self.entries)

    @property
    def regression_passes(self) -> int:
        return sum(1 for e in self.entries if e.regression_pass)

    @property
    def regression_failures(self) -> int:
        return sum(1 for e in self.entries if not e.regression_pass)

    def failed_entries(self) -> list[ScorecardEntry]:
        return [e for e in self.entries if not e.regression_pass]

    def to_dict(self) -> dict[str, Any]:
        """Byte-stable serialisation — same output every run."""
        return {
            "total_fixtures": self.total_fixtures,
            "regression_passes": self.regression_passes,
            "regression_failures": self.regression_failures,
            "entries": [e.to_dict() for e in sorted(self.entries, key=lambda e: (e.rule_id, e.fixture_id))],
        }

    def to_json(self, *, indent: int = 2) -> str:
        """Deterministic JSON encoding (sorted keys, stable entry order)."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


# ---------------------------------------------------------------------------
# Corpus fixtures
# ---------------------------------------------------------------------------


def _base_design(name: str) -> Design:
    from zaptrace.core.models import Design, DesignMeta

    return Design(meta=DesignMeta(name=name))


def _fixture_erc020_missing_footprint() -> Design:
    """ERC020: resistor with empty footprint — fixable (ERC020 handler knows resistor → 0402)."""
    from zaptrace.core.models import Component

    d = _base_design("erc020-missing-footprint")
    d.components["R1"] = Component(id="R1", ref="R1", type="resistor", value="10k", footprint="")
    return d


def _fixture_erc020_unknown_type_declined() -> Design:
    """ERC020: IC with unknown type has empty footprint — handler declines (no default footprint for 'ic')."""
    from zaptrace.core.models import Component

    d = _base_design("erc020-unknown-type-declined")
    d.components["U1"] = Component(id="U1", ref="U1", type="ic", value="STM32", footprint="")
    return d


def _fixture_erc012_en_net_fixable() -> Design:
    """ERC012: EN_ net with one node — fixable because we have a VBUS input net."""
    from zaptrace.core.models import Component, Net, NetNode

    d = _base_design("erc012-en-net-fixable")
    # board input so _board_input_net() can find it
    vbus = Net(id="VBUS", name="VBUS")
    vbus.nodes.append(NetNode(component_ref="J1", pin_name="VBUS"))
    d.nets["VBUS"] = vbus
    d.components["J1"] = Component(id="J1", ref="J1", type="connector", value="USB-C")
    # single-node enable net
    en_net = Net(id="EN_VCC", name="EN_VCC")
    en_net.nodes.append(NetNode(component_ref="U2", pin_name="EN"))
    d.nets["EN_VCC"] = en_net
    d.components["U2"] = Component(id="U2", ref="U2", type="regulator", value="TPS62840")
    return d


def _fixture_erc012_signal_net_declined() -> Design:
    """ERC012: single-pin signal net (not EN_) — handler declines."""
    from zaptrace.core.models import Component, Net, NetNode

    d = _base_design("erc012-signal-net-declined")
    # Add VBUS so _board_input_net() succeeds; still declines because net name ≠ EN_
    vbus = Net(id="VBUS", name="VBUS")
    vbus.nodes.append(NetNode(component_ref="J1", pin_name="VBUS"))
    d.nets["VBUS"] = vbus
    d.components["J1"] = Component(id="J1", ref="J1", type="connector", value="USB-C")
    orphan = Net(id="ORPHAN_SIG", name="ORPHAN_SIG")
    orphan.nodes.append(NetNode(component_ref="R1", pin_name="1"))
    d.nets["ORPHAN_SIG"] = orphan
    d.components["R1"] = Component(id="R1", ref="R1", type="resistor", value="10k")
    return d


def _fixture_erc005_i2c_missing_pullup() -> Design:
    """ERC005: I2C net with no pull-up."""
    from zaptrace.core.models import Component, Net, NetNode

    d = _base_design("erc005-i2c-missing-pullup")
    sda = Net(id="I2C_SDA", name="I2C_SDA")
    sda.nodes.append(NetNode(component_ref="U1", pin_name="SDA"))
    sda.nodes.append(NetNode(component_ref="U2", pin_name="SDA"))
    d.nets["I2C_SDA"] = sda
    d.components["U1"] = Component(id="U1", ref="U1", type="mcu", value="STM32")
    d.components["U2"] = Component(id="U2", ref="U2", type="sensor", value="BME280")
    return d


def _fixture_erc008_led_no_resistor() -> Design:
    """ERC008: LED on VCC_3V3 power net with no series resistor."""
    from zaptrace.core.models import Component, Net, NetNode, NetType

    d = _base_design("erc008-led-no-resistor")
    vcc = Net(id="VCC_3V3", name="VCC_3V3", type=NetType.POWER)
    vcc.nodes.append(NetNode(component_ref="LED1", pin_name="ANODE"))
    d.nets["VCC_3V3"] = vcc
    d.components["LED1"] = Component(id="LED1", ref="LED1", type="LED", value="RED")
    # pin so ERC008 detects the ANODE-on-power connection
    from zaptrace.core.models import Pin, PinType

    d.components["LED1"].pins["ANODE"] = Pin(name="ANODE", type=PinType.PASSIVE, net="VCC_3V3")
    return d


def _fixture_erc001_unconnected_power_pin() -> Design:
    """ERC001: component has a power pin with no net — escalated (no handler)."""
    from zaptrace.core.models import Component, Pin, PinType

    d = _base_design("erc001-unconnected-power-pin")
    comp = Component(id="U1", ref="U1", type="ic", value="LM7805", footprint="TO-220")
    comp.pins["VCC"] = Pin(name="VCC", type=PinType.POWER, net=None)
    d.components["U1"] = comp
    return d


def _fixture_erc002_floating_input_pin() -> Design:
    """ERC002: IC input pin with no net — escalated (no handler)."""
    from zaptrace.core.models import Component, Pin, PinType

    d = _base_design("erc002-floating-input-pin")
    comp = Component(id="U1", ref="U1", type="ic", value="74HC00", footprint="SOIC-14")
    comp.pins["IN1"] = Pin(name="IN1", type=PinType.INPUT, net=None)
    d.components["U1"] = comp
    return d


def _fixture_erc017_duplicate_refs() -> Design:
    """ERC017: two components with the same ref — escalated (no handler)."""
    from zaptrace.core.models import Component

    d = _base_design("erc017-duplicate-refs")
    d.components["R1"] = Component(id="R1", ref="R1", type="resistor", value="10k", footprint="0402")
    d.components["R1_dup"] = Component(id="R1_dup", ref="R1", type="resistor", value="4k7", footprint="0402")
    return d


def _fixture_erc018_missing_test_point() -> Design:
    """ERC018: SWD net without a test point — escalated (no handler)."""
    from zaptrace.core.models import Component, Net, NetNode

    d = _base_design("erc018-missing-test-point")
    swdclk = Net(id="SWD_CLK", name="SWD_CLK")
    swdclk.nodes.append(NetNode(component_ref="J1", pin_name="SWDCLK"))
    swdclk.nodes.append(NetNode(component_ref="U1", pin_name="PA14"))
    d.nets["SWD_CLK"] = swdclk
    d.components["J1"] = Component(id="J1", ref="J1", type="connector", value="SWD-10")
    d.components["U1"] = Component(id="U1", ref="U1", type="mcu", value="STM32", footprint="LQFP-64")
    return d


def _fixture_erc019_illegal_net_name() -> Design:
    """ERC019: net name with illegal characters — escalated (no handler)."""
    from zaptrace.core.models import Component, Net, NetNode

    d = _base_design("erc019-illegal-net-name")
    bad = Net(id="NET_BAD", name="VCC/3V3!")
    bad.nodes.append(NetNode(component_ref="R1", pin_name="1"))
    bad.nodes.append(NetNode(component_ref="R2", pin_name="1"))
    d.nets["NET_BAD"] = bad
    d.components["R1"] = Component(id="R1", ref="R1", type="resistor", value="10k", footprint="0402")
    d.components["R2"] = Component(id="R2", ref="R2", type="resistor", value="10k", footprint="0402")
    return d


# ---------------------------------------------------------------------------
# Public corpus
# ---------------------------------------------------------------------------

#: The stable, ordered corpus used by :func:`run_scorecard`.
CORPUS: list[ScorecardFixture] = [
    ScorecardFixture(
        fixture_id="ERC020-missing-footprint-resistor",
        rule_id="ERC020",
        description="Resistor has empty footprint — handler assigns 0402",
        factory=_fixture_erc020_missing_footprint,
        expected_outcome="fixed",
    ),
    ScorecardFixture(
        fixture_id="ERC020-unknown-type-declined",
        rule_id="ERC020",
        description="IC has empty footprint — handler declines (no default for 'ic' type)",
        factory=_fixture_erc020_unknown_type_declined,
        expected_outcome="declined",
    ),
    ScorecardFixture(
        fixture_id="ERC012-en-net-fixable",
        rule_id="ERC012",
        description="Single-pin EN_ net with board input present",
        factory=_fixture_erc012_en_net_fixable,
        expected_outcome="fixed",
    ),
    ScorecardFixture(
        fixture_id="ERC012-signal-net-declined",
        rule_id="ERC012",
        description="Single-pin signal net (non-EN_) — handler declines",
        factory=_fixture_erc012_signal_net_declined,
        expected_outcome="declined",
    ),
    ScorecardFixture(
        fixture_id="ERC005-i2c-missing-pullup",
        rule_id="ERC005",
        description="I2C net has no pull-up resistor",
        factory=_fixture_erc005_i2c_missing_pullup,
        expected_outcome="fixed",
    ),
    ScorecardFixture(
        fixture_id="ERC008-led-no-series-resistor",
        rule_id="ERC008",
        description="LED on power net with no series current-limit resistor",
        factory=_fixture_erc008_led_no_resistor,
        expected_outcome="declined",
    ),
    ScorecardFixture(
        fixture_id="ERC001-unconnected-power-pin",
        rule_id="ERC001",
        description="IC power pin connected to no net",
        factory=_fixture_erc001_unconnected_power_pin,
        expected_outcome="escalated",
    ),
    ScorecardFixture(
        fixture_id="ERC002-floating-input-pin",
        rule_id="ERC002",
        description="IC input pin connected to no net",
        factory=_fixture_erc002_floating_input_pin,
        expected_outcome="escalated",
    ),
    ScorecardFixture(
        fixture_id="ERC017-duplicate-refs",
        rule_id="ERC017",
        description="Two components share the same reference designator",
        factory=_fixture_erc017_duplicate_refs,
        expected_outcome="escalated",
    ),
    ScorecardFixture(
        fixture_id="ERC018-missing-test-point",
        rule_id="ERC018",
        description="SWD net has no test point",
        factory=_fixture_erc018_missing_test_point,
        expected_outcome="escalated",
    ),
    ScorecardFixture(
        fixture_id="ERC019-illegal-net-name",
        rule_id="ERC019",
        description="Net name contains illegal characters (/, !)",
        factory=_fixture_erc019_illegal_net_name,
        expected_outcome="escalated",
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _determine_outcome(rule_id: str, decisions: list[Any]) -> str:
    """Derive the outcome for *rule_id* from the decision list."""
    rule_decisions = [d for d in decisions if d.rule_id == rule_id]
    if not rule_decisions:
        return "escalated"
    if any(d.outcome == "applied" for d in rule_decisions):
        return "fixed"
    if any(d.outcome == "declined" for d in rule_decisions):
        return "declined"
    return "escalated"


def _build_evidence(rule_id: str, entry_decisions: list[Any], before: int, after: int) -> str:
    outcomes = sorted({d.outcome for d in entry_decisions if d.rule_id == rule_id})
    return f"{rule_id}: {before}→{after} violations; decisions={outcomes}"


def run_scorecard(corpus: list[ScorecardFixture] | None = None) -> ScorecardResult:
    """Execute *corpus* (defaults to :data:`CORPUS`) and return a :class:`ScorecardResult`.

    Each fixture is run in isolation: the design factory is called fresh so
    fixtures cannot interfere with each other.  Results are sorted by
    ``rule_id`` then ``fixture_id`` to ensure byte-stable output.
    """
    from zaptrace.erc.runner import ERCRunner
    from zaptrace.synthesis.repair import repair_design

    if corpus is None:
        corpus = CORPUS

    runner = ERCRunner()
    entries: list[ScorecardEntry] = []

    for fixture in corpus:
        design = fixture.factory()
        # Count violations before repair (independent run, no mutation).
        before_design = copy.deepcopy(design)
        erc_before = runner.run(before_design)
        violations_before = len(erc_before.violations)

        # Run repair on a fresh copy.
        repair_design_input = copy.deepcopy(design)
        result = repair_design(repair_design_input)

        # Count remaining violations.
        violations_after = len(result.remaining)

        outcome = _determine_outcome(fixture.rule_id, result.decisions)
        evidence = _build_evidence(fixture.rule_id, result.decisions, violations_before, violations_after)

        entries.append(
            ScorecardEntry(
                fixture_id=fixture.fixture_id,
                rule_id=fixture.rule_id,
                description=fixture.description,
                expected_outcome=fixture.expected_outcome,
                actual_outcome=outcome,
                violations_before=violations_before,
                violations_after=violations_after,
                decisions=result.decisions,
                evidence=evidence,
            )
        )

    entries.sort(key=lambda e: (e.rule_id, e.fixture_id))
    return ScorecardResult(entries=entries)
