"""SPICE simulation orchestrator.

Ties the SPICE export and the ngspice runner into a single evidence-bearing
workflow:

1. Export a SPICE netlist from a :class:`~zaptrace.core.models.Design`.
2. Run ngspice operating-point analysis (skip-aware — returns a ``skipped``
   result if ngspice is not installed, mirroring the KiCad oracle).
3. Validate node voltages against expected values.
4. Return a structured :class:`SpiceOrchestrationResult` suitable for
   inclusion in a Proof Pack.

This is not a full SPICE wrapper: only DC operating-point (``.op``) analysis
is orchestrated. Transient and AC analysis require device models not yet
in the library and are out of scope for the automated flow.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from zaptrace.analysis.spice_sim import SpiceResult, run_operating_point
from zaptrace.core.models import Design, NetType
from zaptrace.export.spice import export_spice_netlist


@dataclass
class NodeVoltageCheck:
    """Expected-vs-simulated voltage check for a single net."""

    net_name: str
    expected_v: float | None
    simulated_v: float | None
    tolerance_pct: float
    passed: bool | None  # None when no expected value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SpiceOrchestrationResult:
    """Evidence record from a SPICE orchestration run.

    ``status`` is ``"ok"``, ``"skipped"``, or ``"error"``. ``checks``
    contains per-node voltage validations when a reference map is supplied.
    """

    status: str
    design_name: str
    netlist_lines: int
    skipped_components: int
    node_voltages: dict[str, float] = field(default_factory=dict)
    checks: list[NodeVoltageCheck] = field(default_factory=list)
    raw_reason: str = ""
    all_checks_passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def orchestrate_spice(
    design: Design,
    *,
    expected_voltages: dict[str, float] | None = None,
    tolerance_pct: float = 5.0,
    timeout_s: float = 30.0,
) -> SpiceOrchestrationResult:
    """Export, simulate, and validate a DC operating point.

    Args:
        design: Design to simulate.
        expected_voltages: Optional map of net name → expected voltage (V).
            When supplied, each simulated node is validated against the
            expected value within ``tolerance_pct``.
        tolerance_pct: Acceptable voltage error percentage (default 5 %).
        timeout_s: ngspice timeout in seconds.

    Returns:
        A :class:`SpiceOrchestrationResult` with evidence of the simulation.
        When ngspice is not installed, ``status="skipped"`` is returned and
        no checks are run — the result is still recordable as evidence.
    """
    from zaptrace.analysis.dc_bias import behavioral_source_cards

    netlist = export_spice_netlist(design, extra_cards=behavioral_source_cards(design))
    lines = netlist.count("\n")
    skipped_count = sum(1 for line in netlist.splitlines() if line.startswith("* Unsupported:"))

    sim: SpiceResult = run_operating_point(netlist, timeout_s=timeout_s)

    checks: list[NodeVoltageCheck] = []
    all_passed = True

    if sim.status == "ok" and expected_voltages:
        # Build net-name → simulated voltage lookup (ngspice node names are lower-cased)
        simulated = {k.lower(): v for k, v in sim.node_voltages.items()}
        for net_name, expected in expected_voltages.items():
            sim_v = simulated.get(net_name.lower())
            if sim_v is None:
                passed = None  # cannot check, node not in output
            else:
                passed = abs(sim_v - expected) / max(abs(expected), 1e-9) <= tolerance_pct / 100.0
                if not passed:
                    all_passed = False
            checks.append(
                NodeVoltageCheck(
                    net_name=net_name,
                    expected_v=expected,
                    simulated_v=sim_v,
                    tolerance_pct=tolerance_pct,
                    passed=passed,
                )
            )

    return SpiceOrchestrationResult(
        status=sim.status,
        design_name=design.meta.name,
        netlist_lines=lines,
        skipped_components=skipped_count,
        node_voltages=sim.node_voltages,
        checks=checks,
        raw_reason=sim.reason,
        all_checks_passed=all_passed,
    )


def annotate_design_from_spice(design: Design, result: SpiceOrchestrationResult) -> dict[str, float]:
    """Return a net_name→voltage map for nets in the design from a simulation result.

    Only returns nets that have a matching simulated node voltage. Useful for
    annotating a design report with DC bias point results from a simulation.
    """
    if result.status != "ok" or not result.node_voltages:
        return {}
    simulated = {k.lower(): v for k, v in result.node_voltages.items()}
    annotation: dict[str, float] = {}
    for net in design.nets.values():
        node = net.name.lower()
        if node in simulated:
            annotation[net.name] = simulated[node]
        elif net.type == NetType.GROUND:
            annotation[net.name] = 0.0
    return annotation
