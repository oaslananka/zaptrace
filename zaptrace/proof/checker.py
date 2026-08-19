"""Proof check runner — executes checks and collects results."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from zaptrace.core.models import Design
from zaptrace.core.net_identity import canonical_routing_net_ids

from .manifest import CheckDefinition


class CheckStatus(StrEnum):
    """Result status of a single check."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIP = "skip"


@dataclass
class CheckResult:
    """Result of a single proof check."""

    check: CheckDefinition
    status: CheckStatus
    message: str = ""
    details: dict | None = None
    duration_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return self.status == CheckStatus.PASS

    def to_dict(self) -> dict:
        data = {
            "name": self.check.name,
            "category": self.check.category.value,
            "status": self.status.value,
            "message": self.message,
            "duration_ms": round(self.duration_ms, 1),
        }
        extra = self.details
        if extra is not None:
            data["details"] = json.loads(json.dumps(extra, default=str))
        return data


CheckFunction = Callable[..., CheckResult]


def _erc_violation_to_dict(v: object) -> dict:
    """Convert an ERCViolation dataclass to a dict."""
    return asdict(v)  # pyright: ignore[reportArgumentType]


@dataclass
class ProofRunner:
    """Runs a set of proof checks against a design.

    Usage:
        runner = ProofRunner(design)
        results = runner.run_checks([
            CheckDefinition(name="drc", type="drc"),
            CheckDefinition(name="routed", type="routed"),
        ])
    """

    design: Design
    _registry: dict[str, CheckFunction] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._register_builtins()

    def _register_builtins(self) -> None:
        self.register("drc", self._check_drc)
        self.register("erc", self._check_erc)
        self.register("routed", self._check_routed)
        self.register("clearance", self._check_clearance)
        self.register("footprint_exists", self._check_footprint_exists)
        self.register("net_connected", self._check_net_connected)
        self.register("spice", self._check_spice)
        self.register("signal_integrity", self._check_signal_integrity)
        self.register("thermal", self._check_thermal)
        self.register("kicad_erc", self._check_kicad_erc)
        self.register("kicad_drc", self._check_kicad_drc)
        self.register("dfm", self._check_dfm)

    def register(self, name: str, func: CheckFunction) -> None:
        """Register a custom check function."""
        self._registry[name] = func

    def run_checks(
        self,
        checks: list[CheckDefinition],
    ) -> list[CheckResult]:
        """Run a list of checks and return results."""
        results = []
        for check in checks:
            results.append(self._run_single(check))
        return results

    def _run_single(self, check: CheckDefinition) -> CheckResult:
        start = time.perf_counter()
        try:
            func = self._registry.get(check.type)
            if func is None:
                return CheckResult(
                    check=check,
                    status=CheckStatus.SKIP,
                    message=f"Unknown check type: {check.type}",
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
            result = func(check)
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result
        except Exception as e:
            return CheckResult(
                check=check,
                status=CheckStatus.ERROR,
                message=f"Check raised exception: {e}",
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    def _check_drc(self, check: CheckDefinition) -> CheckResult:
        """Run design rule checks."""
        # Delegate to zaptrace's DRC engine
        try:
            from zaptrace.ee.drc import DRCEngine

            result = DRCEngine().run(self.design)
            expected_ok = check.expected_count is None or len(result.violations) <= check.expected_count
            return CheckResult(
                check=check,
                status=CheckStatus.PASS if expected_ok else CheckStatus.FAIL,
                message=f"{len(result.violations)} DRC violations found",
                details={"violations": [v.model_dump() for v in result.violations]},
            )
        except ImportError:
            return CheckResult(
                check=check,
                status=CheckStatus.SKIP,
                message="DRC engine not available",
            )

    def _check_erc(self, check: CheckDefinition) -> CheckResult:
        """Run electrical rule checks."""
        try:
            from zaptrace.erc.runner import ERCRunner

            result = ERCRunner().run(self.design)
            expected_ok = check.expected_count is None or len(result.violations) <= check.expected_count
            return CheckResult(
                check=check,
                status=CheckStatus.PASS if expected_ok else CheckStatus.FAIL,
                message=f"{len(result.violations)} ERC violations found",
                details={"violations": [_erc_violation_to_dict(v) for v in result.violations]},
            )
        except ImportError:
            return CheckResult(
                check=check,
                status=CheckStatus.SKIP,
                message="ERC engine not available",
            )

    def _check_routed(self, check: CheckDefinition) -> CheckResult:
        """Check that all nets are fully routed."""
        routing = self.design.routing
        canonical_routing_net_ids(self.design, routing)
        routed_nets: set[str] = set()
        if routing is not None:
            for trace in routing.traces:
                if trace.net_id:
                    routed_nets.add(trace.net_id)
        unrouted = [net.name for net in self.design.nets.values() if net.id not in routed_nets]
        passed = len(unrouted) == 0
        return CheckResult(
            check=check,
            status=CheckStatus.PASS if passed else CheckStatus.FAIL,
            message=f"{len(unrouted)} unrouted nets" if unrouted else "All nets routed",
            details={"unrouted_nets": unrouted},
        )

    def _check_clearance(self, check: CheckDefinition) -> CheckResult:
        """Check minimum clearance between copper features."""
        min_c = check.params.get("min_clearance_mm", 0.15)
        violations = self._find_clearance_violations(min_c)
        passed = len(violations) == 0
        return CheckResult(
            check=check,
            status=CheckStatus.PASS if passed else CheckStatus.FAIL,
            message=f"{len(violations)} clearance violations" if violations else f"All clearances >= {min_c}mm",
            details={"violations": violations, "min_clearance_mm": min_c},
        )

    def _check_footprint_exists(self, check: CheckDefinition) -> CheckResult:
        """Check that all components have footprint definitions."""
        missing = [comp.ref for comp in self.design.components.values() if not getattr(comp, "footprint", None)]
        passed = len(missing) == 0
        return CheckResult(
            check=check,
            status=CheckStatus.PASS if passed else CheckStatus.FAIL,
            message=f"{len(missing)} missing footprints" if missing else "All footprints found",
            details={"missing_footprints": missing},
        )

    def _check_net_connected(self, check: CheckDefinition) -> CheckResult:
        """Check a specific net is connected to expected pins."""
        net_name = check.params.get("net_name", "")
        expected_pins = check.params.get("expected_pins", [])

        if not net_name:
            return CheckResult(
                check=check,
                status=CheckStatus.ERROR,
                message="net_name param required",
            )

        net = next((n for n in self.design.nets.values() if n.name == net_name), None)
        if net is None:
            return CheckResult(
                check=check,
                status=CheckStatus.FAIL,
                message=f"Net '{net_name}' not found",
            )

        connected = [node.pin_name for node in net.nodes]
        missing = [p for p in expected_pins if p not in connected]
        passed = len(missing) == 0
        if missing:
            msg = f"Net '{net_name}': {len(missing)} missing connections"
        else:
            msg = f"Net '{net_name}': all connections OK"
        return CheckResult(
            check=check,
            status=CheckStatus.PASS if passed else CheckStatus.FAIL,
            message=msg,
            details={"net": net_name, "missing_pins": missing},
        )

    def _check_spice(self, check: CheckDefinition) -> CheckResult:
        """Export design as SPICE netlist and verify unsupported components are reported."""
        try:
            from zaptrace.export.spice import export_spice_netlist  # pyright: ignore[reportMissingImports]

            netlist = export_spice_netlist(self.design)
            has_warnings = "WARNING" in netlist or "Unsupported" in netlist
            unsupported = []
            for line in netlist.splitlines():
                if "Unsupported" in line:
                    unsupported.append(line.replace("*   ", "").replace("* ", ""))

            details = {
                "netlist_length": len(netlist),
                "unsupported_count": len(unsupported),
                "unsupported_components": unsupported,
            }
            passed = not has_warnings
            return CheckResult(
                check=check,
                status=CheckStatus.PASS if passed else CheckStatus.FAIL,
                message=f"SPICE netlist exported ({len(netlist)} chars, {len(unsupported)} unsupported)"
                if has_warnings
                else "SPICE netlist exported cleanly",
                details=details,
            )
        except Exception as e:
            return CheckResult(
                check=check,
                status=CheckStatus.ERROR,
                message=f"SPICE export failed: {e}",
            )

    def _check_signal_integrity(self, check: CheckDefinition) -> CheckResult:
        """Run SI analysis on the design."""
        try:
            from zaptrace.analysis.reports import run_analysis  # pyright: ignore[reportMissingImports]

            report = run_analysis(self.design)
            imp_violations = [e for e in report.impedance if e.tolerance_pct is not None and abs(e.tolerance_pct) > 10]
            lm_violations = [e for e in report.length_match if not e.within_tolerance]
            total = len(imp_violations) + len(lm_violations)
            passed = total == 0
            return CheckResult(
                check=check,
                status=CheckStatus.PASS if passed else CheckStatus.FAIL,
                message=f"{total} SI issues: {len(imp_violations)} impedance, {len(lm_violations)} length-match"
                if total
                else "SI analysis clean",
                details={
                    "impedance_violations": [e.net_name for e in imp_violations],
                    "length_match_violations": [e.group_name for e in lm_violations],
                    "impedance_count": len(imp_violations),
                    "length_match_count": len(lm_violations),
                },
            )
        except ImportError as exc:
            return CheckResult(
                check=check,
                status=CheckStatus.SKIP,
                message=f"SI analysis not available: {exc}",
            )

    def _check_thermal(self, check: CheckDefinition) -> CheckResult:
        """Run thermal analysis on the design."""
        try:
            from zaptrace.analysis.reports import run_analysis  # pyright: ignore[reportMissingImports]

            report = run_analysis(self.design)
            hot = [e for e in report.thermal if e.estimated_temp_rise_c > 60]
            passed = len(hot) == 0
            return CheckResult(
                check=check,
                status=CheckStatus.PASS if passed else CheckStatus.FAIL,
                message=f"{len(hot)} components above 60°C rise" if hot else "Thermal analysis clean",
                details={
                    "hot_components": [e.component_ref for e in hot],
                    "hot_count": len(hot),
                    "total_components_analyzed": len(report.thermal),
                },
            )
        except ImportError as exc:
            return CheckResult(
                check=check,
                status=CheckStatus.SKIP,
                message=f"Thermal analysis not available: {exc}",
            )

    def _check_dfm(self, check: CheckDefinition) -> CheckResult:
        """Run DFM (Design for Manufacturing) checks against a fab profile."""
        profile_name = check.params.get("profile", "jlcpcb-2layer")
        try:
            from zaptrace.fab.dfm import DFMChecker
            from zaptrace.fab.profile import load_profile

            profile = load_profile(profile_name)
            checker = DFMChecker(profile)
            dfm_result = checker.check(self.design)
            passed = dfm_result.passed
            return CheckResult(
                check=check,
                status=CheckStatus.PASS if passed else CheckStatus.FAIL,
                message=f"DFM: {dfm_result.errors} errors, {dfm_result.warnings} warnings"
                if not passed
                else f"DFM passed against {profile_name}",
                details=dfm_result.to_dict(),
            )
        except ValueError as e:
            return CheckResult(
                check=check,
                status=CheckStatus.ERROR,
                message=f"DFM check failed: {e}",
            )

    def _check_kicad_erc(self, check: CheckDefinition) -> CheckResult:
        """Run KiCad ERC via KiCadOracle."""
        from zaptrace.kicad.oracle import KiCadOracle

        sch_path = check.params.get("schematic_path", "")
        if not sch_path:
            return CheckResult(check=check, status=CheckStatus.ERROR, message="schematic_path param required")
        oracle = KiCadOracle()
        if not oracle.available:
            return CheckResult(check=check, status=CheckStatus.SKIP, message="KiCad CLI not available")
        result = oracle.run_erc(sch_path)
        if result.errors > 0 or not result.success:
            return CheckResult(
                check=check, status=CheckStatus.ERROR, message=result.message or f"{result.errors} ERC errors"
            )
        vc = len(result.violations)
        expected_ok = check.expected_count is None or vc <= check.expected_count
        return CheckResult(
            check=check,
            status=CheckStatus.PASS if expected_ok else CheckStatus.FAIL,
            message=f"{vc} KiCad ERC violations",
            details={
                "violation_count": vc,
                "warnings": result.warnings,
                "errors": result.errors,
                "violations": [v.__dict__ for v in result.violations],
                "kicad_version": oracle.version,
            },
        )

    def _check_kicad_drc(self, check: CheckDefinition) -> CheckResult:
        """Run KiCad DRC via KiCadOracle."""
        from zaptrace.kicad.oracle import KiCadOracle

        pcb_path = check.params.get("pcb_path", "")
        if not pcb_path:
            return CheckResult(check=check, status=CheckStatus.ERROR, message="pcb_path param required")
        oracle = KiCadOracle()
        if not oracle.available:
            return CheckResult(check=check, status=CheckStatus.SKIP, message="KiCad CLI not available")
        result = oracle.run_drc(pcb_path)
        if result.errors > 0 or not result.success:
            return CheckResult(
                check=check, status=CheckStatus.ERROR, message=result.message or f"{result.errors} DRC errors"
            )
        vc = len(result.violations)
        expected_ok = check.expected_count is None or vc <= check.expected_count
        return CheckResult(
            check=check,
            status=CheckStatus.PASS if expected_ok else CheckStatus.FAIL,
            message=f"{vc} KiCad DRC violations",
            details={
                "violation_count": vc,
                "warnings": result.warnings,
                "errors": result.errors,
                "violations": [v.__dict__ for v in result.violations],
                "kicad_version": oracle.version,
            },
        )

    def _find_clearance_violations(self, min_clearance: float) -> list[dict]:
        """Find copper clearance violations in the design."""
        violations = []
        traces = self.design.routing.traces if self.design.routing else []
        for i, t1 in enumerate(traces):
            for t2 in traces[i + 1 :]:
                if t1.net_id and t2.net_id and t1.net_id == t2.net_id:
                    continue  # Same net, skip
                dist = self._trace_distance(t1, t2)
                if dist < min_clearance:
                    violations.append(
                        {
                            "trace1": t1.net_id,
                            "trace2": t2.net_id,
                            "distance_mm": round(dist, 4),
                            "min_clearance_mm": min_clearance,
                        }
                    )
        return violations

    @staticmethod
    def _trace_distance(t1: object, t2: object) -> float:
        """Minimum Euclidean distance between two trace segments."""
        try:
            a = (t1.start[0], t1.start[1])  # type: ignore[union-attr]
            b = (t1.end[0], t1.end[1])  # type: ignore[union-attr]
            c = (t2.start[0], t2.start[1])  # type: ignore[union-attr]
            d = (t2.end[0], t2.end[1])  # type: ignore[union-attr]
            return min(
                ProofRunner._point_segment_dist(a, c, d),
                ProofRunner._point_segment_dist(b, c, d),
                ProofRunner._point_segment_dist(c, a, b),
                ProofRunner._point_segment_dist(d, a, b),
            )
        except (AttributeError, IndexError, TypeError):
            return float("inf")

    @staticmethod
    def _point_segment_dist(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        """Minimum distance from point P to segment AB."""
        px, py = p
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        proj_x = ax + t * dx
        proj_y = ay + t * dy
        return ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5
