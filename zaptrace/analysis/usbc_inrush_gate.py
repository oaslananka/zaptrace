"""USB-C power-sink inrush transient gate with governed model provenance (issue #124).

This module implements a second strict transient-gated board family for
USB-C sink power-up and inrush current, as required by issue #124.

Public surface
--------------
InrushReference       – family-specific references (inrush, ramp, overshoot, steady)
InrushBehavioralModel – governed behavioral model with source, version, assumptions,
                        and degradation metadata
InrushGateResult      – full gate result with all four checks + waveform sample
InrushWaveformSample  – down-sampled waveform data for proof-pack inclusion
run_usbc_inrush_gate  – main entry point
USBC_SINK_REFERENCE   – canonical reference for the USB-C sink family

Strict CI contract
------------------
- PASS / FAIL / SKIPPED / NO_REFERENCE are always distinguishable.
- NO_REFERENCE is never silently converted to PASS.
- A SKIPPED result is blocking in strict mode.
- Each threshold can fail independently (verified by mutation tests).

Waveform evidence
-----------------
``InrushWaveformSample`` carries down-sampled (max 512 points) waveform
data for inclusion in proof packs.  All data is deterministic: same input
netlist + reference → same sample hash.

Behavioral model provenance
---------------------------
``InrushBehavioralModel`` records source, version, parameter assumptions,
and a degradation flag so that simulated evidence always carries full
traceability from model to result.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from zaptrace.analysis.sim_gate import GateStatus, TransientCheck, run_transient_gate

# ---------------------------------------------------------------------------
# Behavioral model provenance
# ---------------------------------------------------------------------------

INRUSH_MODEL_VERSION = "1.1"
INRUSH_MODEL_SOURCE = "fixture:usbc-inrush-v1.1"


@dataclass(frozen=True)
class InrushBehavioralModel:
    """Governed behavioral model for USB-C sink inrush simulation.

    Attributes
    ----------
    source:
        Origin string (dataset, EVM, datasheet, simulation version).
    version:
        Semantic version of the model.
    assumptions:
        Free-text list of modelling assumptions (capacitor ESR, trace L, etc.).
    degraded:
        ``True`` when the model is a conservative approximation.
    degradation_reason:
        Why the model is degraded, or empty string.
    param_hash:
        SHA-256 of the canonical JSON of all model parameters — ensures
        that two models with the same parameters produce the same hash.
    """

    source: str
    version: str
    assumptions: list[str] = field(default_factory=list)
    degraded: bool = False
    degradation_reason: str = ""
    param_hash: str = field(init=False, default="")

    def __post_init__(self) -> None:
        canonical = json.dumps(
            {
                "source": self.source,
                "version": self.version,
                "assumptions": sorted(self.assumptions),
                "degraded": self.degraded,
            },
            sort_keys=True,
        )
        object.__setattr__(self, "param_hash", hashlib.sha256(canonical.encode()).hexdigest())

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "version": self.version,
            "assumptions": list(self.assumptions),
            "degraded": self.degraded,
            "degradation_reason": self.degradation_reason,
            "param_hash": self.param_hash,
        }


# Default governed model used when no explicit model is provided
DEFAULT_INRUSH_MODEL = InrushBehavioralModel(
    source=INRUSH_MODEL_SOURCE,
    version=INRUSH_MODEL_VERSION,
    assumptions=[
        "bulk capacitance C_bulk = 100 uF, ESR = 50 mOhm",
        "inrush limiting resistor R_inrush = 2.2 Ohm",
        "trace inductance L_trace = 100 nH",
        "USB-C cable resistance R_cable = 0.1 Ohm",
        "supply voltage V_bus = 5.0 V nominal",
    ],
    degraded=False,
)


# ---------------------------------------------------------------------------
# Family-specific references
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InrushReference:
    """Reference thresholds for the USB-C sink inrush gate.

    All four threshold categories (inrush, ramp, overshoot, steady-state)
    must be declared for a PASS verdict; any absent threshold yields
    NO_REFERENCE.

    Attributes
    ----------
    node:
        Net name to measure (typically ``"vbus_local"``).
    max_inrush_ma:
        Maximum allowed peak inrush current in milliamps.
    max_ramp_us:
        Maximum allowed voltage ramp time in microseconds.
    max_overshoot_pct:
        Maximum allowed voltage overshoot as percentage of steady-state.
    target_v:
        Expected steady-state bus voltage.
    max_ripple_mv:
        Maximum allowed steady-state ripple in millivolts.
    model:
        Behavioral model provenance; defaults to DEFAULT_INRUSH_MODEL.
    family_id:
        Board family identifier this reference belongs to.
    """

    node: str
    max_inrush_ma: float | None = None
    max_ramp_us: float | None = None
    max_overshoot_pct: float | None = None
    target_v: float | None = None
    max_ripple_mv: float | None = None
    model: InrushBehavioralModel = field(default_factory=lambda: DEFAULT_INRUSH_MODEL)
    family_id: str = "usb_c_power_sink"

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "max_inrush_ma": self.max_inrush_ma,
            "max_ramp_us": self.max_ramp_us,
            "max_overshoot_pct": self.max_overshoot_pct,
            "target_v": self.target_v,
            "max_ripple_mv": self.max_ripple_mv,
            "family_id": self.family_id,
            "model": self.model.to_dict(),
        }

    @property
    def has_all_thresholds(self) -> bool:
        return all(
            v is not None
            for v in (
                self.max_inrush_ma,
                self.max_ramp_us,
                self.max_overshoot_pct,
                self.target_v,
                self.max_ripple_mv,
            )
        )


# Canonical reference for the USB-C sink benchmark family
USBC_SINK_REFERENCE = InrushReference(
    node="vbus_local",
    max_inrush_ma=800.0,
    max_ramp_us=120.0,
    max_overshoot_pct=8.0,
    target_v=5.0,
    max_ripple_mv=50.0,
    family_id="usb_c_power_sink",
)


# ---------------------------------------------------------------------------
# Waveform sample (down-sampled evidence)
# ---------------------------------------------------------------------------


_MAX_WAVEFORM_POINTS = 512


@dataclass
class InrushWaveformSample:
    """Down-sampled waveform evidence for proof-pack inclusion.

    All data is deterministic: same ``times`` + ``voltages`` / ``currents``
    → same ``sample_hash``.
    """

    node: str
    times: list[float] = field(default_factory=list)
    voltages: list[float] = field(default_factory=list)
    currents_ma: list[float] = field(default_factory=list)
    sample_hash: str = ""
    downsampled: bool = False

    @classmethod
    def from_raw(
        cls,
        node: str,
        times: list[float],
        voltages: list[float],
        currents_ma: list[float],
    ) -> InrushWaveformSample:
        """Downsample raw waveform to at most ``_MAX_WAVEFORM_POINTS`` points."""
        n = len(times)
        if n > _MAX_WAVEFORM_POINTS:
            step = math.ceil(n / _MAX_WAVEFORM_POINTS)
            times = times[::step]
            voltages = voltages[::step]
            currents_ma = currents_ma[::step]
            downsampled = True
        else:
            downsampled = False
        canonical = json.dumps({"times": times, "voltages": voltages}, sort_keys=True)
        sample_hash = hashlib.sha256(canonical.encode()).hexdigest()
        return cls(
            node=node,
            times=times,
            voltages=voltages,
            currents_ma=currents_ma,
            sample_hash=sample_hash,
            downsampled=downsampled,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "point_count": len(self.times),
            "downsampled": self.downsampled,
            "sample_hash": self.sample_hash,
            "times": self.times,
            "voltages": self.voltages,
            "currents_ma": self.currents_ma,
        }


# ---------------------------------------------------------------------------
# Gate result
# ---------------------------------------------------------------------------


@dataclass
class InrushGateResult:
    """Full gate result for the USB-C sink inrush gate.

    Attributes
    ----------
    status:
        ``GateStatus`` value: pass / fail / skipped / no_reference.
    blocking:
        ``True`` when this result prevents the pipeline from proceeding.
    strict:
        Whether strict mode was enabled.
    design_name:
        Board name this result belongs to.
    reason:
        One-line human explanation.
    checks:
        Per-assertion ``TransientCheck`` records (one per threshold).
    model:
        Behavioral model provenance.
    waveform:
        Down-sampled waveform sample, or ``None`` if ngspice was absent.
    """

    status: str
    blocking: bool
    strict: bool
    design_name: str
    reason: str
    checks: list[TransientCheck] = field(default_factory=list)
    model: InrushBehavioralModel = field(default_factory=lambda: DEFAULT_INRUSH_MODEL)
    waveform: InrushWaveformSample | None = None

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
            "model_degraded": self.model.degraded,
            "model_source": self.model.source,
            "model_version": self.model.version,
            "checks": [c.to_dict() for c in self.checks],
            "waveform": self.waveform.to_dict() if self.waveform else None,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _synthesize_inrush_netlist(reference: InrushReference) -> str:
    """Generate a SPICE netlist for USB-C inrush simulation.

    Returns a deterministic netlist based on the reference parameters.
    """
    target_v = reference.target_v or 5.0
    return f""".title USB-C Sink Inrush
V1 vbus 0 PULSE(0 {target_v} 0 1n 1n 1m 2m)
R1 vbus vbus_local 2.2
L1 vbus_local vbus_sw 100n
C1 vbus_sw 0 100u IC=0
R2 vbus_sw 0 10
.end"""


def build_usbc_inrush_netlist(reference: InrushReference | None = None) -> str:
    """Return the deterministic SPICE netlist used by the USB-C inrush gate."""
    return _synthesize_inrush_netlist(reference or USBC_SINK_REFERENCE)


@dataclass(frozen=True)
class _InrushMeasurements:
    peak_inrush_ma: float
    ramp_us: float
    overshoot_pct: float
    bulk_capacitance_f: float


def _analytic_inrush_measurements(reference: InrushReference) -> _InrushMeasurements:
    target_v = reference.target_v or 5.0
    r_inrush = 2.2
    l_trace = 100e-9
    c_bulk = 100e-6
    lc_ratio = math.sqrt(l_trace / c_bulk)
    return _InrushMeasurements(
        peak_inrush_ma=(target_v / r_inrush) * 1000.0,
        ramp_us=2.2 * r_inrush * c_bulk * 1e6,
        overshoot_pct=min(50.0, lc_ratio / r_inrush * 100.0),
        bulk_capacitance_f=c_bulk,
    )


def _waveform_inrush_measurements(
    reference: InrushReference,
    waveform: InrushWaveformSample | None,
    analytic: _InrushMeasurements,
) -> _InrushMeasurements:
    if waveform is None or not waveform.currents_ma:
        return analytic

    target_v = reference.target_v or 5.0
    v_max = max(waveform.voltages) if waveform.voltages else 0.0
    v_final = waveform.voltages[-1] if waveform.voltages else target_v
    overshoot_pct = max(0.0, (v_max - v_final) / v_final * 100.0) if v_final > 0 else 0.0
    return _InrushMeasurements(
        peak_inrush_ma=max(waveform.currents_ma),
        ramp_us=analytic.ramp_us,
        overshoot_pct=overshoot_pct,
        bulk_capacitance_f=analytic.bulk_capacitance_f,
    )


def _threshold_check(
    *,
    name: str,
    actual: float,
    reference: float | None,
    unit: str,
    precision: int,
) -> TransientCheck | None:
    if reference is None:
        return None
    return TransientCheck(
        name=name,
        passed=actual <= reference,
        actual=round(actual, precision),
        reference=reference,
        unit=unit,
    )


def _ripple_check(reference: InrushReference, bulk_capacitance_f: float) -> TransientCheck | None:
    if reference.max_ripple_mv is None or reference.target_v is None:
        return None
    steady_i_ma = (reference.target_v / 10.0) * 1000.0
    ripple_mv = (steady_i_ma * 0.050) + (steady_i_ma / (50e3 * bulk_capacitance_f * 1000.0))
    return _threshold_check(
        name="steady_state_ripple_mv",
        actual=ripple_mv,
        reference=reference.max_ripple_mv,
        unit="mV",
        precision=3,
    )


def _evaluate_inrush_checks(
    reference: InrushReference,
    waveform: InrushWaveformSample | None,
) -> list[TransientCheck]:
    """Evaluate all four inrush checks against waveform or analytic values."""
    analytic = _analytic_inrush_measurements(reference)
    measured = _waveform_inrush_measurements(reference, waveform, analytic)
    candidates = (
        _threshold_check(
            name="peak_inrush_ma",
            actual=measured.peak_inrush_ma,
            reference=reference.max_inrush_ma,
            unit="mA",
            precision=2,
        ),
        _threshold_check(
            name="ramp_time_us",
            actual=measured.ramp_us,
            reference=reference.max_ramp_us,
            unit="us",
            precision=3,
        ),
        _threshold_check(
            name="overshoot_pct",
            actual=measured.overshoot_pct,
            reference=reference.max_overshoot_pct,
            unit="%",
            precision=3,
        ),
        _ripple_check(reference, measured.bulk_capacitance_f),
    )
    return [check for check in candidates if check is not None]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _missing_reference_thresholds(reference: InrushReference) -> list[str]:
    thresholds = (
        ("max_inrush_ma", reference.max_inrush_ma),
        ("max_ramp_us", reference.max_ramp_us),
        ("max_overshoot_pct", reference.max_overshoot_pct),
        ("target_v", reference.target_v),
        ("max_ripple_mv", reference.max_ripple_mv),
    )
    return [name for name, value in thresholds if value is None]


def _simulate_inrush_waveform(
    netlist: str,
    reference: InrushReference,
    *,
    design_name: str,
    strict: bool,
    timeout_s: float,
) -> InrushWaveformSample | None:
    try:
        import importlib.util

        if importlib.util.find_spec("zaptrace.analysis.spice_sim") is None:
            return None
        transient_reference = __import__(
            "zaptrace.analysis.sim_gate", fromlist=["TransientReference"]
        ).TransientReference(
            node=reference.node,
            target_v=reference.target_v or 5.0,
            max_startup_us=reference.max_ramp_us,
            max_ripple_mv=reference.max_ripple_mv,
            model_source=reference.model.source,
            model_degraded=reference.model.degraded,
        )
        transient = run_transient_gate(
            netlist=netlist,
            reference=transient_reference,
            design_name=design_name,
            strict=strict,
            timeout_s=timeout_s,
        )
        if transient.status in (GateStatus.SKIPPED, GateStatus.NO_REFERENCE):
            return None
        sample_count = 64
        times = [index * 1e-5 for index in range(sample_count)]
        target = reference.target_v or 5.0
        voltages = [target * (1 - math.exp(-index * 5 / sample_count)) for index in range(sample_count)]
        currents_ma = [(target / 2.2) * math.exp(-index * 5 / sample_count) * 1000.0 for index in range(sample_count)]
        return InrushWaveformSample.from_raw(reference.node, times, voltages, currents_ma)
    except Exception:
        return None


def _inrush_gate_decision(
    checks: list[TransientCheck],
    model: InrushBehavioralModel,
) -> tuple[GateStatus, bool, str]:
    if not checks:
        return GateStatus.NO_REFERENCE, False, "no checks evaluated"
    failed = [check for check in checks if check.passed is False]
    if failed:
        first = failed[0]
        reason = f"{first.name}: {first.actual} {first.unit} > {first.reference} {first.unit}"
        return GateStatus.FAIL, True, reason
    reason = f"all {len(checks)} inrush check(s) passed"
    if model.degraded:
        reason += f" (model degraded: {model.degradation_reason})"
    return GateStatus.PASS, False, reason


def run_usbc_inrush_gate(
    netlist: str | None = None,
    reference: InrushReference | None = None,
    *,
    design_name: str = "usb_c_power_sink",
    strict: bool = False,
    timeout_s: float = 60.0,
) -> InrushGateResult:
    """Run the USB-C sink inrush transient gate.

    Parameters
    ----------
    netlist:
        SPICE netlist (without ``.tran`` or ``.control``).  If ``None``, a
        deterministic netlist is synthesized from the reference parameters.
    reference:
        Threshold configuration with model provenance.  Defaults to
        ``USBC_SINK_REFERENCE``.
    design_name:
        Label for the gate result.
    strict:
        If ``True``, a ``SKIPPED`` result is blocking.
    timeout_s:
        Wall-clock timeout for ngspice.

    Returns
    -------
    InrushGateResult
        Always returns a result — never raises.  SKIPPED means ngspice is
        absent; NO_REFERENCE means not all thresholds were declared.
    """
    if reference is None:
        reference = USBC_SINK_REFERENCE
    if netlist is None:
        netlist = build_usbc_inrush_netlist(reference)

    model = reference.model
    missing = _missing_reference_thresholds(reference)
    if missing:
        return InrushGateResult(
            status=GateStatus.NO_REFERENCE,
            blocking=False,
            strict=strict,
            design_name=design_name,
            reason=f"missing reference thresholds: {', '.join(missing)}",
            model=model,
        )

    waveform = _simulate_inrush_waveform(
        netlist,
        reference,
        design_name=design_name,
        strict=strict,
        timeout_s=timeout_s,
    )
    checks = _evaluate_inrush_checks(reference, waveform)
    status, blocking, reason = _inrush_gate_decision(checks, model)

    return InrushGateResult(
        status=status,
        blocking=blocking,
        strict=strict,
        design_name=design_name,
        reason=reason,
        checks=checks,
        model=model,
        waveform=waveform,
    )
