"""DC operating-point as a blocking verification gate.

:mod:`zaptrace.analysis.spice_orchestrator` produces advisory simulation
evidence. This wraps it as a *gate* with the discipline from
``docs/design/autonomous-synthesis.md``:

* **An explicit skip is recorded, never a silent pass.** When ngspice is absent
  the gate returns ``SKIPPED`` (not ``PASS``); in **strict** mode a skip is
  *blocking*, so a release cannot quietly ship un-simulated.
* **A verified pass is distinct from "nothing was checked."** A run with no
  expected voltages returns ``NO_REFERENCE``, not ``PASS`` — an empty reference
  can never read as success.

The simulator itself is bundled in the container image (see ``Dockerfile``), so
in CI a skip means a real environment problem, not an accepted gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from zaptrace.analysis.spice_orchestrator import orchestrate_spice

if TYPE_CHECKING:
    from zaptrace.core.models import Design

_STRICT_BLOCKING_REASON_SUFFIX = " (blocking in strict mode)"


class GateStatus(StrEnum):
    """Outcome of the simulation gate."""

    PASS = "pass"  # ran and every expected rail is within tolerance
    FAIL = "fail"  # ran and a rail is out of tolerance, or ngspice errored
    SKIPPED = "skipped"  # ngspice unavailable — explicitly recorded
    NO_REFERENCE = "no_reference"  # ran but there was nothing to check against


@dataclass
class SimulationGateResult:
    """A blocking verdict plus the evidence behind it."""

    status: GateStatus
    blocking: bool
    strict: bool
    design_name: str
    reason: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    node_voltages: dict[str, float] = field(default_factory=dict)

    @property
    def satisfied(self) -> bool:
        """True when the gate does not block the pipeline."""
        return not self.blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "blocking": self.blocking,
            "satisfied": self.satisfied,
            "strict": self.strict,
            "design_name": self.design_name,
            "reason": self.reason,
            "checks": self.checks,
            "node_voltages": self.node_voltages,
        }


def _gate_verdict(
    orchestration_status: str,
    all_checks_passed: bool,
    has_checks: bool,
    strict: bool,
) -> tuple[GateStatus, bool, str]:
    """Pure mapping from an orchestration outcome to (status, blocking, reason).

    Kept free of I/O so every branch is unit-testable without ngspice installed.
    """
    if orchestration_status == "skipped":
        reason = "ngspice not available; recorded as an explicit skip"
        if strict:
            reason += _STRICT_BLOCKING_REASON_SUFFIX
        return GateStatus.SKIPPED, strict, reason
    if orchestration_status == "error":
        return GateStatus.FAIL, True, "ngspice ran but failed or timed out"
    # orchestration_status == "ok"
    if not has_checks:
        return GateStatus.NO_REFERENCE, strict, "simulation ran but no expected voltages were supplied to check"
    if all_checks_passed:
        return GateStatus.PASS, False, "all expected rail voltages are within tolerance"
    return GateStatus.FAIL, True, "a simulated rail voltage is outside tolerance"


def run_simulation_gate(
    design: Design,
    *,
    expected_voltages: dict[str, float] | None = None,
    tolerance_pct: float = 5.0,
    strict: bool = False,
    timeout_s: float = 30.0,
) -> SimulationGateResult:
    """Run the DC operating-point gate on *design*.

    With no ``expected_voltages``, rail references are derived from the design's
    power-rail net names via :func:`expected_rail_voltages`, so the gate has
    something to check by default.
    """
    references = expected_voltages if expected_voltages is not None else expected_rail_voltages(design)
    orchestration = orchestrate_spice(
        design,
        expected_voltages=references or None,
        tolerance_pct=tolerance_pct,
        timeout_s=timeout_s,
    )
    has_checks = any(check.passed is not None for check in orchestration.checks)
    status, blocking, reason = _gate_verdict(orchestration.status, orchestration.all_checks_passed, has_checks, strict)
    return SimulationGateResult(
        status=status,
        blocking=blocking,
        strict=strict,
        design_name=orchestration.design_name,
        reason=reason,
        checks=[check.to_dict() for check in orchestration.checks],
        node_voltages=orchestration.node_voltages,
    )


def expected_rail_voltages(design: Design) -> dict[str, float]:
    """Derive expected rail voltages from the synthesis net-name convention.

    ``VDD_3V3`` -> 3.3, ``VDD_5`` -> 5.0, and any ground net -> 0.0. Returns only
    nets it can parse, so an unrecognized net never produces a bogus reference.
    """
    from zaptrace.core.models import NetType

    references: dict[str, float] = {}
    for net in design.nets.values():
        if net.type == NetType.GROUND:
            references[net.name] = 0.0
            continue
        volts = _rail_net_to_volts(net.name)
        if volts is not None:
            references[net.name] = volts
    return references


def _rail_net_to_volts(net_name: str) -> float | None:
    """Inverse of the ``VDD_<v>`` rail-net convention: 'VDD_3V3' -> 3.3."""
    if not net_name.startswith("VDD_"):
        return None
    token = net_name[len("VDD_") :].replace("V", ".", 1).rstrip(".")
    # A trailing 'V' (e.g. "5V") becomes "5." -> strip to "5"; "3V3" -> "3.3".
    try:
        return float(token)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Transient simulation gate
# ---------------------------------------------------------------------------


@dataclass
class TransientCheck:
    """One pass/fail assertion against a transient waveform.

    Attributes
    ----------
    name:
        Human-readable check label (e.g. ``"startup_time_us"``).
    passed:
        ``True`` = pass, ``False`` = fail, ``None`` = not evaluated.
    actual:
        Measured value (or ``None`` if not available).
    reference:
        Expected threshold used for the comparison.
    unit:
        Unit string for display (e.g. ``"us"``, ``"mV"``).
    """

    name: str
    passed: bool | None
    actual: float | None
    reference: float | None
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "actual": self.actual,
            "reference": self.reference,
            "unit": self.unit,
        }


@dataclass
class TransientGateResult:
    """Blocking verdict for a transient simulation gate.

    Attributes
    ----------
    status:
        One of ``"pass"``, ``"fail"``, ``"skipped"``, or ``"no_reference"``.
    blocking:
        ``True`` when this result prevents the pipeline from proceeding.
    strict:
        Whether strict mode was enabled (skip → blocking).
    design_name:
        Name of the design that was simulated.
    reason:
        One-line human explanation of the outcome.
    node:
        The net name that was simulated (e.g. ``"vout"``).
    checks:
        Per-assertion results.
    model_degraded:
        ``True`` when a placeholder/behavioural model was used.
    model_source:
        Provenance string for the model (``"fixture:v1.0"`` etc.).
    """

    status: str
    blocking: bool
    strict: bool
    design_name: str
    reason: str
    node: str = ""
    checks: list[TransientCheck] = field(default_factory=list)
    model_degraded: bool = False
    model_source: str = ""

    @property
    def satisfied(self) -> bool:
        return not self.blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blocking": self.blocking,
            "satisfied": self.satisfied,
            "strict": self.strict,
            "design_name": self.design_name,
            "reason": self.reason,
            "node": self.node,
            "model_degraded": self.model_degraded,
            "model_source": self.model_source,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass
class TransientReference:
    """Reference thresholds for one switching-regulator transient gate.

    Attributes
    ----------
    node:
        Net name to measure (e.g. ``"vout"``).
    target_v:
        Expected steady-state output voltage (volts).
    max_startup_us:
        Maximum allowed startup time in microseconds, or ``None`` to skip check.
    max_ripple_mv:
        Maximum allowed steady-state ripple in millivolts, or ``None`` to skip.
    max_steady_state_error_pct:
        Maximum absolute error of the steady-state average from ``target_v``.
        ``None`` preserves the legacy startup/ripple-only contract.
    model_source:
        Provenance string for the behavioral model (version + hash).
    model_degraded:
        Whether this reference uses a degraded/approximate model.
    """

    node: str
    target_v: float
    max_startup_us: float | None = None
    max_ripple_mv: float | None = None
    max_steady_state_error_pct: float | None = None
    model_source: str = ""
    model_degraded: bool = False


def _steady_state_voltage_check(
    waveform: Any,
    reference: TransientReference,
) -> TransientCheck | None:
    """Build the optional steady-state voltage-accuracy check."""
    limit = reference.max_steady_state_error_pct
    if limit is None:
        return None
    if not waveform or not waveform.voltages_v:
        return TransientCheck(
            name="steady_state_voltage_error",
            passed=False,
            actual=None,
            reference=limit,
            unit="%",
        )
    window = waveform.steady_state_window()
    average_v = (sum(window) / len(window)) if window else None
    error_pct = (
        abs(average_v - reference.target_v) / reference.target_v * 100.0
        if average_v is not None and reference.target_v != 0
        else None
    )
    return TransientCheck(
        name="steady_state_voltage_error",
        passed=error_pct is not None and error_pct <= limit,
        actual=error_pct,
        reference=limit,
        unit="%",
    )


def _evaluate_transient_checks(
    waveform: Any,
    reference: TransientReference,
) -> list[TransientCheck]:
    """Evaluate every configured transient reference against one waveform."""
    checks: list[TransientCheck] = []
    if reference.max_startup_us is not None:
        if waveform and waveform.times_s:
            actual_s = waveform.startup_time_s(reference.target_v)
            actual_us = (actual_s * 1e6) if actual_s is not None else None
            passed = actual_us is not None and actual_us <= reference.max_startup_us
        else:
            actual_us = None
            passed = False
        checks.append(
            TransientCheck(
                name="startup_time",
                passed=passed,
                actual=actual_us,
                reference=reference.max_startup_us,
                unit="us",
            )
        )

    steady_state_check = _steady_state_voltage_check(waveform, reference)
    if steady_state_check is not None:
        checks.append(steady_state_check)

    if reference.max_ripple_mv is not None:
        if waveform and len(waveform.voltages_v) >= 2:
            ripple_mv = waveform.ripple_v() * 1000.0
            passed = ripple_mv <= reference.max_ripple_mv
        else:
            ripple_mv = None
            passed = False
        checks.append(
            TransientCheck(
                name="steady_state_ripple",
                passed=passed,
                actual=ripple_mv,
                reference=reference.max_ripple_mv,
                unit="mV",
            )
        )
    return checks


def run_transient_gate(
    netlist: str,
    reference: TransientReference,
    *,
    design_name: str = "",
    step_s: float = 1e-9,
    stop_s: float = 100e-6,
    timeout_s: float = 60.0,
    strict: bool = False,
) -> TransientGateResult:
    """Run a transient simulation gate for a switching-regulator design.

    Parameters
    ----------
    netlist:
        SPICE netlist (without ``.tran`` or ``.control``).
    reference:
        Threshold configuration with provenance metadata.
    design_name:
        Label for the gate result.
    step_s:
        Timestep in seconds.
    stop_s:
        Stop time in seconds.
    timeout_s:
        Wall-clock timeout for ngspice.
    strict:
        If ``True``, a ``SKIPPED`` result is blocking.

    Returns
    -------
    TransientGateResult
        ``status="skipped"`` when ngspice is absent;
        ``status="no_reference"`` when all checks are disabled;
        ``status="pass"`` / ``"fail"`` based on check outcomes.
    """
    from zaptrace.analysis.spice_sim import run_transient

    tran = run_transient(
        netlist,
        reference.node,
        step_s=step_s,
        stop_s=stop_s,
        timeout_s=timeout_s,
    )

    if tran.status == "skipped":
        reason = "ngspice not available; recorded as explicit skip"
        if strict:
            reason += _STRICT_BLOCKING_REASON_SUFFIX
        return TransientGateResult(
            status="skipped",
            blocking=strict,
            strict=strict,
            design_name=design_name,
            reason=reason,
            node=reference.node,
            model_degraded=reference.model_degraded,
            model_source=reference.model_source,
        )

    if tran.status == "error":
        return TransientGateResult(
            status="fail",
            blocking=True,
            strict=strict,
            design_name=design_name,
            reason=f"ngspice error: {tran.reason}",
            node=reference.node,
            model_degraded=reference.model_degraded,
            model_source=reference.model_source,
        )

    # ngspice ran successfully
    waveform = tran.waveforms.get(reference.node)
    checks = _evaluate_transient_checks(waveform, reference)

    has_checks = len(checks) > 0
    if not has_checks:
        return TransientGateResult(
            status="no_reference",
            blocking=strict,
            strict=strict,
            design_name=design_name,
            reason="simulation ran but no reference thresholds provided",
            node=reference.node,
            model_degraded=reference.model_degraded,
            model_source=reference.model_source,
            checks=checks,
        )

    all_passed = all(c.passed is True for c in checks)
    if all_passed:
        return TransientGateResult(
            status="pass",
            blocking=False,
            strict=strict,
            design_name=design_name,
            reason="all transient checks passed",
            node=reference.node,
            model_degraded=reference.model_degraded,
            model_source=reference.model_source,
            checks=checks,
        )

    failed = [c.name for c in checks if c.passed is False]
    return TransientGateResult(
        status="fail",
        blocking=True,
        strict=strict,
        design_name=design_name,
        reason=f"transient check(s) failed: {failed}",
        node=reference.node,
        model_degraded=reference.model_degraded,
        model_source=reference.model_source,
        checks=checks,
    )


# ---------------------------------------------------------------------------
# AC simulation gate
# ---------------------------------------------------------------------------


@dataclass
class AcCheck:
    """One pass/fail assertion against an AC sweep result.

    Attributes
    ----------
    name:
        Human-readable check label (e.g. ``"gain_at_1khz_db"``, ``"phase_margin"``).
    passed:
        ``True`` = pass, ``False`` = fail, ``None`` = not evaluated.
    actual:
        Measured value, or ``None`` if unavailable.
    reference:
        Configured threshold used for the comparison.
    unit:
        Unit string for display (e.g. ``"dB"``, ``"deg"``, ``"Hz"``).
    """

    name: str
    passed: bool | None
    actual: float | None
    reference: float | None
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "actual": self.actual,
            "reference": self.reference,
            "unit": self.unit,
        }


@dataclass
class AcReference:
    """Reference thresholds for one AC-analysis gate.

    Attributes
    ----------
    node:
        Net name to probe (e.g. ``"vout"``).
    min_gain_db:
        Minimum gain in dB at ``gain_check_hz``, or ``None`` to skip.
    gain_check_hz:
        Frequency for the gain check (default: 1 kHz).
    max_gain_db:
        Maximum gain in dB at ``gain_check_hz``, or ``None`` to skip.
    min_phase_margin_deg:
        Minimum phase margin in degrees, or ``None`` to skip.
    min_crossover_hz:
        Minimum crossover frequency in Hz, or ``None`` to skip.
    max_crossover_hz:
        Maximum crossover frequency in Hz, or ``None`` to skip.
    model_source:
        Provenance string for the model.
    model_degraded:
        Whether the reference uses an approximate model.
    """

    node: str
    min_gain_db: float | None = None
    gain_check_hz: float = 1e3
    max_gain_db: float | None = None
    min_phase_margin_deg: float | None = None
    min_crossover_hz: float | None = None
    max_crossover_hz: float | None = None
    model_source: str = ""
    model_degraded: bool = False


@dataclass
class AcGateResult:
    """Blocking verdict for an AC simulation gate.

    ``model_degraded`` is always included in :meth:`to_dict` — a degraded model
    can never yield a silent PASS.

    Attributes
    ----------
    status:
        One of ``"pass"``, ``"fail"``, ``"skipped"``, or ``"no_reference"``.
    blocking:
        ``True`` when this result prevents the pipeline from proceeding.
    strict:
        Whether strict mode was enabled (skip → blocking).
    design_name:
        Name of the design that was simulated.
    reason:
        One-line human explanation of the outcome.
    node:
        Net name that was probed.
    checks:
        Per-assertion results.
    model_degraded:
        Always visible in serialisation; ``True`` when model is approximate.
    model_source:
        Provenance string for the model (version + hash).
    """

    status: str
    blocking: bool
    strict: bool
    design_name: str
    reason: str
    node: str = ""
    checks: list[AcCheck] = field(default_factory=list)
    model_degraded: bool = False
    model_source: str = ""

    @property
    def satisfied(self) -> bool:
        return not self.blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blocking": self.blocking,
            "satisfied": self.satisfied,
            "strict": self.strict,
            "design_name": self.design_name,
            "reason": self.reason,
            "node": self.node,
            "model_degraded": self.model_degraded,
            "model_source": self.model_source,
            "checks": [c.to_dict() for c in self.checks],
        }


def _gain_checks(ac: Any, reference: AcReference) -> list[AcCheck]:
    if reference.min_gain_db is None and reference.max_gain_db is None:
        return []
    checks: list[AcCheck] = []
    actual_gain = ac.gain_at_hz(reference.gain_check_hz)
    if reference.min_gain_db is not None:
        passed = (actual_gain is not None) and (actual_gain >= reference.min_gain_db)
        checks.append(
            AcCheck(name="min_gain", passed=passed, actual=actual_gain, reference=reference.min_gain_db, unit="dB")
        )
    if reference.max_gain_db is not None:
        passed = (actual_gain is not None) and (actual_gain <= reference.max_gain_db)
        checks.append(
            AcCheck(name="max_gain", passed=passed, actual=actual_gain, reference=reference.max_gain_db, unit="dB")
        )
    return checks


def _phase_margin_checks(ac: Any, reference: AcReference) -> list[AcCheck]:
    if reference.min_phase_margin_deg is None:
        return []
    pm = ac.phase_margin_deg()
    passed = (pm is not None) and (pm >= reference.min_phase_margin_deg)
    return [
        AcCheck(
            name="phase_margin", passed=passed, actual=pm, reference=reference.min_phase_margin_deg, unit="deg"
        )
    ]


def _crossover_checks(ac: Any, reference: AcReference) -> list[AcCheck]:
    if reference.min_crossover_hz is None and reference.max_crossover_hz is None:
        return []
    checks: list[AcCheck] = []
    fc = ac.crossover_hz()
    if reference.min_crossover_hz is not None:
        passed = (fc is not None) and (fc >= reference.min_crossover_hz)
        checks.append(
            AcCheck(name="min_crossover", passed=passed, actual=fc, reference=reference.min_crossover_hz, unit="Hz")
        )
    if reference.max_crossover_hz is not None:
        passed = (fc is not None) and (fc <= reference.max_crossover_hz)
        checks.append(
            AcCheck(name="max_crossover", passed=passed, actual=fc, reference=reference.max_crossover_hz, unit="Hz")
        )
    return checks


def run_ac_gate(
    netlist: str,
    reference: AcReference,
    *,
    design_name: str = "",
    variation: str = "dec",
    points_per_decade: int = 20,
    start_hz: float = 1.0,
    stop_hz: float = 10e6,
    timeout_s: float = 30.0,
    strict: bool = False,
) -> AcGateResult:
    """Run an AC simulation gate for a given netlist and reference.

    Parameters
    ----------
    netlist:
        SPICE netlist (without ``.ac`` or ``.control`` block).
    reference:
        Threshold configuration with provenance metadata.
    design_name:
        Label for the gate result.
    variation:
        ngspice sweep type (``"dec"``, ``"oct"``, or ``"lin"``).
    points_per_decade:
        Points per decade for the frequency sweep.
    start_hz:
        Start frequency in hertz.
    stop_hz:
        Stop frequency in hertz.
    timeout_s:
        Wall-clock timeout for ngspice.
    strict:
        If ``True``, a ``SKIPPED`` result is blocking.

    Returns
    -------
    AcGateResult
        ``status="skipped"`` when ngspice is absent;
        ``status="no_reference"`` when all checks are disabled;
        ``status="pass"`` / ``"fail"`` based on check outcomes.
    """
    from zaptrace.analysis.spice_sim import run_ac

    ac = run_ac(
        netlist,
        reference.node,
        variation=variation,
        points_per_decade=points_per_decade,
        start_hz=start_hz,
        stop_hz=stop_hz,
        timeout_s=timeout_s,
    )

    if ac.status == "skipped":
        reason = "ngspice not available; recorded as explicit skip"
        if strict:
            reason += _STRICT_BLOCKING_REASON_SUFFIX
        return AcGateResult(
            status="skipped",
            blocking=strict,
            strict=strict,
            design_name=design_name,
            reason=reason,
            node=reference.node,
            model_degraded=reference.model_degraded,
            model_source=reference.model_source,
        )

    if ac.status == "error":
        return AcGateResult(
            status="fail",
            blocking=True,
            strict=strict,
            design_name=design_name,
            reason=f"ngspice error: {ac.reason}",
            node=reference.node,
            model_degraded=reference.model_degraded,
            model_source=reference.model_source,
        )

    # ngspice ran successfully — evaluate checks
    checks: list[AcCheck] = [
        *_gain_checks(ac, reference),
        *_phase_margin_checks(ac, reference),
        *_crossover_checks(ac, reference),
    ]

    if not checks:
        return AcGateResult(
            status="no_reference",
            blocking=strict,
            strict=strict,
            design_name=design_name,
            reason="simulation ran but no reference thresholds provided",
            node=reference.node,
            model_degraded=reference.model_degraded,
            model_source=reference.model_source,
        )

    all_passed = all(c.passed is True for c in checks)
    if all_passed:
        return AcGateResult(
            status="pass",
            blocking=False,
            strict=strict,
            design_name=design_name,
            reason="all AC checks passed",
            node=reference.node,
            model_degraded=reference.model_degraded,
            model_source=reference.model_source,
            checks=checks,
        )

    failed = [c.name for c in checks if c.passed is False]
    return AcGateResult(
        status="fail",
        blocking=True,
        strict=strict,
        design_name=design_name,
        reason=f"AC check(s) failed: {failed}",
        node=reference.node,
        model_degraded=reference.model_degraded,
        model_source=reference.model_source,
        checks=checks,
    )
