from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from zaptrace.core.models import Design
from zaptrace.erc import rules as _rules
from zaptrace.erc.models import ERCCheck, ERCResult, ERCSeverity, ERCViolation


@dataclass(frozen=True)
class RuleSpec:
    """A single ERC rule paired with the metadata needed to report coverage."""

    rule_id: str
    title: str
    category: str
    fn: Callable[[Design], list[ERCViolation]]


# Each rule is registered with its id, a human title, and the engineering
# category it covers. The category set is what lets an ERC result state *what
# domains were checked* (connectivity, power, interface, …) rather than emitting
# a bare pass/fail. Keep this a 22+ element list literal named ``_ALL_RULES`` —
# scripts/ci_docs_status_sync.py counts its elements to keep the docs in sync.
_ALL_RULES: list[RuleSpec] = [
    RuleSpec("ERC001", "Power pin without a net", "connectivity", _rules.rule_erc001),
    RuleSpec("ERC002", "Floating input pin", "connectivity", _rules.rule_erc002),
    RuleSpec("ERC003", "IC decoupling capacitor present", "power", _rules.rule_erc003),
    RuleSpec("ERC004", "Duplicate net names", "naming", _rules.rule_erc004),
    RuleSpec("ERC005", "I2C pull-up resistors", "interface", _rules.rule_erc005),
    RuleSpec("ERC006", "SPI MOSI/MISO orientation", "interface", _rules.rule_erc006),
    RuleSpec("ERC007", "Power net has a driver", "power", _rules.rule_erc007),
    RuleSpec("ERC008", "LED series resistor", "analog", _rules.rule_erc008),
    RuleSpec("ERC009", "UART TX/RX orientation", "interface", _rules.rule_erc009),
    RuleSpec("ERC010", "Crystal load capacitors", "clock", _rules.rule_erc010),
    RuleSpec("ERC011", "Connector ESD protection", "protection", _rules.rule_erc011),
    RuleSpec("ERC012", "Single-pin (unconnected) net", "connectivity", _rules.rule_erc012),
    RuleSpec("ERC013", "Polarized component polarity", "polarity", _rules.rule_erc013),
    RuleSpec("ERC014", "Voltage-domain mismatch on net", "power", _rules.rule_erc014),
    RuleSpec("ERC015", "Disjoint ground nets", "power", _rules.rule_erc015),
    RuleSpec("ERC016", "Reset pin pull-up", "reset/boot", _rules.rule_erc016),
    RuleSpec("ERC017", "Duplicate component references", "naming", _rules.rule_erc017),
    RuleSpec("ERC018", "Debug/protocol test points", "test", _rules.rule_erc018),
    RuleSpec("ERC019", "Illegal characters in net name", "naming", _rules.rule_erc019),
    RuleSpec("ERC020", "Component footprint assigned", "manufacturing", _rules.rule_erc020),
    RuleSpec("ERC021", "USB-C CC termination resistors", "interface", _rules.rule_erc021),
    RuleSpec("ERC022", "SPI chip-select idle pull-up", "interface", _rules.rule_erc022),
    RuleSpec("ERC023", "No-connect pin wired", "connectivity", _rules.rule_erc023),
    RuleSpec("ERC024", "RS485 direction control defined state", "interface", _rules.rule_erc024),
    RuleSpec("ERC025", "SPI chip-select uniqueness per peripheral", "interface", _rules.rule_erc025),
    RuleSpec("ERC026", "Li-ion/LiPo battery protection IC", "protection", _rules.rule_erc026),
    RuleSpec("ERC027", "Power-tree completeness — every power net needs a source", "power", _rules.rule_erc027),
    RuleSpec("ERC028", "Regulator headroom and current budget", "power", _rules.rule_erc028),
    RuleSpec("ERC029", "DNP/variant-aware ERC", "manufacturing", _rules.rule_erc029),
]

# Honest, code-owned record of what ERC does *not* yet verify, surfaced on every
# result so a passing check is never mistaken for full electrical correctness.
# Tie each gap to the epic item that would close it.
ERC_COVERAGE_GAPS: tuple[str, ...] = (
    "Decoupling (ERC003) is checked at net-ownership level, not by physical "
    "pin-to-capacitor distance (requires placement data).",
    "IC and pin-function detection is structural/heuristic, not datasheet-grounded.",
    "Return-path continuity and decoupling-distance ownership are not yet checked.",
    "RS485 (ERC024) and LiPo protection (ERC026) use keyword heuristics, not datasheet pin maps.",
    "Current-budget (ERC028) uses value-string heuristics — datasheet-grounded consumption would be more precise.",
)


class ERCRunner:
    def run(self, design: Design) -> ERCResult:
        violations: list[ERCViolation] = []
        checks_run: list[ERCCheck] = []
        for spec in _ALL_RULES:
            try:
                rule_violations = spec.fn(design)
            except Exception as exc:
                rule_violations = [
                    ERCViolation(
                        rule_id="ERC_INTERNAL",
                        severity=ERCSeverity.ERROR,
                        message=f"Rule {spec.rule_id} ({spec.fn.__name__}) raised: {exc}",
                    )
                ]
            violations.extend(rule_violations)
            checks_run.append(
                ERCCheck(
                    rule_id=spec.rule_id,
                    title=spec.title,
                    category=spec.category,
                    violation_count=len(rule_violations),
                )
            )
        return ERCResult.from_violations(
            violations,
            design.meta.name,
            checks_run=checks_run,
            coverage_gaps=list(ERC_COVERAGE_GAPS),
        )
