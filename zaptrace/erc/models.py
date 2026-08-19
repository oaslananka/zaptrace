from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ERCSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ERCViolation:
    rule_id: str
    severity: ERCSeverity
    message: str
    component_refs: list[str] = field(default_factory=list)
    net_refs: list[str] = field(default_factory=list)
    patch_suggestion: str | None = None
    waiver_reason: str | None = None

    @property
    def is_waived(self) -> bool:
        return self.waiver_reason is not None


@dataclass
class ERCCheck:
    """Record of a single ERC rule that was executed.

    Lets an ERC result honestly report *what was checked* — not just the
    violations found — so a bare "passed" cannot be mistaken for "verified".
    """

    rule_id: str
    title: str
    category: str
    violation_count: int


@dataclass
class ERCResult:
    violations: list[ERCViolation]
    design_name: str
    total_errors: int
    total_warnings: int
    total_info: int
    checks_run: list[ERCCheck] = field(default_factory=list)
    coverage_gaps: list[str] = field(default_factory=list)

    total_waivers: int = 0

    @classmethod
    def from_violations(
        cls,
        violations: list[ERCViolation],
        design_name: str,
        checks_run: list[ERCCheck] | None = None,
        coverage_gaps: list[str] | None = None,
    ) -> ERCResult:
        active = [v for v in violations if not v.is_waived]
        return cls(
            violations=violations,
            design_name=design_name,
            total_errors=sum(1 for v in active if v.severity == ERCSeverity.ERROR),
            total_warnings=sum(1 for v in active if v.severity == ERCSeverity.WARNING),
            total_info=sum(1 for v in active if v.severity == ERCSeverity.INFO),
            total_waivers=sum(1 for v in violations if v.is_waived),
            checks_run=checks_run or [],
            coverage_gaps=coverage_gaps or [],
        )

    @property
    def active_violations(self) -> list[ERCViolation]:
        """Violations that are not waived."""
        return [v for v in self.violations if not v.is_waived]

    @property
    def waived_violations(self) -> list[ERCViolation]:
        """Violations suppressed by a human waiver."""
        return [v for v in self.violations if v.is_waived]

    @property
    def passed(self) -> bool:
        return self.total_errors == 0

    @property
    def categories_covered(self) -> list[str]:
        """Distinct rule categories that were executed, in first-seen order."""
        seen: dict[str, None] = {}
        for check in self.checks_run:
            seen.setdefault(check.category, None)
        return list(seen)

    def coverage_summary(self) -> str:
        """One-line honest summary of what ERC actually checked.

        Reads ``"22 checks run across 9 categories (connectivity, power, …);
        N coverage gap(s) noted"`` so a passing result advertises its scope and
        its limits instead of an unqualified "passed".
        """
        n_checks = len(self.checks_run)
        cats = self.categories_covered
        cat_str = ", ".join(cats) if cats else "none"
        summary = f"{n_checks} check(s) run across {len(cats)} categor{'y' if len(cats) == 1 else 'ies'} ({cat_str})"
        if self.total_waivers:
            summary += f"; {self.total_waivers} violation(s) waived"
        if self.coverage_gaps:
            summary += f"; {len(self.coverage_gaps)} coverage gap(s) noted"
        return summary
